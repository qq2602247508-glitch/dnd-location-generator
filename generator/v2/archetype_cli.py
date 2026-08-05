"""CLI for solving a declarative archetype manifest into room topology."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .archetype_manifest import canonical_bytes, load_manifest
from .room_solver import solve_room_layout, validate_room_layout


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve a D&D archetype manifest into rooms and connectors")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--width", type=int, default=24)
    parser.add_argument("--height", type=int, default=18)
    parser.add_argument("--theme", default="default")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    layout = solve_room_layout(manifest, seed=args.seed, width=args.width, height=args.height, theme_id=args.theme)
    report = validate_room_layout(layout, manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical_bytes(layout))
    args.out.with_suffix(".verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
