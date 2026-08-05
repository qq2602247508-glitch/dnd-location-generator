#!/usr/bin/env python3
"""Regression gate for the planner -> Blender/Viewer input bridge."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.profile_visual import compose_profile_visual_input, validate_profile_visual_input  # noqa: E402
from generator.v2.scene_contract import canonical_bytes  # noqa: E402


def main() -> None:
    fixtures = [
        ROOT / "specs" / "districts" / "harbor_district_composer.json",
        ROOT / "specs" / "buildings" / "darkflow_pump_house.json",
        ROOT / "specs" / "buildings" / "visual_tower.json",
        ROOT / "specs" / "buildings" / "visual_manor.json",
        ROOT / "specs" / "buildings" / "visual_sewer.json",
        ROOT / "specs" / "outdoor" / "silverfall_outdoor_composer.json",
    ]
    reports = []
    for path in fixtures:
        brief = json.loads(path.read_text(encoding="utf-8"))
        first = compose_profile_visual_input(brief)
        second = compose_profile_visual_input(brief)
        if canonical_bytes(first) != canonical_bytes(second):
            raise AssertionError(f"profile visual input is non-deterministic: {path.name}")
        report = validate_profile_visual_input(first)
        if report["packs"] < 2:
            raise AssertionError(f"visual pack bridge is incomplete: {path.name}")
        reports.append(report)
    if {item["category"] for item in reports} != {"district", "building", "outdoor"}:
        raise AssertionError("profile visual bridge does not cover all categories")
    print(json.dumps({"status": "passed", "fixtures": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
