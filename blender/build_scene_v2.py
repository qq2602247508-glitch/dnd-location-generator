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


# The V2 plan already carries a capability-facing volume vocabulary: kind,
# archetype, roof and facade.  Keep visual grammar here rather than assigning
# details by scene id so any compatible plan gets a coherent, distinct block.
DEFAULT_VISUAL_STYLE: dict[str, Any] = {
    "roof_profile": "gable_ns",
    "roof_material": "roof",
    "wall_material": "wall",
    "trim_material": "trim_building",
    "detail_group": "building",
    "window_stride": 5,
}
KIND_VISUAL_STYLES: dict[str, dict[str, Any]] = {
    "tower": {"roof_profile": "parapet", "roof_material": "roof_tower", "wall_material": "facade_tower", "trim_material": "trim_tower", "detail_group": "tower", "window_stride": 3},
    "building": {"roof_profile": "gable_ns", "roof_material": "roof", "wall_material": "wall", "trim_material": "trim_building", "detail_group": "building", "window_stride": 5},
}
ARCHETYPE_VISUAL_STYLES: dict[str, dict[str, Any]] = {
    "clock_tower": {"roof_profile": "copper_cap", "roof_material": "roof_copper", "wall_material": "facade_tower", "trim_material": "trim_tower", "detail_group": "clock_tower", "window_stride": 2},
    "signal_tower": {"roof_profile": "parapet", "roof_material": "roof_tower", "wall_material": "facade_tower", "trim_material": "trim_tower", "detail_group": "signal_tower", "window_stride": 3},
    "inn": {"roof_profile": "gable_ns", "roof_material": "inn_roof", "wall_material": "facade_inn", "trim_material": "trim_inn", "detail_group": "harbor_inn", "window_stride": 3},
    "guildhall": {"roof_profile": "stepped_gable", "roof_material": "roof_guild", "wall_material": "facade_guild", "trim_material": "trim_guild", "detail_group": "guildhall", "window_stride": 3},
    "shrine": {"roof_profile": "hipped", "roof_material": "roof_shrine", "wall_material": "facade_shrine", "trim_material": "trim_shrine", "detail_group": "shrine", "window_stride": 2},
    "shop": {"roof_profile": "shed_ew", "roof_material": "roof_shop", "wall_material": "facade_shop", "trim_material": "trim_shop", "detail_group": "shop", "window_stride": 4},
    "tenement": {"roof_profile": "lean_to", "roof_material": "roof_tenement", "wall_material": "facade_tenement", "trim_material": "trim_tenement", "detail_group": "tenement", "window_stride": 4},
    "watchhouse": {"roof_profile": "parapet", "roof_material": "roof_watchhouse", "wall_material": "facade_watchhouse", "trim_material": "trim_watchhouse", "detail_group": "watchhouse", "window_stride": 3},
    "warehouse": {"roof_profile": "gable_ew", "roof_material": "roof", "wall_material": "wall", "trim_material": "trim_building", "detail_group": "warehouse", "window_stride": 5},
    "manor": {"roof_profile": "hipped", "roof_material": "roof_guild", "wall_material": "facade_guild", "trim_material": "trim_guild", "detail_group": "manor", "window_stride": 4},
    "market": {"roof_profile": "shed_ns", "roof_material": "roof_shop", "wall_material": "facade_shop", "trim_material": "trim_shop", "detail_group": "market", "window_stride": 5},
}
PRESENTATION_ROOF_PROFILES = {
    "copper_belfry": "copper_cap",
    "crooked_gable": "gable_ns",
    "walkable_roofline": "parapet",
    "pitched": "gable_ns",
    "barrel_vault": "hipped",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cells_from_rle(mask: dict[str, Any]) -> set[tuple[int, int]]:
    if mask.get("encoding") != "rle-v1":
        raise ValueError(f"unsupported mask encoding: {mask.get('encoding')}")
    result: set[tuple[int, int]] = set()
    for row, start_col, length in mask.get("runs", []):
        result.update((int(row), col) for col in range(int(start_col), int(start_col) + int(length)))
    return result


def volume_visual_style(volume: dict[str, Any]) -> dict[str, Any]:
    """Resolve a reusable visual grammar from plan capabilities/presentation."""
    style = dict(DEFAULT_VISUAL_STYLE)
    style.update(KIND_VISUAL_STYLES.get(str(volume.get("kind", "")), {}))
    archetype = str(volume.get("archetype", ""))
    archetype_style = ARCHETYPE_VISUAL_STYLES.get(archetype)
    if archetype_style:
        style.update(archetype_style)
    else:
        roof = volume.get("roof", {})
        roof_shape = str(roof.get("shape", "")) if isinstance(roof, dict) else ""
        if roof_shape in PRESENTATION_ROOF_PROFILES:
            style["roof_profile"] = PRESENTATION_ROOF_PROFILES[roof_shape]
    style["archetype"] = archetype or str(volume.get("kind", "building"))
    style["presentation_roof"] = (
        str(volume.get("roof", {}).get("shape", ""))
        if isinstance(volume.get("roof"), dict) else ""
    )
    style["presentation_facade"] = (
        str(volume.get("facade", {}).get("primary", ""))
        if isinstance(volume.get("facade"), dict) else ""
    )
    return style


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


def weathered_ground_material(value: bpy.types.Material) -> None:
    """Give city ground a procedural, texture-free cobble/weathering breakup."""
    nodes = value.node_tree.nodes
    links = value.node_tree.links
    bsdf = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
    if not bsdf:
        return
    base_color = next((socket for socket in bsdf.inputs if socket.identifier == "Base Color"), None)
    if not base_color:
        return
    noise = nodes.new("ShaderNodeTexNoise")
    noise.noise_dimensions = "3D"
    noise.inputs["Scale"].default_value = 7.5
    noise.inputs["Detail"].default_value = 3.0
    noise.inputs["Roughness"].default_value = .72
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = .30
    ramp.color_ramp.elements[0].color = (.045, .060, .068, 1)
    ramp.color_ramp.elements[1].position = .72
    ramp.color_ramp.elements[1].color = (.26, .30, .31, 1)
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], base_color)


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


def cell_run_boxes(cells: set[tuple[int, int]], z: float, *, height: float = .12, inset: float = .018) -> list[Box]:
    """Collapse same-row tactical cells into floor slabs; grid overlays stay exact."""
    by_row: dict[int, list[int]] = defaultdict(list)
    for row, col in cells:
        by_row[row].append(col)
    boxes: list[Box] = []
    for row, cols in sorted(by_row.items()):
        ordered = sorted(cols)
        start = previous = ordered[0]
        for col in ordered[1:]:
            if col != previous + 1:
                span = previous - start + 1
                boxes.append(((start * CELL + span * CELL / 2, row * CELL + CELL / 2, z - height / 2), (span * CELL - inset, CELL - inset, height)))
                start = col
            previous = col
        span = previous - start + 1
        boxes.append(((start * CELL + span * CELL / 2, row * CELL + CELL / 2, z - height / 2), (span * CELL - inset, CELL - inset, height)))
    return boxes


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


def grid_strip_boxes(cells: set[tuple[int, int]], z: float, *, thickness: float = .022) -> list[Box]:
    """Merge per-cell grid marks into continuous strips.

    The tactical contract still exposes every five-foot cell through the floor
    mesh/runtime.  This only compresses the visual overlay, avoiding two tiny
    cuboids (and their vertices) for every cell in a large map.
    """
    horizontal: dict[int, list[int]] = defaultdict(list)
    vertical: dict[int, list[int]] = defaultdict(list)
    for row, col in cells:
        horizontal[row].append(col)
        vertical[col].append(row)

    def runs(values: list[int]) -> Iterable[tuple[int, int]]:
        ordered = sorted(set(values))
        if not ordered:
            return
        start = previous = ordered[0]
        for value in ordered[1:]:
            if value != previous + 1:
                yield start, previous + 1
                start = value
            previous = value
        yield start, previous + 1

    boxes: list[Box] = []
    for row, cols in sorted(horizontal.items()):
        for start, end in runs(cols):
            boxes.append((
                (((start + end) * CELL / 2), row * CELL + .012, z),
                ((end - start) * CELL - .025, thickness, .014),
            ))
    for col, rows in sorted(vertical.items()):
        for start, end in runs(rows):
            boxes.append((
                (col * CELL + .012, ((start + end) * CELL / 2), z),
                (thickness, (end - start) * CELL - .025, .014),
            ))
    return boxes


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
            f"Surface_{level_id}_{kind}", cell_run_boxes(cells, z + z_offset, height=height),
            MATERIALS[terrain_material.get(kind, "ground")],
            kind="surface", level_id=level_id, material_id=kind, visibility="public",
            pick_role="tactical_floor" if terrain.get("walkable") else "blocked_surface",
            surface_kind=kind, walkable=bool(terrain.get("walkable")), area_id=terrain["id"], cell_count=len(cells),
        )
        grid_boxes = grid_strip_boxes(cells, z + z_offset + .012)
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
    grid_cells_by_level: dict[tuple[str, str], set[tuple[int, int]]] = defaultdict(set)
    for (level_id, surface, visibility), cells in sorted(runtime_groups().items()):
        z = float(LEVELS[level_id]["z_base_ft"]) * FT
        material_name = "sewage" if surface == "sewage" else ("secret_floor" if visibility == "dm_only" else "interior")
        room_ids = sorted({cell.get("room_id", "") for cell in cells if cell.get("room_id")})
        volume_ids = sorted({cell.get("volume_id", "") for cell in cells if cell.get("volume_id")})
        boxes_mesh(
            f"Floor_{level_id}_{surface}_{visibility}",
            cell_run_boxes({(int(cell["row"]), int(cell["col"])) for cell in cells}, z), MATERIALS[material_name],
            kind="floor", level_id=level_id, material_id=material_name, visibility=visibility, pick_role="tactical_floor",
            room_ids=room_ids, volume_ids=volume_ids, surface_kind=surface, cell_count=len(cells),
        )
        grid_cells_by_level[(level_id, visibility)].update(
            (int(cell["row"]), int(cell["col"])) for cell in cells
        )
    for (level_id, visibility), grid_cells in grid_cells_by_level.items():
        z = float(LEVELS[level_id]["z_base_ft"]) * FT
        boxes = grid_strip_boxes(grid_cells, z + .018, thickness=.024)
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
        style = volume_visual_style(volume)
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
            wall_material = "secret_wall" if visibility == "dm_only" else style["wall_material"]
            boxes_mesh(
                f"Walls_{level_id}_{visibility}", (edge_box(edge, z, height) for edge in sorted(edges)), MATERIALS[wall_material],
                kind="wall", level_id=level_id, material_id=wall_material, visibility=visibility, pick_role="occluder",
                volume_ids=volume_ids, room_ids=room_ids, edge_count=len(edges), archetype=style["archetype"],
            )


def roof_profile_boxes(cells: set[tuple[int, int]], z: float, profile: str) -> list[Box]:
    """Create a single low-poly roof mesh whose silhouette follows its mask."""
    min_row, min_col, max_row, max_col = mask_bounds(cells)
    boxes: list[Box] = []
    for row, col in sorted(cells):
        row_distance = min(row - min_row, max_row - 1 - row)
        col_distance = min(col - min_col, max_col - 1 - col)
        if profile == "gable_ew":
            rise = col_distance * .17
        elif profile == "stepped_gable":
            rise = min(row_distance, col_distance) * .13 + (abs(row - col) % 2) * .025
        elif profile == "hipped":
            rise = min(row_distance, col_distance) * .14
        elif profile == "shed_ew":
            rise = (col - min_col) * .065
        elif profile == "shed_ns":
            rise = (row - min_row) * .065
        elif profile == "lean_to":
            rise = (max_col - 1 - col) * .052 + row_distance * .025
        elif profile == "parapet":
            exterior = any(neighbor not in cells for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)))
            rise = .22 if exterior else .02
        elif profile == "copper_cap":
            rise = min(row_distance, col_distance) * .11 + .05
        else:
            rise = row_distance * .17
        height = .16 + rise
        boxes.append(((col * CELL + CELL / 2, row * CELL + CELL / 2, z + rise / 2), (CELL - .04, CELL - .04, height)))
    return boxes


def build_roofs() -> None:
    for volume in PLAN["volumes"]:
        if volume.get("kind") in {"sewer", "roof_route"} or not volume.get("level_ids") or str(volume.get("roof", {}).get("shape", "")) == "none":
            continue
        level_id = volume["level_ids"][-1]
        level = LEVELS[level_id]
        cells = cells_from_rle(level["cell_mask"])
        z = (float(level["z_base_ft"]) + float(level["height_ft"]) * .82) * FT
        style = volume_visual_style(volume)
        boxes_mesh(
            f"Roof_{volume['id']}_{level_id}", roof_profile_boxes(cells, z, style["roof_profile"]), MATERIALS[style["roof_material"]],
            kind="roof", level_id=level_id, material_id=style["roof_material"], visibility="public", pick_role="hideable",
            volume_id=volume["id"], archetype=style["archetype"], cell_count=len(cells), roof_profile=style["roof_profile"],
            presentation_roof=style["presentation_roof"], detail_group=style["detail_group"],
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
    connector_type = str(connector.get("type", ""))
    boxes: list[Box] = []
    for endpoint, z in points:
        x = int(endpoint["col"]) * CELL + CELL / 2
        y = int(endpoint["row"]) * CELL + CELL / 2
        if connector_type == "stairs":
            # Four unequal treads form an arrow-like ramp in plan view. The
            # high endpoint reverses the taper, so paired up/down landings can
            # be distinguished without labels or scene-specific metadata.
            lengths = (.34, .52, .70, .88)
            if z > min(z_left, z_right):
                lengths = tuple(reversed(lengths))
            for index, length in enumerate(lengths):
                boxes.append(((x, y - .30 + index * .20, z + .17 + index * .012), (length, .12, .20)))
        elif connector_type == "ladder":
            boxes.extend([
                ((x - .34, y, z + .18), (.10, .88, .22)),
                ((x + .34, y, z + .18), (.10, .88, .22)),
                *[((x, y - .30 + index * .20, z + .19), (.72, .09, .24)) for index in range(4)],
            ])
        elif connector_type in {"hatch", "secret_door"}:
            boxes.extend([
                ((x - .38, y, z + .18), (.10, .86, .24)),
                ((x + .38, y, z + .18), (.10, .86, .24)),
                ((x, y - .38, z + .18), (.66, .10, .24)),
                ((x, y + .38, z + .18), (.66, .10, .24)),
            ])
        else:
            boxes.append(((x, y, z + .16), (.92, .92, .26)))
    return boxes


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
    # Vertical transitions share a luminous cyan language; doors remain warm
    # and secrets magenta. This is type-based, never scene-ID based, and lets
    # a DM parse level changes from either tactical camera without a legend.
    visual_materials = {"door": "door_frame", "stairs": "connector_vertical", "ladder": "connector_vertical", "bridge": "stair_wood", "hatch": "connector_vertical", "secret_door": "secret_portal"}
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


def facade_window_boxes(cells: set[tuple[int, int]], z: float, wall_height: float, stride: int) -> list[Box]:
    """Place low-poly windows on actual exterior edges, including L-shapes."""
    boxes: list[Box] = []
    for index, edge in enumerate(sorted(boundary_edges(cells))):
        if index % max(2, stride):
            continue
        (row, col), (other_row, other_col) = edge
        window_z = z + wall_height * .56
        if row == other_row:
            x, y = max(col, other_col) * CELL, row * CELL + CELL / 2
            boxes.append(((x, y, window_z), (.06, .46, .46)))
        else:
            x, y = col * CELL + CELL / 2, max(row, other_row) * CELL
            boxes.append(((x, y, window_z), (.46, .06, .46)))
    return boxes


def facade_band_and_eave_boxes(cells: set[tuple[int, int]], z: float, wall_height: float, *, top_level: bool) -> list[Box]:
    boxes: list[Box] = []
    for index, edge in enumerate(sorted(boundary_edges(cells))):
        if index % 2 == 0:
            boxes.append(edge_box(edge, z + wall_height * .48, .09, .055))
        if top_level:
            boxes.append(edge_box(edge, z + wall_height - .10, .14, .075))
    return boxes


def build_archetype_details() -> None:
    window_boxes: list[Box] = []
    window_volume_ids: list[str] = []
    window_level_ids: list[str] = []
    window_archetypes: list[str] = []
    for volume in PLAN["volumes"]:
        if volume.get("kind") in {"sewer", "roof_route"} or not volume.get("level_ids"):
            continue
        style = volume_visual_style(volume)
        grammar_boxes: list[Box] = []
        top_level_id = volume["level_ids"][-1]
        top_level = LEVELS[top_level_id]
        top_cells = cells_from_rle(top_level["cell_mask"])
        min_row, min_col, max_row, max_col = mask_bounds(top_cells)
        roof_z = (float(top_level["z_base_ft"]) + float(top_level["height_ft"]) * .82) * FT
        for level_id in volume["level_ids"]:
            level = LEVELS[level_id]
            cells = cells_from_rle(level["cell_mask"])
            z = float(level["z_base_ft"]) * FT
            wall_height = max(1.35, float(level["height_ft"]) * FT * .78)
            grammar_boxes.extend(facade_band_and_eave_boxes(cells, z, wall_height, top_level=level_id == top_level_id))
            window_boxes.extend(facade_window_boxes(cells, z, wall_height, int(style["window_stride"])))
            window_volume_ids.append(volume["id"])
            window_level_ids.append(level_id)
            window_archetypes.append(style["archetype"])
        if style["archetype"] in {"signal_tower", "clock_tower", "tower"}:
            perimeter = sorted({edge[0] for edge in boundary_edges(top_cells)})
            grammar_boxes.extend(
                ((col * CELL + CELL / 2, row * CELL + CELL / 2, roof_z + .24), (.38, .38, .48))
                for index, (row, col) in enumerate(perimeter) if index % 2 == 0
            )
        detail_role = "stepped_gable" if style["archetype"] == "inn" else "facade_grammar"
        boxes_mesh(
            f"FacadeGrammar_{volume['id']}", grammar_boxes, MATERIALS[style["trim_material"]],
            kind="archetype_detail", level_id=top_level_id, material_id=style["trim_material"], visibility="public", pick_role="none",
            detail_group=style["detail_group"], detail_role=detail_role, volume_id=volume["id"], level_ids=volume["level_ids"],
            grammar_roles=["windows", "eaves", "facade_band"], roof_profile=style["roof_profile"],
            presentation_facade=style["presentation_facade"],
        )
        cx, cy = (min_col + max_col) * CELL / 2, (min_row + max_row) * CELL / 2
        if style["archetype"] == "clock_tower":
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
        elif style["archetype"] == "signal_tower":
            boxes_mesh(
                f"TowerBeacon_{volume['id']}", [
                    ((cx, cy, roof_z + .20), (1.25, 1.25, .24)),
                    ((cx, cy, roof_z + .88), (.22, .22, 1.25)),
                    ((cx, cy, roof_z + 1.58), (.70, .70, .34)),
                ], MATERIALS["beacon"],
                kind="archetype_detail", level_id=top_level_id, material_id="beacon", visibility="public", pick_role="none",
                detail_group="signal_tower", detail_role="beacon", volume_id=volume["id"],
            )
    boxes_mesh(
        "FacadeWindows", window_boxes, MATERIALS["window_glow"],
        kind="archetype_detail", level_id="", material_id="window_glow", visibility="public", pick_role="none",
        detail_group="building_grammar", detail_role="windows", volume_ids=sorted(set(window_volume_ids)),
        level_ids=sorted(set(window_level_ids)), archetypes=sorted(set(window_archetypes)),
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
    # Variants alter only dressing presentation, never its tactical cell or
    # collision truth. A stable variant hash gives reusable size/offset
    # families without consuming another RNG stream or increasing draw calls.
    variant = str(feature.get("variant", "weathered"))
    variant_digest = hashlib.sha256(variant.encode("utf-8")).digest()
    scale_x *= .90 + variant_digest[0] / 255 * .20
    scale_y *= .90 + variant_digest[1] / 255 * .20
    scale_z *= .88 + variant_digest[2] / 255 * .24
    if any(token in variant for token in ("loaded", "stacked", "leaf_choked")):
        scale_z *= 1.14
    if any(token in variant for token in ("worn", "faded", "swept_aside", "picked_over")):
        scale_z *= .88
    jitter_x = (variant_digest[3] / 255 - .5) * .12
    jitter_y = (variant_digest[4] / 255 - .5) * .12
    quarter_turn = round(float(feature.get("rotation_deg", 0)) / 90) % 2 == 1
    transformed: list[Box] = []
    for (cx, cy, cz), (sx, sy, sz) in boxes:
        dx, dy = (cx - x) * scale_x, (cy - y) * scale_y
        out_sx, out_sy = sx * scale_x, sy * scale_y
        if quarter_turn:
            dx, dy = -dy, dx
            out_sx, out_sy = sy * scale_y, sx * scale_x
        transformed.append(((x + jitter_x + dx, y + jitter_y + dy, z + (cz - z) * scale_z), (out_sx, out_sy, sz * scale_z)))
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


def content_camera_frame() -> dict[str, Any]:
    """Frame authored content, not the full allocation rectangle, with padding."""
    cells: set[tuple[int, int]] = set()
    for volume in PLAN["volumes"]:
        for level_id in volume.get("level_ids", []):
            cells.update(cells_from_rle(LEVELS[level_id]["cell_mask"]))
    for terrain in PLAN["terrain"]:
        if terrain.get("kind") != "ground":
            cells.update(cells_from_rle(terrain["cell_mask"]))
    cells.update((int(item["row"]), int(item["col"])) for item in PLAN["features"])
    cells.update((int(item["row"]), int(item["col"])) for item in PLAN["anchors"])
    if not cells:
        cells = {
            (row, col)
            for row in range(int(PLAN["grid"]["height"]))
            for col in range(int(PLAN["grid"]["width"]))
        }
    min_row, min_col, max_row, max_col = mask_bounds(cells)
    # Once the visual grammar exists, include its real XY bounds. Roofs,
    # eaves, stairs and landmarks may legitimately extend beyond semantic
    # masks; certification captures must never crop those additions. Terrain
    # and grid objects are excluded because they span the allocation canvas.
    framed_objects = [
        obj for obj in OBJECTS
        if str(obj.get("prototype_kind", "")) not in {"surface", "grid"}
    ]
    if framed_objects:
        corners = [obj.matrix_world @ Vector(corner) for obj in framed_objects for corner in obj.bound_box]
        min_col = min(min_col, math.floor(min(point.x for point in corners) / CELL))
        max_col = max(max_col, math.ceil(max(point.x for point in corners) / CELL))
        min_row = min(min_row, math.floor(min(point.y for point in corners) / CELL))
        max_row = max(max_row, math.ceil(max(point.y for point in corners) / CELL))
    span_rows, span_cols = max_row - min_row, max_col - min_col
    padding = max(2.0, min(5.0, max(span_rows, span_cols) * .08))
    framed_rows, framed_cols = span_rows + padding * 2, span_cols + padding * 2
    frame_span = max(framed_rows, framed_cols) * CELL
    target_x = (min_col + max_col) * CELL / 2
    target_y = (min_row + max_row) * CELL / 2
    top_z = max(
        (float(level["z_base_ft"]) + float(level.get("height_ft", 0))) * FT
        for level in PLAN["levels"]
    )
    target = (target_x, target_y, max(1.25, top_z * .28))
    return {
        "target": target,
        "iso_location": (target_x + frame_span * .72, target_y - frame_span * 1.05, top_z + frame_span * .78),
        "top_location": (target_x, target_y, top_z + frame_span * 1.48),
        "iso_ortho": frame_span * 1.10,
        # The certification top-down is an atlas view, not a beauty crop.
        # Extra margin also contains roof/eave grammar that can extend beyond
        # semantic cell masks, so unseen archetypes cannot be clipped.
        "top_ortho": frame_span * 1.35,
        "content_bounds_cells": [min_row, min_col, max_row, max_col],
        "content_padding_cells": padding,
    }


def configure_scene() -> bpy.types.Object:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1400, 1000, 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.look = "AgX - Medium Low Contrast"
    # Large tactical maps clip into AgX's desaturated highlight shoulder very
    # quickly. Keep headroom so material hue, not white light, carries zones.
    scene.view_settings.exposure = .72
    scene.world.use_nodes = True
    background = next(node for node in scene.world.node_tree.nodes if node.type == "BACKGROUND")
    background.inputs["Color"].default_value = (.004, .010, .022, 1)
    background.inputs["Strength"].default_value = .48
    width, height = float(PLAN["grid"]["width"]) * CELL, float(PLAN["grid"]["height"]) * CELL
    frame = content_camera_frame()
    target = frame["target"]
    for name, location, energy, color, size in (
        ("HarborKey", (width * .25, -height * .25, 52), 1350, (1.0, .68, .42), 24),
        ("HarborFill", (width * 1.15, height * .85, 35), 1050, (.30, .52, 1.0), 24),
    ):
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.name = name
        light.data.energy, light.data.color, light.data.size = energy, color, size
        look_at(light, target)
    bpy.ops.object.light_add(type="AREA", location=(target[0], target[1], 70))
    tactical_fill = bpy.context.object
    tactical_fill.name = "TacticalAmbientFill"
    tactical_fill.data.energy = 1500
    tactical_fill.data.color = (.42, .54, .72)
    tactical_fill.data.size = 120
    tactical_fill.data.use_shadow = False
    look_at(tactical_fill, target)
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 30))
    sun = bpy.context.object
    sun.name = "HarborSun"
    sun.data.energy = .90
    sun.data.angle = math.radians(22)
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
    bpy.ops.object.camera_add(location=frame["iso_location"])
    camera = bpy.context.object
    camera.name = "SceneV2Camera"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = frame["iso_ortho"]
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
    material("ground", (.16, .20, .22, 1), roughness=.98, emission=.012)
    weathered_ground_material(MATERIALS["ground"])
    material("road", (.17, .23, .31, 1), roughness=.9, emission=.09)
    material("water", (.006, .25, .49, 1), roughness=.2, metallic=.12, emission=.42)
    material("sewage", (.03, .52, .24, 1), roughness=.48, emission=1.15)
    material("interior", (.43, .16, .055, 1), roughness=.8, emission=.025)
    material("secret_floor", (.47, .015, .62, 1), roughness=.48, emission=.5)
    material("grid", (.035, .27, .34, 1), roughness=.48, metallic=.06, emission=.14)
    material("grid_surface", (.075, .25, .30, 1), roughness=.56, emission=.10)
    material("wall", (.42, .34, .30, 1), roughness=.88, emission=.018)
    material("secret_wall", (.58, .025, .72, 1), roughness=.55, emission=.42)
    material("roof", (.61, .105, .025, 1), roughness=.78, emission=.025)
    material("trim_building", (.55, .37, .22, 1), roughness=.86)
    material("facade_tower", (.23, .30, .34, 1), roughness=.90)
    material("trim_tower", (.50, .60, .63, 1), roughness=.66, metallic=.16)
    material("roof_tower", (.20, .29, .34, 1), roughness=.66, metallic=.32)
    material("roof_copper", (.08, .36, .35, 1), roughness=.46, metallic=.56)
    material("facade_inn", (.32, .15, .075, 1), roughness=.92)
    material("trim_inn", (.68, .28, .09, 1), roughness=.78)
    material("facade_guild", (.37, .30, .22, 1), roughness=.90)
    material("trim_guild", (.62, .50, .30, 1), roughness=.72)
    material("roof_guild", (.34, .17, .08, 1), roughness=.82)
    material("facade_shrine", (.19, .32, .31, 1), roughness=.78, metallic=.12)
    material("trim_shrine", (.70, .50, .16, 1), roughness=.50, metallic=.38)
    material("roof_shrine", (.18, .44, .39, 1), roughness=.48, metallic=.42)
    material("facade_shop", (.39, .20, .08, 1), roughness=.92)
    material("trim_shop", (.76, .40, .12, 1), roughness=.74)
    material("roof_shop", (.46, .11, .045, 1), roughness=.84)
    material("facade_tenement", (.25, .23, .27, 1), roughness=.94)
    material("trim_tenement", (.46, .38, .34, 1), roughness=.86)
    material("roof_tenement", (.16, .18, .24, 1), roughness=.88)
    material("facade_watchhouse", (.18, .28, .36, 1), roughness=.86)
    material("trim_watchhouse", (.54, .65, .64, 1), roughness=.65, metallic=.14)
    material("roof_watchhouse", (.16, .27, .33, 1), roughness=.68, metallic=.24)
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
    frame = content_camera_frame()
    render(camera, "scene-isometric.png", frame["iso_location"], frame["target"], frame["iso_ortho"])
    render(camera, "scene-topdown.png", frame["top_location"], (frame["target"][0], frame["target"][1], 0), frame["top_ortho"])
    camera.location = frame["iso_location"]
    camera.data.ortho_scale = frame["iso_ortho"]
    look_at(camera, frame["target"])
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
        "camera": {"content_bounds_cells": frame["content_bounds_cells"], "content_padding_cells": frame["content_padding_cells"], "iso_ortho": frame["iso_ortho"], "top_ortho": frame["top_ortho"]},
        "object_kinds": {key[5:]: value for key, value in sorted(STATS.items()) if key.startswith("kind_")},
        "outputs": ["scene.glb", "scene-prototype.blend", "scene-isometric.png", "scene-topdown.png"],
    }
    (OUT / "scene-render-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
