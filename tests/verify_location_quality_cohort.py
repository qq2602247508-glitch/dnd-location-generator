#!/usr/bin/env python3
"""Run the generic V2.4 evaluator against unseen location seeds.

Only the canonical seed is rendered each iteration.  Cohort samples reuse its
measured performance as a labelled proxy while every plan/runtime, hard gate,
layout fingerprint and spatial score is recomputed from that seed's artifacts.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.compiler import canonical_bytes, compile_runtime
from generator.v2.location import compile_location
from generator.v2.location_realize import compile_location_plan, validate_old_clock
from generator.v2.quality import evaluate_cohort, evaluate_scene, load_policy


ROUND_SAMPLE_COUNTS = {"round1": 8, "round2": 24, "round3": 64}
SEED_START = 731_029
SEED_STEP = 104_729


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", choices=tuple(ROUND_SAMPLE_COUNTS), default="round1")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--performance-report", type=Path, default=ROOT / "output" / "quality-v24" / "round-1" / "quality.report.json")
    args = parser.parse_args()

    brief = json.loads((ROOT / "specs" / "locations" / "old_clock_quarter.json").read_text(encoding="utf-8"))
    policy = copy.deepcopy(load_policy())
    policy["hard_gates"]["require_render_manifest"] = False
    performance_report = json.loads(args.performance_report.read_text(encoding="utf-8"))
    proxy = performance_report["dimensions"]["performance"]["raw"]

    reports = []
    for index in range(ROUND_SAMPLE_COUNTS[args.round]):
        seeded = copy.deepcopy(brief)
        seeded["scene"]["seed"] = SEED_START + index * SEED_STEP
        location = compile_location(seeded)
        first = compile_location_plan(location)
        second = compile_location_plan(location)
        if canonical_bytes(first) != canonical_bytes(second):
            raise AssertionError(f"plan determinism failed for seed {seeded['scene']['seed']}")
        runtime = compile_runtime(first)
        validate_old_clock(first, runtime)
        receipts = {
            "runtime_bytes": len(canonical_bytes(runtime)),
            "glb_bytes": int(proxy["glb_bytes"]),
            "draw_calls": int(proxy["draw_calls"]),
            "vertices": int(proxy["vertices"]),
            "build_seconds": float(proxy["build_seconds"]),
            "performance_proxy": "canonical-render-from-same-algorithm-version",
        }
        reports.append(evaluate_scene(first, runtime, None, policy=policy, receipts=receipts))

    cohort = evaluate_cohort(reports, policy=policy, round_name=args.round)
    if cohort["status"] != "passed":
        raise AssertionError(json.dumps(cohort, ensure_ascii=False, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(cohort, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(cohort, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
