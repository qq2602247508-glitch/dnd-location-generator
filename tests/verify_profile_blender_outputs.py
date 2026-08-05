"""Validate Blender artifacts produced from the shared profile visual bridge."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE_ROOT = ROOT / "output" / "profile-visual"
FIXTURES = {
    "harbor_district": "district",
    "silverfall_outdoor": "outdoor",
    "darkflow_pump_house": "building",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise AssertionError(f"not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


def main() -> None:
    results = []
    for fixture, expected_category in FIXTURES.items():
        input_path = PROFILE_ROOT / f"{fixture}.json"
        output_dir = PROFILE_ROOT / fixture
        manifest_path = output_dir / "scene.render-manifest.json"
        assert input_path.is_file(), input_path
        assert manifest_path.is_file(), manifest_path
        document = json.loads(input_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert document["category"] == expected_category
        assert manifest["category"] == expected_category
        assert manifest["scene"]["id"] == document["scene"]["id"]
        assert manifest["profile_hash"]
        assert manifest["visual_plan_hash"]
        outputs = {item["path"]: item for item in manifest["outputs"]}
        for name in ("scene.glb", "scene-prototype.blend", "scene-isometric.png", "scene-topdown.png"):
            path = output_dir / name
            assert path.is_file() and path.stat().st_size > 0, path
            assert outputs[name]["bytes"] == path.stat().st_size
            assert outputs[name]["sha256"] == sha256(path)
        assert png_size(output_dir / "scene-isometric.png") == (1200, 900)
        assert png_size(output_dir / "scene-topdown.png") == (1200, 900)
        results.append({
            "fixture": fixture,
            "category": expected_category,
            "prototype_objects": manifest["prototype_objects"],
            "mesh_vertices": manifest["mesh_vertices"],
            "views": manifest["visual_evidence_views"],
        })
    print(json.dumps({"status": "passed", "fixtures": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
