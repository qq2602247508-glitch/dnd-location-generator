from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, deque
from pathlib import Path
from typing import Any


def stable_noise(seed: int, row: int, col: int) -> float:
    payload = f"{seed}:{row}:{col}".encode()
    value = int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "little")
    return value / ((1 << 64) - 1)


def generate_cells(spec: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    width = int(spec["width"])
    height = int(spec["height"])
    seed = int(spec["seed"])
    center_row = (height - 1) / 2
    center_col = (width - 1) / 2
    cells: dict[tuple[int, int], dict[str, Any]] = {}

    for row in range(height):
        for col in range(width):
            ellipse = ((row - center_row) / (height * 0.49)) ** 2 + ((col - center_col) / (width * 0.49)) ** 2
            edge_noise = (stable_noise(seed, row, col) - 0.5) * 0.18
            walkable = ellipse <= 1.0 + edge_noise
            elevation = 1
            zone = "central_cavern"

            if 5 <= col <= 16 and 6 <= row <= 29:
                elevation = 3
                zone = "western_ridge"
            if 26 <= col <= 43 and 3 <= row <= 10:
                elevation = 4
                zone = "northern_ruin"
            if 31 <= col <= 45 and 15 <= row <= 32:
                elevation = 0
                zone = "fungal_basin"

            chasm_center = 23 + round(math.sin(row * 0.42) * 1.8)
            if abs(col - chasm_center) <= 1:
                walkable = False
                zone = "chasm"

            cells[(row, col)] = {
                "row": row,
                "col": col,
                "walkable": walkable,
                "elevation": elevation,
                "zone": zone,
                "movement_cost": 1,
            }

    def carve_path(points: list[tuple[int, int, int]], zone: str) -> None:
        for row, col, elevation in points:
            for spread in (-1, 0, 1):
                key = (row + spread, col)
                if key in cells:
                    cells[key].update(walkable=True, elevation=elevation, zone=zone)

    carve_path(
        [(18, col, elevation) for col, elevation in zip(range(13, 22), (3, 3, 3, 2, 2, 1, 1, 1, 1), strict=True)],
        "western_ramp",
    )
    carve_path(
        [(row, 35, elevation) for row, elevation in zip(range(8, 17), (4, 4, 3, 3, 2, 2, 1, 1, 1), strict=True)],
        "northern_ramp",
    )
    carve_path(
        [(22, col, elevation) for col, elevation in zip(range(27, 34), (1, 1, 1, 0, 0, 0, 0), strict=True)],
        "basin_ramp",
    )

    for bridge_row in (11, 26):
        chasm_center = 23 + round(math.sin(bridge_row * 0.42) * 1.8)
        for col in range(chasm_center - 3, chasm_center + 4):
            for row in (bridge_row, bridge_row + 1):
                cells[(row, col)].update(
                    walkable=True,
                    elevation=1,
                    zone="stone_bridge",
                    movement_cost=1,
                )

    for anchor_name, point in spec["anchors"].items():
        row, col = point
        cells[(row, col)].update(walkable=True, zone=anchor_name)

    # Natural ellipse noise can leave tiny shelves outside the playable cave.
    # Keep only the movement-connected component containing the party start so
    # every rendered tactical tile is genuinely reachable under the same
    # one-elevation-step movement contract used by validation.
    start = tuple(spec["anchors"]["party_start"])
    reachable = {start}
    queue = deque([start])
    while queue:
        row, col = queue.popleft()
        current_height = int(cells[(row, col)]["elevation"])
        for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            if neighbor not in cells or neighbor in reachable or not cells[neighbor]["walkable"]:
                continue
            if abs(int(cells[neighbor]["elevation"]) - current_height) > 1:
                continue
            reachable.add(neighbor)
            queue.append(neighbor)
    for key, cell in cells.items():
        if cell["walkable"] and key not in reachable:
            cell.update(walkable=False, zone="sealed_ledge")
    return cells


def validate(spec: dict[str, Any], cells: dict[tuple[int, int], dict[str, Any]]) -> dict[str, Any]:
    walkable = {key for key, cell in cells.items() if cell["walkable"]}
    start = tuple(spec["anchors"]["party_start"])
    if start not in walkable:
        raise AssertionError("party_start is not walkable")

    visited = {start}
    queue = deque([start])
    while queue:
        row, col = queue.popleft()
        current_height = int(cells[(row, col)]["elevation"])
        for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            if neighbor not in walkable or neighbor in visited:
                continue
            if abs(int(cells[neighbor]["elevation"]) - current_height) > 1:
                continue
            visited.add(neighbor)
            queue.append(neighbor)

    anchors = {name: tuple(point) for name, point in spec["anchors"].items()}
    unreachable_anchors = sorted(name for name, point in anchors.items() if point not in visited)
    if unreachable_anchors:
        raise AssertionError(f"unreachable anchors: {unreachable_anchors}")
    disconnected = walkable - visited
    if disconnected:
        raise AssertionError(f"{len(disconnected)} walkable cells are disconnected")

    elevations = Counter(int(cells[key]["elevation"]) for key in walkable)
    zones = Counter(str(cells[key]["zone"]) for key in walkable)
    bridges = {key for key in walkable if cells[key]["zone"] == "stone_bridge"}
    if len(bridges) < 20:
        raise AssertionError("bridge coverage is too small")
    if max(elevations) - min(elevations) < 4:
        raise AssertionError("elevation range is too small")

    return {
        "status": "passed",
        "width": spec["width"],
        "height": spec["height"],
        "physical_size_ft": [spec["width"] * spec["cell_size_ft"], spec["height"] * spec["cell_size_ft"]],
        "walkable_cells": len(walkable),
        "blocked_cells": len(cells) - len(walkable),
        "reachable_cells": len(visited),
        "elevation_counts": dict(sorted(elevations.items())),
        "zone_counts": dict(sorted(zones.items())),
        "anchors": {name: list(point) for name, point in anchors.items()},
        "bridges_cells": len(bridges),
    }


def load_and_generate(path: Path) -> tuple[dict[str, Any], dict[tuple[int, int], dict[str, Any]], dict[str, Any]]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    cells = generate_cells(spec)
    report = validate(spec, cells)
    return spec, cells, report
