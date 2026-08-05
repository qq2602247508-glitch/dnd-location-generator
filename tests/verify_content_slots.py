#!/usr/bin/env python3
"""Regression gate for category-neutral NPC/monster/reward interfaces."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.building_factory import resolve_building_profile  # noqa: E402
from generator.v2.content_slots import compose_content_slots, validate_content_slots  # noqa: E402
from generator.v2.district_composer import compose_district  # noqa: E402
from generator.v2.outdoor_composer import compose_outdoor  # noqa: E402
from generator.v2.scene_contract import canonical_bytes  # noqa: E402


def main() -> None:
    dm_profile = json.loads((ROOT / "specs" / "dm_profiles" / "standard_level6.json").read_text(encoding="utf-8"))
    profiles = [
        compose_district(json.loads((ROOT / "specs" / "districts" / "harbor_district_composer.json").read_text(encoding="utf-8"))),
        compose_outdoor(json.loads((ROOT / "specs" / "outdoor" / "silverfall_outdoor_composer.json").read_text(encoding="utf-8"))),
    ]
    building = resolve_building_profile(json.loads((ROOT / "specs" / "buildings" / "darkflow_pump_house.json").read_text(encoding="utf-8")))
    building["category"] = "building"
    building["scene"] = {"id": building["building"]["id"], "name": building["building"]["name"], "seed": building["building"]["seed"]}
    profiles.append(building)
    reports = []
    for profile in profiles:
        first = compose_content_slots(profile, dm_profile)
        second = compose_content_slots(profile, dm_profile)
        if canonical_bytes(first) != canonical_bytes(second):
            raise AssertionError(f"content slots are non-deterministic: {profile['category']}")
        report = validate_content_slots(first)
        if report["population_slots"] < 2 or report["encounter_slots"] < 2 or report["reward_slots"] != report["encounter_slots"]:
            raise AssertionError(f"content slot cohort is incomplete: {profile['category']}")
        if first["external_resolution"]["writes_external_project"]:
            raise AssertionError("prototype content adapter crossed external project boundary")
        reports.append(report)
    print(json.dumps({"status": "passed", "reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

