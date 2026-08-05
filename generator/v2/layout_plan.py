"""Adapt a solved archetype layout to the existing Blender scene-plan contract."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from .archetype_manifest import canonical_bytes
from .layout_runtime import compile_layout_runtime
from .mask import CellMask


def _mask_for_cells(cells: list[tuple[int, int]]) -> dict[str, Any]:
    return CellMask(set(cells)).to_rle()


def compile_layout_plan(layout: Mapping[str, Any], *, runtime: Mapping[str, Any] | None = None, manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    runtime = runtime or compile_layout_runtime(layout, manifest=manifest)
    manifest_id = str(layout.get("manifest_id", "archetype"))
    family = str((manifest or {}).get("family", manifest_id))
    kind = "sewer" if manifest_id == "sewer" or "dungeon" in family else ("tower" if manifest_id == "tower" else "building")
    level_items = list(runtime["scene"]["levels"])
    level_map = {str(item["id"]): item for item in level_items}
    runtime_cells = list(runtime["cells"])
    cells_by_level: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for cell in runtime_cells:
        cells_by_level[str(cell["level_id"])].append((int(cell["row"]), int(cell["col"])))

    volumes = [{
        "id": manifest_id,
        "name": str((manifest or {}).get("name", manifest_id)),
        "kind": kind,
        "archetype": manifest_id,
        "level_ids": [item["id"] for item in level_items],
        # Archetype exports are tactical interior cutaways.  The Viewer can
        # still provide an exterior presentation later, but a closed roof here
        # would hide the generated rooms, stairs and DM-only chamber in the
        # certification render.
        "roof": {"shape": "none", "material": "generated"},
        "facade": {"primary": str(runtime["scene"].get("theme", {}).get("family", manifest_id))},
        "style": {"theme_id": layout.get("theme_id", "default"), "theme": layout.get("theme", {})},
    }]
    levels: list[dict[str, Any]] = []
    for level in level_items:
        levels.append({
            "id": level["id"],
            "label": level.get("label", level["id"]),
            "volume_id": manifest_id,
            "z_base_ft": int(level.get("z_base_ft", 0)),
            "height_ft": int(level.get("height_ft", 12)),
            "cell_mask": _mask_for_cells(cells_by_level[level["id"]]),
        })

    rooms: list[dict[str, Any]] = []
    for floor in layout.get("floors", []):
        for room in floor.get("rooms", []):
            rooms.append({
                "id": room["id"],
                "name": room["name"],
                "level_id": level_map[f"{manifest_id}_{floor['id']}"]["id"],
                "volume_id": manifest_id,
                "role": room["role"],
                "visibility": room.get("visibility", "public"),
                "tags": sorted(str(tag) for tag in room.get("tags", [])),
                "cell_mask": room["cell_mask"],
            })

    connectors: list[dict[str, Any]] = []
    for connector in runtime.get("connectors", []):
        endpoints = []
        for endpoint in connector["endpoints"]:
            endpoints.append({
                **endpoint,
                "volume_id": manifest_id,
            })
        connectors.append({
            "id": connector["id"],
            "type": connector["type"],
            "visibility": connector.get("visibility", "public"),
            "bidirectional": connector.get("bidirectional", True),
            "endpoints": endpoints,
        })

    features = [dict(feature) for feature in runtime.get("features", [])]
    anchors = [
        {**anchor, "volume_id": manifest_id}
        for anchor in runtime.get("anchors", [])
    ]
    terrain: list[dict[str, Any]] = []
    if manifest_id == "sewer":
        sewer_cells = [(int(cell["row"]), int(cell["col"])) for cell in runtime_cells if cell.get("surface") == "sewage"]
        if sewer_cells:
            level_id = runtime_cells[0]["level_id"]
            terrain.append({
                "id": "generated_sewer_water",
                "kind": "sewage",
                "level_id": level_id,
                "cell_mask": _mask_for_cells(sewer_cells),
                "walkable": True,
            })

    scene_id = str(runtime["scene"]["id"])
    return {
        "schema_version": "dnd-scene-plan-2.0",
        "generator_version": str(layout.get("solver_version", "")),
        "scene": {
            "id": scene_id,
            "name": str(runtime["scene"].get("name", manifest_id)),
            "archetype": manifest_id,
            "family": family,
            "seed": int(layout.get("seed", 0)),
            "theme_id": str(layout.get("theme_id", "default")),
        },
        "grid": {
            "width": int(runtime["scene"]["grid"]["width"]),
            "height": int(runtime["scene"]["grid"]["height"]),
            "cell_size_ft": 5,
            "coordinate_contract": runtime["scene"]["grid"].get("coordinate_contract", "cell(row,col)->world_ft(col*5,-row*5,z_base_ft)"),
        },
        "levels": levels,
        "volumes": volumes,
        "rooms": rooms,
        "connectors": connectors,
        "terrain": terrain,
        "features": features,
        "anchors": anchors,
        "metadata": {
            "source_layout_sha256": layout.get("layout_sha256", ""),
            "source_runtime_sha256": runtime.get("runtime_sha256", ""),
            "theme": layout.get("theme", {}),
        },
    }


def canonical_plan_bytes(plan: Mapping[str, Any]) -> bytes:
    return canonical_bytes(plan)
