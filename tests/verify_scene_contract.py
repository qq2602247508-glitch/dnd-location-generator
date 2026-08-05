#!/usr/bin/env python3
"""Regression gate for the extensible three-family scene contract."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.scene_contract import (  # noqa: E402
    CATEGORIES,
    PACK_REGISTRY,
    TRAIT_REGISTRY,
    canonical_bytes,
    resolve_scene_profile,
    validate_scene_brief,
)


def main() -> None:
    fixture_paths = sorted((ROOT / "specs" / "scene_briefs").glob("*.json"))
    if {path.stem for path in fixture_paths} != {"harbor_district", "silverfall_outdoor", "tower_building"}:
        raise AssertionError("scene brief fixture cohort changed unexpectedly")
    profiles = []
    for path in fixture_paths:
        brief = json.loads(path.read_text(encoding="utf-8"))
        report = validate_scene_brief(brief)
        first = resolve_scene_profile(brief)
        second = resolve_scene_profile(brief)
        if canonical_bytes(first) != canonical_bytes(second):
            raise AssertionError(f"scene profile is non-deterministic: {path.name}")
        if first["category"] not in CATEGORIES or not first["packs"]:
            raise AssertionError(f"scene profile lost category/packs: {path.name}")
        if first["source_brief_sha256"] != report["brief_sha256"]:
            raise AssertionError(f"brief hash mismatch: {path.name}")
        profiles.append(first)

    if {profile["category"] for profile in profiles} != set(CATEGORIES):
        raise AssertionError("scene brief cohort does not cover all three top-level families")
    if "building_count" not in profiles[0]["planning"]:
        raise AssertionError("district brief must express derived building count")

    invalid = copy.deepcopy(json.loads((ROOT / "specs" / "scene_briefs" / "tower_building.json").read_text(encoding="utf-8")))
    invalid["traits"].append("urban_density")
    try:
        validate_scene_brief(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("category-incompatible trait was accepted")

    unknown_pack = copy.deepcopy(json.loads((ROOT / "specs" / "scene_briefs" / "harbor_district.json").read_text(encoding="utf-8")))
    unknown_pack["packs"] = ["future_pack"]
    try:
        validate_scene_brief(unknown_pack)
    except ValueError:
        pass
    else:
        raise AssertionError("unregistered visual pack was accepted")

    print(json.dumps({
        "status": "passed",
        "categories": list(CATEGORIES),
        "registered_traits": len(TRAIT_REGISTRY),
        "registered_packs": len(PACK_REGISTRY),
        "fixtures": [{"scene_id": item["scene"]["id"], "category": item["category"], "packs": len(item["packs"])} for item in profiles],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
