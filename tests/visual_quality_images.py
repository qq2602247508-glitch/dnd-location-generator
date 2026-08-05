#!/usr/bin/env python3
"""Dependency-free visual measurements and blind review certificates.

The project deliberately keeps this module independent from Blender and the
Viewer.  It reads the rendered PNG bytes that are already production
artifacts, so a certificate can be compared across rendering implementations.
Only non-interlaced, 8-bit PNGs are supported; that is the format emitted by
the existing Blender render scripts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SCHEMA_VERSION = "dnd-visual-certificate-1.0"
ANALYSIS_VERSION = "visual-quality-images-1.0"
RATING_FIELDS = (
    "composition",
    "readability",
    "lighting",
    "material_separation",
    "tactical_clarity",
)
CRITICAL_DEFECT_CODES = {
    "black_frame",
    "empty_frame",
    "unreadable_tactical_surface",
    "permission_leak",
    "layer_leak",
    "transition_obscured",
    "render_artifact",
    "other",
}


@dataclass(frozen=True)
class DecodedPng:
    width: int
    height: int
    bit_depth: int
    color_type: int
    rgba: bytes


def _paeth(left: int, above: int, upper_left: int) -> int:
    predictor = left + above - upper_left
    left_distance = abs(predictor - left)
    above_distance = abs(predictor - above)
    upper_left_distance = abs(predictor - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def decode_png(path: Path) -> DecodedPng:
    """Decode an existing non-interlaced 8-bit PNG into black-composited RGBA."""
    raw = path.read_bytes()
    if not raw.startswith(PNG_SIGNATURE):
        raise ValueError(f"not a PNG: {path}")
    offset = len(PNG_SIGNATURE)
    header: tuple[int, int, int, int, int, int, int] | None = None
    palette: bytes | None = None
    transparency: bytes | None = None
    compressed = bytearray()
    saw_end = False
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError(f"truncated PNG chunk: {path}")
        length = struct.unpack_from(">I", raw, offset)[0]
        kind = raw[offset + 4: offset + 8]
        start, end = offset + 8, offset + 8 + length
        if end + 4 > len(raw):
            raise ValueError(f"truncated PNG chunk data: {path}")
        data = raw[start:end]
        expected_crc = struct.unpack_from(">I", raw, end)[0]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != expected_crc:
            raise ValueError(f"PNG CRC mismatch in {kind.decode('ascii', 'replace')}: {path}")
        offset = end + 4
        if kind == b"IHDR":
            if header is not None or len(data) != 13:
                raise ValueError(f"invalid PNG header: {path}")
            header = struct.unpack(">IIBBBBB", data)
        elif kind == b"PLTE":
            palette = data
        elif kind == b"tRNS":
            transparency = data
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            saw_end = True
            break
    if header is None or not saw_end:
        raise ValueError(f"incomplete PNG: {path}")
    width, height, bit_depth, color_type, compression, filter_method, interlace = header
    if not width or not height or bit_depth != 8 or interlace != 0:
        raise ValueError(f"only non-interlaced 8-bit PNGs are supported: {path}")
    if compression != 0 or filter_method != 0 or color_type not in {0, 2, 3, 4, 6}:
        raise ValueError(f"unsupported PNG encoding: {path}")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = width * channels
    filtered = zlib.decompress(bytes(compressed))
    if len(filtered) != height * (row_bytes + 1):
        raise ValueError(f"unexpected decompressed PNG size: {path}")
    rows: list[bytearray] = []
    position = 0
    for _ in range(height):
        filter_type = filtered[position]
        position += 1
        source = filtered[position: position + row_bytes]
        position += row_bytes
        previous = rows[-1] if rows else bytearray(row_bytes)
        rebuilt = bytearray(row_bytes)
        for index, value in enumerate(source):
            left = rebuilt[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                rebuilt[index] = value
            elif filter_type == 1:
                rebuilt[index] = (value + left) & 0xFF
            elif filter_type == 2:
                rebuilt[index] = (value + above) & 0xFF
            elif filter_type == 3:
                rebuilt[index] = (value + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                rebuilt[index] = (value + _paeth(left, above, upper_left)) & 0xFF
            else:
                raise ValueError(f"unsupported PNG filter {filter_type}: {path}")
        rows.append(rebuilt)
    if color_type == 3 and (palette is None or len(palette) % 3):
        raise ValueError(f"invalid indexed PNG palette: {path}")

    rgba = bytearray(width * height * 4)
    output = 0
    for row in rows:
        for index in range(0, row_bytes, channels):
            if color_type == 0:
                red = green = blue = row[index]
                alpha = 255
            elif color_type == 2:
                red, green, blue, alpha = row[index], row[index + 1], row[index + 2], 255
            elif color_type == 3:
                palette_index = row[index]
                palette_offset = palette_index * 3
                if palette is None or palette_offset + 3 > len(palette):
                    raise ValueError(f"indexed PNG palette reference is invalid: {path}")
                red, green, blue = palette[palette_offset: palette_offset + 3]
                alpha = transparency[palette_index] if transparency and palette_index < len(transparency) else 255
            elif color_type == 4:
                red = green = blue = row[index]
                alpha = row[index + 1]
            else:
                red, green, blue, alpha = row[index:index + 4]
            # Transparent render layers must not make a bright color look like
            # visual coverage.  The existing renders use an opaque black world.
            rgba[output: output + 4] = bytes((red * alpha // 255, green * alpha // 255, blue * alpha // 255, alpha))
            output += 4
    return DecodedPng(width, height, bit_depth, color_type, bytes(rgba))


def _percentile(values: bytes, fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate a percentile of no values")
    index = round((len(ordered) - 1) * fraction)
    return ordered[index] / 255.0


def _median(values: Iterable[int]) -> int:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate a median of no values")
    return ordered[len(ordered) // 2]


def _background_rgb(image: DecodedPng) -> tuple[int, int, int]:
    border = max(1, min(8, min(image.width, image.height) // 20))
    red: list[int] = []
    green: list[int] = []
    blue: list[int] = []
    for row in range(image.height):
        for col in range(image.width):
            if border <= row < image.height - border and border <= col < image.width - border:
                continue
            offset = (row * image.width + col) * 4
            red.append(image.rgba[offset])
            green.append(image.rgba[offset + 1])
            blue.append(image.rgba[offset + 2])
    return _median(red), _median(green), _median(blue)


def _edge_metrics(luminance: bytes, width: int, height: int) -> tuple[float, float, int]:
    # Sample at most roughly 384 pixels on the long side.  This keeps the
    # metric cheap for 1500px renders while preserving scene-scale features.
    step = max(1, math.ceil(max(width, height) / 384))
    sampled_width = (width + step - 1) // step
    sampled_height = (height + step - 1) // step
    if sampled_width < 3 or sampled_height < 3:
        return 0.0, 0.0, step
    edge_pixels = 0
    edge_strength_total = 0.0
    samples = 0
    threshold = 0.10
    for sample_row in range(1, sampled_height - 1):
        row = min(height - 1, sample_row * step)
        for sample_col in range(1, sampled_width - 1):
            col = min(width - 1, sample_col * step)
            left = luminance[row * width + max(0, col - step)]
            right = luminance[row * width + min(width - 1, col + step)]
            above = luminance[max(0, row - step) * width + col]
            below = luminance[min(height - 1, row + step) * width + col]
            strength = (abs(right - left) + abs(below - above)) / 510.0
            edge_strength_total += strength
            edge_pixels += strength >= threshold
            samples += 1
    return edge_pixels / samples, edge_strength_total / samples, step


def analyze_png(path: Path) -> dict[str, Any]:
    """Measure a rendered PNG without scoring it or applying scene thresholds."""
    image = decode_png(path)
    background = _background_rgb(image)
    background_distance_threshold = 0.075
    luminance = bytearray(image.width * image.height)
    all_buckets: Counter[tuple[int, int, int]] = Counter()
    foreground_buckets: Counter[tuple[int, int, int]] = Counter()
    foreground = 0
    for pixel in range(image.width * image.height):
        offset = pixel * 4
        red, green, blue = image.rgba[offset: offset + 3]
        # ITU-R BT.709 coefficients over the encoded sRGB render values.
        luminance[pixel] = (54 * red + 183 * green + 19 * blue) // 256
        bucket = (red >> 5, green >> 5, blue >> 5)
        all_buckets[bucket] += 1
        distance = math.sqrt((red - background[0]) ** 2 + (green - background[1]) ** 2 + (blue - background[2]) ** 2) / (255.0 * math.sqrt(3.0))
        if distance > background_distance_threshold:
            foreground += 1
            foreground_buckets[bucket] += 1
    edge_density, mean_edge_strength, edge_step = _edge_metrics(bytes(luminance), image.width, image.height)
    dominant_bucket, dominant_count = max(all_buckets.items(), key=lambda item: (item[1], item[0]))
    foreground_dominant_bucket, foreground_dominant_count = max(
        foreground_buckets.items(), key=lambda item: (item[1], item[0]), default=((0, 0, 0), 0)
    )
    p05, p50, p95 = (_percentile(bytes(luminance), fraction) for fraction in (0.05, 0.50, 0.95))
    return {
        "analysis_version": ANALYSIS_VERSION,
        "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "byte_size": path.stat().st_size,
        "png": {
            "width": image.width,
            "height": image.height,
            "bit_depth": image.bit_depth,
            "color_type": image.color_type,
            "interlaced": False,
        },
        "luminance": {
            "method": "bt709_srgb_encoded",
            "p05": round(p05, 6),
            "p50": round(p50, 6),
            "p95": round(p95, 6),
            "contrast_p95_minus_p05": round(p95 - p05, 6),
        },
        "coverage": {
            "background_rgb": list(background),
            "distance_threshold": background_distance_threshold,
            "non_background_fraction": round(foreground / (image.width * image.height), 6),
        },
        "edges": {
            "method": "central_difference_luminance",
            "sample_step": edge_step,
            "threshold": 0.10,
            "density": round(edge_density, 6),
            "mean_strength": round(mean_edge_strength, 6),
        },
        "colors": {
            "quantization": "rgb_3bit_per_channel",
            "bucket_count": len(all_buckets),
            "dominant_bucket": list(dominant_bucket),
            "dominant_bucket_fraction": round(dominant_count / (image.width * image.height), 6),
            "non_background_bucket_count": len(foreground_buckets),
            "dominant_non_background_bucket": list(foreground_dominant_bucket),
            "dominant_non_background_bucket_fraction": round(foreground_dominant_count / foreground, 6) if foreground else 0.0,
        },
    }


def _normalise_defects(defects: Iterable[dict[str, str]] | None) -> list[dict[str, str]]:
    normalised: list[dict[str, str]] = []
    for defect in defects or ():
        code = defect.get("code", "")
        note = defect.get("note", "")
        if code not in CRITICAL_DEFECT_CODES or not isinstance(note, str):
            raise ValueError(f"invalid critical defect: {defect!r}")
        normalised.append({"code": code, "note": note})
    return normalised


def create_certificate(
    path: Path,
    blind_case_id: str,
    ratings: dict[str, int],
    critical_defects: Iterable[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Create a review-ready certificate without leaking a scene name or path."""
    if not blind_case_id or not isinstance(blind_case_id, str):
        raise ValueError("blind_case_id is required")
    if set(ratings) != set(RATING_FIELDS) or any(not isinstance(value, int) or not 1 <= value <= 5 for value in ratings.values()):
        raise ValueError(f"ratings must contain exactly {', '.join(RATING_FIELDS)} as integers from 1 to 5")
    metrics = analyze_png(path)
    certificate = {
        "schema_version": SCHEMA_VERSION,
        "certificate_id": f"visual-{metrics['image_sha256'][:16]}",
        "blind_case_id": blind_case_id,
        "image": {
            "sha256": metrics["image_sha256"],
            "byte_size": metrics["byte_size"],
            "width": metrics["png"]["width"],
            "height": metrics["png"]["height"],
            "png_color_type": metrics["png"]["color_type"],
            "png_bit_depth": metrics["png"]["bit_depth"],
        },
        "metrics": metrics,
        "ratings": {field: ratings[field] for field in RATING_FIELDS},
        "critical_defects": _normalise_defects(critical_defects),
    }
    validate_certificate(certificate)
    return certificate


def validate_certificate(certificate: dict[str, Any]) -> None:
    """Validate the cross-field guarantees JSON Schema alone cannot express."""
    if certificate.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unexpected visual certificate schema version")
    image, metrics = certificate.get("image"), certificate.get("metrics")
    if not isinstance(image, dict) or not isinstance(metrics, dict):
        raise ValueError("certificate is missing image or metrics")
    if image.get("sha256") != metrics.get("image_sha256"):
        raise ValueError("certificate image hash does not match metrics image hash")
    if image.get("width") != metrics.get("png", {}).get("width") or image.get("height") != metrics.get("png", {}).get("height"):
        raise ValueError("certificate dimensions do not match metrics")
    ratings = certificate.get("ratings")
    if not isinstance(ratings, dict) or set(ratings) != set(RATING_FIELDS):
        raise ValueError("certificate ratings are incomplete")
    if any(not isinstance(value, int) or not 1 <= value <= 5 for value in ratings.values()):
        raise ValueError("certificate ratings must be integers from 1 to 5")
    _normalise_defects(certificate.get("critical_defects"))


def _parse_ratings(text: str) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for item in text.split(","):
        name, separator, raw_value = item.partition("=")
        if not separator:
            raise ValueError("ratings must use name=value pairs")
        parsed[name.strip()] = int(raw_value.strip())
    return parsed


def _parse_defect(text: str) -> dict[str, str]:
    code, _, note = text.partition(":")
    return {"code": code, "note": note}


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure existing PNG renders and create blind visual certificates")
    parser.add_argument("--image", action="append", required=True, type=Path)
    parser.add_argument("--blind-case-id", action="append", default=[])
    parser.add_argument("--ratings", required=True, help="composition=1,readability=1,lighting=1,material_separation=1,tactical_clarity=1")
    parser.add_argument("--critical-defect", action="append", default=[], help="code[:note]")
    parser.add_argument("--out", type=Path, help="optional JSON receipt path")
    args = parser.parse_args()
    if args.blind_case_id and len(args.blind_case_id) != len(args.image):
        raise SystemExit("supply either no --blind-case-id values or one for each --image")
    ratings = _parse_ratings(args.ratings)
    defects = [_parse_defect(item) for item in args.critical_defect]
    certificates = [
        create_certificate(path, args.blind_case_id[index] if args.blind_case_id else f"blind-{index + 1:03d}", ratings, defects)
        for index, path in enumerate(args.image)
    ]
    payload = {"certificates": certificates}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
