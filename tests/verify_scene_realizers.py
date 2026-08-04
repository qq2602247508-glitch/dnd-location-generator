#!/usr/bin/env python3
"""Regression gate for the V2.2 SceneProgram tactical-grid realizers."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.program import canonical_bytes, compile_program  # noqa: E402
from generator.v2.realize import generate_realization, realize_program, validate_grid  # noqa: E402


CELL_FIELDS = {"id", "level_id", "row", "col", "elevation", "walkable", "zone", "surface", "visibility"}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    reports = []
    programs_dir = ROOT / "output" / "programs"
    specs_dir = ROOT / "specs" / "programs"
    expected_archetypes = {"city_district", "wilderness", "infrastructure_dungeon", "special_site"}
    with tempfile.TemporaryDirectory() as left_temp, tempfile.TemporaryDirectory() as right_temp:
        left_root, right_root = Path(left_temp), Path(right_temp)
        for spec_path in sorted(specs_dir.glob("*.json")):
            slug = spec_path.stem
            frozen_path = programs_dir / f"{slug}.program.json"
            spec = read_json(spec_path)
            compiled = compile_program(spec)
            frozen = read_json(frozen_path)
            if canonical_bytes(compiled) != canonical_bytes(frozen):
                raise AssertionError(f"frozen SceneProgram drifted from planner: {slug}")
            before = canonical_bytes(frozen)
            first, second = realize_program(frozen), realize_program(frozen)
            if canonical_bytes(first) != canonical_bytes(second):
                raise AssertionError(f"realizer is non-deterministic: {slug}")
            if canonical_bytes(frozen) != before:
                raise AssertionError(f"realizer mutated SceneProgram input: {slug}")
            report = validate_grid(frozen, first)
            reports.append(report)
            left_out, right_out = left_root / slug, right_root / slug
            left_report = generate_realization(frozen_path, left_out)
            right_report = generate_realization(frozen_path, right_out)
            if left_report != right_report:
                raise AssertionError(f"generation reports drifted: {slug}")
            for filename in ("scene.grid.json", "scene.manifest.json"):
                if (left_out / filename).read_bytes() != (right_out / filename).read_bytes():
                    raise AssertionError(f"generated file is non-deterministic: {slug}/{filename}")
            committed_out = ROOT / "output" / "v22-scenes" / slug
            for filename in ("scene.grid.json", "scene.manifest.json"):
                if (committed_out / filename).read_bytes() != (left_out / filename).read_bytes():
                    raise AssertionError(f"committed realization is stale: {slug}/{filename}")
            grid = read_json(left_out / "scene.grid.json")
            manifest = read_json(left_out / "scene.manifest.json")
            if any(not CELL_FIELDS <= cell.keys() for cell in grid["cells"]):
                raise AssertionError(f"cell contract incomplete: {slug}")
            if grid["source"]["program_sha256"] != frozen["program_sha256"]:
                raise AssertionError(f"grid does not consume frozen SceneProgram: {slug}")
            if manifest["files"][0]["sha256"] != sha256(left_out / "scene.grid.json"):
                raise AssertionError(f"manifest grid hash is stale: {slug}")

            archetype = frozen["archetype"]
            if archetype == "wilderness":
                if report["rules"] != {"river_downhill": True, "legal_crossings": 2}:
                    raise AssertionError("river-valley hydraulic/crossing rules regressed")
                by_position = {(cell["row"], cell["col"]): cell for cell in grid["cells"]}
                first_contour_breaks = set()
                for col in range(36, 46):
                    breaks = [
                        row for row in range(1, grid["scene"]["grid"]["height"])
                        if by_position[(row, col)]["zone"] == "pine_slope"
                        and by_position[(row - 1, col)]["zone"] == "pine_slope"
                        and by_position[(row, col)]["elevation"] < by_position[(row - 1, col)]["elevation"]
                    ]
                    if breaks:
                        first_contour_breaks.add(breaks[0])
                if len(first_contour_breaks) < 3:
                    raise AssertionError("wilderness land contours regressed to full-width row terraces")
            elif archetype == "infrastructure_dungeon":
                rules = report["rules"]
                if rules.get("junction_degree", 0) < 3 or not rules.get("maintenance_loop") or not rules.get("pump_hall"):
                    raise AssertionError("sewer loop/junction/pump-hall rules regressed")
            elif archetype == "special_site":
                if "rooms" in grid or grid["room_dependencies"] or grid["spatial_model"] != "open_tactical_site":
                    raise AssertionError("special site illegally depends on rooms")
                if report["rules"].get("elevation_bands") not in {5, 6, 7}:
                    raise AssertionError("special site no longer has 5–7 elevation bands")
                if grid["topology"].get("contour_style") != "warped_radial":
                    raise AssertionError("special site lost its warped radial contour contract")
                terrain_cells = [
                    cell for cell in grid["cells"]
                    if "open_tactical_site" in cell.get("tags", []) and "route" not in cell.get("tags", [])
                ]
                for elevation_cap in (20, 30, 40):
                    sector_radii = []
                    for sector in range(8):
                        lower = -math.pi + sector * math.pi / 4
                        upper = lower + math.pi / 4
                        radii = [
                            math.hypot(cell["row"] - 30, cell["col"] - 30)
                            for cell in terrain_cells
                            if cell["elevation"] <= elevation_cap
                            and lower <= math.atan2(cell["row"] - 30, cell["col"] - 30) < upper
                        ]
                        if not radii:
                            raise AssertionError("special site terrain is missing an angular contour sector")
                        sector_radii.append(max(radii))
                    if max(sector_radii) - min(sector_radii) < 2.0:
                        raise AssertionError("special-site elevation boundary regressed to a near-perfect concentric ring")
            elif archetype == "city_district":
                if not grid["source"].get("mapped_runtime") or not grid["topology"].get("mapped_from_v21"):
                    raise AssertionError("harbor did not map its existing V2.1 runtime")

    if {report["archetype"] for report in reports} != expected_archetypes:
        raise AssertionError("not every V2.2 realizer archetype was exercised")
    print(json.dumps({"status": "passed", "realizers": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
