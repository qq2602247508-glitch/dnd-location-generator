#!/usr/bin/env python3
"""Regression gate for visual scoring and seed diversity checks."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.district_composer import compose_district  # noqa: E402
from generator.v2.visual_gate import certify_visual_plan, compare_seed_variants, validate_certificate  # noqa: E402
from generator.v2.visual_packs import resolve_visual_plan  # noqa: E402


def main() -> None:
    source = json.loads((ROOT / "specs" / "districts" / "harbor_district_composer.json").read_text(encoding="utf-8"))
    first_profile = compose_district(source)
    first_plan = resolve_visual_plan(first_profile)
    first = certify_visual_plan(first_profile, first_plan)
    validate_certificate(first)
    if set(first["scores"]) != {"composition", "silhouette", "material_coherence", "vertical_readability", "tactical_legibility"}:
        raise AssertionError("visual score dimensions are incomplete")
    if first["status"] != "passed":
        raise AssertionError(f"baseline district proxy unexpectedly failed: {first}")

    variant_source = copy.deepcopy(source)
    variant_source["scene"]["seed"] += 1
    second_profile = compose_district(variant_source)
    second = certify_visual_plan(second_profile, resolve_visual_plan(second_profile))
    diversity = compare_seed_variants([first, second])
    if diversity["unique_signatures"] < 2:
        raise AssertionError("different seeds collapsed to one visual signature")
    print(json.dumps({"status": "passed", "certificate": first, "seed_diversity": diversity}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

