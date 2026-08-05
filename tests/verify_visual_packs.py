#!/usr/bin/env python3
"""Regression gate for shared visual packs and four-view evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.building_factory import resolve_building_profile  # noqa: E402
from generator.v2.district_composer import compose_district  # noqa: E402
from generator.v2.outdoor_composer import compose_outdoor  # noqa: E402
from generator.v2.scene_contract import resolve_scene_profile  # noqa: E402
from generator.v2.visual_packs import PACK_RECIPES, resolve_visual_plan, validate_visual_plan  # noqa: E402


def main() -> None:
    district = compose_district(json.loads((ROOT / "specs" / "districts" / "harbor_district_composer.json").read_text(encoding="utf-8")))
    outdoor = compose_outdoor(json.loads((ROOT / "specs" / "outdoor" / "silverfall_outdoor_composer.json").read_text(encoding="utf-8")))
    building = resolve_building_profile(json.loads((ROOT / "specs" / "buildings" / "darkflow_pump_house.json").read_text(encoding="utf-8")))
    building["category"] = "building"
    building["scene"] = building["building"] | {"seed": building["building"]["seed"]}
    profiles = {"district": district, "building": building, "outdoor": outdoor}
    reports = {}
    for category, profile in profiles.items():
        first = resolve_visual_plan(profile)
        second = resolve_visual_plan(profile)
        if first != second:
            raise AssertionError(f"visual plan is non-deterministic: {category}")
        reports[category] = validate_visual_plan(first)
        if first["evidence"]["required_views"] != ["far", "mid", "near", "tactical"]:
            raise AssertionError(f"four-view evidence missing: {category}")
    if set(PACK_RECIPES) != {"street_network", "urban_facades", "water_edge", "dockside", "landmark_detail", "vertical_connections", "room_dressing", "lived_in_detail", "masonry_defense", "utility_detail", "hydrology", "rock_formation", "terrain_detail", "ruin_detail", "secret_detail"}:
        raise AssertionError("visual pack registry is incomplete")
    scene_profile = resolve_scene_profile(json.loads((ROOT / "specs" / "scene_briefs" / "silverfall_outdoor.json").read_text(encoding="utf-8")))
    scene_profile["scene"] = {"seed": 20260807}
    if validate_visual_plan(resolve_visual_plan(scene_profile))["category"] != "outdoor":
        raise AssertionError("scene profile cannot feed visual resolver")
    print(json.dumps({"status": "passed", "registered_packs": len(PACK_RECIPES), "reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

