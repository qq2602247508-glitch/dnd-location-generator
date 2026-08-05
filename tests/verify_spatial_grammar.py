#!/usr/bin/env python3
"""Contract tests for the shared V2.4 spatial grammar solver."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.program import compile_program  # noqa: E402
from generator.v2.spatial_grammar import SpatialGrammarError, solve_spatial_grammar  # noqa: E402


def _programs() -> list[dict]:
    return [compile_program(json.loads(path.read_text(encoding="utf-8"))) for path in sorted((ROOT / "specs" / "programs").glob("*.json"))]


def _expect_failure(program: dict, path: tuple[str | int, ...], message: str) -> None:
    broken = copy.deepcopy(program)
    target = broken
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = message
    try:
        solve_spatial_grammar(broken)
    except SpatialGrammarError:
        return
    raise AssertionError(f"solver accepted invalid program mutation: {path}")


def main() -> None:
    programs = _programs()
    if {program["archetype"] for program in programs} != {"city_district", "wilderness", "infrastructure_dungeon", "special_site"}:
        raise AssertionError("grammar test fixtures do not cover every archetype")
    reports = [solve_spatial_grammar(program) for program in programs]
    if any(report["status"] != "passed" for report in reports):
        raise AssertionError("valid archetype failed the shared grammar")
    if any(report["topology"]["cycle_rank"] < report["topology"]["required_cycles"] for report in reports):
        raise AssertionError("cycle contract was not enforced")

    city = next(program for program in programs if program["archetype"] == "city_district")
    secret_index = next(index for index, route in enumerate(city["routes"]) if route["role"] == "secret")
    _expect_failure(city, ("routes", secret_index, "visibility"), "public")

    wilderness = next(program for program in programs if program["archetype"] == "wilderness")
    broken_wilderness = copy.deepcopy(wilderness)
    broken_wilderness["flows"][0]["direction"] = "low_to_high"
    try:
        solve_spatial_grammar(broken_wilderness)
    except SpatialGrammarError:
        pass
    else:
        raise AssertionError("watershed accepted a low_to_high-only flow")

    dungeon = next(program for program in programs if program["archetype"] == "infrastructure_dungeon")
    broken_dungeon = copy.deepcopy(dungeon)
    broken_dungeon["spatial_grammar"]["required_cycles"] = 99
    try:
        solve_spatial_grammar(broken_dungeon)
    except SpatialGrammarError:
        pass
    else:
        raise AssertionError("cycle budget accepted an impossible requirement")

    print(json.dumps({"status": "passed", "archetypes": len(reports), "grammar_version": reports[0]["version"], "cycle_ranks": [report["topology"]["cycle_rank"] for report in reports]}))


if __name__ == "__main__":
    main()
