#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict, deque
from pathlib import Path


def fail(message: str) -> None:
    raise AssertionError(message)


def cells_for_room(room: dict) -> set[tuple[int, int]]:
    bounds = room["bounds"]
    return {
        (row, col)
        for row in range(bounds["row"], bounds["row"] + bounds["height"])
        for col in range(bounds["col"], bounds["col"] + bounds["width"])
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_spec.py SPEC.json")
    path = Path(sys.argv[1]).resolve()
    raw = path.read_bytes()
    spec = json.loads(raw)
    levels = spec["levels"]
    indexes = [level["level_index"] for level in levels]
    if indexes != [1, 2, 3]:
        fail(f"expected three contiguous levels, got {indexes}")

    all_room_ids: set[str] = set()
    secret_count = 0
    normal_door_count = 0
    secret_door_count = 0
    vertical_links: set[tuple[int, int]] = set()
    level_reports = []

    for level in levels:
        width, height = level["width"], level["height"]
        occupied: dict[tuple[int, int], str] = {}
        rooms = {room["id"]: room for room in level["rooms"]}
        graph: dict[str, set[str]] = defaultdict(set)
        for room in level["rooms"]:
            room_id = room["id"]
            if room_id in all_room_ids:
                fail(f"duplicate room id: {room_id}")
            all_room_ids.add(room_id)
            secret_count += room.get("visibility") == "dm_only"
            cells = cells_for_room(room)
            for row, col in cells:
                if not (0 <= row < height and 0 <= col < width):
                    fail(f"{room_id} leaves level bounds at {(row, col)}")
                if (row, col) in occupied:
                    fail(f"room overlap at {(row, col)}: {occupied[(row, col)]} / {room_id}")
                occupied[(row, col)] = room_id

        for connector in level["connectors"]:
            left = connector["from_room"]
            right = connector["to_room"]
            if left not in rooms or right not in rooms:
                fail(f"connector references missing room: {connector['id']}")
            from_cell = tuple(connector["from_cell"])
            to_cell = tuple(connector["to_cell"])
            if occupied.get(from_cell) != left or occupied.get(to_cell) != right:
                fail(f"connector cells do not belong to rooms: {connector['id']}")
            if abs(from_cell[0] - to_cell[0]) + abs(from_cell[1] - to_cell[1]) != 1:
                fail(f"connector cells are not adjacent: {connector['id']}")
            graph[left].add(right)
            graph[right].add(left)
            if connector["connector_type"] == "secret_door":
                secret_door_count += 1
                if not (rooms[left].get("visibility") == "dm_only" or rooms[right].get("visibility") == "dm_only"):
                    fail(f"secret door does not lead to secret room: {connector['id']}")
            else:
                normal_door_count += 1

        public_rooms = {room_id for room_id, room in rooms.items() if room.get("visibility") != "dm_only"}
        start = next(iter(public_rooms))
        visited = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in graph[current]:
                if neighbor in public_rooms and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        if visited != public_rooms:
            fail(f"public rooms are disconnected on level {level['level_index']}: {public_rooms - visited}")

        for stair in level["stairs"]:
            target = stair["to_level"]
            if target not in indexes or abs(target - level["level_index"]) != 1:
                fail(f"invalid vertical stair target: {stair['id']}")
            vertical_links.add(tuple(sorted((level["level_index"], target))))
            if (stair["row"], stair["col"]) not in occupied:
                fail(f"stair is not inside a room: {stair['id']}")

        level_reports.append(
            {
                "level": level["level_index"],
                "rooms": len(rooms),
                "public_rooms": len(public_rooms),
                "occupied_cells": len(occupied),
            }
        )

    if secret_count < 3 or secret_door_count < 3:
        fail("prototype needs at least one secret room and secret door per level")
    if vertical_links != {(1, 2), (2, 3)}:
        fail(f"vertical graph is incomplete: {vertical_links}")

    print(
        json.dumps(
            {
                "status": "passed",
                "schema_version": spec["schema_version"],
                "seed": spec["seed"],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "levels": level_reports,
                "rooms": len(all_room_ids),
                "secret_rooms": secret_count,
                "normal_doors": normal_door_count,
                "secret_doors": secret_door_count,
                "vertical_links": sorted([list(link) for link in vertical_links]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
