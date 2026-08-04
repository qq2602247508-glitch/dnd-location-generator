from __future__ import annotations

import json
from collections import Counter, deque
from pathlib import Path
from typing import Any, Iterable


def rect_cells(bounds: dict[str, Any]) -> set[tuple[int, int]]:
    return {
        (row, col)
        for row in range(int(bounds["row"]), int(bounds["row"]) + int(bounds["height"]))
        for col in range(int(bounds["col"]), int(bounds["col"]) + int(bounds["width"]))
    }


def composed_cells(item: dict[str, Any]) -> set[tuple[int, int]]:
    """Resolve a backwards-compatible cell mask.

    V1 items use one ``bounds`` rectangle. V2 generators may emit multiple
    non-overlapping ``areas`` rectangles or an exact ``cells`` mask. Consumers
    therefore do not need separate code paths for rectangles, L-shapes, towers,
    caves, or narrow underground networks.
    """
    if "cells" in item:
        return {(int(row), int(col)) for row, col in item["cells"]}
    areas: Iterable[dict[str, Any]] = item.get("areas") or ([item["bounds"]] if "bounds" in item else [])
    points: set[tuple[int, int]] = set()
    for area in areas:
        points.update(rect_cells(area))
    return points


def room_cells(room: dict[str, Any]) -> set[tuple[int, int]]:
    return composed_cells(room)


def building_cells(building: dict[str, Any]) -> set[tuple[int, int]]:
    return composed_cells(building)


def is_subterranean(building: dict[str, Any]) -> bool:
    return building.get("structure_kind") in {"underground", "subterranean"}


def outdoor_zone(row: int, col: int) -> str:
    if 11 <= row <= 16 and 10 <= col <= 22:
        return "market_plaza"
    if 14 <= col <= 17:
        return "main_street"
    if col in {10, 22} or row in {10, 16}:
        return "alley"
    return "side_street"


def generate_cells(spec: dict[str, Any]) -> list[dict[str, Any]]:
    width, height = int(spec["width"]), int(spec["height"])
    footprints: dict[tuple[int, int], str] = {}
    for building in spec["buildings"]:
        if is_subterranean(building):
            continue
        for point in building_cells(building):
            if point in footprints:
                raise AssertionError(f"overlapping building footprints at {point}")
            footprints[point] = building["id"]

    cells: list[dict[str, Any]] = []
    for row in range(height):
        for col in range(width):
            if (row, col) not in footprints:
                cells.append({
                    "row": row, "col": col, "level_index": 0, "walkable": True,
                    "surface_type": "outdoor", "space_kind": "outdoor", "zone": outdoor_zone(row, col),
                    "building_id": "", "room_id": "", "movement_cost": 1,
                })

    for building in spec["buildings"]:
        for floor in building["floors"]:
            for room in floor["rooms"]:
                for row, col in room_cells(room):
                    cells.append({
                        "row": row, "col": col, "level_index": floor["floor_index"],
                        "walkable": True, "surface_type": "indoor", "space_kind": "interior", "zone": "interior",
                        "building_id": building["id"], "room_id": room["id"],
                        "movement_cost": 1,
                    })
    return cells


def generate_transitions(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Explicit tactical links; consumers never need to infer door or stair rules."""
    transitions: list[dict[str, Any]] = []
    for building in spec["buildings"]:
        for entry in building["entrances"]:
            row, col = int(entry["row"]), int(entry["col"])
            # The exterior endpoint is the first unoccupied neighbouring cell.
            footprint = building_cells(building)
            explicit_outside = entry.get("outside")
            outside = tuple(map(int, explicit_outside)) if explicit_outside else next(
                ((row + dr, col + dc) for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)) if (row + dr, col + dc) not in footprint),
                None,
            )
            if outside is None:
                raise AssertionError(f"entrance has no exterior endpoint: {building['id']}")
            transitions.append({
                "id": f"entrance_{building['id']}_{row}_{col}", "type": "entrance", "bidirectional": True,
                "from": {"level_index": 0, "row": outside[0], "col": outside[1], "space_kind": "outdoor"},
                "to": {"level_index": 1, "row": row, "col": col, "space_kind": "interior", "building_id": building["id"], "room_id": entry["room_id"]},
            })
        for floor in building["floors"]:
            for stair in floor["stairs"]:
                if stair["direction"] != "up":
                    continue
                row, col = int(stair["row"]), int(stair["col"])
                transitions.append({
                    "id": f"stairs_{building['id']}_{floor['floor_index']}_{stair['to_floor']}_{row}_{col}", "type": "stairs", "bidirectional": True,
                    "from": {"level_index": floor["floor_index"], "row": row, "col": col, "space_kind": "interior", "building_id": building["id"]},
                    "to": {"level_index": stair["to_floor"], "row": row, "col": col, "space_kind": "interior", "building_id": building["id"]},
                })
    return transitions


def _reachable(start: tuple[int, int], points: set[tuple[int, int]]) -> set[tuple[int, int]]:
    visited = {start}
    queue = deque([start])
    while queue:
        row, col = queue.popleft()
        for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            if neighbor in points and neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return visited


def validate(spec: dict[str, Any], cells: list[dict[str, Any]]) -> dict[str, Any]:
    width, height = int(spec["width"]), int(spec["height"])
    footprint: dict[tuple[int, int], str] = {}
    room_lookup: dict[str, tuple[str, int, set[tuple[int, int]]]] = {}
    building_reports: list[dict[str, Any]] = []
    multi_level = 0
    for building in spec["buildings"]:
        b_cells = building_cells(building)
        for point in b_cells:
            if not (0 <= point[0] < height and 0 <= point[1] < width):
                raise AssertionError(f"{building['id']} leaves map bounds")
            if point in footprint and not is_subterranean(building):
                raise AssertionError(f"overlapping buildings at {point}")
            if not is_subterranean(building):
                footprint[point] = building["id"]
        floors = building["floors"]
        multi_level += len(floors) >= 2
        floor_indexes = [floor["floor_index"] for floor in floors]
        if floor_indexes != list(range(1, len(floors) + 1)):
            raise AssertionError(f"non-contiguous floor indexes: {building['id']}")
        entry_rooms = {entry["room_id"] for entry in building["entrances"]}
        for floor in floors:
            occupied: dict[tuple[int, int], str] = {}
            rooms = {room["id"]: room for room in floor["rooms"]}
            graph: dict[str, set[str]] = {room_id: set() for room_id in rooms}
            for room in floor["rooms"]:
                if room["id"] in room_lookup:
                    raise AssertionError(f"duplicate room id: {room['id']}")
                points = room_cells(room)
                if not points <= b_cells:
                    raise AssertionError(f"room outside its building: {room['id']}")
                for point in points:
                    if point in occupied:
                        raise AssertionError(f"room overlap: {room['id']} / {occupied[point]}")
                    occupied[point] = room["id"]
                room_lookup[room["id"]] = (building["id"], floor["floor_index"], points)
            for connector in floor["connectors"]:
                left, right = connector["from_room"], connector["to_room"]
                if left not in rooms or right not in rooms:
                    raise AssertionError(f"connector missing room: {building['id']}")
                a, b = tuple(connector["from_cell"]), tuple(connector["to_cell"])
                if occupied.get(a) != left or occupied.get(b) != right or abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                    raise AssertionError(f"invalid room connector: {building['id']} {left}/{right}")
                graph[left].add(right)
                graph[right].add(left)
            if floor["floor_index"] == 1:
                starts = entry_rooms & set(rooms)
                if not starts:
                    raise AssertionError(f"no valid ground-floor entrance: {building['id']}")
                seen = set(starts)
                queue = deque(starts)
                while queue:
                    current = queue.popleft()
                    for neighbor in graph[current]:
                        if neighbor not in seen:
                            seen.add(neighbor)
                            queue.append(neighbor)
                if seen != set(rooms):
                    raise AssertionError(f"disconnected ground-floor rooms: {building['id']}")
            for stair in floor["stairs"]:
                point = (stair["row"], stair["col"])
                if point not in occupied or abs(int(stair["to_floor"]) - int(floor["floor_index"])) != 1:
                    raise AssertionError(f"invalid stair: {building['id']}")
        for entry in building["entrances"]:
            point = (entry["row"], entry["col"])
            if point not in b_cells or entry["room_id"] not in room_lookup:
                raise AssertionError(f"invalid entrance: {building['id']}")
            entry_building, entry_floor, entry_room_cells = room_lookup[entry["room_id"]]
            if entry_building != building["id"] or entry_floor != 1 or point not in entry_room_cells:
                raise AssertionError(f"entrance room metadata mismatch: {building['id']} {entry['room_id']}")
            explicit_outside = entry.get("outside")
            adjacent_outdoor = bool(explicit_outside) or any(
                (point[0] + dr, point[1] + dc) not in footprint
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
            )
            if not adjacent_outdoor:
                raise AssertionError(f"entrance is not on exterior: {building['id']}")
        building_reports.append({"id": building["id"], "floors": len(floors), "rooms": sum(len(f["rooms"]) for f in floors)})

    outdoor = {(cell["row"], cell["col"]) for cell in cells if cell["surface_type"] == "outdoor"}
    start = tuple(spec["anchors"]["party_start"])
    if start not in outdoor:
        raise AssertionError("party start must be outdoors")
    connected = _reachable(start, outdoor)
    if connected != outdoor:
        raise AssertionError(f"{len(outdoor - connected)} outdoor cells are disconnected")
    zone_counts = Counter(cell["zone"] for cell in cells if cell["surface_type"] == "outdoor")
    return {
        "status": "passed", "width": width, "height": height,
        "physical_size_ft": [width * int(spec["cell_size_ft"]), height * int(spec["cell_size_ft"])],
        "buildings": building_reports, "building_count": len(building_reports), "multi_level_buildings": multi_level,
        "outdoor_walkable_cells": len(outdoor), "outdoor_reachable_cells": len(connected),
        "indoor_walkable_cells": sum(cell["surface_type"] == "indoor" for cell in cells),
        "outdoor_zone_counts": dict(sorted(zone_counts.items())),
        "anchors": spec["anchors"],
    }


def load_and_generate(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    cells = generate_cells(spec)
    return spec, cells, validate(spec, cells)
