"""Compile a solved room layout into the generic Viewer runtime contract.

The room solver intentionally knows nothing about rendering or token movement.
This module is the small, deterministic bridge between those concerns: a room
mask becomes tactical cells, shared boundaries become interactive doors, and
floor changes become explicit stair edges.  It keeps the layout JSON as the
authoritative source while allowing the existing Viewer navigation code to
load generated archetypes without a scene-specific adapter.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any, Mapping

from .archetype_manifest import canonical_bytes
from .mask import CellMask


RUNTIME_SCHEMA = "dnd-scene-runtime-2.0"


def _cell_id(level_id: str, row: int, col: int) -> str:
    return f"{level_id}:{row}:{col}"


def _center(mask: CellMask) -> tuple[int, int]:
    cells = mask.sorted_cells()
    if not cells:
        raise ValueError("room mask must contain at least one cell")
    row = sum(cell[0] for cell in cells) / len(cells)
    col = sum(cell[1] for cell in cells) / len(cells)
    return min(cells, key=lambda cell: (abs(cell[0] - row) + abs(cell[1] - col), cell[0], cell[1]))


def _surface(manifest_id: str, tags: list[str]) -> str:
    tag_set = set(tags)
    if manifest_id == "sewer" or "water" in tag_set or "route" in tag_set:
        return "sewage" if manifest_id == "sewer" else "stone_floor"
    return "secret_floor" if "secret" in tag_set else "interior_floor"


def _feature_for_room(manifest_id: str, room: Mapping[str, Any], center: tuple[int, int]) -> dict[str, Any]:
    tags = set(room.get("tags", []))
    role = str(room.get("role", "support"))
    if role == "entry":
        kind = "entry_table"
    elif role in {"objective", "boss"}:
        kind = "pump_controls" if manifest_id == "sewer" else "objective_core"
    elif role == "secret":
        kind = "secret_cache"
    elif role in {"landing", "stair"}:
        kind = "stair_landing"
    elif "water" in tags:
        kind = "channel_marker"
    elif "machine" in tags or "control" in tags:
        kind = "pump_controls"
    elif "clue" in tags:
        kind = "bookcase"
    elif "lived_in" in tags:
        kind = "bedroll"
    elif "security" in tags:
        kind = "weapon_rack"
    elif "high_ground" in tags or "rooftop" in tags:
        kind = "lookout_marker"
    elif "social" in tags:
        kind = "table"
    else:
        kind = "cargo_cluster"
    visibility = str(room.get("visibility", "public"))
    return {
        "id": f"feature:{room['id']}:{kind}",
        "kind": kind,
        "level_id": str(room["floor_id"]),
        "row": int(center[0]),
        "col": int(center[1]),
        "room_id": str(room["id"]),
        "volume_id": manifest_id,
        "visibility": visibility,
        "blocks_movement": False,
        "tags": sorted(tags | {role}),
        "variant": "generated",
        "rotation_deg": 0,
        "dimensions_ft": [5, 5, 5],
    }


def _runtime_level_id(manifest_id: str, floor_id: str) -> str:
    return f"{manifest_id}_{floor_id}"


def _connector_runtime(connector: Mapping[str, Any], floor_map: Mapping[str, str], room_map: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    endpoints = []
    for endpoint in connector["endpoints"]:
        floor_id = str(endpoint["floor_id"])
        room_id = str(endpoint["room_id"])
        endpoints.append({
            "level_id": floor_map[floor_id],
            "room_id": room_id,
            "row": int(endpoint["row"]),
            "col": int(endpoint["col"]),
            "volume_id": str(room_map[room_id].get("volume_id", "")),
        })
    return {
        "id": str(connector["id"]),
        "type": str(connector["type"]),
        "visibility": str(connector.get("visibility", "public")),
        "bidirectional": bool(connector.get("bidirectional", True)),
        "endpoints": endpoints,
        "cell_ids": [_cell_id(item["level_id"], item["row"], item["col"]) for item in endpoints],
    }


def compile_layout_runtime(layout: Mapping[str, Any], *, manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a deterministic ``scene.runtime.json`` from ``room.layout.json``."""

    manifest_id = str(layout.get("manifest_id", "archetype"))
    theme = layout.get("theme", {})
    footprint = layout.get("footprint", {})
    floor_map = {
        str(floor["id"]): _runtime_level_id(manifest_id, str(floor["id"]))
        for floor in layout.get("floors", [])
    }
    floors = list(layout.get("floors", []))
    room_map: dict[str, dict[str, Any]] = {}
    room_masks: dict[str, CellMask] = {}
    runtime_levels: list[dict[str, Any]] = []
    rooms: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []

    for floor in floors:
        floor_id = str(floor["id"])
        runtime_level_id = floor_map[floor_id]
        runtime_levels.append({
            "id": runtime_level_id,
            "label": str(floor.get("label", floor_id)),
            "volume_id": manifest_id,
            "z_base_ft": int(floor.get("z_base_ft", 0)),
            "height_ft": int(floor.get("height_ft", 12)),
        })
        for room in floor.get("rooms", []):
            room_id = str(room["id"])
            mask = CellMask.from_rle(room["cell_mask"])
            room_map[room_id] = {**room, "volume_id": manifest_id}
            room_masks[room_id] = mask
            visibility = str(room.get("visibility", "public"))
            tags = sorted(str(tag) for tag in room.get("tags", []))
            rooms.append({
                "id": room_id,
                "name": str(room["name"]),
                "role": str(room["role"]),
                "level_id": runtime_level_id,
                "volume_id": manifest_id,
                "visibility": visibility,
                "tags": tags,
            })
            center = _center(mask)
            feature = _feature_for_room(manifest_id, {**room, "floor_id": floor_id}, center)
            feature["level_id"] = runtime_level_id
            features.append(feature)
            role = str(room.get("role", "support"))
            if role == "entry":
                anchors.append({"id": "party_start", "kind": "party_start", "level_id": runtime_level_id, "row": center[0], "col": center[1], "visibility": "public"})
            elif role in {"objective", "boss"}:
                anchors.append({"id": f"objective:{room_id}", "kind": "objective", "level_id": runtime_level_id, "row": center[0], "col": center[1], "visibility": visibility})
            elif role == "secret":
                anchors.append({"id": f"secret:{room_id}", "kind": "secret", "level_id": runtime_level_id, "row": center[0], "col": center[1], "visibility": "dm_only"})

            z_base_ft = int(floor.get("z_base_ft", 0))
            for row, col in mask.sorted_cells():
                cells.append({
                    "id": _cell_id(runtime_level_id, row, col),
                    "level_id": runtime_level_id,
                    "row": row,
                    "col": col,
                    "z_base_ft": z_base_ft,
                    "walkable": True,
                    "surface": _surface(manifest_id, tags),
                    "volume_id": manifest_id,
                    "room_id": room_id,
                    "visibility": visibility,
                    "movement": {"walk": 1},
                    "navigation_group": room_id,
                })

    connectors = [_connector_runtime(connector, floor_map, room_map) for connector in layout.get("connectors", [])]
    nav_edges: list[dict[str, Any]] = []
    room_at: dict[tuple[str, int, int], str] = {}
    for room_id, mask in room_masks.items():
        floor_id = str(room_map[room_id]["floor_id"])
        level_id = floor_map[floor_id]
        for row, col in mask.cells:
            room_at[(level_id, row, col)] = room_id
            for other in ((row + 1, col), (row, col + 1)):
                if other not in mask.cells:
                    continue
                nav_edges.append({"a": _cell_id(level_id, row, col), "b": _cell_id(level_id, other[0], other[1]), "kind": "walk", "cost": 1})

    for connector in connectors:
        left, right = connector["cell_ids"]
        connector_type = str(connector["type"])
        nav_edges.append({
            "a": left,
            "b": right,
            "kind": connector_type,
            "connector_id": connector["id"],
            "cost": 1 if connector_type == "door" else 2,
            "interaction_required": True,
            "visibility": connector["visibility"],
        })

    # The runtime contract is also consumed by older Viewer code; retain a
    # compact hash so stale assets can be diagnosed without opening the layout.
    scene_id = f"{manifest_id}_archetype"
    family = str((manifest or {}).get("family", manifest_id))
    kind = "sewer" if manifest_id == "sewer" or "dungeon" in family else ("tower" if manifest_id == "tower" else "building")
    runtime: dict[str, Any] = {
        "schema_version": RUNTIME_SCHEMA,
        "generator_version": str(layout.get("solver_version", "")),
        "scene": {
            "id": scene_id,
            "name": str((manifest or {}).get("name", manifest_id)),
            "archetype": manifest_id,
            "family": family,
            "theme_id": str(layout.get("theme_id", "default")),
            "theme": theme,
            "seed": int(layout.get("seed", 0)),
            "grid": {
                "cell_size_ft": 5,
                "width": int(footprint.get("width", 0)),
                "height": int(footprint.get("height", 0)),
                "origin_ft": [0, 0, 0],
                "coordinate_contract": "cell(row,col)->world_ft(col*5,-row*5,z_base_ft)",
            },
            "levels": runtime_levels,
        },
        "volumes": [{
            "id": manifest_id,
            "name": str((manifest or {}).get("name", manifest_id)),
            "kind": kind,
            "archetype": manifest_id,
            "level_ids": [level["id"] for level in runtime_levels],
            "theme": theme,
        }],
        "rooms": sorted(rooms, key=lambda item: item["id"]),
        "cells": sorted(cells, key=lambda item: (item["level_id"], item["row"], item["col"])),
        "connectors": sorted(connectors, key=lambda item: item["id"]),
        "anchors": sorted(anchors, key=lambda item: item["id"]),
        "features": sorted(features, key=lambda item: item["id"]),
        "nav": {"mode": "explicit", "edges": sorted(nav_edges, key=lambda item: (item["a"], item["b"], item["kind"]))},
        "source": {
            "layout_sha256": str(layout.get("layout_sha256", "")),
            "manifest_id": manifest_id,
        },
    }
    runtime["runtime_sha256"] = hashlib.sha256(canonical_bytes(runtime)).hexdigest()
    return runtime


def validate_layout_runtime(runtime: Mapping[str, Any], layout: Mapping[str, Any]) -> dict[str, Any]:
    if runtime.get("schema_version") != RUNTIME_SCHEMA:
        raise ValueError("invalid runtime schema")
    if runtime.get("source", {}).get("layout_sha256") != layout.get("layout_sha256"):
        raise ValueError("runtime source layout hash mismatch")
    rooms = {room["id"] for room in runtime.get("rooms", [])}
    cells = {cell["id"] for cell in runtime.get("cells", [])}
    if not cells or not rooms:
        raise ValueError("runtime must contain rooms and cells")
    for cell in runtime["cells"]:
        if cell.get("room_id") not in rooms:
            raise ValueError(f"runtime cell references missing room: {cell.get('id')}")
    connector_ids = {connector["id"] for connector in runtime.get("connectors", [])}
    for edge in runtime.get("nav", {}).get("edges", []):
        if edge["a"] not in cells or edge["b"] not in cells:
            raise ValueError("runtime nav edge references missing cell")
        if edge.get("connector_id") and edge["connector_id"] not in connector_ids:
            raise ValueError("runtime nav edge references missing connector")
    return {
        "status": "passed",
        "scene_id": runtime["scene"]["id"],
        "levels": len(runtime["scene"]["levels"]),
        "rooms": len(runtime["rooms"]),
        "cells": len(runtime["cells"]),
        "connectors": len(runtime["connectors"]),
        "nav_edges": len(runtime["nav"]["edges"]),
        "anchors": len(runtime["anchors"]),
        "features": len(runtime["features"]),
        "runtime_sha256": runtime["runtime_sha256"],
    }
