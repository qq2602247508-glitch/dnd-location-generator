#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
SPEC = ROOT / "specs" / "underdark.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"invalid PNG: {path.name}")
    return struct.unpack(">II", header[16:24])


def main() -> None:
    manifest_path = OUTPUT / "underdark-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["source_sha256"] != sha256(SPEC):
        raise AssertionError("manifest source hash mismatch")
    validation = manifest["validation"]
    if validation["status"] != "passed" or validation["reachable_cells"] != validation["walkable_cells"]:
        raise AssertionError("terrain reachability failed")
    if validation["physical_size_ft"] != [240, 180]:
        raise AssertionError("physical map size changed")
    if len(validation["elevation_counts"]) != 5:
        raise AssertionError("expected five elevation bands")

    images = {}
    for name in ("underdark-isometric.png", "underdark-topdown.png"):
        path = OUTPUT / name
        if png_size(path) != (1400, 1000):
            raise AssertionError(f"unexpected render size: {name}")
        images[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    if images["underdark-isometric.png"]["sha256"] == images["underdark-topdown.png"]["sha256"]:
        raise AssertionError("camera views are identical")

    glb = OUTPUT / "underdark-dm.glb"
    magic, version, declared = struct.unpack("<4sII", glb.read_bytes()[:12])
    if magic != b"glTF" or version != 2 or declared != glb.stat().st_size:
        raise AssertionError("invalid GLB")
    blend = OUTPUT / "underdark-prototype.blend"
    if blend.stat().st_size < 1_000_000:
        raise AssertionError("BLEND file is unexpectedly small")

    report = {
        "status": "passed",
        "source_sha256": manifest["source_sha256"],
        "physical_size_ft": validation["physical_size_ft"],
        "walkable_cells": validation["walkable_cells"],
        "reachable_cells": validation["reachable_cells"],
        "elevation_counts": validation["elevation_counts"],
        "bridges_cells": validation["bridges_cells"],
        "prototype_objects": manifest["prototype_objects"],
        "props": manifest["props"],
        "images": images,
        "glb": {"version": version, "bytes": glb.stat().st_size, "sha256": sha256(glb)},
        "blend_bytes": blend.stat().st_size,
    }
    (OUTPUT / "underdark-verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
