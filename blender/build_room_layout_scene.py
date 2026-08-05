"""Build Blender assets for a V2.5 room layout.

This is intentionally a thin adapter.  It writes the existing V2 scene plan
contract, then invokes ``build_scene_v2`` so generated archetypes share the
same low-poly geometry, metadata, GLB export and camera framing as the harbor
and old-clock scenes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BLENDER_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BLENDER_DIR) not in sys.path:
    sys.path.insert(0, str(BLENDER_DIR))

from generator.v2.archetype_manifest import load_manifest
from generator.v2.layout_plan import compile_layout_plan, canonical_plan_bytes
from generator.v2.layout_runtime import compile_layout_runtime, validate_layout_runtime


def _args() -> tuple[Path, Path, Path | None]:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    def value(name: str, required: bool = True) -> Path | None:
        if name not in args:
            if required:
                raise SystemExit(f"missing {name}")
            return None
        return Path(args[args.index(name) + 1]).expanduser().resolve()
    layout = value("--layout")
    out_dir = value("--out-dir")
    manifest = value("--manifest", required=False)
    assert layout is not None and out_dir is not None
    return layout, out_dir, manifest


def main() -> None:
    layout_path, out_dir, manifest_path = _args()
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    manifest = load_manifest(manifest_path) if manifest_path else None
    runtime = compile_layout_runtime(layout, manifest=manifest)
    validate_layout_runtime(runtime, layout)
    plan = compile_layout_plan(layout, runtime=runtime, manifest=manifest)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scene.runtime.json").write_bytes(json.dumps(runtime, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    (out_dir / "scene.plan.json").write_bytes(canonical_plan_bytes(plan))

    # build_scene_v2 resolves its input directory from the Blender command
    # line.  Import only after the adapter files exist because that module
    # loads the plan/runtime at import time.
    sys.argv.extend(["--input-dir", str(out_dir)])
    from build_scene_v2 import build  # type: ignore

    build()


if __name__ == "__main__":
    main()
