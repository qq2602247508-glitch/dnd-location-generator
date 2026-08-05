#!/usr/bin/env python3
"""Regression gate for generic elevation-first outdoor composition."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.outdoor_composer import compose_outdoor, validate_outdoor_profile  # noqa: E402
from generator.v2.scene_contract import canonical_bytes  # noqa: E402


def main() -> None:
    brief = json.loads((ROOT / "specs" / "outdoor" / "silverfall_outdoor_composer.json").read_text(encoding="utf-8"))
    first = compose_outdoor(brief)
    second = compose_outdoor(brief)
    if canonical_bytes(first) != canonical_bytes(second):
        raise AssertionError("outdoor composition is non-deterministic")
    report = validate_outdoor_profile(first)
    if report["elevation_bands"] < 5 or report["route_count"] < 4:
        raise AssertionError("outdoor profile lacks elevation or route variety")
    if report["watercourses"] != 1 or report["tactical_platforms"] < 2:
        raise AssertionError("outdoor profile lost water or tactical platforms")
    if not any(feature["kind"] == "cave_mouth" for feature in first["terrain"]["features"]):
        raise AssertionError("cave trait did not produce a cave mouth")
    if not any(route["role"] == "secret" and route["visibility"] == "dm_only" for route in first["routes"]):
        raise AssertionError("secret route contract was lost")

    invalid = copy.deepcopy(brief)
    invalid["category"] = "building"
    try:
        compose_outdoor(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("non-outdoor brief was accepted")

    print(json.dumps({"status": "passed", "report": report, "required_evidence": first["quality_profile"]["required_evidence"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

