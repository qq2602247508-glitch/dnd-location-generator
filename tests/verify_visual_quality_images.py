#!/usr/bin/env python3
"""Regression coverage for the dependency-free visual quality certificate."""

from __future__ import annotations

import json
from pathlib import Path

from visual_quality_images import (
    CRITICAL_DEFECT_CODES,
    RATING_FIELDS,
    analyze_png,
    create_certificate,
    validate_certificate,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "specs" / "quality" / "visual-certificate.schema.json"
CASES = {
    "blind-001": ROOT / "output" / "old-clock-v23" / "scene-isometric.png",
    "blind-002": ROOT / "output" / "v22-scenes" / "river_valley" / "scene-isometric.png",
    "blind-003": ROOT / "output" / "v22-scenes" / "sewer_dungeon" / "scene-isometric.png",
    "blind-004": ROOT / "output" / "v22-scenes" / "dragonbone_rift" / "scene-isometric.png",
}


def main() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or schema.get("$id") != "dnd-visual-certificate.schema.json":
        raise AssertionError("visual certificate JSON Schema identity is stale")
    required = set(schema.get("required", []))
    if not {"schema_version", "certificate_id", "blind_case_id", "image", "metrics", "ratings", "critical_defects"} <= required:
        raise AssertionError("visual certificate schema omits a required binding")
    rating_properties = schema["properties"]["ratings"]["properties"]
    if set(rating_properties) != set(RATING_FIELDS):
        raise AssertionError("visual certificate schema does not define exactly five ratings")
    defect_codes = set(schema["properties"]["critical_defects"]["items"]["properties"]["code"]["enum"])
    if defect_codes != CRITICAL_DEFECT_CODES:
        raise AssertionError("visual certificate schema defect vocabulary drifted")

    metrics_by_case = {case_id: analyze_png(path) for case_id, path in CASES.items()}
    hashes = {metrics["image_sha256"] for metrics in metrics_by_case.values()}
    if len(hashes) != len(CASES):
        raise AssertionError("visual QA fixture images unexpectedly share a byte hash")
    for case_id, metrics in metrics_by_case.items():
        png = metrics["png"]
        if not png["width"] or not png["height"] or png["interlaced"]:
            raise AssertionError(f"PNG decoder did not report a supported image: {case_id}")
        # These are universal non-degeneracy checks, deliberately not
        # scene-specific artistic thresholds.
        if metrics["coverage"]["non_background_fraction"] <= 0:
            raise AssertionError(f"render is an empty/background-only frame: {case_id}")
        if metrics["luminance"]["contrast_p95_minus_p05"] <= 0 or metrics["edges"]["density"] <= 0:
            raise AssertionError(f"render has no measurable visual structure: {case_id}")
        if metrics["colors"]["bucket_count"] < 2 or metrics["colors"]["non_background_bucket_count"] < 1:
            raise AssertionError(f"render has no measurable colour structure: {case_id}")
        for section, fields in (("luminance", ("p05", "p50", "p95", "contrast_p95_minus_p05")), ("coverage", ("non_background_fraction",)), ("edges", ("density", "mean_strength")), ("colors", ("dominant_bucket_fraction", "dominant_non_background_bucket_fraction"))):
            for field in fields:
                value = metrics[section][field]
                if not 0 <= value <= 1:
                    raise AssertionError(f"metric outside normalised range: {case_id}/{section}/{field}")

    ratings = {
        "composition": 3,
        "readability": 3,
        "lighting": 3,
        "material_separation": 3,
        "tactical_clarity": 3,
    }
    certificate = create_certificate(
        CASES["blind-001"],
        "blind-001",
        ratings,
        [{"code": "transition_obscured", "note": "review fixture exercises the defect vocabulary"}],
    )
    validate_certificate(certificate)
    if certificate["blind_case_id"] != "blind-001" or "old-clock" in json.dumps(certificate, ensure_ascii=False).lower():
        raise AssertionError("certificate leaked a source-scene label instead of retaining a blind case ID")
    if certificate["image"]["sha256"] != metrics_by_case["blind-001"]["image_sha256"]:
        raise AssertionError("certificate does not bind its analyzed image hash")
    broken = json.loads(json.dumps(certificate))
    broken["image"]["sha256"] = "0" * 64
    try:
        validate_certificate(broken)
    except ValueError:
        pass
    else:
        raise AssertionError("certificate validation accepted a mismatched image hash")

    print(json.dumps({"status": "passed", "fixtures": len(CASES), "metrics": metrics_by_case}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
