"""CLI for composing an outdoor SceneBrief into a terrain profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .outdoor_composer import compose_outdoor, validate_outdoor_profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose a dnd-scene-brief-1.0 outdoor scene")
    parser.add_argument("brief", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args()
    result = validate_outdoor_profile(json.loads(args.validate.read_text(encoding="utf-8"))) if args.validate else compose_outdoor(json.loads(args.brief.read_text(encoding="utf-8")))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()

