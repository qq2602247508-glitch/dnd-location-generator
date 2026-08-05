#!/usr/bin/env python3
"""Regression checks for V2.3 rule-layer exterior dressing placement."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.compiler import canonical_bytes, compile_runtime
from generator.v2.location import compile_location
from generator.v2.location_realize import (
    MARKET_DRESSING,
    SEWER_DRESSING,
    STREET_DRESSING,
    _edge_cells,
    _manhattan,
    _old_clock_layout,
    _outside_clearance,
    _scatter_poisson_like,
    compile_location_plan,
    validate_old_clock,
)


RECIPES = {
    "market": MARKET_DRESSING,
    "street": STREET_DRESSING,
    "sewer": SEWER_DRESSING,
}
EXPECTED_QUOTAS = {kind: quota for recipes in RECIPES.values() for kind, quota, _, _ in recipes}
EXPECTED_KINDS = set(EXPECTED_QUOTAS)


def _location_for_seed(brief: dict, seed: int) -> dict:
    seeded = deepcopy(brief)
    seeded["scene"]["seed"] = seed
    return compile_location(seeded)


def _protected(plan: dict) -> set[tuple[str, int, int]]:
    cells = {
        (endpoint["level_id"], endpoint["row"], endpoint["col"])
        for connector in plan["connectors"]
        for endpoint in connector["endpoints"]
    }
    cells.update((anchor["level_id"], anchor["row"], anchor["col"]) for anchor in plan["anchors"])
    return cells


def _assert_geometry(plan: dict, seed: int) -> None:
    layout = _old_clock_layout(seed, int(plan["grid"]["width"]), int(plan["grid"]["height"]))
    protected = _protected(plan)
    dressing = [
        feature for feature in plan["features"]
        if feature["id"].startswith(("market_trace_", "street_trace_", "sewer_trace_"))
    ]
    if len(plan["features"]) > 90:
        raise AssertionError("dressing exceeded the gameplay feature budget")
    if {feature["kind"] for feature in dressing} != EXPECTED_KINDS:
        raise AssertionError("a dressing kind is missing or unexpected")
    quotas = Counter(feature["kind"] for feature in dressing)
    if quotas != EXPECTED_QUOTAS:
        raise AssertionError(f"dressing quotas regressed: {quotas}")
    for feature in dressing:
        point = (feature["row"], feature["col"])
        if (feature["level_id"], *point) in protected:
            raise AssertionError(f"dressing occupies a protected endpoint or anchor: {feature['id']}")

    market_candidates = {
        point for point in layout["market"].cells
        if point in layout["surface_ground"].cells and ("surface", *point) not in protected
    }
    market_perimeter = set(_edge_cells(market_candidates, layout["market"]))
    for feature in dressing:
        point = (feature["row"], feature["col"])
        if feature["id"].startswith("market_trace_") and point not in market_perimeter:
            raise AssertionError(f"market dressing escaped the market perimeter: {feature['id']}")

    street_candidates = {
        point for point in layout["routes"].cells
        if point not in layout["market"].cells and ("surface", *point) not in protected
    }
    clearance = (
        layout["tower_entry_out"], layout["inn_entry_out"], layout["party_start"],
        layout["market_well"], *layout["hatches"],
    )
    street_candidates = set(_outside_clearance(street_candidates, clearance, 2))
    street_edges = set(_edge_cells(street_candidates, layout["routes"]))
    for feature in dressing:
        if not feature["id"].startswith("street_trace_"):
            continue
        point = (feature["row"], feature["col"])
        if point not in street_candidates:
            raise AssertionError(f"street dressing escaped a circulation route: {feature['id']}")
        if any(_manhattan(point, entrance) <= 2 for entrance in clearance):
            raise AssertionError(f"street dressing reduced entrance clearance: {feature['id']}")
        if feature["kind"] in {"puddle", "drain_grate"} and point not in street_edges:
            raise AssertionError(f"edge-bound street dressing is not on an edge: {feature['id']}")

    sewer_candidates = {
        point for point in layout["sewer_public"].cells
        if ("old_clock_sewer_b1", *point) not in protected
    }
    sewer_walls = set(_edge_cells(sewer_candidates, layout["sewer_public"]))
    channel_adjacent = {
        point for point in sewer_candidates
        if point in layout["sewage"].cells
        or any(neighbor in layout["sewage"].cells for neighbor in ((point[0] - 1, point[1]), (point[0] + 1, point[1]), (point[0], point[1] - 1), (point[0], point[1] + 1)))
    }
    for feature in dressing:
        if feature["id"].startswith("sewer_trace_") and (feature["row"], feature["col"]) not in sewer_walls | channel_adjacent:
            raise AssertionError(f"sewer dressing is away from walls and the channel: {feature['id']}")


def _assert_stream_isolation() -> None:
    candidates = [(0, col) for col in range(20)]
    target = "location:old_clock:dressing:market:market_stall:placement"
    expected = _scatter_poisson_like(candidates, 4, seed=81, stream=target, minimum_distance=3)
    _scatter_poisson_like(candidates, 4, seed=81, stream="location:old_clock:dressing:street:puddle:placement", minimum_distance=3)
    _scatter_poisson_like(candidates, 3, seed=81, stream="location:old_clock:dressing:sewer:fungus_patch:placement", minimum_distance=3)
    actual = _scatter_poisson_like(candidates, 4, seed=81, stream=target, minimum_distance=3)
    if actual != expected:
        raise AssertionError("a dressing kind's placement depends on another kind's RNG consumption")


def main() -> None:
    brief = json.loads((ROOT / "specs" / "locations" / "old_clock_quarter.json").read_text(encoding="utf-8"))
    location = _location_for_seed(brief, int(brief["scene"]["seed"]))
    first, second = compile_location_plan(location), compile_location_plan(location)
    if canonical_bytes(first) != canonical_bytes(second):
        raise AssertionError("same seed produced different dressing plans")
    runtime_first, runtime_second = compile_runtime(first), compile_runtime(second)
    if canonical_bytes(runtime_first) != canonical_bytes(runtime_second):
        raise AssertionError("same seed produced different dressing runtimes")
    validate_old_clock(first, runtime_first)
    _assert_geometry(first, int(first["scene"]["seed"]))
    _assert_stream_isolation()

    positions: dict[str, set[tuple[int, int]]] = defaultdict(set)
    variants: dict[str, set[str]] = defaultdict(set)
    for seed in range(20_260_000, 20_260_512):
        plan = compile_location_plan(_location_for_seed(brief, seed))
        runtime = compile_runtime(plan)
        validate_old_clock(plan, runtime)
        _assert_geometry(plan, seed)
        for feature in plan["features"]:
            if feature["kind"] in EXPECTED_KINDS:
                positions[feature["kind"]].add((feature["row"], feature["col"]))
                variants[feature["kind"]].add(feature["variant"])
    if any(len(positions[kind]) < 16 for kind in EXPECTED_KINDS):
        stagnant = {kind: len(positions[kind]) for kind in EXPECTED_KINDS if len(positions[kind]) < 16}
        raise AssertionError(f"cross-seed positional diversity is too low: {stagnant}")
    if any(len(variants[kind]) < 2 for kind in EXPECTED_KINDS):
        stagnant = {kind: sorted(variants[kind]) for kind in EXPECTED_KINDS if len(variants[kind]) < 2}
        raise AssertionError(f"variant entropy is too low: {stagnant}")
    print(json.dumps({"seeds": 512, "kinds": len(EXPECTED_KINDS), "feature_budget": len(first["features"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
