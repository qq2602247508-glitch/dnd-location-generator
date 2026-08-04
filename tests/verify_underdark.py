#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.underdark_core import load_and_generate  # noqa: E402


if __name__ == "__main__":
    _, _, report = load_and_generate(ROOT / "specs" / "underdark.json")
    print(json.dumps(report, ensure_ascii=False, indent=2))
