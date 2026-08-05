"""CLI for resolving an independent BuildingBrief into a factory profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .building_factory import resolve_building_profile, validate_building_brief


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate or resolve a dnd-building-brief-1.0")
    parser.add_argument("brief", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--resolve", action="store_true")
    args = parser.parse_args()
    brief = json.loads(args.brief.read_text(encoding="utf-8"))
    result = resolve_building_profile(brief) if args.resolve else validate_building_brief(brief)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
