#!/usr/bin/env python3
"""Regression gate for district roads, lots, landmarks and building collage."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.district_composer import compose_district, validate_district_profile  # noqa: E402
from generator.v2.scene_contract import canonical_bytes  # noqa: E402


def main() -> None:
    brief = json.loads((ROOT / "specs" / "districts" / "harbor_district_composer.json").read_text(encoding="utf-8"))
    first = compose_district(brief)
    second = compose_district(brief)
    if canonical_bytes(first) != canonical_bytes(second):
        raise AssertionError("district composition is non-deterministic")
    report = validate_district_profile(first)
    if report["building_count"] < 8 or report["road_count"] < 5:
        raise AssertionError("district composition is too small")
    if report["landmark_count"] != 2 or "tower" not in report["building_types"]:
        raise AssertionError("landmark building was not composed")
    if report["orientation_count"] < 2:
        raise AssertionError("district lacks facade orientation variation")
    if first["planning"]["building_count"]["mode"] != "derived":
        raise AssertionError("fixture should exercise derived building count")
    if first["quality_profile"]["required_evidence"] != ["street_network", "landmark_hierarchy", "building_mix", "irregular_lots", "skyline_variation"]:
        raise AssertionError("district visual evidence contract changed")

    invalid = copy.deepcopy(brief)
    invalid["planning"]["building_mix"][0]["id"] = "future_palace"
    try:
        compose_district(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown building type was accepted by district composer")

    print(json.dumps({"status": "passed", "report": report, "skyline": first["skyline"], "entries": first["entries"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
