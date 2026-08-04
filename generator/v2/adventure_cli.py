from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adventure import direct_adventure, validate_adventure
from .program import canonical_bytes, compile_program


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AdventureDirector content slots for a SceneProgram spec")
    parser.add_argument("program_spec", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    program = compile_program(json.loads(args.program_spec.read_text(encoding="utf-8")))
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    adventure = direct_adventure(program, profile)
    report = validate_adventure(program, adventure)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical_bytes(adventure))
    args.out.with_suffix(".verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
