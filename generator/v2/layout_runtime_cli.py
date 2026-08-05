"""CLI for compiling room layouts into Viewer runtime JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .archetype_manifest import canonical_bytes, load_manifest
from .layout_runtime import compile_layout_runtime, validate_layout_runtime
from .room_solver import validate_room_layout


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a room.layout.json into scene.runtime.json")
    parser.add_argument("layout", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    layout = json.loads(args.layout.read_text(encoding="utf-8"))
    manifest = load_manifest(args.manifest) if args.manifest else None
    if manifest:
        validate_room_layout(layout, manifest)
    runtime = compile_layout_runtime(layout, manifest=manifest)
    report = validate_layout_runtime(runtime, layout)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical_bytes(runtime))
    args.out.with_suffix(".verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
