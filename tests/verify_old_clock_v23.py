#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.location_realize import compile_location_plan, generate_location_scene, validate_old_clock
from generator.v2.compiler import canonical_bytes, compile_runtime


def main() -> None:
    location_path = ROOT / "output" / "locations" / "old_clock_quarter.location.json"
    location = json.loads(location_path.read_text(encoding="utf-8"))
    first, second = compile_location_plan(location), compile_location_plan(location)
    if canonical_bytes(first) != canonical_bytes(second):
        raise AssertionError("old-clock V2.3 plan is not deterministic")
    runtime_first, runtime_second = compile_runtime(first), compile_runtime(second)
    if canonical_bytes(runtime_first) != canonical_bytes(runtime_second):
        raise AssertionError("old-clock V2.3 runtime is not deterministic")
    report = validate_old_clock(first, runtime_first)
    with tempfile.TemporaryDirectory() as temporary:
        manifest = generate_location_scene(location_path, Path(temporary))
        if manifest["validation"] != report:
            raise AssertionError("generated old-clock validation report differs from direct compilation")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

