#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.program import canonical_bytes, compile_program, generate_program, validate_program


def main() -> None:
    reports = []
    with tempfile.TemporaryDirectory() as temporary:
        temp = Path(temporary)
        for spec_path in sorted((ROOT / "specs" / "programs").glob("*.json")):
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            first, second = compile_program(spec), compile_program(spec)
            if canonical_bytes(first) != canonical_bytes(second):
                raise AssertionError(f"program is not deterministic: {spec_path.name}")
            direct = validate_program(first)
            generated = generate_program(spec_path, temp / f"{spec_path.stem}.program.json")
            if direct != generated:
                raise AssertionError("direct and file generation reports differ")
            reports.append(direct)
    archetypes = {item["archetype"] for item in reports}
    if archetypes != {"city_district", "wilderness", "infrastructure_dungeon", "special_site"}:
        raise AssertionError("not every V2.2 planner archetype was exercised")
    if min(item["quality_score"] for item in reports) < 85:
        raise AssertionError("program quality gate regressed")
    print(json.dumps({"status": "passed", "programs": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
