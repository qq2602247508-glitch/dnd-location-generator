"""CLI for validating and resolving a three-family SceneBrief."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .scene_contract import resolve_scene_profile, validate_scene_brief


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate or resolve a dnd-scene-brief-1.0")
    parser.add_argument("brief", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--resolve", action="store_true", help="emit the planner-facing resolved profile")
    args = parser.parse_args()
    brief = json.loads(args.brief.read_text(encoding="utf-8"))
    result = resolve_scene_profile(brief) if args.resolve else validate_scene_brief(brief)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
