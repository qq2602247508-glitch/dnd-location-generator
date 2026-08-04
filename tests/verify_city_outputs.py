#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
SPEC = ROOT / "specs" / "city.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"invalid PNG: {path.name}")
    return struct.unpack(">II", header[16:24])


def main() -> None:
    manifest = json.loads((OUTPUT / "city-manifest.json").read_text(encoding="utf-8"))
    if manifest["source_sha256"] != sha256(SPEC) or manifest["validation"]["status"] != "passed":
        raise AssertionError("manifest/spec validation mismatch")
    validation = manifest["validation"]
    if validation["physical_size_ft"] != [160, 140] or validation["building_count"] != 7 or validation["multi_level_buildings"] < 1:
        raise AssertionError("city contract changed")
    grid = json.loads((OUTPUT / "city-grid.json").read_text(encoding="utf-8"))
    required = {"level_index", "row", "col", "space_kind", "building_id", "room_id"}
    if not grid["cells"] or not required <= grid["cells"][0].keys():
        raise AssertionError("city grid metadata is incomplete")
    if sum(item["type"] == "entrance" for item in grid["transitions"]) < 2 or sum(item["type"] == "stairs" for item in grid["transitions"]) < 1:
        raise AssertionError("city transitions are incomplete")
    images = {}
    for name in ("city-isometric.png", "city-topdown.png"):
        path = OUTPUT / name
        if png_size(path) != (1400, 1000):
            raise AssertionError(f"unexpected render dimensions: {name}")
        images[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    if images["city-isometric.png"]["sha256"] == images["city-topdown.png"]["sha256"]:
        raise AssertionError("city render views are identical")
    glb = OUTPUT / "city-dm.glb"
    magic, version, declared = struct.unpack("<4sII", glb.read_bytes()[:12])
    if magic != b"glTF" or version != 2 or declared != glb.stat().st_size:
        raise AssertionError("invalid city GLB")
    blend = OUTPUT / "city-prototype.blend"
    if blend.stat().st_size < 100_000:
        raise AssertionError("city blend unexpectedly small")
    report = {"status": "passed", "physical_size_ft": validation["physical_size_ft"], "building_count": validation["building_count"], "prototype_objects": manifest["prototype_objects"], "images": images, "glb_bytes": glb.stat().st_size, "blend_bytes": blend.stat().st_size}
    (OUTPUT / "city-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
