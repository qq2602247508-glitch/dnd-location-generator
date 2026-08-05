#!/usr/bin/env python3
"""Regression gate for declarative archetypes and the generic room solver."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.archetype_manifest import canonical_bytes, load_manifest, resolve_theme  # noqa: E402
from generator.v2.room_solver import solve_room_layout, validate_room_layout  # noqa: E402


def _rooms(layout: dict) -> list[dict]:
    return [room for floor in layout["floors"] for room in floor["rooms"]]


def main() -> None:
    manifest_paths = sorted((ROOT / "specs" / "archetypes").glob("*.json"))
    if {path.stem for path in manifest_paths} != {"manor", "sewer", "tower"}:
        raise AssertionError("archetype fixture set changed unexpectedly")
    reports = []
    with tempfile.TemporaryDirectory() as temporary:
        for path in manifest_paths:
            manifest = load_manifest(path)
            default_theme = resolve_theme(manifest)
            if default_theme["resolved_theme_id"] != "default":
                raise AssertionError(f"default theme did not resolve: {path.name}")
            theme_ids = sorted(manifest["themes"])
            first = solve_room_layout(manifest, seed=20260805, width=24, height=18, theme_id=theme_ids[0])
            second = solve_room_layout(manifest, seed=20260805, width=24, height=18, theme_id=theme_ids[0])
            if canonical_bytes(first) != canonical_bytes(second):
                raise AssertionError(f"room solve is non-deterministic: {path.name}")
            report = validate_room_layout(first, manifest)
            rooms = _rooms(first)
            if report["rooms"] != len(rooms) or report["connectors"] != len(first["connectors"]):
                raise AssertionError(f"room report count mismatch: {path.name}")
            if not any(room["role"] == "entry" for room in rooms) or not any(room["role"] in {"objective", "boss"} for room in rooms):
                raise AssertionError(f"required room roles missing: {path.name}")
            if not any(room["role"] == "secret" and room["visibility"] == "dm_only" for room in rooms):
                raise AssertionError(f"secret room visibility missing: {path.name}")
            if manifest["id"] == "tower" and report["floors"] != 3:
                raise AssertionError("tower lost three floors")
            if manifest["id"] == "manor" and report["floors"] != 2:
                raise AssertionError("manor lost two floors")
            if manifest["id"] == "sewer" and report["cycle_rank"] < 1:
                raise AssertionError("sewer lost its loop")
            output_path = Path(temporary) / f"{path.stem}.layout.json"
            output_path.write_bytes(canonical_bytes(first))
            if json.loads(output_path.read_text(encoding="utf-8"))["layout_sha256"] != first["layout_sha256"]:
                raise AssertionError("layout serialization changed its hash")
            reports.append(report)

    broken = copy.deepcopy(load_manifest(ROOT / "specs" / "archetypes" / "sewer.json"))
    broken["constraints"]["required_cycles"] = 99
    try:
        solve_room_layout(broken, seed=20260805, width=24, height=18)
    except ValueError:
        pass
    else:
        raise AssertionError("impossible sewer cycle budget was accepted")

    print(json.dumps({"status": "passed", "archetypes": len(reports), "reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
