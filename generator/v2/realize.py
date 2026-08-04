"""Deterministic V2.2 SceneProgram -> tactical-grid realization.

The V2.1 compiler remains the owner of the harbor's production ``scene.plan``
and ``scene.runtime`` contracts.  This module is deliberately a sibling rather
than a change to that compiler: it realizes the higher-level V2.2 SceneProgram
into a small, renderer-neutral tactical-grid contract that a later Blender
builder and viewer loader can consume together.

The contract is intentionally explicit.  A cell always carries its spatial and
tabletop meaning (coordinates, elevation, movement, zone, surface and
visibility); routes are cell sequences; anchors bind program nodes to geometry;
and slots preserve the unresolved AdventureDirector boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable, Mapping

from .program import SUPPORTED_ARCHETYPES, canonical_bytes, validate_program


GRID_SCHEMA = "dnd-tactical-grid-1.0"
GRID_VERSION = "2.2.0-prototype.1"
MANIFEST_SCHEMA = "dnd-tactical-grid-manifest-1.0"
ROOT = Path(__file__).resolve().parents[2]

Point = tuple[int, int]
LayerPoint = tuple[str, int, int]


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _slug(program: Mapping[str, Any]) -> str:
    scene_id = str(program["scene"]["id"])
    return scene_id[:-8] if scene_id.endswith("_program") else scene_id


def _cell_id(level_id: str, row: int, col: int) -> str:
    return f"{level_id}:{row}:{col}"


def _dedupe(values: Iterable[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if not result or value != result[-1]:
            result.append(value)
    return result


def _orthogonal_path(points: Iterable[Point], *, horizontal_first: bool = True) -> list[Point]:
    """Expand waypoint pairs into an ordered 4-neighbour path."""

    waypoints = list(points)
    if not waypoints:
        return []
    result = [waypoints[0]]
    for target_row, target_col in waypoints[1:]:
        row, col = result[-1]
        axes = (("col", target_col), ("row", target_row)) if horizontal_first else (("row", target_row), ("col", target_col))
        for axis, target in axes:
            if axis == "col":
                while col != target:
                    col += 1 if target > col else -1
                    result.append((row, col))
            else:
                while row != target:
                    row += 1 if target > row else -1
                    result.append((row, col))
    return _dedupe(result)


def _round_to(value: float, step: int = 5) -> int:
    return int(round(value / step) * step)


class TacticalCanvas:
    """Mutable construction helper; serialized output is plain deterministic JSON."""

    def __init__(self, width: int, height: int, *, level_id: str = "surface", z_base_ft: int = 0) -> None:
        self.width = width
        self.height = height
        self.level_id = level_id
        self.z_base_ft = z_base_ft
        self.cells: dict[Point, dict[str, Any]] = {}
        for row in range(height):
            for col in range(width):
                self.cells[(row, col)] = {
                    "id": _cell_id(level_id, row, col),
                    "level_id": level_id,
                    "row": row,
                    "col": col,
                    "elevation": z_base_ft,
                    "walkable": False,
                    "zone": "void",
                    "surface": "void",
                    "visibility": "public",
                    "tags": [],
                }

    def contains(self, point: Point) -> bool:
        row, col = point
        return 0 <= row < self.height and 0 <= col < self.width

    def cell(self, point: Point) -> dict[str, Any]:
        if point not in self.cells:
            raise ValueError(f"cell is outside tactical canvas: {point}")
        return self.cells[point]

    def cell_id(self, point: Point) -> str:
        return self.cell(point)["id"]

    def set(self, point: Point, **changes: Any) -> None:
        cell = self.cell(point)
        tags = changes.pop("tags", None)
        cell.update(changes)
        if tags is not None:
            cell["tags"] = sorted(set(cell.get("tags", [])) | {str(tag) for tag in tags})

    def paint(self, points: Iterable[Point], **changes: Any) -> None:
        for point in _dedupe(points):
            self.set(point, **changes)

    def rect(self, row: int, col: int, height: int, width: int, **changes: Any) -> None:
        self.paint(((r, c) for r in range(row, row + height) for c in range(col, col + width) if self.contains((r, c))), **changes)

    def sorted_cells(self) -> list[dict[str, Any]]:
        return [self.cells[(row, col)] for row, col in sorted(self.cells)]


def _grade(canvas: TacticalCanvas, path: list[Point], elevations: list[int], *, step: int = 10) -> None:
    """Assign discrete, renderer-friendly elevations along a waypoint route."""

    if len(path) != len(elevations):
        raise ValueError("grade requires a per-cell elevation list")
    for point, elevation in zip(path, elevations):
        canvas.set(point, elevation=_round_to(elevation, step))


def _graded_waypoints(canvas: TacticalCanvas, points: list[Point], elevations: list[int], *, horizontal_first: bool = True) -> list[Point]:
    if len(points) != len(elevations):
        raise ValueError("waypoint grades must match waypoint count")
    full: list[Point] = []
    for index, (left, right) in enumerate(zip(points, points[1:])):
        segment = _orthogonal_path([left, right], horizontal_first=horizontal_first)
        count = max(1, len(segment) - 1)
        values = [_round_to(elevations[index] + (elevations[index + 1] - elevations[index]) * offset / count, 10) for offset in range(len(segment))]
        _grade(canvas, segment, values, step=10)
        full.extend(segment if not full else segment[1:])
    if len(points) == 1:
        canvas.set(points[0], elevation=elevations[0])
        return points
    return full


def _route_cells(canvas: TacticalCanvas, path: Iterable[Point]) -> list[str]:
    return [canvas.cell_id(point) for point in _dedupe(path)]


def _paint_route(
    canvas: TacticalCanvas,
    path: Iterable[Point],
    *,
    surface: str,
    tags: Iterable[str],
    visibility: str = "public",
    preserve_surfaces: frozenset[str] = frozenset({"water", "ford", "bridge"}),
) -> None:
    for point in _dedupe(path):
        cell = canvas.cell(point)
        if cell["surface"] == "water":
            raise AssertionError(f"route would cross water without a legal crossing: {point}")
        updates: dict[str, Any] = {"walkable": True, "visibility": visibility, "tags": [*tags, "graded_route"]}
        if cell["surface"] not in preserve_surfaces:
            updates["surface"] = surface
        canvas.set(point, **updates)


def _node_locations(
    program: Mapping[str, Any],
    canvas: TacticalCanvas,
    locations: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for node in program["nodes"]:
        location = locations.get(node["id"])
        if location is None:
            raise ValueError(f"missing geometric location for SceneProgram node: {node['id']}")
        row, col = int(location["row"]), int(location["col"])
        cell = canvas.cell((row, col))
        zone = str(location.get("zone", node.get("zone_id", cell["zone"])))
        visibility = str(location.get("visibility", "public"))
        canvas.set((row, col), walkable=True, zone=zone, visibility=visibility, tags=["program_anchor", node["id"]])
        anchors.append({
            "id": node["id"],
            "source_node_id": node["id"],
            "name": node["name"],
            "kind": node["role"],
            "zone": zone,
            "cell_id": cell["id"],
            "level_id": cell["level_id"],
            "row": row,
            "col": col,
            "elevation": cell["elevation"],
            "visibility": visibility,
            "tactical_role": location.get("tactical_role", node["role"]),
        })
    return sorted(anchors, key=lambda item: item["id"])


def _route_records(program: Mapping[str, Any], paths: Mapping[str, list[str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for route in program["routes"]:
        route_path = paths.get(route["id"])
        if not route_path:
            raise ValueError(f"missing geometric route for SceneProgram route: {route['id']}")
        records.append({
            "id": route["id"],
            "source_route_id": route["id"],
            "name": route["name"],
            "role": route["role"],
            "from_anchor_id": route["from"],
            "to_anchor_id": route["to"],
            "via_anchor_ids": list(route.get("via", [])),
            "visibility": route["visibility"],
            "traversal": route["traversal"],
            "risk": route["risk"],
            "cell_ids": _dedupe(route_path),
        })
    return sorted(records, key=lambda item: item["id"])


def _slot_records(program: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    encounter_nodes = [item for item in program["nodes"] if item["role"] not in {"entry", "exit", "secret"}]
    return {
        "population": sorted([
            {
                "id": f"population_{faction['id']}",
                "source_faction_id": faction["id"],
                "zone": faction["home_zone"],
                "role": faction["role"],
                "resolution_status": "slot",
            }
            for faction in program["factions"]
        ], key=lambda item: item["id"]),
        "encounters": sorted([
            {
                "id": f"encounter_{node['id']}",
                "anchor_id": node["id"],
                "role": "boss" if node["role"] == "boss" else "set_piece",
                "resolution_status": "slot",
            }
            for node in encounter_nodes
        ], key=lambda item: item["id"]),
        "rewards": sorted([
            {
                "id": f"reward_{node['id']}",
                "anchor_id": node["id"],
                "visibility": "dm_only" if node["role"] == "secret" else "public",
                "risk_anchor_id": node["id"],
                "resolution_status": "slot",
            }
            for node in program["nodes"] if node["role"] in {"objective", "boss", "secret"}
        ], key=lambda item: item["id"]),
        "interactions": sorted([
            {
                "id": f"interaction_{directive['id']}",
                "source_directive_id": directive["id"],
                "zones": list(directive["zones"]),
                "role": directive["role"],
                "resolution_status": "slot",
            }
            for directive in program["tactical_directives"]
        ], key=lambda item: item["id"]),
        "hooks": [
            {
                "id": "hook_scene_objective",
                "entry_anchor_id": next(item["id"] for item in program["nodes"] if item["role"] == "entry"),
                "target_anchor_id": next(item["id"] for item in program["nodes"] if item["role"] in {"objective", "boss"}),
                "resolution_status": "slot",
            }
        ],
    }


def _base_grid(
    program: Mapping[str, Any],
    *,
    width: int,
    height: int,
    spatial_model: str,
    room_dependencies: bool,
    canvas: TacticalCanvas,
    levels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": GRID_SCHEMA,
        "realizer_version": GRID_VERSION,
        "scene": {
            "id": program["scene"]["id"],
            "name": program["scene"]["name"],
            "seed": program["scene"]["seed"],
            "archetype": program["archetype"],
            "grid": {
                "width": width,
                "height": height,
                "cell_size_ft": 5,
                "coordinate_contract": "cell(row,col,level_id)->world_ft(col*5,-row*5,elevation)",
                "connectivity": "orthogonal_4_plus_declared_links",
            },
        },
        "source": {
            "program_schema_version": program["schema_version"],
            "program_sha256": program["program_sha256"],
            "program_scene_id": program["scene"]["id"],
        },
        "spatial_model": spatial_model,
        "room_dependencies": room_dependencies,
        "levels": levels or [{"id": canvas.level_id, "z_base_ft": canvas.z_base_ft, "label": "Surface"}],
        "cells": canvas.sorted_cells(),
        "anchors": [],
        "routes": [],
        "links": [],
        "features": [],
        "slots": _slot_records(program),
        "topology": {},
    }


def _feature(
    canvas: TacticalCanvas,
    feature_id: str,
    kind: str,
    points: Iterable[Point],
    *,
    zone: str,
    visibility: str = "public",
    tags: Iterable[str] = (),
    blocks_movement: bool = False,
) -> dict[str, Any]:
    cells = [canvas.cell_id(point) for point in _dedupe(points)]
    return {
        "id": feature_id,
        "kind": kind,
        "zone": zone,
        "visibility": visibility,
        "cell_ids": cells,
        "tags": sorted(set(tags)),
        "blocks_movement": blocks_movement,
    }


def _realize_wilderness(program: Mapping[str, Any]) -> dict[str, Any]:
    canvas = TacticalCanvas(64, 56)

    def river_elevation(row: int) -> int:
        return max(0, 45 - (row // 6) * 5)

    def land_elevation(row: int, col: int) -> int:
        """A watershed slope whose 5-ft contour breaks wander across the valley.

        The river remains the authoritative hydraulic datum.  Land uses a
        fixed mathematical displacement instead of a row-only step function,
        so a Blender terrain builder receives staggered contour boundaries
        rather than full-width parallel terraces.
        """

        contour_shift = (
            3.15 * math.sin(col / 6.7)
            + 1.65 * math.sin((row + col) / 12.3)
            + 0.95 * math.sin((2 * col - row) / 17.1)
        )
        downhill_distance = max(0.0, row + contour_shift)
        return max(0, 45 - int(downhill_distance // 6) * 5)

    for row in range(canvas.height):
        for col in range(canvas.width):
            waterline = land_elevation(row, col)
            if col < 19:
                ridge_warp = _round_to(3.5 * math.sin(row / 5.8 + col / 4.1))
                zone, surface, elevation = "western_ridge", "ridge_scree", min(60, waterline + 30 + (18 - col) // 4 * 5 + ridge_warp)
            elif col < 30:
                slope_warp = _round_to(2.5 * math.sin(row / 7.1 - col / 3.7))
                zone, surface, elevation = "western_ridge", "rocky_slope", min(50, waterline + 15 + (29 - col) // 3 * 5 + slope_warp)
            elif col <= 35:
                zone, surface, elevation = "river_valley", "riverbank", waterline + 5
            elif col < 46:
                slope_warp = _round_to(2.5 * math.sin(row / 6.3 + col / 5.4))
                zone, surface, elevation = "pine_slope", "pine_slope", min(50, waterline + 10 + (col - 36) // 3 * 5 + slope_warp)
            else:
                forest_warp = _round_to(3.5 * math.sin(row / 8.7 + col / 3.9))
                zone, surface, elevation = "pine_slope", "pine_forest", min(55, waterline + 20 + (col - 46) // 4 * 5 + forest_warp)
            if 9 <= row <= 23 and 7 <= col <= 18:
                zone, surface = "cave_karst", "karst_rock"
            if 39 <= row <= 48 and 22 <= col <= 29:
                zone, surface, elevation = "waterfall_basin", "mossy_ledge", max(0, waterline)
            canvas.set((row, col), walkable=True, zone=zone, surface=surface, elevation=_round_to(elevation), tags=["open_terrain"])

    river_core: list[Point] = []
    for row in range(canvas.height):
        river_core.append((row, 32))
        for col in range(30, 35):
            canvas.set((row, col), walkable=False, zone="river_valley", surface="water", elevation=river_elevation(row), tags=["river", "water_flow"])

    ford_points = [(30, col) for col in range(30, 35)]
    bridge_points = [(8, col) for col in range(30, 35)]
    canvas.paint(ford_points, walkable=True, zone="river_valley", surface="ford", elevation=river_elevation(30), tags=["legal_crossing", "shallow_water"])
    canvas.paint(bridge_points, walkable=True, zone="river_valley", surface="bridge", elevation=river_elevation(8), tags=["legal_crossing", "old_bridge"])
    canvas.rect(40, 23, 6, 4, walkable=False, zone="waterfall_basin", surface="waterfall", elevation=0, tags=["waterfall", "hazard"])

    locations = {
        "trailhead": {"row": 50, "col": 48, "zone": "pine_slope", "tactical_role": "arrival"},
        "river_ford": {"row": 30, "col": 32, "zone": "river_valley", "tactical_role": "crossing"},
        "high_pass": {"row": 8, "col": 8, "zone": "western_ridge", "tactical_role": "high_ground"},
        "cave_mouth": {"row": 15, "col": 14, "zone": "cave_karst", "tactical_role": "objective_approach"},
        "hidden_shrine": {"row": 44, "col": 25, "zone": "waterfall_basin", "visibility": "dm_only", "tactical_role": "hidden_reward"},
    }
    points = {key: (value["row"], value["col"]) for key, value in locations.items()}
    paths = {
        "valley_trail": _orthogonal_path([points["trailhead"], (35, 38), (30, 36), points["river_ford"], (30, 28), (22, 20), points["cave_mouth"]]),
        "ridge_path": _orthogonal_path([points["trailhead"], (8, 48), (8, 35), (8, 28), points["high_pass"], points["cave_mouth"]]),
        "ford_loop": _orthogonal_path([points["river_ford"], (30, 25), (20, 20), points["high_pass"]]),
        "waterfall_secret": _orthogonal_path([points["river_ford"], (36, 28), (44, 28), points["hidden_shrine"]]),
    }
    for route_id, path in paths.items():
        _paint_route(canvas, path, surface="trail", tags=["route", route_id], visibility="dm_only" if route_id == "waterfall_secret" else "public")
    canvas.set(points["hidden_shrine"], surface="wet_shrine_ledge", visibility="dm_only", tags=["secret"])
    anchors = _node_locations(program, canvas, locations)

    grid = _base_grid(program, width=canvas.width, height=canvas.height, spatial_model="open_watershed", room_dependencies=False, canvas=canvas)
    grid["anchors"] = anchors
    grid["routes"] = _route_records(program, {route_id: _route_cells(canvas, path) for route_id, path in paths.items()})
    grid["waterways"] = [{
        "id": "silverfall_river", "source_flow_id": "watershed", "direction": "north_to_south",
        "cell_ids": _route_cells(canvas, river_core), "source_elevation": river_elevation(0), "outlet_elevation": river_elevation(canvas.height - 1),
    }]
    grid["crossings"] = [
        {"id": "river_ford_crossing", "kind": "ford", "cell_ids": _route_cells(canvas, ford_points), "waterway_cell_ids": [canvas.cell_id((30, 32))], "route_ids": ["valley_trail", "ford_loop", "waterfall_secret"]},
        {"id": "old_bridge_crossing", "kind": "bridge", "cell_ids": _route_cells(canvas, bridge_points), "waterway_cell_ids": [canvas.cell_id((8, 32))], "route_ids": ["ridge_path"]},
    ]
    grid["features"] = [
        _feature(canvas, "ford_boulders", "cover_boulders", [(29, 28), (31, 28), (29, 36), (31, 36)], zone="river_valley", tags=["cover", "crossfire"]),
        _feature(canvas, "ridge_drop", "fall_hazard", [(7, 12), (8, 12), (9, 12)], zone="western_ridge", tags=["fall", "high_ground"]),
        _feature(canvas, "waterfall_screen", "moving_water", [(40, 27), (41, 27), (42, 27)], zone="waterfall_basin", tags=["secret_approach", "difficult_terrain"]),
    ]
    grid["topology"] = {
        "terrain_driver": "watershed",
        "primary_entry_anchor_id": "trailhead",
        "objective_anchor_id": "cave_mouth",
        "crossing_required_for_primary": True,
        "room_count": 0,
    }
    return grid


def _realize_sewer(program: Mapping[str, Any]) -> dict[str, Any]:
    canvas = TacticalCanvas(56, 56, level_id="sewer", z_base_ft=-15)
    locations = {
        "north_hatch": {"row": 6, "col": 26, "zone": "intake", "tactical_role": "entry"},
        "fourway_junction": {"row": 22, "col": 26, "zone": "collector", "tactical_role": "three_way_junction"},
        "pump_controls": {"row": 30, "col": 34, "zone": "pump_hall", "tactical_role": "state_control"},
        "overflow_gate": {"row": 42, "col": 42, "zone": "overflow_cistern", "tactical_role": "water_level_control"},
        "shrine_altar": {"row": 42, "col": 49, "zone": "buried_shrine", "visibility": "dm_only", "tactical_role": "boss_platform"},
        "south_outfall": {"row": 50, "col": 26, "zone": "collector", "tactical_role": "exit"},
    }
    points = {key: (value["row"], value["col"]) for key, value in locations.items()}
    paths = {
        "collector_spine": _orthogonal_path([points["north_hatch"], points["fourway_junction"], (22, 34), points["pump_controls"], (35, 34), (35, 26), points["south_outfall"]]),
        "maintenance_loop_a": _orthogonal_path([points["fourway_junction"], (18, 42), points["overflow_gate"], (35, 42), points["pump_controls"]]),
        "maintenance_loop_b": _orthogonal_path([points["pump_controls"], (30, 12), (8, 12), points["north_hatch"]]),
        "overflow_shortcut": _orthogonal_path([points["overflow_gate"], (42, 26), points["south_outfall"]]),
        "cult_breach": _orthogonal_path([points["overflow_gate"], points["shrine_altar"]]),
    }
    for route_id, path in paths.items():
        _paint_route(canvas, path, surface="dry_brick", tags=["route", route_id], visibility="dm_only" if route_id == "cult_breach" else "public", preserve_surfaces=frozenset({"bridge"}))
    canvas.rect(27, 30, 7, 9, walkable=True, zone="pump_hall", surface="pump_floor", elevation=-15, tags=["machinery", "pump_hall"])
    canvas.rect(40, 38, 6, 8, walkable=True, zone="overflow_cistern", surface="wet_brick", elevation=-15, tags=["overflow", "cistern"])
    canvas.rect(39, 46, 7, 7, walkable=True, zone="buried_shrine", surface="sealed_masonry", elevation=-15, tags=["secret", "occupation"])
    canvas.rect(4, 23, 7, 7, walkable=True, zone="intake", surface="hatch_platform", elevation=-15, tags=["entry", "maintenance"])

    sewage_flow = _orthogonal_path([(6, 28), (22, 28), (30, 30), (42, 40), (42, 28), (50, 28)], horizontal_first=False)
    canvas.paint(sewage_flow, walkable=False, zone="collector", surface="sewage", elevation=-20, tags=["sewage", "utility_flow", "hazard"])
    overflow_bridge_points = [(42, col) for col in range(26, 31)]
    service_bridge_points = [(30, col) for col in range(26, 31)]
    junction_bridge_points = [(22, 28)]
    route_crossing_points = sorted({point for path in paths.values() for point in path if canvas.cell(point)["surface"] == "sewage"})
    bridge_points = _dedupe([*overflow_bridge_points, *service_bridge_points, *junction_bridge_points, *route_crossing_points])
    canvas.paint(overflow_bridge_points, walkable=True, zone="overflow_cistern", surface="bridge", elevation=-15, tags=["maintenance_bridge", "legal_crossing"])
    canvas.paint(service_bridge_points, walkable=True, zone="maintenance_ring", surface="bridge", elevation=-15, tags=["maintenance_bridge", "legal_crossing"])
    canvas.paint(junction_bridge_points, walkable=True, zone="collector", surface="bridge", elevation=-15, tags=["maintenance_bridge", "legal_crossing"])
    canvas.paint(route_crossing_points, walkable=True, surface="bridge", elevation=-15, tags=["maintenance_bridge", "legal_crossing"])
    canvas.paint([(22, 25), (22, 26), (22, 27), (21, 26), (23, 26)], walkable=True, zone="collector", surface="junction_brick", elevation=-15, tags=["junction", "route_choice"])
    canvas.set(points["pump_controls"], walkable=True, zone="pump_hall", surface="pump_controls", elevation=-15, tags=["pump", "state_control"])
    canvas.set(points["shrine_altar"], walkable=True, zone="buried_shrine", surface="altar_platform", elevation=-15, visibility="dm_only", tags=["boss", "secret"])
    anchors = _node_locations(program, canvas, locations)

    grid = _base_grid(program, width=canvas.width, height=canvas.height, spatial_model="infrastructure_network", room_dependencies=False, canvas=canvas)
    grid["anchors"] = anchors
    grid["routes"] = _route_records(program, {route_id: _route_cells(canvas, path) for route_id, path in paths.items()})
    grid["waterways"] = [{
        "id": "sewage_main", "source_flow_id": "sewage_flow", "direction": "intake_to_outfall", "cell_ids": _route_cells(canvas, sewage_flow),
        "source_elevation": -20, "outlet_elevation": -20,
    }]
    grid["crossings"] = [{
        "id": "overflow_maintenance_bridge", "kind": "maintenance_bridge", "cell_ids": _route_cells(canvas, bridge_points),
        "waterway_cell_ids": [canvas.cell_id((42, 28))], "route_ids": ["overflow_shortcut"],
    }]
    grid["features"] = [
        _feature(canvas, "main_pump_assembly", "pump_assembly", [(29, 33), (29, 34), (30, 33), (30, 34), (31, 34)], zone="pump_hall", tags=["machine", "state_change"]),
        _feature(canvas, "iron_overflow_gate", "floodgate", [(42, 41), (42, 42), (42, 43)], zone="overflow_cistern", tags=["water_level", "destructible"]),
        _feature(canvas, "junction_grates", "junction_grate", [(21, 26), (22, 26), (23, 26)], zone="collector", tags=["navigation", "ambush"]),
    ]
    grid["topology"] = {
        "terrain_driver": "infrastructure_flow",
        "primary_entry_anchor_id": "north_hatch",
        "objective_anchor_id": "shrine_altar",
        "loop_route_ids": ["collector_spine", "maintenance_loop_b"],
        "junction_anchor_id": "fourway_junction",
        "pump_anchor_id": "pump_controls",
        "room_count": 0,
    }
    return grid


def _realize_special_site(program: Mapping[str, Any]) -> dict[str, Any]:
    canvas = TacticalCanvas(61, 61)
    center = (30, 30)
    for row in range(canvas.height):
        for col in range(canvas.width):
            distance = math.hypot(row - center[0], col - center[1])
            angle = math.atan2(row - center[0], col - center[1])
            # A fixed angular/radial warp breaks the visual "layer cake" that
            # a distance-only crater creates.  Including distance in the phase
            # prevents every contour from being a merely translated copy of the
            # previous one while retaining a legible central rift.
            contour_warp = (
                2.45 * math.sin(3.0 * angle + distance / 8.5)
                + 1.35 * math.sin(5.0 * angle - distance / 6.7)
                + 0.55 * math.sin((row + 2 * col) / 9.1)
            )
            warped_distance = distance + contour_warp
            outer_warp = distance + 1.55 * math.sin(3.0 * angle + 0.4) + 0.65 * math.sin((row - col) / 10.7)
            if outer_warp > 28.5:
                continue
            if distance <= 5:
                elevation, zone, surface, walkable = 0, "rift_floor", "arcane_rift", False
            elif warped_distance <= 10:
                elevation, zone, surface, walkable = 10, "rift_floor", "shattered_talus", True
            elif warped_distance <= 15:
                elevation, zone, surface, walkable = 20, "bonefield", "dragon_bonefield", True
            elif warped_distance <= 21:
                elevation, zone, surface, walkable = 30, "bonefield", "crater_slope", True
            elif warped_distance <= 25:
                elevation, zone, surface, walkable = 40, "crater_rim", "crater_rim", True
            else:
                elevation, zone, surface, walkable = 50, "crater_rim", "high_rim", True
            canvas.set((row, col), elevation=elevation, walkable=walkable, zone=zone, surface=surface, tags=["open_tactical_site", f"band_{elevation}"])

    locations = {
        "rim_entry": {"row": 51, "col": 15, "zone": "crater_rim", "tactical_role": "entry_platform"},
        "spine_bridge": {"row": 31, "col": 16, "zone": "bonefield", "tactical_role": "bone_bridge"},
        "rift_vent": {"row": 30, "col": 30, "zone": "rift_floor", "tactical_role": "hazard_control"},
        "dragon_skull": {"row": 16, "col": 43, "zone": "skull_arena", "tactical_role": "boss_high_ground"},
        "marrow_cache": {"row": 29, "col": 17, "zone": "bonefield", "visibility": "dm_only", "tactical_role": "secret_reward"},
        "float_anchor": {"row": 12, "col": 30, "zone": "floating_steps", "tactical_role": "vertical_route"},
    }
    points = {key: (value["row"], value["col"]) for key, value in locations.items()}
    route_waypoints = {
        "rim_descent": ([points["rim_entry"], (46, 16), (40, 17), points["spine_bridge"], (24, 25), (20, 35), points["dragon_skull"]], [50, 40, 30, 20, 20, 30, 40]),
        "bone_ridge": ([points["spine_bridge"], (30, 24), (25, 32), points["dragon_skull"]], [20, 10, 20, 40]),
        "floating_path": ([points["float_anchor"], (12, 36), (15, 39), points["dragon_skull"]], [50, 50, 40, 40]),
        "rift_loop": ([points["spine_bridge"], (35, 21), (35, 29), points["rift_vent"], (24, 30), points["float_anchor"]], [20, 10, 0, 0, 10, 50]),
        "marrow_secret": ([points["spine_bridge"], points["marrow_cache"]], [20, 20]),
    }
    paths: dict[str, list[Point]] = {}
    for route_id, (waypoints, elevations) in route_waypoints.items():
        path = _graded_waypoints(canvas, waypoints, elevations)
        paths[route_id] = path
        _paint_route(
            canvas,
            path,
            surface="floating_rock" if route_id == "floating_path" else "bone_route",
            tags=["route", route_id, "vertical_tactics"],
            visibility="dm_only" if route_id == "marrow_secret" else "public",
            preserve_surfaces=frozenset(),
        )
    canvas.rect(12, 39, 9, 9, walkable=True, zone="skull_arena", surface="skull_plateau", elevation=40, tags=["boss_arena", "large_creature"])
    canvas.set(points["dragon_skull"], walkable=True, zone="skull_arena", surface="dragon_skull", elevation=40, tags=["boss", "landmark"])
    canvas.set(points["rift_vent"], walkable=True, zone="rift_floor", surface="arcane_vent", elevation=0, tags=["hazard", "state_control"])
    canvas.set(points["float_anchor"], walkable=True, zone="floating_steps", surface="floating_rock", elevation=50, tags=["vertical", "jump_or_fly"])
    canvas.set(points["marrow_cache"], walkable=True, zone="bonefield", surface="bone_crevice", elevation=20, visibility="dm_only", tags=["secret", "reward"])
    anchors = _node_locations(program, canvas, locations)

    grid = _base_grid(program, width=canvas.width, height=canvas.height, spatial_model="open_tactical_site", room_dependencies=False, canvas=canvas)
    grid["anchors"] = anchors
    grid["routes"] = _route_records(program, {route_id: _route_cells(canvas, path) for route_id, path in paths.items()})
    grid["elevation_bands"] = [
        {"id": "rift_floor", "elevation": 0},
        {"id": "talus", "elevation": 10},
        {"id": "bonefield", "elevation": 20},
        {"id": "lower_rim", "elevation": 30},
        {"id": "upper_rim", "elevation": 40},
        {"id": "floating_steps", "elevation": 50},
    ]
    grid["features"] = [
        _feature(canvas, "rib_cover_field", "directional_cover", [(27, 18), (28, 20), (31, 20), (33, 18)], zone="bonefield", tags=["cover", "ambush"]),
        _feature(canvas, "collapsible_spine", "collapsible_bone_bridge", [(31, 16), (30, 17), (29, 18)], zone="bonefield", tags=["destructible", "fall_hazard"]),
        _feature(canvas, "arcane_vent", "arcane_vent", [points["rift_vent"]], zone="rift_floor", tags=["moving_hazard", "forced_movement"]),
        _feature(canvas, "floating_stones", "floating_stones", [(12, 30), (12, 36), (15, 39)], zone="floating_steps", tags=["jump", "fly", "high_risk"]),
    ]
    grid["topology"] = {
        "terrain_driver": "mythic_landmark",
        "primary_entry_anchor_id": "rim_entry",
        "objective_anchor_id": "dragon_skull",
        "room_count": 0,
        "supports_large_creature": True,
        "vertical_route_ids": ["bone_ridge", "floating_path", "rift_loop"],
        "contour_style": "warped_radial",
    }
    return grid


def _harbor_zone(cell: Mapping[str, Any]) -> str:
    """Map the stable V2.1 harbor ownership records onto V2.2 program zones."""

    if cell.get("level_id") == "sewer_main" or cell.get("volume_id") == "undertide_sewer":
        return "underworks"
    if cell.get("volume_id") == "signal_tower":
        return "civic_spine"
    if cell.get("volume_id") in {"dock_store"} or int(cell.get("col", 0)) >= 40:
        return "waterfront"
    if 13 <= int(cell.get("row", 0)) <= 42:
        return "market_quarter"
    return "residential_lanes"


def _graph_from_cells(cells: Mapping[str, Mapping[str, Any]], links: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {cell_id: set() for cell_id, cell in cells.items() if cell.get("walkable")}
    by_position = {(str(cell["level_id"]), int(cell["row"]), int(cell["col"])): cell_id for cell_id, cell in cells.items() if cell.get("walkable")}
    for (level_id, row, col), cell_id in by_position.items():
        for target in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            other = by_position.get((level_id, *target))
            if other:
                graph[cell_id].add(other)
    for link in links:
        endpoint_ids = [item["cell_id"] for item in link.get("endpoints", [])]
        for left, right in zip(endpoint_ids, endpoint_ids[1:]):
            if left in graph and right in graph:
                graph[left].add(right)
                graph[right].add(left)
    return graph


def _shortest_path(graph: Mapping[str, set[str]], start: str, goal: str) -> list[str]:
    if start not in graph or goal not in graph:
        raise ValueError(f"route endpoint is not walkable: {start} -> {goal}")
    queue: deque[str] = deque([start])
    previous: dict[str, str | None] = {start: None}
    while queue:
        current = queue.popleft()
        if current == goal:
            result = [goal]
            while previous[result[-1]] is not None:
                parent = previous[result[-1]]
                assert parent is not None
                result.append(parent)
            return list(reversed(result))
        for candidate in sorted(graph[current]):
            if candidate not in previous:
                previous[candidate] = current
                queue.append(candidate)
    raise ValueError(f"unreachable grid endpoints: {start} -> {goal}")


def _path_via(graph: Mapping[str, set[str]], anchor_ids: list[str]) -> list[str]:
    result: list[str] = []
    for left, right in zip(anchor_ids, anchor_ids[1:]):
        segment = _shortest_path(graph, left, right)
        result.extend(segment if not result else segment[1:])
    return result


def _realize_harbor(program: Mapping[str, Any]) -> dict[str, Any]:
    """Expose the existing V2.1 harbor runtime as the V2.2 grid contract."""

    runtime_path = ROOT / "output" / "harbor-v2" / "scene.runtime.json"
    plan_path = ROOT / "output" / "harbor-v2" / "scene.plan.json"
    if not runtime_path.exists() or not plan_path.exists():
        raise FileNotFoundError("harbor V2.1 runtime/plan are required for the city_district adapter")
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    levels = [
        {"id": item["id"], "z_base_ft": item["z_base_ft"], "label": item["label"], "volume_id": item.get("volume_id", "")}
        for item in runtime["scene"]["levels"]
    ]
    level_rank = {item["id"]: index for index, item in enumerate(levels)}
    cells: list[dict[str, Any]] = []
    for source in runtime["cells"]:
        cells.append({
            "id": source["id"],
            "level_id": source["level_id"],
            "row": source["row"],
            "col": source["col"],
            "elevation": source.get("z_base_ft", 0),
            "walkable": source["walkable"],
            "zone": _harbor_zone(source),
            "surface": source["surface"],
            "visibility": source["visibility"],
            "tags": sorted({item for item in [source.get("room_id", ""), source.get("volume_id", ""), source.get("navigation_group", "")] if item}),
        })
    cells.sort(key=lambda item: (level_rank[item["level_id"]], item["row"], item["col"]))
    links = []
    for connector in plan["connectors"]:
        endpoints = []
        for endpoint in connector["endpoints"]:
            endpoint_id = _cell_id(endpoint["level_id"], endpoint["row"], endpoint["col"])
            endpoints.append({"cell_id": endpoint_id, "level_id": endpoint["level_id"], "row": endpoint["row"], "col": endpoint["col"]})
        links.append({"id": connector["id"], "type": connector["type"], "visibility": connector["visibility"], "endpoints": endpoints})
    links.sort(key=lambda item: item["id"])
    cell_by_id = {item["id"]: item for item in cells}
    locations = {
        "landward_gate": {"cell_id": "surface:52:29", "zone": "residential_lanes", "tactical_role": "entry"},
        "tide_square": {"cell_id": "surface:28:29", "zone": "market_quarter", "tactical_role": "junction"},
        "beacon_tower": {"cell_id": "signal_tower_l4:5:8", "zone": "civic_spine", "tactical_role": "objective_high_ground"},
        "cargo_yard": {"cell_id": "surface:21:53", "zone": "waterfront", "tactical_role": "cargo_cover"},
        "sewer_exchange": {"cell_id": "sewer_main:12:30", "zone": "underworks", "tactical_role": "secret_junction"},
    }
    anchors: list[dict[str, Any]] = []
    for node in program["nodes"]:
        location = locations[node["id"]]
        cell = cell_by_id[location["cell_id"]]
        anchors.append({
            "id": node["id"], "source_node_id": node["id"], "name": node["name"], "kind": node["role"],
            "zone": location["zone"], "cell_id": cell["id"], "level_id": cell["level_id"], "row": cell["row"], "col": cell["col"],
            "elevation": cell["elevation"], "visibility": "public", "tactical_role": location["tactical_role"],
        })
    anchors.sort(key=lambda item: item["id"])
    graph = _graph_from_cells(cell_by_id, links)
    anchor_cells = {item["id"]: item["cell_id"] for item in anchors}
    route_stops = {
        "public_spine": ["landward_gate", "tide_square", "beacon_tower"],
        "freight_loop": ["tide_square", "beacon_tower", "cargo_yard"],
        "dock_return": ["cargo_yard", "landward_gate"],
        "smuggler_cut": ["sewer_exchange", "cargo_yard"],
        "sewer_access": ["tide_square", "sewer_exchange"],
    }
    paths = {route_id: _path_via(graph, [anchor_cells[item] for item in stops]) for route_id, stops in route_stops.items()}
    grid = {
        "schema_version": GRID_SCHEMA,
        "realizer_version": GRID_VERSION,
        "scene": {
            "id": program["scene"]["id"], "name": program["scene"]["name"], "seed": program["scene"]["seed"], "archetype": program["archetype"],
            "grid": {
                "width": runtime["scene"]["grid"]["width"], "height": runtime["scene"]["grid"]["height"], "cell_size_ft": runtime["scene"]["grid"]["cell_size_ft"],
                "coordinate_contract": "cell(row,col,level_id)->world_ft(col*5,-row*5,elevation)", "connectivity": "orthogonal_4_plus_declared_links",
            },
        },
        "source": {
            "program_schema_version": program["schema_version"], "program_sha256": program["program_sha256"], "program_scene_id": program["scene"]["id"],
            "mapped_runtime": "output/harbor-v2/scene.runtime.json", "mapped_plan": "output/harbor-v2/scene.plan.json",
        },
        "spatial_model": "mapped_multilevel_district",
        "room_dependencies": True,
        "levels": levels,
        "cells": cells,
        "anchors": anchors,
        "routes": _route_records(program, paths),
        "links": links,
        "features": [
            {
                "id": feature["id"], "kind": feature["kind"], "zone": _harbor_zone(feature), "visibility": feature["visibility"],
                "cell_ids": [_cell_id(feature["level_id"], feature["row"], feature["col"])], "tags": sorted(feature.get("tags", [])), "blocks_movement": feature["blocks_movement"],
                "source_feature_id": feature["id"],
            }
            for feature in sorted(plan["features"], key=lambda item: item["id"])
        ],
        "slots": _slot_records(program),
        "topology": {
            "terrain_driver": "shoreline", "primary_entry_anchor_id": "landward_gate", "objective_anchor_id": "beacon_tower",
            "mapped_from_v21": True,
        },
    }
    return grid


REALIZERS = {
    "city_district": _realize_harbor,
    "wilderness": _realize_wilderness,
    "infrastructure_dungeon": _realize_sewer,
    "special_site": _realize_special_site,
}


def realize_program(program: Mapping[str, Any]) -> dict[str, Any]:
    """Realize an already-compiled SceneProgram without mutating it."""

    validate_program(dict(program))
    archetype = str(program["archetype"])
    if archetype not in REALIZERS:
        raise ValueError(f"no V2.2 realizer for archetype: {archetype}")
    grid = REALIZERS[archetype](program)
    unsigned = dict(grid)
    grid["grid_sha256"] = _sha256(unsigned)
    return grid


def _link_pairs(grid: Mapping[str, Any]) -> set[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for link in grid.get("links", []):
        endpoint_ids = [item["cell_id"] for item in link.get("endpoints", [])]
        for left, right in zip(endpoint_ids, endpoint_ids[1:]):
            pairs.add(frozenset({left, right}))
    return pairs


def _path_is_contiguous(path: list[str], cell_by_id: Mapping[str, Mapping[str, Any]], link_pairs: set[frozenset[str]]) -> bool:
    for left, right in zip(path, path[1:]):
        if left == right:
            continue
        if frozenset({left, right}) in link_pairs:
            continue
        left_cell, right_cell = cell_by_id[left], cell_by_id[right]
        if left_cell["level_id"] != right_cell["level_id"]:
            return False
        if abs(left_cell["row"] - right_cell["row"]) + abs(left_cell["col"] - right_cell["col"]) != 1:
            return False
    return True


def _has_cycle(graph: Mapping[str, set[str]]) -> bool:
    seen: set[str] = set()
    for start in sorted(graph):
        if start in seen:
            continue
        stack: list[tuple[str, str | None]] = [(start, None)]
        while stack:
            current, parent = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for neighbor in graph[current]:
                if neighbor == parent:
                    continue
                if neighbor in seen:
                    return True
                stack.append((neighbor, current))
    return False


def _validate_specific_rules(program: Mapping[str, Any], grid: Mapping[str, Any], cell_by_id: Mapping[str, Mapping[str, Any]], routes: Mapping[str, Mapping[str, Any]], graph: Mapping[str, set[str]]) -> dict[str, Any]:
    archetype = program["archetype"]
    report: dict[str, Any] = {}
    if archetype == "wilderness":
        waterways = grid.get("waterways", [])
        crossings = grid.get("crossings", [])
        if not waterways or not crossings:
            raise AssertionError("wilderness realizer requires a waterway and legal crossings")
        waterway_ids: set[str] = set()
        for waterway in waterways:
            elevations = [int(cell_by_id[cell_id]["elevation"]) for cell_id in waterway["cell_ids"]]
            if any(later > earlier for earlier, later in zip(elevations, elevations[1:])):
                raise AssertionError("wilderness river flows uphill")
            waterway_ids.update(waterway["cell_ids"])
        crossing_ids: set[str] = set()
        for crossing in crossings:
            if not set(crossing["waterway_cell_ids"]) <= waterway_ids:
                raise AssertionError("crossing does not touch its declared waterway")
            if not all(cell_by_id[cell_id]["surface"] in {"ford", "bridge"} and cell_by_id[cell_id]["walkable"] for cell_id in crossing["cell_ids"]):
                raise AssertionError("river crossing is not a legal walkable ford/bridge")
            for route_id in crossing["route_ids"]:
                if not set(crossing["cell_ids"]) & set(routes[route_id]["cell_ids"]):
                    raise AssertionError("declared crossing is not actually used by its route")
            crossing_ids.update(crossing["waterway_cell_ids"])
        for route in routes.values():
            if (set(route["cell_ids"]) & waterway_ids) - crossing_ids:
                raise AssertionError("route crosses water outside a legal crossing")
        if any(cell["surface"] == "water" and cell["walkable"] for cell in cell_by_id.values()):
            raise AssertionError("open river water must not be ordinary walkable ground")
        report["river_downhill"] = True
        report["legal_crossings"] = len(crossings)
    elif archetype == "infrastructure_dungeon":
        topology = grid["topology"]
        junction = next(item for item in grid["anchors"] if item["id"] == topology["junction_anchor_id"])
        if len(graph[junction["cell_id"]]) < 3:
            raise AssertionError("sewer junction does not have at least three traversable branches")
        loop_cells = {cell_id for route_id in topology["loop_route_ids"] for cell_id in routes[route_id]["cell_ids"]}
        loop_graph = {cell_id: {neighbor for neighbor in graph[cell_id] if neighbor in loop_cells} for cell_id in loop_cells}
        if not _has_cycle(loop_graph):
            raise AssertionError("sewer topology lacks a realized maintenance loop")
        pump = next(item for item in grid["anchors"] if item["id"] == topology["pump_anchor_id"])
        if pump["zone"] != "pump_hall" or not any(feature["kind"] == "pump_assembly" for feature in grid["features"]):
            raise AssertionError("sewer pump hall is not geometrically realized")
        report["junction_degree"] = len(graph[junction["cell_id"]])
        report["maintenance_loop"] = True
        report["pump_hall"] = True
    elif archetype == "special_site":
        if grid.get("spatial_model") != "open_tactical_site" or grid.get("room_dependencies") is not False or "rooms" in grid:
            raise AssertionError("special site must remain an open no-room tactical space")
        bands = grid.get("elevation_bands", [])
        elevations = {int(item["elevation"]) for item in bands}
        active = {int(cell["elevation"]) for cell in cell_by_id.values() if cell["walkable"]}
        if not 5 <= len(bands) <= 7 or not elevations <= active:
            raise AssertionError("special site must expose five to seven populated elevation bands")
        report["elevation_bands"] = len(bands)
        report["room_free"] = True
    return report


def validate_grid(program: Mapping[str, Any], grid: Mapping[str, Any]) -> dict[str, Any]:
    """Validate universal reachability plus the V2.2 archetype-specific rules."""

    validate_program(dict(program))
    if grid.get("schema_version") != GRID_SCHEMA or grid.get("scene", {}).get("archetype") not in SUPPORTED_ARCHETYPES:
        raise AssertionError("invalid tactical grid schema")
    if grid.get("source", {}).get("program_sha256") != program.get("program_sha256"):
        raise AssertionError("tactical grid was not built from the supplied SceneProgram")
    unsigned = dict(grid)
    claimed_hash = unsigned.pop("grid_sha256", "")
    if claimed_hash != _sha256(unsigned):
        raise AssertionError("tactical grid hash is stale")

    required_cell_keys = {"id", "level_id", "row", "col", "elevation", "walkable", "zone", "surface", "visibility"}
    cells = grid.get("cells", [])
    if not cells or any(not required_cell_keys <= item.keys() for item in cells):
        raise AssertionError("tactical cells do not satisfy the common contract")
    cell_by_id = {item["id"]: item for item in cells}
    if len(cell_by_id) != len(cells):
        raise AssertionError("tactical grid has duplicate cell IDs")
    dimensions = grid["scene"]["grid"]
    if any(not (0 <= int(cell["row"]) < int(dimensions["height"]) and 0 <= int(cell["col"]) < int(dimensions["width"])) for cell in cells):
        raise AssertionError("tactical grid contains out-of-bounds cells")
    if any(cell["visibility"] not in {"public", "dm_only"} for cell in cells):
        raise AssertionError("tactical cell visibility is invalid")

    anchors = {item["id"]: item for item in grid.get("anchors", [])}
    program_nodes = {item["id"]: item for item in program["nodes"]}
    if anchors.keys() != program_nodes.keys():
        raise AssertionError("SceneProgram nodes are not fully represented by grid anchors")
    for anchor_id, anchor in anchors.items():
        cell = cell_by_id.get(anchor["cell_id"])
        if not cell or (cell["row"], cell["col"], cell["level_id"]) != (anchor["row"], anchor["col"], anchor["level_id"]):
            raise AssertionError(f"anchor has no matching cell: {anchor_id}")
        if not cell["walkable"]:
            raise AssertionError(f"anchor is not reachable terrain: {anchor_id}")
        if anchor["zone"] != program_nodes[anchor_id].get("zone_id"):
            raise AssertionError(f"anchor zone diverged from SceneProgram: {anchor_id}")

    routes = {item["id"]: item for item in grid.get("routes", [])}
    program_route_ids = {item["id"] for item in program["routes"]}
    if routes.keys() != program_route_ids:
        raise AssertionError("SceneProgram routes are not fully represented by tactical routes")
    link_pairs = _link_pairs(grid)
    for route_id, route in routes.items():
        path = route["cell_ids"]
        if not path or any(cell_id not in cell_by_id or not cell_by_id[cell_id]["walkable"] for cell_id in path):
            raise AssertionError(f"route has non-walkable cell: {route_id}")
        if path[0] != anchors[route["from_anchor_id"]]["cell_id"] or path[-1] != anchors[route["to_anchor_id"]]["cell_id"]:
            raise AssertionError(f"route endpoints do not bind to program anchors: {route_id}")
        if any(anchors[anchor_id]["cell_id"] not in path for anchor_id in route["via_anchor_ids"]):
            raise AssertionError(f"route skips a planned via anchor: {route_id}")
        if not _path_is_contiguous(path, cell_by_id, link_pairs):
            raise AssertionError(f"route is not spatially contiguous: {route_id}")

    graph = _graph_from_cells(cell_by_id, grid.get("links", []))
    entries = [item["id"] for item in program["nodes"] if item["role"] == "entry"]
    targets = [item["id"] for item in program["nodes"] if item["role"] in {"objective", "boss"}]
    reachable = set(_shortest_path(graph, anchors[entries[0]]["cell_id"], anchors[targets[0]]["cell_id"]))
    if not reachable:
        raise AssertionError("entry cannot reach objective/boss on tactical grid")
    slots = grid.get("slots", {})
    if not {"population", "encounters", "rewards", "interactions", "hooks"} <= slots.keys() or any(item.get("resolution_status") != "slot" for group in slots.values() for item in group):
        raise AssertionError("content slots must remain unresolved in the geometry prototype")
    specific = _validate_specific_rules(program, grid, cell_by_id, routes, graph)
    return {
        "status": "passed",
        "scene_id": grid["scene"]["id"],
        "archetype": program["archetype"],
        "cells": len(cells),
        "walkable_cells": sum(1 for item in cells if item["walkable"]),
        "anchors": len(anchors),
        "routes": len(routes),
        "features": len(grid.get("features", [])),
        "slots": {key: len(value) for key, value in sorted(slots.items())},
        "grid_sha256": grid["grid_sha256"],
        "rules": specific,
    }


def generate_realization(program_path: Path, output_dir: Path) -> dict[str, Any]:
    """Read a frozen SceneProgram JSON and write deterministic grid + manifest."""

    program = json.loads(program_path.read_text(encoding="utf-8"))
    grid = realize_program(program)
    report = validate_grid(program, grid)
    output_dir.mkdir(parents=True, exist_ok=True)
    grid_path = output_dir / "scene.grid.json"
    grid_path.write_bytes(canonical_bytes(grid))
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "status": "generated",
        "scene_id": grid["scene"]["id"],
        "archetype": grid["scene"]["archetype"],
        "program_sha256": program["program_sha256"],
        "grid_sha256": grid["grid_sha256"],
        "files": [{"path": "scene.grid.json", "sha256": hashlib.sha256(grid_path.read_bytes()).hexdigest()}],
        "counts": {key: report[key] for key in ("cells", "walkable_cells", "anchors", "routes", "features")},
        "validation": report,
    }
    (output_dir / "scene.manifest.json").write_bytes(canonical_bytes(manifest))
    return report


def generate_default_realizations(root: Path = ROOT) -> list[dict[str, Any]]:
    reports = []
    for program_path in sorted((root / "output" / "programs").glob("*.program.json")):
        slug = program_path.name.removesuffix(".program.json")
        reports.append(generate_realization(program_path, root / "output" / "v22-scenes" / slug))
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Realize frozen V2.2 ScenePrograms as tactical grids")
    parser.add_argument("program", nargs="?", type=Path, help="scene.program.json to realize")
    parser.add_argument("--out-dir", type=Path, help="directory for scene.grid.json and scene.manifest.json")
    parser.add_argument("--all", action="store_true", help="realize every output/programs/*.program.json fixture")
    args = parser.parse_args()
    if args.all:
        if args.program or args.out_dir:
            parser.error("--all cannot be combined with program or --out-dir")
        print(json.dumps({"status": "passed", "realizations": generate_default_realizations()}, ensure_ascii=False, indent=2))
        return
    if not args.program or not args.out_dir:
        parser.error("program and --out-dir are required unless --all is used")
    print(json.dumps(generate_realization(args.program, args.out_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
