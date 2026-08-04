#!/usr/bin/env python3
"""Artifact gate for Blender-built V2.2 tactical scenes."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCENES = ("river_valley", "sewer_dungeon", "dragonbone_rift")
REQUIRED_KINDS = {
    "river_valley": {"surface", "grid", "route", "anchor", "feature", "terrain_cliff", "landmark"},
    "sewer_dungeon": {"surface", "grid", "route", "anchor", "feature", "wall", "machinery", "infrastructure"},
    "dragonbone_rift": {"surface", "grid", "route", "anchor", "feature", "terrain_cliff", "bone", "landmark", "hazard"},
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


def glb_json(path: Path) -> tuple[int, dict]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise AssertionError(f"not a GLB: {path}")
    version, total_length = struct.unpack_from("<II", data, 4)
    if version != 2 or total_length != len(data):
        raise AssertionError(f"invalid GLB header: {path}")
    json_length, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != 0x4E4F534A:
        raise AssertionError(f"GLB first chunk is not JSON: {path}")
    return version, json.loads(data[20 : 20 + json_length].decode("utf-8"))


def verify_scene(slug: str) -> dict:
    out = ROOT / "output" / "v22-scenes" / slug
    grid_path, source_manifest_path = out / "scene.grid.json", out / "scene.manifest.json"
    render_manifest_path = out / "scene.render-manifest.json"
    grid, source_manifest, render_manifest = map(read_json, (grid_path, source_manifest_path, render_manifest_path))
    expected = ("scene.glb", "scene-prototype.blend", "scene-isometric.png", "scene-topdown.png")
    for name in expected:
        if not (out / name).is_file() or (out / name).stat().st_size < 1000:
            raise AssertionError(f"missing or trivial V2.2 output: {slug}/{name}")
    if render_manifest["grid_file_sha256"] != sha256(grid_path):
        raise AssertionError(f"stale render grid hash: {slug}")
    if render_manifest["grid_semantic_sha256"] != source_manifest["grid_sha256"]:
        raise AssertionError(f"semantic grid hash drift: {slug}")
    if render_manifest["input_manifest_sha256"] != sha256(source_manifest_path):
        raise AssertionError(f"stale source manifest hash: {slug}")
    records = {item["path"]: item for item in render_manifest["outputs"]}
    for name in expected:
        path = out / name
        if records[name] != {"path": name, "bytes": path.stat().st_size, "sha256": sha256(path)}:
            raise AssertionError(f"stale output receipt: {slug}/{name}")
    image_sizes = {name: png_size(out / name) for name in expected if name.endswith(".png")}
    if set(image_sizes.values()) != {(1500, 1100)}:
        raise AssertionError(f"unexpected render size: {slug}/{image_sizes}")
    if sha256(out / "scene-isometric.png") == sha256(out / "scene-topdown.png"):
        raise AssertionError(f"camera renders are identical: {slug}")
    version, document = glb_json(out / "scene.glb")
    encoded = json.dumps(document, ensure_ascii=False)
    for anchor in grid["anchors"]:
        if anchor["id"] not in encoded:
            raise AssertionError(f"anchor missing from GLB extras: {slug}/{anchor['id']}")
    for feature in grid["features"]:
        if feature["id"] not in encoded:
            raise AssertionError(f"feature missing from GLB extras: {slug}/{feature['id']}")
    kinds = render_manifest["object_kinds"]
    missing_kinds = REQUIRED_KINDS[slug] - kinds.keys()
    if missing_kinds:
        raise AssertionError(f"semantic visual kinds missing: {slug}/{sorted(missing_kinds)}")
    if render_manifest["prototype_objects"] > 250 or render_manifest["mesh_vertices"] > 450_000:
        raise AssertionError(f"render budget exceeded: {slug}")
    if slug == "river_valley" and render_manifest["elevation_range_ft"] != [0.0, 60.0]:
        raise AssertionError("river valley lost its vertical range")
    if slug == "sewer_dungeon" and kinds.get("wall", 0) < 2:
        raise AssertionError("sewer public/secret wall semantics regressed")
    if slug == "dragonbone_rift":
        if render_manifest["elevation_range_ft"] != [0.0, 50.0] or grid.get("room_dependencies"):
            raise AssertionError("special site height/room-free contract regressed")
    return {
        "scene": slug,
        "glb_version": version,
        "glb_bytes": (out / "scene.glb").stat().st_size,
        "blend_bytes": (out / "scene-prototype.blend").stat().st_size,
        "objects": render_manifest["prototype_objects"],
        "vertices": render_manifest["mesh_vertices"],
        "images": image_sizes,
    }


def main() -> None:
    requested = tuple(sys.argv[1:]) or SCENES
    unknown = set(requested) - set(SCENES)
    if unknown:
        raise SystemExit(f"unknown V2.2 scene(s): {', '.join(sorted(unknown))}")
    print(json.dumps({"status": "passed", "scenes": [verify_scene(slug) for slug in requested]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
