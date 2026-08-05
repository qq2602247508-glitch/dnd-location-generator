"""Create a Blender/Viewer-ready profile visual input from a SceneBrief."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .profile_visual import compose_profile_visual_input, validate_profile_visual_input


def main() -> None:
    parser = argparse.ArgumentParser(description="Build dnd-profile-visual-input-1.0")
    parser.add_argument("brief", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    document = json.loads(args.brief.read_text(encoding="utf-8"))
    result = compose_profile_visual_input(document)
    report = validate_profile_visual_input(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

