from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]


def input_directory() -> Path:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if "--input-dir" in args:
        return Path(args[args.index("--input-dir") + 1]).expanduser().resolve()
    return ROOT / "output" / "harbor-v2"


OUT = input_directory()
PLAN_PATH = OUT / "scene.plan.json"
RUNTIME_PATH = OUT / "scene.runtime.json"
PLAN = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
RUNTIME = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
CELL = float(PLAN["grid"]["cell_size_ft"]) / 5.0
FT = 1.0 / 5.0
LEVELS = {item["id"]: item for item in PLAN["levels"]}
ROOMS = {item["id"]: item for item in PLAN["rooms"]}
VOLUMES = {item["id"]: item for item in PLAN["volumes"]}
OBJECTS: list[bpy.types.Object] = []
MATERIALS: dict[str, bpy.types.Material] = {}
STATS: defaultdict[str, int] = defaultdict(int)

Box = tuple[tuple[float, float, float], tuple[float, float, float]]
Edge = tuple[tuple[int, int], tuple[int, int]]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cells_from_rle(mask: dict[str, Any]) -> set[tuple[int, int]]:
    if mask.get("encoding") != "rle-v1":
        raise ValueError(f"unsupported mask encoding: {mask.get('encoding')}")
    result: set[tuple[int, int]] = set()
    for row, start_col, length in mask.get("runs", []):
        result.update((int(row), col) for col in range(int(start_col), int(start_col) + int(length)))
    return result


def clean_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.users == 0:
            bpy.data.collections.remove(collection)


def material(name: str, color: tuple[float, float, float, float], *, roughness: float = .72, metallic: float = 0.0, emission: float = 0.0) -> bpy.types.Material:
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    # Node display names can be localized or renamed between Blender builds;
    # node.type and socket identifiers are stable API contracts.
    bsdf = next((node for node in value.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        sockets = {socket.identifier: socket for socket in bsdf.inputs}
        sockets["Base Color"].default_value = color
        sockets["Roughness"].default_value = roughness
        sockets["Metallic"].default_value = metallic
        if emission and "Emission Color" in sockets:
            sockets["Emission Color"].default_value = color
            sockets["Emission Strength"].default_value = emission
    MATERIALS[name] = value
    return value


def tag(obj: bpy.types.Object, *, kind: str, level_id: str = "", material_id: str = "", visibility: str = "public", pick_role: str = "none", **extras: Any) -> bpy.types.Object:
    obj["prototype"] = True
    obj["schema_version"] = PLAN["schema_version"]
    obj["prototype_kind"] = kind
    obj["level_id"] = level_id
    obj["z_base_ft"] = float(LEVELS.get(level_id, {}).get("z_base_ft", 0))
    obj["material_id"] = material_id
    obj["prototype_visibility"] = visibility
    obj["pick_role"] = pick_role
    for key, value in extras.items():
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            value = json.dumps(list(value) if isinstance(value, set) else value, ensure_ascii=False, separators=(",", ":"))
        obj[key] = value
    OBJECTS.append(obj)
    STATS[f"kind_{kind}"] += 1
    return obj


def boxes_mesh(name: str, boxes: Iterable[Box], mat: bpy.types.Material, **metadata: Any) -> bpy.types.Object | None:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    count = 0
    for (cx, cy, cz), (sx, sy, sz) in boxes:
        base = len(vertices)
        vertices.extend([
            (cx - sx / 2, cy - sy / 2, cz - sz / 2), (cx + sx / 2, cy - sy / 2, cz - sz / 2),
            (cx + sx / 2, cy + sy / 2, cz - sz / 2), (cx - sx / 2, cy + sy / 2, cz - sz / 2),
            (cx - sx / 2, cy - sy / 2, cz + sz / 2), (cx + sx / 2, cy - sy / 2, cz + sz / 2),
            (cx + sx / 2, cy + sy / 2, cz + sz / 2), (cx - sx / 2, cy + sy / 2, cz + sz / 2),
        ])
        faces.extend([(base + a, base + b, base + c, base + d) for a, b, c, d in (
            (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
        )])
        count += 1
    if not count:
        return None
    data = bpy.data.meshes.new(f"{name}_Mesh")
    data.from_pydata(vertices, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(mat)
    STATS["batched_boxes"] += count
    STATS["mesh_vertices"] += len(vertices)
    return tag(obj, **metadata)


def cell_box(row: int, col: int, z: float, *, height: float = .12, inset: float = .018) -> Box:
    size = CELL - inset
    return ((col * CELL + CELL / 2, row * CELL + CELL / 2, z - height / 2), (size, size, height))


def edge_box(edge: Edge, z: float, height: float, thickness: float = .11) -> Box:
    (row, col), (other_row, other_col) = edge
    if row == other_row:
        x, y = max(col, other_col) * CELL, row * CELL + CELL / 2
        dims = (thickness, CELL + thickness, height)
    else:
        x, y = col * CELL + CELL / 2, max(row, other_row) * CELL
        dims = (CELL + thickness, thickness, height)
    return ((x, y, z + height / 2), dims)


def boundary_edges(cells: set[tuple[int, int]]) -> set[Edge]:
    result: set[Edge] = set()
    for row, col in cells:
        for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            if neighbor not in cells:
                result.add(((row, col), neighbor))
    return result


def edge_key(left: tuple[int, int], right: tuple[int, int]) -> frozenset[tuple[int, int]]:
    return frozenset((left, right))


def mask_bounds(cells: set[tuple[int, int]]) -> tuple[int, int, int, int]:
    rows = [point[0] for point in cells]
    cols = [point[1] for point in cells]
    return min(rows), min(cols), max(rows) + 1, max(cols) + 1


def frame_boxes(edge: Edge, z: float, *, panel: bool = False) -> list[Box]:
    """Low-poly door frame centered on a tactical cell boundary."""
    (row, col), (other_row, other_col) = edge
    boxes: list[Box] = []
    if row == other_row:
        x, y = max(col, other_col) * CELL, row * CELL + CELL / 2
        boxes.extend([
            ((x, y - .36, z + .78), (.13, .13, 1.56)), ((x, y + .36, z + .78), (.13, .13, 1.56)),
            ((x, y, z + 1.53), (.15, .84, .14)),
        ])
        if panel:
            boxes.append(((x, y, z + .71), (.07, .61, 1.34)))
    else:
        x, y = col * CELL + CELL / 2, max(row, other_row) * CELL
        boxes.extend([
            ((x - .36, y, z + .78), (.13, .13, 1.56)), ((x + .36, y, z + .78), (.13, .13, 1.56)),
            ((x, y, z + 1.53), (.84, .15, .14)),
        ])
        if panel:
            boxes.append(((x, y, z + .71), (.61, .07, 1.34)))
    return boxes


def build_terrain() -> None:
    terrain_material = {"ground": "ground", "road": "road", "water": "water", "sewage": "sewage"}
    for terrain in PLAN["terrain"]:
        cells = cells_from_rle(terrain["cell_mask"])
        level_id = terrain["level_id"]
        z = float(LEVELS[level_id]["z_base_ft"]) * FT
        kind = terrain["kind"]
        height = .08 if kind == "water" else .12
        z_offset = -.12 if kind == "water" else 0.0
        boxes_mesh(
            f"Surface_{level_id}_{kind}",
            (cell_box(row, col, z + z_offset, height=height) for row, col in sorted(cells)),
            MATERIALS[terrain_material.get(kind, "ground")],
            kind="surface", level_id=level_id, material_id=kind, visibility="public",
            pick_role="tactical_floor" if terrain.get("walkable") else "blocked_surface",
            surface_kind=kind, walkable=bool(terrain.get("walkable")), area_id=terrain["id"], cell_count=len(cells),
        )
        grid_boxes = []
        for row, col in sorted(cells):
            grid_z = z + z_offset + .012
            grid_boxes.extend([
                ((col * CELL + CELL / 2, row * CELL + .012, grid_z), (CELL - .025, .022, .014)),
                ((col * CELL + .012, row * CELL + CELL / 2, grid_z), (.022, CELL - .025, .014)),
            ])
        boxes_mesh(
            f"SurfaceGrid_{level_id}_{kind}", grid_boxes, MATERIALS["grid_surface"],
            kind="grid", level_id=level_id, material_id="grid_surface", visibility="public", pick_role="none",
            surface_kind=kind, area_id=terrain["id"], line_count=len(grid_boxes),
        )


def runtime_groups() -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    explicit_terrain = {
        (terrain["level_id"], row, col)
        for terrain in PLAN["terrain"]
        for row, col in cells_from_rle(terrain["cell_mask"])
    }
    for cell in RUNTIME["cells"]:
        if cell["level_id"] == "surface":
            continue
        if (cell["level_id"], int(cell["row"]), int(cell["col"])) in explicit_terrain:
            continue
        groups[(cell["level_id"], cell["surface"], cell.get("visibility", "public"))].append(cell)
    return groups


def build_level_floors_and_grids() -> None:
    grid_by_level: dict[tuple[str, str], list[Box]] = defaultdict(list)
    for (level_id, surface, visibility), cells in sorted(runtime_groups().items()):
        z = float(LEVELS[level_id]["z_base_ft"]) * FT
        material_name = "sewage" if surface == "sewage" else ("secret_floor" if visibility == "dm_only" else "interior")
        room_ids = sorted({cell.get("room_id", "") for cell in cells if cell.get("room_id")})
        volume_ids = sorted({cell.get("volume_id", "") for cell in cells if cell.get("volume_id")})
        boxes_mesh(
            f"Floor_{level_id}_{surface}_{visibility}",
            (cell_box(int(cell["row"]), int(cell["col"]), z) for cell in cells), MATERIALS[material_name],
            kind="floor", level_id=level_id, material_id=material_name, visibility=visibility, pick_role="tactical_floor",
            room_ids=room_ids, volume_ids=volume_ids, surface_kind=surface, cell_count=len(cells),
        )
        for cell in cells:
            row, col = int(cell["row"]), int(cell["col"])
            grid_by_level[(level_id, visibility)].extend([
                ((col * CELL + CELL / 2, row * CELL + .012, z + .018), (CELL - .03, .024, .016)),
                ((col * CELL + .012, row * CELL + CELL / 2, z + .018), (.024, CELL - .03, .016)),
            ])
    for (level_id, visibility), boxes in grid_by_level.items():
        boxes_mesh(f"Grid_{level_id}_{visibility}", boxes, MATERIALS["grid"], kind="grid", level_id=level_id, material_id="grid", visibility=visibility, pick_role="none", line_count=len(boxes))


def connector_open_edges() -> dict[str, set[frozenset[tuple[int, int]]]]:
    result: dict[str, set[frozenset[tuple[int, int]]]] = defaultdict(set)
    for connector in PLAN["connectors"]:
        left, right = connector["endpoints"]
        adjacent = abs(left["row"] - right["row"]) + abs(left["col"] - right["col"]) == 1
        if adjacent:
            opening = edge_key((left["row"], left["col"]), (right["row"], right["col"]))
            if left["level_id"] == right["level_id"]:
                result[left["level_id"]].add(opening)
            else:
                # Surface-to-volume doors remove the matching exterior wall on
                # the building level, producing a real doorway rather than a
                # colored marker pasted onto a closed facade.
                for endpoint in (left, right):
                    if endpoint["level_id"] != "surface":
                        result[endpoint["level_id"]].add(opening)
    return result


def build_walls() -> None:
    openings = connector_open_edges()
    rooms_by_level: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for room in PLAN["rooms"]:
        rooms_by_level[room["level_id"]].append(room)
    for level_id, level in LEVELS.items():
        if level_id == "surface" or float(level.get("height_ft", 0)) <= 0:
            continue
        volume = VOLUMES.get(level.get("volume_id", ""), {})
        if volume.get("kind") == "roof_route":
            continue
        cells = cells_from_rle(level["cell_mask"])
        room_at: dict[tuple[int, int], dict[str, Any]] = {}
        for room in rooms_by_level[level_id]:
            for point in cells_from_rle(room["cell_mask"]):
                room_at[point] = room
        wall_groups: dict[str, set[Edge]] = defaultdict(set)
        for edge in boundary_edges(cells):
            if edge_key(*edge) in openings[level_id]:
                continue
            room = room_at.get(edge[0])
            visibility = room.get("visibility", "public") if room else "public"
            wall_groups[visibility].add(edge)
        seen: set[frozenset[tuple[int, int]]] = set()
        for point, room in room_at.items():
            row, col = point
            for neighbor in ((row + 1, col), (row, col + 1)):
                other = room_at.get(neighbor)
                key = edge_key(point, neighbor)
                if not other or other["id"] == room["id"] or key in openings[level_id] or key in seen:
                    continue
                seen.add(key)
                visibility = "dm_only" if room.get("visibility") == other.get("visibility") == "dm_only" else "public"
                wall_groups[visibility].add((point, neighbor))
        z = float(level["z_base_ft"]) * FT
        height = max(1.35, float(level["height_ft"]) * FT * .78)
        for visibility, edges in wall_groups.items():
            volume_ids = sorted({room.get("volume_id", "") for room in rooms_by_level[level_id] if room.get("volume_id")})
            room_ids = sorted(room["id"] for room in rooms_by_level[level_id] if room.get("visibility", "public") == visibility)
            boxes_mesh(
                f"Walls_{level_id}_{visibility}", (edge_box(edge, z, height) for edge in sorted(edges)), MATERIALS["secret_wall" if visibility == "dm_only" else "wall"],
                kind="wall", level_id=level_id, material_id="wall", visibility=visibility, pick_role="occluder",
                volume_ids=volume_ids, room_ids=room_ids, edge_count=len(edges),
            )


def build_roofs() -> None:
    for volume in PLAN["volumes"]:
        if volume.get("kind") in {"sewer", "roof_route"} or not volume.get("level_ids"):
            continue
        level_id = volume["level_ids"][-1]
        level = LEVELS[level_id]
        cells = cells_from_rle(level["cell_mask"])
        z = (float(level["z_base_ft"]) + float(level["height_ft"]) * .82) * FT
        boxes_mesh(
            f"Roof_{volume['id']}_{level_id}", (cell_box(row, col, z, height=.16, inset=.04) for row, col in sorted(cells)), MATERIALS["roof"],
            kind="roof", level_id=level_id, material_id="roof", visibility="public", pick_role="hideable",
            volume_id=volume["id"], archetype=volume.get("archetype", ""), cell_count=len(cells),
        )


def connector_boxes(connector: dict[str, Any]) -> list[Box]:
    left, right = connector["endpoints"]
    z_left = float(LEVELS[left["level_id"]]["z_base_ft"]) * FT
    z_right = float(LEVELS[right["level_id"]]["z_base_ft"]) * FT
    points = [(left, z_left), (right, z_right)]
    if left["level_id"] == right["level_id"] and abs(left["row"] - right["row"]) + abs(left["col"] - right["col"]) == 1:
        edge = ((int(left["row"]), int(left["col"])), (int(right["row"]), int(right["col"])))
        center, dims = edge_box(edge, z_left + .035, .07, .52)
        return [(center, dims)]
    return [
        ((int(endpoint["col"]) * CELL + CELL / 2, int(endpoint["row"]) * CELL + CELL / 2, z + .12), (.82, .82, .22))
        for endpoint, z in points
    ]


def connector_visual_boxes(connector: dict[str, Any]) -> list[Box]:
    left, right = connector["endpoints"]
    z_left = float(LEVELS[left["level_id"]]["z_base_ft"]) * FT
    z_right = float(LEVELS[right["level_id"]]["z_base_ft"]) * FT
    left_point = (int(left["row"]), int(left["col"]))
    right_point = (int(right["row"]), int(right["col"]))
    connector_type = connector["type"]
    adjacent = abs(left_point[0] - right_point[0]) + abs(left_point[1] - right_point[1]) == 1
    if connector_type == "door" and adjacent:
        return frame_boxes((left_point, right_point), max(z_left, z_right), panel=False)
    if connector_type == "secret_door" and adjacent and left["level_id"] == right["level_id"]:
        return frame_boxes((left_point, right_point), z_left, panel=True)
    if connector_type in {"hatch", "secret_door"}:
        boxes: list[Box] = []
        for endpoint, z in ((left, z_left), (right, z_right)):
            x, y = int(endpoint["col"]) * CELL + CELL / 2, int(endpoint["row"]) * CELL + CELL / 2
            boxes.extend([
                ((x, y, z + .055), (.68, .68, .08)),
                ((x - .39, y, z + .10), (.09, .88, .18)), ((x + .39, y, z + .10), (.09, .88, .18)),
                ((x, y - .39, z + .10), (.70, .09, .18)), ((x, y + .39, z + .10), (.70, .09, .18)),
            ])
        return boxes
    if connector_type in {"stairs", "ladder"}:
        low, high = sorted((z_left, z_right))
        x = int(left["col"]) * CELL + CELL / 2
        y = int(left["row"]) * CELL + CELL / 2
        volume_id = left.get("volume_id") or right.get("volume_id", "")
        archetype = VOLUMES.get(volume_id, {}).get("archetype", "")
        boxes = []
        if archetype in {"signal_tower", "clock_tower"}:
            # A square spiral reads clearly from the tactical camera while
            # remaining boxes-only and inexpensive.
            offsets = [(-.28, -.28), (0, -.34), (.28, -.28), (.34, 0), (.28, .28), (0, .34), (-.28, .28), (-.34, 0)]
            for index in range(16):
                dx, dy = offsets[index % len(offsets)]
                z = low + (high - low) * (index + 1) / 17
                boxes.append(((x + dx, y + dy, z), (.30, .30, .13)))
        elif connector_type == "stairs":
            for index in range(12):
                run = index if index < 6 else 11 - index
                dx = -.23 if index < 6 else .23
                dy = -.38 + run * .15
                z = low + (high - low) * (index + 1) / 13
                boxes.append(((x + dx, y + dy, z), (.38, .18, .14)))
            boxes.append(((x, y + .42, (low + high) / 2), (.92, .34, .12)))
        else:
            for index in range(9):
                z = low + (high - low) * (index + 1) / 10
                boxes.append(((x, y, z), (.72, .14, .08)))
            boxes.extend([((x - .38, y, (low + high) / 2), (.08, .12, high - low)), ((x + .38, y, (low + high) / 2), (.08, .12, high - low))])
        return boxes
    if connector_type == "bridge":
        x0, y0 = left_point[1] * CELL + CELL / 2, left_point[0] * CELL + CELL / 2
        x1, y1 = right_point[1] * CELL + CELL / 2, right_point[0] * CELL + CELL / 2
        steps = max(2, int(max(abs(x1 - x0), abs(y1 - y0)) / .28))
        return [
            ((x0 + (x1 - x0) * index / steps, y0 + (y1 - y0) * index / steps, max(z_left, z_right) + .08), (.34, .82, .14))
            for index in range(steps + 1)
        ]
    return []


def build_connectors() -> None:
    visual_batches: dict[tuple[str, tuple[str, ...], tuple[str, ...], str, str], list[tuple[dict[str, Any], Box]]] = defaultdict(list)
    for connector in PLAN["connectors"]:
        level_ids = sorted({endpoint["level_id"] for endpoint in connector["endpoints"]})
        volume_ids = sorted({endpoint.get("volume_id", "") for endpoint in connector["endpoints"]})
        primary_level = level_ids[0]
        connector_type = connector["type"]
        material_name = "connector_secret" if connector.get("visibility") == "dm_only" else ("connector_vertical" if connector_type in {"stairs", "hatch", "ladder", "bridge"} else "connector")
        boxes_mesh(
            f"Connector_{connector['id']}", connector_boxes(connector), MATERIALS[material_name],
            kind="connector", level_id=primary_level, material_id=material_name, visibility=connector.get("visibility", "public"), pick_role="connector",
            connector_id=connector["id"], connector_type=connector_type, bidirectional=bool(connector.get("bidirectional")),
            level_ids=level_ids, volume_ids=volume_ids, endpoints=connector["endpoints"],
        )
        for box in connector_visual_boxes(connector):
            signature = (primary_level, tuple(level_ids), tuple(volume_ids), connector_type, connector.get("visibility", "public"))
            visual_batches[signature].append((connector, box))
    visual_materials = {"door": "door_frame", "stairs": "stair_wood", "ladder": "hatch_metal", "bridge": "stair_wood", "hatch": "hatch_metal", "secret_door": "secret_portal"}
    for (level_id, signature_levels, signature_volumes, connector_type, visibility), items in visual_batches.items():
        connector_ids = sorted({connector["id"] for connector, _ in items})
        level_ids = list(signature_levels)
        volume_ids = list(signature_volumes)
        material_name = visual_materials.get(connector_type, "door_frame")
        boxes_mesh(
            f"ConnectorVisual_{level_id}_{'_'.join(volume_ids) or 'surface'}_{connector_type}_{visibility}",
            (box for _, box in items), MATERIALS[material_name],
            kind="connector_visual", level_id=level_id, material_id=material_name, visibility=visibility, pick_role="none",
            visual_role=connector_type, connector_ids=connector_ids, level_ids=level_ids, volume_ids=volume_ids,
            connector_count=len(connector_ids),
        )


def facade_window_boxes(cells: set[tuple[int, int]], z: float) -> list[Box]:
    min_row, min_col, max_row, max_col = mask_bounds(cells)
    mid_row = (min_row + max_row) / 2 * CELL
    mid_col = (min_col + max_col) / 2 * CELL
    inset = .035
    return [
        ((mid_col, min_row * CELL - inset, z + 1.15), (.48, .06, .42)),
        ((mid_col, max_row * CELL + inset, z + 1.15), (.48, .06, .42)),
        ((min_col * CELL - inset, mid_row, z + 1.15), (.06, .48, .42)),
        ((max_col * CELL + inset, mid_row, z + 1.15), (.06, .48, .42)),
    ]


def build_archetype_details() -> None:
    for volume in PLAN["volumes"]:
        archetype = volume.get("archetype", "")
        if archetype not in {"signal_tower", "clock_tower", "inn"}:
            continue
        for level_id in volume["level_ids"]:
            level = LEVELS[level_id]
            cells = cells_from_rle(level["cell_mask"])
            z = float(level["z_base_ft"]) * FT
            boxes_mesh(
                f"Windows_{volume['id']}_{level_id}", facade_window_boxes(cells, z), MATERIALS["window_glow"],
                kind="archetype_detail", level_id=level_id, material_id="window_glow", visibility="public", pick_role="none",
                detail_group=archetype, detail_role="windows", volume_id=volume["id"],
            )

        top_level_id = volume["level_ids"][-1]
        top_level = LEVELS[top_level_id]
        top_cells = cells_from_rle(top_level["cell_mask"])
        min_row, min_col, max_row, max_col = mask_bounds(top_cells)
        roof_z = (float(top_level["z_base_ft"]) + float(top_level["height_ft"]) * .82) * FT
        if archetype in {"signal_tower", "clock_tower"}:
            perimeter = sorted({edge[0] for edge in boundary_edges(top_cells)})
            battlements = [
                ((col * CELL + CELL / 2, row * CELL + CELL / 2, roof_z + .24), (.38, .38, .48))
                for index, (row, col) in enumerate(perimeter) if index % 2 == 0
            ]
            boxes_mesh(
                f"TowerBattlements_{volume['id']}", battlements, MATERIALS["tower_stone"],
                kind="archetype_detail", level_id=top_level_id, material_id="tower_stone", visibility="public", pick_role="none",
                detail_group="signal_tower", detail_role="battlements", volume_id=volume["id"],
            )
            cx, cy = (min_col + max_col) * CELL / 2, (min_row + max_row) * CELL / 2
            if archetype == "clock_tower":
                boxes_mesh(
                    f"ClockBelfry_{volume['id']}", [
                        ((cx, cy, roof_z + .42), (1.42, 1.42, .18)),
                        ((cx, cy, roof_z + 1.02), (.82, .82, 1.05)),
                        ((cx, cy, roof_z + 1.65), (1.18, 1.18, .18)),
                    ], MATERIALS["clock_gold"],
                    kind="archetype_detail", level_id=top_level_id, material_id="clock_gold", visibility="public", pick_role="none",
                    detail_group="clock_tower", detail_role="great_bell", volume_id=volume["id"],
                )
                face_boxes = [
                    ((cx, min_row * CELL - .07, roof_z - .50), (1.08, .08, 1.08)),
                    ((cx, max_row * CELL + .07, roof_z - .50), (1.08, .08, 1.08)),
                    ((min_col * CELL - .07, cy, roof_z - .50), (.08, 1.08, 1.08)),
                    ((max_col * CELL + .07, cy, roof_z - .50), (.08, 1.08, 1.08)),
                ]
                boxes_mesh(
                    f"ClockFaces_{volume['id']}", face_boxes, MATERIALS["clock_face"],
                    kind="archetype_detail", level_id=top_level_id, material_id="clock_face", visibility="public", pick_role="none",
                    detail_group="clock_tower", detail_role="clock_faces", volume_id=volume["id"],
                )
            else:
                boxes_mesh(
                    f"TowerBeacon_{volume['id']}", [
                        ((cx, cy, roof_z + .20), (1.25, 1.25, .24)),
                        ((cx, cy, roof_z + .88), (.22, .22, 1.25)),
                        ((cx, cy, roof_z + 1.58), (.70, .70, .34)),
                    ], MATERIALS["beacon"],
                    kind="archetype_detail", level_id=top_level_id, material_id="beacon", visibility="public", pick_role="none",
                    detail_group="signal_tower", detail_role="beacon", volume_id=volume["id"],
                )
        else:
            # A cell-stepped gable follows arbitrary L-shaped inn masks while
            # preserving the same single batched mesh and hideable roof role.
            roof_boxes = []
            for row, col in sorted(top_cells):
                rise = min(row - min_row, max_row - 1 - row) * .20
                roof_boxes.append(((col * CELL + CELL / 2, row * CELL + CELL / 2, roof_z + .10 + rise), (CELL - .025, CELL - .025, .18)))
            boxes_mesh(
                f"InnGableRoof_{volume['id']}", roof_boxes, MATERIALS["inn_roof"],
                kind="archetype_detail", level_id=top_level_id, material_id="inn_roof", visibility="public", pick_role="hideable",
                detail_group="harbor_inn", detail_role="stepped_gable", volume_id=volume["id"],
            )
            cx = (min_col + max_col) * CELL / 2
            boxes_mesh(
                f"InnDetails_{volume['id']}", [
                    (((max_col - .8) * CELL, (min_row + 1.0) * CELL, roof_z + .80), (.42, .42, 1.45)),
                    ((cx, min_row * CELL - .20, .82), (1.15, .16, .62)),
                    ((cx, min_row * CELL - .16, 1.48), (.10, .10, .75)),
                ], MATERIALS["inn_trim"],
                kind="archetype_detail", level_id=top_level_id, material_id="inn_trim", visibility="public", pick_role="none",
                detail_group="harbor_inn", detail_role="chimney_sign", volume_id=volume["id"],
            )


def build_sewer_details() -> None:
    channel = next((item for item in PLAN["terrain"] if item["kind"] == "sewage"), None)
    if not channel:
        return
    level_id = channel["level_id"]
    z = float(LEVELS[level_id]["z_base_ft"]) * FT
    channel_cells = cells_from_rle(channel["cell_mask"])
    level_cells = cells_from_rle(LEVELS[level_id]["cell_mask"])
    curbs = [edge_box(edge, z + .015, .20, .12) for edge in boundary_edges(channel_cells) if edge[1] in level_cells]
    boxes_mesh(
        "SewerChannelCurbs", curbs, MATERIALS["sewer_stone"], kind="archetype_detail", level_id=level_id,
        material_id="sewer_stone", visibility="public", pick_role="none", detail_group="sewer", detail_role="channel_curbs",
    )
    ordered = sorted(channel_cells)
    bridge_points = [ordered[index] for index in sorted({len(ordered) * fraction // 5 for fraction in (1, 2, 3, 4)}) if index < len(ordered)]
    bridge_boxes = [((col * CELL + CELL / 2, row * CELL + CELL / 2, z + .12), (1.35, .72, .16)) for row, col in bridge_points]
    boxes_mesh(
        "SewerDryBridges", bridge_boxes, MATERIALS["sewer_bridge"], kind="archetype_detail", level_id=level_id,
        material_id="sewer_bridge", visibility="public", pick_role="none", detail_group="sewer", detail_role="dry_bridges",
    )
    outer_edges = sorted(boundary_edges(level_cells))
    pipe_boxes = [edge_box(edge, z + 1.05, .16, .18) for index, edge in enumerate(outer_edges) if index % 11 == 0]
    boxes_mesh(
        "SewerWallPipes", pipe_boxes, MATERIALS["pipe_metal"], kind="archetype_detail", level_id=level_id,
        material_id="pipe_metal", visibility="public", pick_role="none", detail_group="sewer", detail_role="wall_pipes",
    )


def build_clock_district_details() -> None:
    roof_volume = next((item for item in PLAN["volumes"] if item.get("kind") == "roof_route"), None)
    if roof_volume:
        level_id = roof_volume["level_ids"][0]
        z = float(LEVELS[level_id]["z_base_ft"]) * FT
        cells = cells_from_rle(LEVELS[level_id]["cell_mask"])
        rail_boxes = [edge_box(edge, z + .02, .42, .08) for edge in boundary_edges(cells)]
        boxes_mesh(
            "OldClockRoofRails", rail_boxes, MATERIALS["roof_rail"], kind="archetype_detail", level_id=level_id,
            material_id="roof_rail", visibility="public", pick_role="none", detail_group="old_clock",
            detail_role="roof_route_parapets", volume_id=roof_volume["id"],
        )
    if PLAN["scene"].get("id") != "old_clock_quarter_v23":
        return
    street = next((item for item in PLAN["terrain"] if item["id"] == "old_clock_streets"), None)
    if street:
        cells = cells_from_rle(street["cell_mask"])
        curb_boxes = [edge_box(edge, .015, .14, .08) for edge in boundary_edges(cells) if edge[1] not in cells]
        boxes_mesh(
            "OldClockStreetCurbs", curb_boxes, MATERIALS["curb_stone"], kind="life_trace", level_id="surface",
            material_id="curb_stone", visibility="public", pick_role="none", detail_group="old_clock",
            detail_role="irregular_street_edges",
        )


def build_harbor_details() -> None:
    water = next((item for item in PLAN["terrain"] if item["kind"] == "water"), None)
    if not water:
        return
    cells = cells_from_rle(water["cell_mask"])
    rows: dict[int, list[int]] = defaultdict(list)
    for row, col in cells:
        rows[row].append(col)
    candidate_rows = sorted(rows)
    chosen_rows = [candidate_rows[len(candidate_rows) * index // 5] for index in (1, 2, 3, 4)]
    deck_boxes: list[Box] = []
    piling_boxes: list[Box] = []
    crane_boxes: list[Box] = []
    for row in chosen_rows:
        shore = min(rows[row])
        for offset in range(4):
            deck_boxes.append((((shore + offset) * CELL + CELL / 2, row * CELL + CELL / 2, .10), (.96, 1.28, .18)))
        for offset in (0, 3):
            x = (shore + offset) * CELL + CELL / 2
            piling_boxes.extend([((x, row * CELL - .58, -.24), (.16, .16, .82)), ((x, row * CELL + 1.58, -.24), (.16, .16, .82))])
        if row in chosen_rows[::2]:
            x, y = (shore - .45) * CELL, row * CELL + CELL / 2
            crane_boxes.extend([((x, y, 1.10), (.22, .22, 2.20)), ((x + .78, y, 2.08), (1.65, .18, .18)), ((x + 1.50, y, 1.62), (.07, .07, .90))])
    boxes_mesh(
        "HarborPierDecks", deck_boxes, MATERIALS["dock_wood"], kind="harbor_detail", level_id="surface", material_id="dock_wood",
        visibility="public", pick_role="none", detail_group="harbor", detail_role="pier_decks", pier_count=len(chosen_rows),
    )
    boxes_mesh(
        "HarborPilings", piling_boxes, MATERIALS["wet_wood"], kind="harbor_detail", level_id="surface", material_id="wet_wood",
        visibility="public", pick_role="none", detail_group="harbor", detail_role="pilings",
    )
    boxes_mesh(
        "HarborCranes", crane_boxes, MATERIALS["dock_metal"], kind="harbor_detail", level_id="surface", material_id="dock_metal",
        visibility="public", pick_role="none", detail_group="harbor", detail_role="cranes",
    )


def feature_boxes(feature: dict[str, Any], z: float) -> list[Box]:
    x, y = int(feature["col"]) * CELL + CELL / 2, int(feature["row"]) * CELL + CELL / 2
    kind = feature["kind"]
    if kind == "market_stall":
        return [((x, y, z + .52), (.86, .62, .12)), ((x - .33, y - .22, z + .26), (.10, .10, .52)), ((x + .33, y - .22, z + .26), (.10, .10, .52)), ((x - .33, y + .22, z + .26), (.10, .10, .52)), ((x + .33, y + .22, z + .26), (.10, .10, .52))]
    if kind == "canvas_awning":
        return [((x, y, z + 1.18), (1.05, .82, .10)), ((x - .42, y - .30, z + .58), (.08, .08, 1.16)), ((x + .42, y - .30, z + .58), (.08, .08, 1.16))]
    if kind == "handcart":
        return [((x, y, z + .35), (.82, .48, .32)), ((x - .33, y, z + .18), (.18, .62, .36)), ((x + .33, y, z + .18), (.18, .62, .36)), ((x, y - .45, z + .24), (.16, .72, .12))]
    if kind in {"puddle", "wheel_rut"}:
        return [((x, y, z + .018), (.82, .34 if kind == "wheel_rut" else .68, .035))]
    if kind == "notice_board":
        return [((x, y, z + .72), (.82, .12, .72)), ((x - .30, y, z + .34), (.10, .10, .68)), ((x + .30, y, z + .34), (.10, .10, .68))]
    if kind == "laundry_line":
        return [((x - .42, y, z + .75), (.08, .08, 1.50)), ((x + .42, y, z + .75), (.08, .08, 1.50)), ((x, y, z + 1.38), (.92, .06, .06)), ((x - .18, y, z + 1.16), (.28, .05, .40)), ((x + .22, y, z + 1.12), (.30, .05, .46))]
    if kind == "drain_grate":
        return [((x, y, z + .025), (.70, .52, .05))]
    if kind == "great_bell":
        return [((x, y, z + .72), (.82, .82, 1.18)), ((x, y, z + 1.38), (1.02, 1.02, .18))]
    if kind in {"bell_rope", "counterweight"}:
        return [((x, y, z + .82), (.14, .14, 1.64)), ((x, y, z + .14), (.42, .42, .28))]
    if kind == "hearth":
        return [((x, y, z + .48), (.82, .52, .90)), ((x, y, z + 1.05), (.42, .42, .38))]
    if kind == "cargo_cluster":
        return [((x - .18, y, z + .18), (.34, .42, .36)), ((x + .18, y + .13, z + .13), (.28, .3, .26))]
    if kind == "harbor_lantern":
        return [((x, y, z + .52), (.09, .09, 1.04)), ((x, y, z + 1.04), (.24, .24, .22))]
    if kind == "rope_coil":
        return [((x, y, z + .07), (.56, .56, .14))]
    if kind == "fish_basket":
        return [((x, y, z + .13), (.48, .38, .26))]
    if "fungus" in kind:
        return [((x, y, z + .09), (.42, .42, .18))]
    if "pipe" in kind:
        return [((x, y, z + .42), (.92, .18, .18)), ((x - .30, y, z + .42), (.12, .42, .42)), ((x + .32, y, z + .42), (.10, .34, .34))]
    if "bridge" in kind:
        return [((x, y, z + .09), (.92, .70, .16)), ((x, y - .32, z + .31), (.92, .08, .44)), ((x, y + .32, z + .31), (.92, .08, .44))]
    if "beacon" in kind:
        return [((x, y, z + .35), (.72, .72, .20)), ((x, y, z + .92), (.18, .18, 1.0)), ((x, y, z + 1.48), (.58, .58, .34))]
    if "telescope" in kind:
        return [((x, y, z + .52), (.84, .18, .18)), ((x - .26, y, z + .28), (.10, .10, .56)), ((x + .26, y, z + .28), (.10, .10, .56))]
    if any(token in kind for token in ("weapon_rack", "flag_rack", "rack")) and "gear" not in kind:
        return [((x, y, z + .65), (.78, .16, 1.28)), ((x, y - .12, z + .26), (.70, .10, .08)), ((x, y - .12, z + .72), (.70, .10, .08)), ((x, y - .12, z + 1.10), (.70, .10, .08))]
    if any(token in kind for token in ("controls", "control_panel")):
        return [((x, y, z + .45), (.72, .42, .70)), ((x, y - .16, z + .87), (.64, .18, .22)), ((x + .22, y - .28, z + 1.05), (.08, .08, .26))]
    if any(token in kind for token in ("reservoir", "tank")):
        return [((x, y, z + .28), (.64, .64, .56)), ((x, y, z + .64), (.72, .72, .16)), ((x, y, z + .98), (.64, .64, .52))]
    if any(token in kind for token in ("bar_counter", "counter", "bar_top")):
        return [((x, y, z + .43), (.92, .34, .78)), ((x, y, z + .86), (1.0, .42, .10))]
    if any(token in kind for token in ("table", "desk")):
        boxes = [((x, y, z + .56), (.82, .58, .12))]
        boxes.extend([((x + dx, y + dy, z + .27), (.10, .10, .54)) for dx in (-.32, .32) for dy in (-.20, .20)])
        return boxes
    if any(token in kind for token in ("chair", "stool")):
        return [((x, y, z + .30), (.40, .40, .12)), ((x, y + .17, z + .59), (.40, .10, .55)), ((x, y, z + .15), (.09, .09, .30))]
    if "bed" in kind or "bunk" in kind:
        return [((x, y, z + .25), (.88, .56, .42)), ((x - .29, y, z + .49), (.24, .48, .10)), ((x + .40, y, z + .43), (.09, .62, .86))]
    if any(token in kind for token in ("cabinet", "wardrobe", "bookcase", "shelf")):
        return [((x, y, z + .68), (.72, .24, 1.34))] + [
            ((x, y - .14, z + height), (.64, .08, .06)) for height in (.25, .62, .99)
        ]
    if any(token in kind for token in ("barrel", "cask", "keg")):
        return [((x, y, z + .18), (.48, .48, .36)), ((x, y, z + .40), (.56, .56, .12)), ((x, y, z + .62), (.48, .48, .36))]
    if any(token in kind for token in ("machinery", "mechanism", "winch", "gear")):
        return [((x, y, z + .35), (.70, .58, .70)), ((x + .25, y, z + .79), (.12, .12, .46)), ((x - .24, y, z + .73), (.30, .18, .18))]
    if any(token in kind for token in ("crate", "chest", "trunk", "locker", "cache")):
        return [((x - .16, y, z + .20), (.48, .50, .40)), ((x + .23, y + .14, z + .13), (.36, .36, .26))]
    if any(token in kind for token in ("lamp", "lantern", "sconce")):
        return [((x, y, z + .50), (.08, .08, 1.0)), ((x, y, z + 1.02), (.26, .26, .24))]
    if any(token in kind for token in ("bench", "pew")):
        return [((x, y, z + .32), (.92, .34, .16)), ((x, y + .13, z + .60), (.92, .10, .52)), ((x - .35, y, z + .14), (.10, .10, .28)), ((x + .35, y, z + .14), (.10, .10, .28))]
    if any(token in kind for token in ("stove", "forge", "altar")):
        return [((x, y, z + .40), (.74, .60, .72)), ((x, y, z + .82), (.82, .68, .12)), ((x + .25, y, z + 1.24), (.16, .16, .80))]
    if "washstand" in kind:
        return [((x, y, z + .48), (.58, .38, .10)), ((x - .20, y, z + .24), (.09, .09, .48)), ((x + .20, y, z + .24), (.09, .09, .48)), ((x, y, z + .66), (.32, .32, .24))]
    if "debris" in kind or "tracks" in kind:
        return [((x - .20, y, z + .025), (.24, .10, .05)), ((x + .06, y + .12, z + .025), (.18, .08, .05)), ((x + .24, y - .10, z + .025), (.16, .08, .05))]
    return [((x, y, z + .04), (.38, .20, .08))]


def feature_material_name(kind: str) -> str:
    exact = f"feature_{kind}"
    if exact in MATERIALS:
        return exact
    if kind in {"market_stall", "handcart", "notice_board"}:
        return "market_wood"
    if kind in {"canvas_awning", "laundry_line"}:
        return "market_canvas"
    if kind == "puddle":
        return "puddle"
    if kind in {"wheel_rut", "drain_grate"}:
        return "street_wear"
    if kind in {"great_bell", "bell_rope", "counterweight"}:
        return "clock_gold"
    if any(token in kind for token in ("lamp", "lantern", "sconce", "forge")):
        return "feature_lamp"
    if "fungus" in kind:
        return "feature_fungus_patch"
    if "beacon" in kind:
        return "beacon"
    if any(token in kind for token in ("machinery", "mechanism", "winch", "gear", "stove")):
        return "feature_metal"
    if any(token in kind for token in ("pipe", "controls", "telescope", "reservoir")):
        return "feature_metal"
    if any(token in kind for token in ("bed", "bunk")):
        return "feature_fabric"
    return "feature_default"


def oriented_feature_boxes(feature: dict[str, Any], z: float) -> list[Box]:
    boxes = feature_boxes(feature, z)
    x = int(feature["col"]) * CELL + CELL / 2
    y = int(feature["row"]) * CELL + CELL / 2
    dimensions = feature.get("dimensions_ft", [5, 5, 5])
    scale_x = min(2.0, max(.5, float(dimensions[0]) * FT))
    scale_y = min(2.0, max(.5, float(dimensions[1]) * FT))
    scale_z = min(1.8, max(.55, float(dimensions[2]) * FT))
    quarter_turn = round(float(feature.get("rotation_deg", 0)) / 90) % 2 == 1
    transformed: list[Box] = []
    for (cx, cy, cz), (sx, sy, sz) in boxes:
        dx, dy = (cx - x) * scale_x, (cy - y) * scale_y
        out_sx, out_sy = sx * scale_x, sy * scale_y
        if quarter_turn:
            dx, dy = -dy, dx
            out_sx, out_sy = sy * scale_y, sx * scale_x
        transformed.append(((x + dx, y + dy, z + (cz - z) * scale_z), (out_sx, out_sy, sz * scale_z)))
    return transformed


def build_features() -> None:
    batches: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for feature in PLAN["features"]:
        batches[(
            feature["level_id"], feature.get("volume_id", ""), feature.get("room_id", ""),
            feature["kind"], feature.get("visibility", "public"),
        )].append(feature)
    for (level_id, volume_id, room_id, kind, visibility), features in batches.items():
        z = float(LEVELS[level_id]["z_base_ft"]) * FT
        material_name = feature_material_name(kind)
        boxes_mesh(
            f"Features_{level_id}_{volume_id or 'surface'}_{room_id or 'unassigned'}_{kind}_{visibility}",
            (box for feature in features for box in oriented_feature_boxes(feature, z)), MATERIALS[material_name],
            kind="feature", level_id=level_id, material_id=material_name, visibility=visibility, pick_role="feature",
            volume_id=volume_id, room_ids=[room_id] if room_id else [], feature_kind=kind,
            feature_ids=[feature["id"] for feature in features],
            blocks_movement=any(feature.get("blocks_movement") for feature in features), feature_count=len(features),
        )


def build_anchors() -> None:
    batches: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for anchor in PLAN["anchors"]:
        batches[(anchor["level_id"], anchor.get("visibility", "public"))].append(anchor)
    for (level_id, visibility), anchors in batches.items():
        z = float(LEVELS[level_id]["z_base_ft"]) * FT
        boxes = [((a["col"] * CELL + CELL / 2, a["row"] * CELL + CELL / 2, z + .08), (.72, .72, .16)) for a in anchors]
        boxes_mesh(f"Anchors_{level_id}_{visibility}", boxes, MATERIALS["anchor_secret" if visibility == "dm_only" else "anchor"], kind="anchor", level_id=level_id, material_id="anchor", visibility=visibility, pick_role="anchor", anchor_ids=[a["id"] for a in anchors])


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def configure_scene() -> bpy.types.Object:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1400, 1000, 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.look = "AgX - Medium High Contrast"
    # Large tactical maps clip into AgX's desaturated highlight shoulder very
    # quickly. Keep headroom so material hue, not white light, carries zones.
    scene.view_settings.exposure = -.28
    scene.world.use_nodes = True
    background = next(node for node in scene.world.node_tree.nodes if node.type == "BACKGROUND")
    background.inputs["Color"].default_value = (.004, .010, .022, 1)
    background.inputs["Strength"].default_value = .20
    width, height = float(PLAN["grid"]["width"]) * CELL, float(PLAN["grid"]["height"]) * CELL
    target = (width / 2, height / 2, 2.0)
    for name, location, energy, color, size in (
        ("HarborKey", (width * .25, -height * .25, 52), 1150, (1.0, .62, .34), 22),
        ("HarborFill", (width * 1.15, height * .85, 35), 720, (.20, .43, 1.0), 20),
    ):
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.name = name
        light.data.energy, light.data.color, light.data.size = energy, color, size
        look_at(light, target)
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 30))
    sun = bpy.context.object
    sun.name = "HarborSun"
    sun.data.energy = .58
    sun.rotation_euler = (math.radians(30), math.radians(-20), math.radians(-35))
    # Broad, low-energy pools produce harbor haze/depth without volumetrics,
    # which keeps headless Eevee renders deterministic and avoids black frames.
    for index, (x, y, color, energy) in enumerate((
        (width * .82, height * .18, (.06, .40, 1.0), 170),
        (width * .78, height * .52, (.04, .55, .72), 145),
        (width * .72, height * .82, (1.0, .26, .04), 110),
    )):
        bpy.ops.object.light_add(type="POINT", location=(x, y, 4.2))
        haze = bpy.context.object
        haze.name = f"HarborHazeLight_{index}"
        haze.data.energy = energy
        haze.data.color = color
        haze.data.shadow_soft_size = 7.0
    bpy.ops.object.camera_add(location=(width * 1.2, -height * .65, max(width, height) * .78))
    camera = bpy.context.object
    camera.name = "SceneV2Camera"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(width, height) * 1.24
    look_at(camera, target)
    scene.camera = camera
    return camera


def render(camera: bpy.types.Object, filename: str, location: tuple[float, float, float], target: tuple[float, float, float], ortho: float) -> None:
    camera.location = location
    camera.data.ortho_scale = ortho
    look_at(camera, target)
    bpy.context.scene.render.filepath = str(OUT / filename)
    bpy.ops.render.render(write_still=True)


def export_glb() -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in OBJECTS:
        if obj.type in {"MESH", "CURVE", "FONT"}:
            obj.select_set(True)
    properties = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    kwargs: dict[str, Any] = {"filepath": str(OUT / "scene.glb"), "export_format": "GLB"}
    if "use_selection" in properties:
        kwargs["use_selection"] = True
    elif "export_selected" in properties:
        kwargs["export_selected"] = True
    if "export_extras" in properties:
        kwargs["export_extras"] = True
    bpy.ops.export_scene.gltf(**kwargs)
    bpy.ops.object.select_all(action="DESELECT")


def create_materials() -> None:
    material("ground", (.09, .29, .20, 1), roughness=.94, emission=.04)
    material("road", (.10, .115, .15, 1), roughness=.9, emission=.025)
    material("water", (.006, .25, .49, 1), roughness=.2, metallic=.12, emission=.42)
    material("sewage", (.03, .52, .24, 1), roughness=.48, emission=1.15)
    material("interior", (.43, .16, .055, 1), roughness=.8, emission=.025)
    material("secret_floor", (.47, .015, .62, 1), roughness=.48, emission=.5)
    material("grid", (.055, .48, .62, 1), roughness=.42, metallic=.08, emission=.32)
    material("grid_surface", (.12, .42, .48, 1), roughness=.5, emission=.22)
    material("wall", (.42, .34, .30, 1), roughness=.88, emission=.018)
    material("secret_wall", (.58, .025, .72, 1), roughness=.55, emission=.42)
    material("roof", (.61, .105, .025, 1), roughness=.78, emission=.025)
    material("connector", (1.0, .28, .015, 1), roughness=.35, metallic=.12, emission=.62)
    material("connector_vertical", (.015, .66, 1.0, 1), roughness=.3, metallic=.12, emission=2.2)
    material("connector_secret", (1.0, .015, .58, 1), roughness=.26, emission=2.4)
    material("door_frame", (.34, .085, .018, 1), roughness=.82)
    material("stair_wood", (.42, .15, .035, 1), roughness=.78)
    material("hatch_metal", (.18, .29, .34, 1), roughness=.4, metallic=.62, emission=.08)
    material("secret_portal", (.82, .018, .62, 1), roughness=.28, metallic=.12, emission=1.4)
    material("window_glow", (.04, .48, 1.0, 1), roughness=.20, emission=2.2)
    material("tower_stone", (.34, .38, .42, 1), roughness=.86)
    material("beacon", (1.0, .18, .015, 1), roughness=.22, metallic=.15, emission=4.0)
    material("inn_roof", (.56, .075, .018, 1), roughness=.82)
    material("inn_trim", (.42, .16, .035, 1), roughness=.78)
    material("sewer_stone", (.18, .28, .22, 1), roughness=.90)
    material("sewer_bridge", (.38, .16, .035, 1), roughness=.85)
    material("pipe_metal", (.12, .29, .31, 1), roughness=.36, metallic=.68, emission=.05)
    material("dock_wood", (.39, .14, .025, 1), roughness=.90)
    material("wet_wood", (.18, .065, .018, 1), roughness=.94)
    material("dock_metal", (.17, .21, .25, 1), roughness=.43, metallic=.62)
    material("feature_default", (.42, .18, .055, 1), roughness=.78)
    material("feature_cargo_cluster", (.34, .075, .012, 1), roughness=.84)
    material("feature_rope_coil", (.56, .19, .035, 1), roughness=.9)
    material("feature_harbor_lantern", (1.0, .20, .008, 1), roughness=.22, emission=3.0)
    material("feature_fish_basket", (.44, .14, .035, 1), roughness=.82)
    material("feature_fungus_patch", (.015, .84, .38, 1), roughness=.34, emission=2.0)
    material("feature_rat_sign", (.16, .085, .035, 1), roughness=.94)
    material("feature_lamp", (1.0, .20, .008, 1), roughness=.22, emission=3.0)
    material("feature_metal", (.18, .25, .29, 1), roughness=.42, metallic=.58)
    material("feature_fabric", (.26, .055, .08, 1), roughness=.94)
    material("anchor", (.015, 1.0, .52, 1), roughness=.25, emission=2.1)
    material("anchor_secret", (1.0, .015, .55, 1), roughness=.25, emission=2.2)
    material("clock_gold", (.62, .31, .035, 1), roughness=.34, metallic=.72, emission=.10)
    material("clock_face", (.08, .36, .42, 1), roughness=.30, metallic=.46, emission=.52)
    material("roof_rail", (.22, .12, .055, 1), roughness=.84)
    material("curb_stone", (.31, .30, .32, 1), roughness=.94)
    material("market_wood", (.39, .16, .045, 1), roughness=.88)
    material("market_canvas", (.46, .08, .12, 1), roughness=.92)
    material("puddle", (.015, .18, .30, 1), roughness=.18, metallic=.12, emission=.18)
    material("street_wear", (.055, .065, .075, 1), roughness=.96)


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clean_scene()
    create_materials()
    camera = configure_scene()
    build_terrain()
    build_level_floors_and_grids()
    build_walls()
    build_roofs()
    build_connectors()
    build_archetype_details()
    build_sewer_details()
    build_harbor_details()
    build_clock_district_details()
    build_features()
    build_anchors()
    width, height = float(PLAN["grid"]["width"]) * CELL, float(PLAN["grid"]["height"]) * CELL
    target = (width / 2, height / 2, 2.0)
    render(camera, "scene-isometric.png", (width * 1.2, -height * .65, max(width, height) * .78), target, max(width, height) * 1.24)
    render(camera, "scene-topdown.png", (width / 2, height / 2, max(width, height) * 1.55), (width / 2, height / 2, 0), max(width, height) * 1.07)
    camera.location = (width * 1.2, -height * .65, max(width, height) * .78)
    camera.data.ortho_scale = max(width, height) * 1.24
    look_at(camera, target)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "scene-prototype.blend"))
    export_glb()
    manifest = {
        "status": "generated", "schema_version": "dnd-scene-render-manifest-2.0", "scene_id": PLAN["scene"]["id"],
        "generator_version": PLAN.get("generator_version", ""), "plan_sha256": sha256(PLAN_PATH), "runtime_sha256": sha256(RUNTIME_PATH),
        "blender_version": bpy.app.version_string, "grid": PLAN["grid"], "levels": len(PLAN["levels"]), "rooms": len(PLAN["rooms"]),
        "connectors": len(PLAN["connectors"]), "features": len(PLAN["features"]), "prototype_objects": len(OBJECTS),
        "estimated_draw_calls": len(OBJECTS), "visual_layer_version": "2.3" if PLAN["scene"].get("id") == "old_clock_quarter_v23" else "2.1",
        "batched_boxes": STATS["batched_boxes"], "mesh_vertices": STATS["mesh_vertices"],
        "object_kinds": {key[5:]: value for key, value in sorted(STATS.items()) if key.startswith("kind_")},
        "outputs": ["scene.glb", "scene-prototype.blend", "scene-isometric.png", "scene-topdown.png"],
    }
    (OUT / "scene-render-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
