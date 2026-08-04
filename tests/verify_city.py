#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.city_core import load_and_generate  # noqa: E402


if __name__ == "__main__":
    _, _, report = load_and_generate(ROOT / "specs" / "city.json")
    if report["building_count"] != 7 or report["multi_level_buildings"] < 1:
        raise AssertionError("city must have seven buildings including a multi-level building")
    if report["physical_size_ft"] != [160, 140]:
        raise AssertionError("unexpected city dimensions")
    print(json.dumps(report, ensure_ascii=False, indent=2))
