#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.location import compile_location, infer_capabilities, resolve_packs, validate_location
from generator.v2.program import canonical_bytes


def main() -> None:
    brief_path = ROOT / "specs" / "locations" / "old_clock_quarter.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    first = compile_location(brief)
    second = compile_location(brief)
    if canonical_bytes(first) != canonical_bytes(second):
        raise AssertionError("V2.3 location compiler is not deterministic")
    report = validate_location(first)

    inferred = infer_capabilities(brief["prompt"])
    expected = {"deepwater_style", "irregular_streets", "clock_tower", "inn", "market", "roof_route", "sewer", "smuggler_route", "lived_in_dressing"}
    if not expected <= inferred:
        raise AssertionError(f"deterministic brief inference missed capabilities: {sorted(expected - inferred)}")
    inferred_brief = {**brief, "required_capabilities": []}
    inferred_packs, inferred_requested = resolve_packs(inferred_brief)
    if not expected <= set(inferred_requested) or len(inferred_packs) < 9:
        raise AssertionError("prompt-only one-click pack resolution is incomplete")
    if report["quality_score"] < 90 or report["buildings"] != 7 or report["enterable_buildings"] != 2:
        raise AssertionError("old-clock pressure hierarchy regressed")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

