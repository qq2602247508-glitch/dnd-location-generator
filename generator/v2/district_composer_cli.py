"""CLI for composing a district SceneBrief into a deterministic profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .district_composer import compose_district, validate_district_profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose a dnd-scene-brief-1.0 district")
    parser.add_argument("brief", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--validate", type=Path, help="validate an existing district profile")
    args = parser.parse_args()
    if args.validate:
        result = validate_district_profile(json.loads(args.validate.read_text(encoding="utf-8")))
    else:
        result = compose_district(json.loads(args.brief.read_text(encoding="utf-8")))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()

