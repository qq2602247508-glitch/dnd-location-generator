#!/usr/bin/env python3
"""Regression gate for the room-layout -> Viewer runtime adapter."""

from __future__ import annotations

import json
import hashlib
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.archetype_manifest import canonical_bytes, load_manifest  # noqa: E402
from generator.v2.layout_runtime import compile_layout_runtime, validate_layout_runtime  # noqa: E402
from generator.v2.room_solver import solve_room_layout, validate_room_layout  # noqa: E402


def main() -> None:
    reports: list[dict[str, object]] = []
    for manifest_path in sorted((ROOT / "specs" / "archetypes").glob("*.json")):
        manifest = load_manifest(manifest_path)
        theme_id = sorted(manifest["themes"])[0]
        layout = solve_room_layout(manifest, seed=20260805, width=24, height=18, theme_id=theme_id)
        validate_room_layout(layout, manifest)
        first = compile_layout_runtime(layout, manifest=manifest)
        second = compile_layout_runtime(layout, manifest=manifest)
        if canonical_bytes(first) != canonical_bytes(second):
            raise AssertionError(f"runtime is non-deterministic: {manifest_path.name}")
        report = validate_layout_runtime(first, layout)
        if report["scene_id"] != f"{manifest['id']}_archetype":
            raise AssertionError(f"runtime scene id mismatch: {manifest_path.name}")
        if report["rooms"] != len(layout["floors"][0]["rooms"]) + sum(len(floor["rooms"]) for floor in layout["floors"][1:]):
            raise AssertionError(f"runtime room count mismatch: {manifest_path.name}")
        if report["connectors"] != len(layout["connectors"]):
            raise AssertionError(f"runtime connector count mismatch: {manifest_path.name}")
        if not first["nav"]["edges"]:
            raise AssertionError(f"runtime navigation graph is empty: {manifest_path.name}")
        if not any(room["visibility"] == "dm_only" for room in first["rooms"]):
            raise AssertionError(f"runtime lost DM-only room: {manifest_path.name}")
        if not any(feature["kind"] == "secret_cache" for feature in first["features"]):
            raise AssertionError(f"runtime lost secret feature: {manifest_path.name}")
        reports.append(report)

    # Compare the checked-in runtime artifacts as an additional stale-asset
    # guard: generated outputs must still validate against their source layouts.
    for manifest_path in sorted((ROOT / "specs" / "archetypes").glob("*.json")):
        manifest_id = manifest_path.stem
        output_dir = ROOT / "output" / "archetypes" / manifest_id
        layout_path = ROOT / "output" / "archetypes" / f"{manifest_id}.layout.json"
        runtime_path = output_dir / "scene.runtime.json"
        if not layout_path.is_file() or not runtime_path.is_file():
            raise AssertionError(f"missing generated runtime artifact: {manifest_id}")
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        validate_layout_runtime(runtime, layout)
        manifest = json.loads((output_dir / "scene-render-manifest.json").read_text(encoding="utf-8"))
        if manifest["status"] != "generated":
            raise AssertionError(f"render manifest is not generated: {manifest_id}")
        if hashlib.sha256((output_dir / "scene.plan.json").read_bytes()).hexdigest() != manifest["plan_sha256"]:
            raise AssertionError(f"stale plan render hash: {manifest_id}")
        if hashlib.sha256(runtime_path.read_bytes()).hexdigest() != manifest["runtime_sha256"]:
            raise AssertionError(f"stale runtime render hash: {manifest_id}")
        for image_name in ("scene-isometric.png", "scene-topdown.png"):
            image = output_dir / image_name
            header = image.read_bytes()
            if header[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", header[16:24]) != (1400, 1000):
                raise AssertionError(f"invalid certification image: {manifest_id}/{image_name}")
        glb = (output_dir / "scene.glb").read_bytes()
        if glb[:4] != b"glTF" or struct.unpack_from("<I", glb, 4)[0] != 2 or struct.unpack_from("<I", glb, 8)[0] != len(glb):
            raise AssertionError(f"invalid GLB artifact: {manifest_id}")

    print(json.dumps({"status": "passed", "archetypes": len(reports), "reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
