#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.adapter import NullDndContentAdapter
from generator.v2.adventure import direct_adventure, validate_adventure
from generator.v2.program import canonical_bytes, compile_program


def main() -> None:
    profile = json.loads((ROOT / "specs" / "dm_profiles" / "standard_level6.json").read_text(encoding="utf-8"))
    reports = []
    for spec_path in sorted((ROOT / "specs" / "programs").glob("*.json")):
        program = compile_program(json.loads(spec_path.read_text(encoding="utf-8")))
        program_before = hashlib.sha256(canonical_bytes(program)).hexdigest()
        first, second = direct_adventure(program, profile), direct_adventure(program, profile)
        if canonical_bytes(first) != canonical_bytes(second):
            raise AssertionError("AdventureDirector output is not deterministic")
        if hashlib.sha256(canonical_bytes(program)).hexdigest() != program_before:
            raise AssertionError("AdventureDirector mutated spatial planning")
        report = validate_adventure(program, first)
        resolved = NullDndContentAdapter().resolve(program, first, {"campaign_id": "future-integration"})
        if resolved["status"] != "unresolved" or resolved["capabilities"]["writes_external_project"]:
            raise AssertionError("Null adapter crossed the prototype integration boundary")
        if resolved["slots"] != first["content"]:
            raise AssertionError("Null adapter did not preserve content slots")
        reports.append(report)
    print(json.dumps({"status": "passed", "adventures": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
