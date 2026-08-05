#!/usr/bin/env python3
"""Materialize one visual input for every registered building recipe.

The showcase is generated from the catalog rather than a hand-maintained list
of scene branches.  It is intentionally safe to rerun: existing hand-tuned
validation fixtures (tower/manor/sewer) are preserved byte-for-byte.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.building_factory import BUILDING_CATALOG
from generator.v2.profile_visual import compose_profile_visual_input


SPEC_ROOT = ROOT / "specs" / "buildings"
PROFILE_ROOT = ROOT / "output" / "profile-visual"
HAND_TUNED = {"tower", "manor", "sewer", "pump_house"}
NAMES = {
    "barracks": "边墙兵营",
    "cavern": "菌光洞窟",
    "church": "圣烛教堂",
    "fortress": "灰石堡垒",
    "inn": "盐风旅店",
    "lighthouse": "潮灯塔",
    "library": "星图图书馆",
    "mine": "黑脉矿井",
    "ruin": "坍塌遗迹",
    "tavern": "铜杯酒馆",
    "temple": "月门神殿",
    "warehouse": "潮仓",
    "workshop": "船匠工坊",
}


def main() -> None:
    generated = []
    for index, building_type in enumerate(sorted(BUILDING_CATALOG)):
        if building_type in HAND_TUNED:
            continue
        recipe = BUILDING_CATALOG[building_type]
        policy = recipe["floor_policy"]
        floors = min(int(policy["maximum"]), max(2, int(policy["minimum"]) + 1))
        scene_id = f"visual_{building_type}"
        brief = {
            "schema_version": "dnd-building-brief-1.0",
            "building": {
                "id": scene_id,
                "name": f"{NAMES.get(building_type, building_type)}·通用验证",
                "type": building_type,
                "seed": 20260820 + index,
            },
            "scale": "large" if building_type in {"fortress", "library", "cavern", "mine"} else "medium",
            "traits": [],
            "packs": [],
            "floors": {"mode": "target", "value": floors},
        }
        input_document = compose_profile_visual_input(brief)
        (SPEC_ROOT / f"{scene_id}.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (PROFILE_ROOT / f"{scene_id}.json").write_text(json.dumps(input_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (PROFILE_ROOT / scene_id).mkdir(parents=True, exist_ok=True)
        generated.append(scene_id)
    print(json.dumps({"status": "passed", "generated": generated}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
