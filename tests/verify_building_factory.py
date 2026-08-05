#!/usr/bin/env python3
"""Regression gate for extensible standalone building recipes."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.building_factory import BUILDING_CATALOG, resolve_building_profile, validate_building_brief  # noqa: E402
from generator.v2.scene_contract import canonical_bytes  # noqa: E402


def brief(building_type: str, seed: int) -> dict:
    return {
        "schema_version": "dnd-building-brief-1.0",
        "building": {"id": f"sample_{building_type}", "name": building_type, "type": building_type, "seed": seed},
        "scale": "medium",
        "traits": [],
        "packs": [],
        "floors": {"mode": "derived"},
    }


def main() -> None:
    profiles = []
    for index, building_type in enumerate(sorted(BUILDING_CATALOG)):
        source = brief(building_type, 20300000 + index)
        report = validate_building_brief(source)
        first = resolve_building_profile(source)
        second = resolve_building_profile(source)
        if canonical_bytes(first) != canonical_bytes(second):
            raise AssertionError(f"building profile is non-deterministic: {building_type}")
        if first["building"]["type"] != building_type or not first["room_grammar"] or not first["packs"]:
            raise AssertionError(f"building recipe is incomplete: {building_type}")
        if first["source_brief_sha256"] != report["brief_sha256"]:
            raise AssertionError(f"building brief hash mismatch: {building_type}")
        profiles.append(first)

    fixture_profiles = []
    for path in sorted((ROOT / "specs" / "buildings").glob("*.json")):
        source = json.loads(path.read_text(encoding="utf-8"))
        validate_building_brief(source)
        fixture_profiles.append(resolve_building_profile(source))
    if {profile["building"]["type"] for profile in fixture_profiles} != {"tower", "inn", "pump_house"}:
        raise AssertionError("standalone building fixture cohort is incomplete")
    if next(profile for profile in fixture_profiles if profile["building"]["type"] == "pump_house")["floor_policy"] != {"mode": "target", "value": 3}:
        raise AssertionError("pump house floor target was not preserved")

    if len({profile["footprint"] for profile in profiles}) < 6:
        raise AssertionError("building recipes collapsed to too few footprint grammars")
    if not any(profile["vertical_grammar"] == "low_channel_catwalk_pump_deck" for profile in profiles):
        raise AssertionError("pump house lost its split-level vertical grammar")

    invalid = brief("tower", 20301000)
    invalid["traits"] = ["urban_density"]
    try:
        validate_building_brief(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("district-only trait was accepted by building factory")

    unknown = copy.deepcopy(brief("tower", 20301001))
    unknown["building"]["type"] = "future_palace"
    try:
        validate_building_brief(unknown)
    except ValueError:
        pass
    else:
        raise AssertionError("unregistered building type was accepted")

    print(json.dumps({
        "status": "passed",
        "building_types": len(BUILDING_CATALOG),
        "standalone_fixtures": len(fixture_profiles),
        "footprint_grammars": len({profile["footprint"] for profile in profiles}),
        "profiles": [{"type": item["building"]["type"], "family": item["family"], "floors": item["floor_policy"], "packs": len(item["packs"])} for item in profiles],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
