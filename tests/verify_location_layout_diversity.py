#!/usr/bin/env python3
"""Regression gate for Old Clock Quarter macro-layout diversity.

The fingerprint intentionally excludes the scene seed and all feature dressing.
It therefore catches a regression where only props vary while streets, building
geometry, connectors and play anchors remain fixed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.compiler import canonical_bytes, compile_runtime
from generator.v2.location import compile_location
from generator.v2.location_realize import compile_location_plan, validate_old_clock
from generator.v2.mask import CellMask


SEEDS = (
    20260806,
    20260807,
    20260808,
    20260809,
    20260810,
    20260811,
    20260812,
    20260813,
)


def _mask(plan: dict[str, Any], terrain_id: str) -> frozenset[tuple[int, int]]:
    terrain = next(item for item in plan["terrain"] if item["id"] == terrain_id)
    return CellMask.from_rle(terrain["cell_mask"]).cells


def _building_cells(plan: dict[str, Any]) -> frozenset[tuple[str, int, int]]:
    levels = {level["id"]: level for level in plan["levels"]}
    return frozenset(
        (volume["id"], row, col)
        for volume in plan["volumes"]
        if volume["kind"] in {"building", "tower"}
        for row, col in CellMask.from_rle(levels[volume["level_ids"][0]]["cell_mask"]).cells
    )


def _connector_cells(plan: dict[str, Any]) -> frozenset[tuple[str, int, str, int, int]]:
    return frozenset(
        (connector["id"], index, endpoint["level_id"], endpoint["row"], endpoint["col"])
        for connector in plan["connectors"]
        for index, endpoint in enumerate(connector["endpoints"])
    )


def _structural_fingerprint(plan: dict[str, Any]) -> str:
    levels = {level["id"]: level for level in plan["levels"]}
    structural = {
        "terrain": [
            (item["id"], item["level_id"], item["cell_mask"])
            for item in plan["terrain"]
        ],
        "building_levels": [
            (volume["id"], levels[volume["level_ids"][0]]["cell_mask"])
            for volume in plan["volumes"]
            if volume["kind"] in {"building", "tower"}
        ],
        "parcels": [(item["id"], item["cell_mask"]) for item in plan["parcels"]],
        "connectors": [
            (item["id"], item["type"], item["endpoints"])
            for item in plan["connectors"]
        ],
        "anchors": [
            (item["id"], item["level_id"], item["row"], item["col"])
            for item in plan["anchors"]
        ],
    }
    return hashlib.sha256(canonical_bytes(structural)).hexdigest()


def _relative_delta(left: frozenset[Any], right: frozenset[Any]) -> float:
    union = left | right
    return len(left ^ right) / len(union) if union else 0.0


def _semantic_delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, float]:
    road = _relative_delta(_mask(left, "old_clock_streets"), _mask(right, "old_clock_streets"))
    buildings = _relative_delta(_building_cells(left), _building_cells(right))
    connectors = _relative_delta(_connector_cells(left), _connector_cells(right))
    return {
        "roads": road,
        "buildings": buildings,
        "connectors": connectors,
        "combined": (road + buildings + connectors) / 3,
    }


def _compile_seed(brief: dict[str, Any], seed: int) -> dict[str, Any]:
    seeded_brief = copy.deepcopy(brief)
    seeded_brief["scene"]["seed"] = seed
    location = compile_location(seeded_brief)
    first = compile_location_plan(location)
    second = compile_location_plan(location)
    if canonical_bytes(first) != canonical_bytes(second):
        raise AssertionError(f"layout is not deterministic for seed {seed}")
    runtime_first, runtime_second = compile_runtime(first), compile_runtime(second)
    if canonical_bytes(runtime_first) != canonical_bytes(runtime_second):
        raise AssertionError(f"runtime is not deterministic for seed {seed}")
    validate_old_clock(first, runtime_first)
    return first


def main() -> None:
    brief_path = ROOT / "specs" / "locations" / "old_clock_quarter.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    plans = {seed: _compile_seed(brief, seed) for seed in SEEDS}
    fingerprints = {seed: _structural_fingerprint(plan) for seed, plan in plans.items()}
    unique_ratio = len(set(fingerprints.values())) / len(SEEDS)
    if unique_ratio < 0.75:
        raise AssertionError(f"layout fingerprint uniqueness regressed: {unique_ratio:.2%}")

    pair_deltas: dict[str, dict[str, float]] = {}
    for left_seed, right_seed in combinations(SEEDS, 2):
        delta = _semantic_delta(plans[left_seed], plans[right_seed])
        pair_deltas[f"{left_seed}-{right_seed}"] = delta
        if delta["roads"] < 0.10 or delta["buildings"] < 0.10:
            raise AssertionError(
                f"seed pair {left_seed}/{right_seed} lacks independent street and building variation: {delta}"
            )
        if delta["combined"] < 0.10:
            raise AssertionError(f"seed pair {left_seed}/{right_seed} lacks meaningful semantic variation: {delta}")

    print(json.dumps({
        "status": "passed",
        "seeds": len(SEEDS),
        "unique_fingerprints": len(set(fingerprints.values())),
        "unique_ratio": unique_ratio,
        "minimum_pair_delta": {
            key: min(delta[key] for delta in pair_deltas.values())
            for key in ("roads", "buildings", "connectors", "combined")
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
