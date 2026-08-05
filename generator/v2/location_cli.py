from __future__ import annotations

import argparse
import json
from pathlib import Path

from .location import compile_location, validate_location
from .program import canonical_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a deterministic one-click D&D LocationBrief")
    parser.add_argument("brief", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    brief = json.loads(args.brief.read_text(encoding="utf-8"))
    program = compile_location(brief)
    report = validate_location(program)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical_bytes(program))
    args.out.with_suffix(".verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

