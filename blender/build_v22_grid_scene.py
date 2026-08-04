from __future__ import annotations

"""Build a readable Blender tactical scene from the V2.2 grid contract.

The spatial contract stays renderer-neutral.  This file owns visual language:
shared grid/metadata/export behavior plus archetype-specific landmarks and
environmental storytelling for wilderness, infrastructure and special sites.
"""

import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
ARGS = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def argument(name: str, default: str) -> str:
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


OUT = Path(argument("--input-dir", str(ROOT / "output" / "v22-scenes" / "river_valley"))).expanduser().resolve()
GRID_PATH = OUT / "scene.grid.json"
GRID = json.loads(GRID_PATH.read_text(encoding="utf-8"))
ARCHETYPE = str(GRID["scene"]["archetype"])
SEED = int(GRID["scene"]["seed"])
RNG = random.Random(SEED)
CELL = float(GRID["scene"]["grid"]["cell_size_ft"]) / 5.0
FT = 1.0 / 5.0
WIDTH = int(GRID["scene"]["grid"]["width"])
HEIGHT = int(GRID["scene"]["grid"]["height"])
CELLS = {str(cell["id"]): cell for cell in GRID["cells"]}
AT = {(str(cell["level_id"]), int(cell["row"]), int(cell["col"])): cell for cell in GRID["cells"]}
DEFAULT_LEVEL_ID = str(GRID.get("levels", [{}])[0].get("id", "surface"))
OBJECTS: list[bpy.types.Object] = []
MATERIALS: dict[str, bpy.types.Material] = {}
STATS: defaultdict[str, int] = defaultdict(int)

Box = tuple[tuple[float, float, float], tuple[float, float, float]]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"path": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}


def clean_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in list(bpy.data.materials):
        bpy.data.materials.remove(block)


def material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    roughness: float = 0.75,
    metallic: float = 0.0,
    emission: float = 0.0,
    alpha: float = 1.0,
) -> bpy.types.Material:
    value = bpy.data.materials.new(name)
    value.diffuse_color = (*color[:3], alpha)
    value.use_nodes = True
    bsdf = next((node for node in value.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        sockets = {socket.identifier: socket for socket in bsdf.inputs}
        sockets["Base Color"].default_value = (*color[:3], alpha)
        sockets["Roughness"].default_value = roughness
        sockets["Metallic"].default_value = metallic
        if "Alpha" in sockets:
            sockets["Alpha"].default_value = alpha
        if emission and "Emission Color" in sockets:
            sockets["Emission Color"].default_value = (*color[:3], 1)
            sockets["Emission Strength"].default_value = emission
    if alpha < 1:
        value.surface_render_method = "DITHERED"
    MATERIALS[name] = value
    return value


def tag(
    obj: bpy.types.Object,
    *,
    kind: str,
    material_id: str,
    visibility: str = "public",
    pick_role: str = "none",
    **extras: Any,
) -> bpy.types.Object:
    obj["prototype"] = True
    obj["schema_version"] = GRID["schema_version"]
    obj["scene_id"] = GRID["scene"]["id"]
    obj["level_id"] = str(extras.pop("level_id", DEFAULT_LEVEL_ID))
    obj["prototype_kind"] = kind
    obj["material_id"] = material_id
    obj["prototype_visibility"] = visibility
    obj["pick_role"] = pick_role
    obj["scene_archetype"] = ARCHETYPE
    for key, value in extras.items():
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            value = json.dumps(list(value) if isinstance(value, set) else value, ensure_ascii=False, separators=(",", ":"))
        obj[key] = value
    OBJECTS.append(obj)
    STATS[f"kind_{kind}"] += 1
    return obj


def append_box(vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int, int]], box: Box) -> None:
    (cx, cy, cz), (sx, sy, sz) = box
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


def boxes_mesh(name: str, boxes: Iterable[Box], material_name: str, **metadata: Any) -> bpy.types.Object | None:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    count = 0
    for box in boxes:
        append_box(vertices, faces, box)
        count += 1
    if not count:
        return None
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(MATERIALS[material_name])
    STATS["batched_boxes"] += count
    STATS["mesh_vertices"] += len(vertices)
    return tag(obj, material_id=material_name, **metadata)


def cube(name: str, location: tuple[float, float, float], dimensions: tuple[float, float, float], material_name: str, **metadata: Any) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    obj.data.materials.append(MATERIALS[material_name])
    return tag(obj, material_id=material_name, **metadata)


def cylinder(
    name: str,
    location: tuple[float, float, float],
    radius: float,
    depth: float,
    material_name: str,
    *,
    vertices: int = 10,
    rotation: tuple[float, float, float] = (0, 0, 0),
    **metadata: Any,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(MATERIALS[material_name])
    return tag(obj, material_id=material_name, **metadata)


def cone(
    name: str,
    location: tuple[float, float, float],
    radius1: float,
    radius2: float,
    depth: float,
    material_name: str,
    *,
    vertices: int = 8,
    rotation: tuple[float, float, float] = (0, 0, 0),
    **metadata: Any,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius1, radius2=radius2, depth=depth, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(MATERIALS[material_name])
    return tag(obj, material_id=material_name, **metadata)


def curve_object(
    name: str,
    points: list[tuple[float, float, float]],
    material_name: str,
    *,
    bevel: float,
    cyclic: bool = False,
    **metadata: Any,
) -> bpy.types.Object:
    curve = bpy.data.curves.new(f"{name}_Curve", "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 2
    curve.bevel_depth = bevel
    curve.bevel_resolution = 2
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for point, value in zip(spline.bezier_points, points):
        point.co = value
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(MATERIALS[material_name])
    return tag(obj, material_id=material_name, **metadata)


def world_point(cell: dict[str, Any], z_offset: float = 0.0) -> tuple[float, float, float]:
    # Keep the realizer's row direction in Blender. glTF's axis conversion is
    # the only coordinate transform; flipping here would mirror Viewer nav.
    return ((int(cell["col"]) + 0.5) * CELL, (int(cell["row"]) + 0.5) * CELL, float(cell["elevation"]) * FT + z_offset)


def cell_box(cell: dict[str, Any], *, height: float = 0.16, inset: float = 0.025, z_offset: float = 0.0) -> Box:
    x, y, z = world_point(cell, z_offset)
    return ((x, y, z - height / 2), (CELL - inset, CELL - inset, height))


def neighbor(cell: dict[str, Any], dr: int, dc: int) -> dict[str, Any] | None:
    return AT.get((str(cell["level_id"]), int(cell["row"]) + dr, int(cell["col"]) + dc))


def surface_material(surface: str) -> str:
    if surface in {"water", "waterfall"}:
        return "water"
    if surface in {"sewage"}:
        return "sewage"
    if surface in {"bridge", "hatch_platform"}:
        return "wood"
    if surface in {"trail", "bone_route", "floating_rock"}:
        return "route"
    if surface in {"pine_forest", "pine_slope", "mossy_ledge", "wet_shrine_ledge"}:
        return "moss"
    if surface in {"ridge_scree", "rocky_slope", "karst_rock", "crater_rim", "high_rim", "crater_slope", "shattered_talus"}:
        return "rock"
    if "bone" in surface or surface in {"dragon_skull", "skull_plateau"}:
        return "bone_ground"
    if surface in {"arcane_rift", "arcane_vent"}:
        return "rift"
    if surface in {"dry_brick", "junction_brick", "pump_floor", "wet_brick", "sealed_masonry", "altar_platform", "pump_controls"}:
        return "brick"
    return "earth"


def build_ground() -> None:
    groups: defaultdict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for cell in GRID["cells"]:
        if cell["surface"] == "void":
            continue
        groups[(surface_material(str(cell["surface"])), int(cell["elevation"]), str(cell.get("visibility", "public")))].append(cell)
    for (material_name, elevation, visibility), cells in sorted(groups.items()):
        boxes_mesh(
            f"Terrain_{material_name}_{elevation}_{visibility}",
            (cell_box(cell, height=.13 if material_name not in {"water", "sewage", "rift"} else .07, z_offset=-.07 if material_name in {"water", "sewage"} else 0) for cell in cells),
            material_name,
            kind="surface",
            visibility=visibility,
            pick_role="tactical_floor" if any(bool(cell["walkable"]) for cell in cells) else "blocked_surface",
            elevation_ft=elevation,
            surface_kinds=sorted({str(cell["surface"]) for cell in cells}),
            cell_ids=[cell["id"] for cell in cells],
        )

    cliff_groups: defaultdict[tuple[str, str], list[Box]] = defaultdict(list)
    for cell in GRID["cells"]:
        if cell["surface"] == "void":
            continue
        x, y, top = world_point(cell)
        for dr, dc, axis in ((-1, 0, "north"), (1, 0, "south"), (0, -1, "west"), (0, 1, "east")):
            other = neighbor(cell, dr, dc)
            other_top = float(other["elevation"]) * FT if other and other["surface"] != "void" else min(-.55, top - 1.0)
            if top - other_top < .35:
                continue
            height = top - other_top
            if axis == "north":
                center, dims = (x, y + CELL / 2, other_top + height / 2), (CELL + .03, .08, height)
            elif axis == "south":
                center, dims = (x, y - CELL / 2, other_top + height / 2), (CELL + .03, .08, height)
            elif axis == "west":
                center, dims = (x - CELL / 2, y, other_top + height / 2), (.08, CELL + .03, height)
            else:
                center, dims = (x + CELL / 2, y, other_top + height / 2), (.08, CELL + .03, height)
            cliff_groups[("sewer_wall" if ARCHETYPE == "infrastructure_dungeon" else "cliff", str(cell.get("visibility", "public")))].append((center, dims))
    for (material_name, visibility), boxes in cliff_groups.items():
        boxes_mesh(
            f"Cliffs_{material_name}_{visibility}", boxes, material_name,
            kind="wall" if ARCHETYPE == "infrastructure_dungeon" else "terrain_cliff",
            visibility=visibility,
            pick_role="occluder" if ARCHETYPE == "infrastructure_dungeon" else "none",
        )


def build_grid() -> None:
    groups: defaultdict[tuple[int, str], list[Box]] = defaultdict(list)
    for cell in GRID["cells"]:
        if not cell["walkable"]:
            continue
        x, y, z = world_point(cell, .025)
        key = (int(cell["elevation"]), str(cell.get("visibility", "public")))
        groups[key].extend([
            ((x, y - CELL / 2 + .012, z), (CELL - .025, .022, .018)),
            ((x - CELL / 2 + .012, y, z), (.022, CELL - .025, .018)),
        ])
    for (elevation, visibility), boxes in groups.items():
        boxes_mesh(
            f"Grid_{elevation}_{visibility}", boxes, "grid_secret" if visibility == "dm_only" else "grid",
            kind="grid", visibility=visibility, pick_role="grid", elevation_ft=elevation,
        )


def build_route_marks() -> None:
    for route in GRID["routes"]:
        points = [world_point(CELLS[cell_id], .045) for cell_id in route["cell_ids"] if cell_id in CELLS]
        if len(points) < 2:
            continue
        material_name = "secret" if route["visibility"] == "dm_only" else "route_mark"
        curve_object(
            f"Route_{route['id']}", points, material_name, bevel=.025,
            kind="route", visibility=route["visibility"], pick_role="none",
            route_id=route["id"], route_role=route["role"], traversal=route["traversal"], risk=route["risk"],
        )


def anchor_by_id(anchor_id: str) -> dict[str, Any]:
    return next(anchor for anchor in GRID["anchors"] if anchor["id"] == anchor_id)


def anchor_point(anchor_id: str, z_offset: float = 0.0) -> tuple[float, float, float]:
    return world_point(CELLS[anchor_by_id(anchor_id)["cell_id"]], z_offset)


def build_anchors() -> None:
    batches: defaultdict[str, list[Box]] = defaultdict(list)
    anchor_ids: defaultdict[str, list[str]] = defaultdict(list)
    for anchor in GRID["anchors"]:
        cell = CELLS[anchor["cell_id"]]
        x, y, z = world_point(cell, .10)
        visibility = str(anchor.get("visibility", "public"))
        batches[visibility].append(((x, y, z), (.58, .58, .18)))
        anchor_ids[visibility].append(anchor["id"])
    for visibility, boxes in batches.items():
        boxes_mesh(
            f"Anchors_{visibility}", boxes, "secret" if visibility == "dm_only" else "anchor",
            kind="anchor", visibility=visibility, pick_role="anchor", anchor_ids=anchor_ids[visibility],
        )


def build_feature_semantics() -> None:
    """Every contract feature gets a visible, pickable semantic footprint.

    Archetype builders may add richer geometry with the same feature_id; these
    low pads make unknown future feature kinds degrade explicitly, never vanish.
    """
    for feature in GRID.get("features", []):
        ordered_ids = list(dict.fromkeys(str(cell_id) for cell_id in feature.get("cell_ids", [])))
        cells = [CELLS[cell_id] for cell_id in ordered_ids if cell_id in CELLS]
        if not cells:
            continue
        visibility = str(feature.get("visibility", "public"))
        boxes_mesh(
            f"FeatureFootprint_{feature['id']}",
            (cell_box(cell, height=.045, inset=.28, z_offset=.075) for cell in cells),
            "secret" if visibility == "dm_only" else "feature_semantic",
            kind="feature", visibility=visibility, pick_role="feature",
            feature_id=feature["id"], feature_kind=feature["kind"],
            blocks_movement=bool(feature.get("blocks_movement", False)),
            cell_ids=ordered_ids, feature_unhandled=False,
        )


def build_wilderness_details() -> None:
    pine_cells = [cell for cell in GRID["cells"] if cell["walkable"] and cell["surface"] in {"pine_forest", "pine_slope"} and "route" not in cell["tags"]]
    RNG.shuffle(pine_cells)
    for index, cell in enumerate(pine_cells[:34]):
        x, y, z = world_point(cell)
        jitter_x, jitter_y = RNG.uniform(-.24, .24), RNG.uniform(-.24, .24)
        height = RNG.uniform(.75, 1.55)
        cylinder(f"PineTrunk_{index}", (x + jitter_x, y + jitter_y, z + height * .26), .055, height * .52, "wood", vertices=7, kind="vegetation", pick_role="none")
        cone(f"PineCrown_{index}", (x + jitter_x, y + jitter_y, z + height * .72), .26, .018, height, "pine", vertices=7, kind="vegetation", pick_role="none")

    rock_cells = [cell for cell in GRID["cells"] if cell["walkable"] and cell["surface"] in {"ridge_scree", "rocky_slope", "karst_rock"} and "route" not in cell["tags"]]
    RNG.shuffle(rock_cells)
    for index, cell in enumerate(rock_cells[:28]):
        x, y, z = world_point(cell)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=RNG.uniform(.14, .38), location=(x + RNG.uniform(-.25, .25), y + RNG.uniform(-.25, .25), z + .10))
        obj = bpy.context.object
        obj.name = f"ValleyRock_{index}"
        obj.scale = (RNG.uniform(.7, 1.4), RNG.uniform(.7, 1.35), RNG.uniform(.5, 1.15))
        obj.data.materials.append(MATERIALS["rock_detail"])
        tag(obj, kind="rock", material_id="rock_detail", pick_role="cover")

    bridge = next((crossing for crossing in GRID.get("crossings", []) if crossing["kind"] == "bridge"), None)
    if bridge:
        planks: list[Box] = []
        for cell_id in bridge["cell_ids"]:
            x, y, z = world_point(CELLS[cell_id], .10)
            planks.append(((x, y, z), (.92, .82, .12)))
        boxes_mesh("OldBridgePlanks", planks, "wood", kind="feature", visibility="public", pick_role="tactical_floor", feature_id=bridge["id"])

    cave_x, cave_y, cave_z = anchor_point("cave_mouth")
    boxes_mesh("CaveMouthArch", [
        ((cave_x - .65, cave_y, cave_z + .72), (.50, .82, 1.45)),
        ((cave_x + .65, cave_y, cave_z + .72), (.50, .82, 1.45)),
        ((cave_x, cave_y, cave_z + 1.45), (1.65, .86, .42)),
    ], "karst", kind="landmark", visibility="public", pick_role="occluder", landmark_id="cave_mouth")

    shrine_x, shrine_y, shrine_z = anchor_point("hidden_shrine")
    boxes_mesh("HiddenWaterShrine", [
        ((shrine_x, shrine_y, shrine_z + .24), (1.25, .84, .44)),
        ((shrine_x, shrine_y + .22, shrine_z + .73), (.42, .26, .72)),
    ], "shrine", kind="feature", visibility="dm_only", pick_role="feature", feature_id="hidden_shrine")

    waterfall_cells = [cell for cell in GRID["cells"] if cell["surface"] == "waterfall"]
    if waterfall_cells:
        xs = [world_point(cell)[0] for cell in waterfall_cells]
        ys = [world_point(cell)[1] for cell in waterfall_cells]
        z_top = max(world_point(cell)[2] for cell in waterfall_cells) + 1.7
        cube("SilverfallCurtain", ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, z_top - .85), (max(.9, max(xs) - min(xs) + .9), .16, 1.8), "waterfall", kind="landmark", visibility="public", pick_role="none", landmark_id="silver_fall")

    trail = next(route for route in GRID["routes"] if route["id"] == "valley_trail")
    waystones: list[Box] = []
    for cell_id in trail["cell_ids"][12::32]:
        x, y, z = world_point(CELLS[cell_id])
        waystones.extend([
            ((x + .26, y - .22, z + .36), (.22, .30, .72)),
            ((x + .26, y - .22, z + .78), (.36, .20, .14)),
        ])
    boxes_mesh("OldValleyWaystones", waystones, "waystone", kind="life_trace", visibility="public", pick_role="none", detail_group="life_trace")


def build_sewer_walls() -> None:
    walkable = {(str(cell["level_id"]), int(cell["row"]), int(cell["col"])) for cell in GRID["cells"] if cell["walkable"]}
    public: list[Box] = []
    secret: list[Box] = []
    for cell in GRID["cells"]:
        if not cell["walkable"]:
            continue
        x, y, z = world_point(cell)
        target = secret if cell.get("visibility") == "dm_only" else public
        for dr, dc, axis in ((-1, 0, "north"), (1, 0, "south"), (0, -1, "west"), (0, 1, "east")):
            if (str(cell["level_id"]), int(cell["row"]) + dr, int(cell["col"]) + dc) in walkable:
                continue
            # Waist-high tactical walls keep the network readable in the
            # generated overview; Viewer cutaway can still fade them further.
            if axis == "north":
                target.append(((x, y + CELL / 2, z + .43), (CELL + .06, .12, .86)))
            elif axis == "south":
                target.append(((x, y - CELL / 2, z + .43), (CELL + .06, .12, .86)))
            elif axis == "west":
                target.append(((x - CELL / 2, y, z + .43), (.12, CELL + .06, .86)))
            else:
                target.append(((x + CELL / 2, y, z + .43), (.12, CELL + .06, .86)))
    boxes_mesh("SewerWalls_public", public, "sewer_wall", kind="wall", visibility="public", pick_role="occluder")
    boxes_mesh("SewerWalls_dm_only", secret, "secret_wall", kind="wall", visibility="dm_only", pick_role="occluder")


def build_sewer_details() -> None:
    build_sewer_walls()
    pump_x, pump_y, pump_z = anchor_point("pump_controls")
    for index, dx in enumerate((-.65, .65)):
        cylinder(f"PumpDrum_{index}", (pump_x + dx, pump_y, pump_z + .48), .38, .80, "iron", vertices=12, rotation=(0, math.pi / 2, 0), kind="machinery", pick_role="feature", feature_id="main_pump_assembly")
        cylinder(f"PumpAxle_{index}", (pump_x + dx, pump_y, pump_z + .48), .10, 1.12, "brass", vertices=10, rotation=(0, math.pi / 2, 0), kind="machinery", pick_role="feature")
    boxes_mesh("PumpControlConsole", [
        ((pump_x, pump_y - .72, pump_z + .46), (1.55, .42, .82)),
        ((pump_x, pump_y - .91, pump_z + .92), (1.42, .12, .22)),
    ], "iron", kind="machinery", visibility="public", pick_role="feature", feature_id="pump_controls")

    gate_x, gate_y, gate_z = anchor_point("overflow_gate")
    boxes_mesh("OverflowGate", [
        ((gate_x - .52, gate_y, gate_z + .75), (.16, .28, 1.5)),
        ((gate_x + .52, gate_y, gate_z + .75), (.16, .28, 1.5)),
        ((gate_x, gate_y, gate_z + 1.45), (1.18, .28, .18)),
        ((gate_x, gate_y, gate_z + .68), (1.00, .12, 1.22)),
    ], "rust", kind="feature", visibility="public", pick_role="feature", feature_id="iron_overflow_gate")

    junction_x, junction_y, junction_z = anchor_point("fourway_junction")
    cylinder("JunctionGrate", (junction_x, junction_y, junction_z + .045), .62, .07, "grate", vertices=16, kind="feature", pick_role="feature", feature_id="junction_grates")

    shrine_x, shrine_y, shrine_z = anchor_point("shrine_altar")
    boxes_mesh("BuriedShrineAltar", [
        ((shrine_x, shrine_y, shrine_z + .32), (1.25, .82, .62)),
        ((shrine_x, shrine_y, shrine_z + .69), (1.42, .94, .14)),
        ((shrine_x, shrine_y + .28, shrine_z + 1.15), (.42, .22, .88)),
    ], "shrine", kind="feature", visibility="dm_only", pick_role="feature", feature_id="shrine_altar")

    dry_cells = [cell for cell in GRID["cells"] if cell["walkable"] and cell["surface"] in {"dry_brick", "junction_brick"}]
    for index, cell in enumerate(dry_cells[::18][:26]):
        x, y, z = world_point(cell)
        boxes_mesh(f"PipeBracket_{index}", [
            ((x, y, z + 1.05), (.88, .12, .12)),
            ((x - .34, y, z + .88), (.12, .12, .42)),
        ], "pipe", kind="infrastructure", visibility="public", pick_role="none", infrastructure_role="drain_pipe")

    collector = next(route for route in GRID["routes"] if route["id"] == "collector_spine")
    collector_cells = [CELLS[cell_id] for cell_id in collector["cell_ids"]]
    arch_boxes: list[Box] = []
    for index in range(7, len(collector_cells) - 1, 15):
        cell, before, after = collector_cells[index], collector_cells[index - 1], collector_cells[index + 1]
        x, y, z = world_point(cell)
        horizontal = int(before["col"]) != int(after["col"])
        if horizontal:
            arch_boxes.extend([
                ((x, y - .46, z + .62), (.14, .14, 1.24)), ((x, y + .46, z + .62), (.14, .14, 1.24)),
                ((x, y, z + 1.20), (.16, 1.06, .16)),
            ])
        else:
            arch_boxes.extend([
                ((x - .46, y, z + .62), (.14, .14, 1.24)), ((x + .46, y, z + .62), (.14, .14, 1.24)),
                ((x, y, z + 1.20), (1.06, .16, .16)),
            ])
    boxes_mesh("CollectorSupportArches", arch_boxes, "brick_trim", kind="infrastructure", visibility="public", pick_role="occluder", infrastructure_role="support_arches")

    debris_boxes: list[Box] = []
    for cell in dry_cells[10::37]:
        x, y, z = world_point(cell)
        debris_boxes.extend([
            ((x - .18, y + .22, z + .07), (.28, .18, .14)),
            ((x + .12, y + .28, z + .045), (.18, .12, .09)),
        ])
    boxes_mesh("MaintenanceDebris", debris_boxes, "rust", kind="life_trace", visibility="public", pick_role="none", detail_group="maintenance_trace")


def build_dragon_details() -> None:
    skull_x, skull_y, skull_z = anchor_point("dragon_skull")
    skull = cone("DragonSkull", (skull_x, skull_y, skull_z + .72), 1.35, .52, 2.1, "bone", vertices=8, rotation=(math.pi / 2, 0, math.radians(-18)), kind="landmark", pick_role="cover", landmark_id="skull_landmark")
    skull.scale.y = .72
    for index, side in enumerate((-1, 1)):
        cone(f"DragonHorn_{index}", (skull_x + side * .78, skull_y + .38, skull_z + 1.55), .24, .015, 1.42, "bone_dark", vertices=7, rotation=(math.radians(-28), side * math.radians(18), side * math.radians(12)), kind="landmark_detail", pick_role="cover")
        cube(f"SkullEye_{index}", (skull_x + side * .50, skull_y - .52, skull_z + .85), (.22, .10, .18), "rift", kind="landmark_detail", visibility="public", pick_role="none")

    spine_points = [(31, col) for col in range(16, 40, 2)]
    for index, point in enumerate(spine_points):
        cell = AT.get(("surface", point[0], point[1]))
        if not cell or cell["surface"] == "void":
            continue
        x, y, z = world_point(cell, .25)
        cylinder(f"Vertebra_{index}", (x, y, z), .30, .22, "bone", vertices=8, rotation=(math.pi / 2, 0, 0), kind="bone", pick_role="cover", bone_role="spine")
        cone(f"SpineSpike_{index}", (x, y, z + .42), .16, .01, .72, "bone_dark", vertices=7, kind="bone", pick_role="cover")

    rib_origin = anchor_point("spine_bridge", .25)
    for index in range(9):
        offset = (index - 4) * .78
        base = (rib_origin[0] + offset, rib_origin[1], rib_origin[2])
        for side in (-1, 1):
            points = [
                base,
                (base[0] + offset * .08, base[1] + side * .75, base[2] + 1.05),
                (base[0], base[1] + side * 1.55, base[2] + .65),
                (base[0] - offset * .04, base[1] + side * 2.10, base[2] + .12),
            ]
            curve_object(f"Rib_{index}_{side}", points, "bone", bevel=.10, kind="bone", pick_role="cover", bone_role="rib")

    float_feature = next((feature for feature in GRID["features"] if feature["kind"] == "floating_stones"), None)
    if float_feature:
        for index, cell_id in enumerate(float_feature["cell_ids"]):
            x, y, z = world_point(CELLS[cell_id], .18)
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=.62 + index * .12, location=(x, y, z))
            obj = bpy.context.object
            obj.name = f"FloatingStone_{index}"
            obj.scale = (1.25, .88, .42)
            obj.rotation_euler = (RNG.uniform(-.2, .2), RNG.uniform(-.2, .2), RNG.uniform(0, math.pi))
            obj.data.materials.append(MATERIALS["floating_rock"])
            tag(obj, kind="feature", material_id="floating_rock", pick_role="tactical_floor", feature_id="floating_stones")

    vent_x, vent_y, vent_z = anchor_point("rift_vent")
    for index in range(7):
        angle = index / 7 * math.tau
        radius = .45 + index * .12
        cone(f"RiftShard_{index}", (vent_x + math.cos(angle) * radius, vent_y + math.sin(angle) * radius, vent_z + .42 + index * .05), .17, .015, .85 + index * .08, "rift", vertices=6, rotation=(math.sin(angle) * .18, math.cos(angle) * .18, angle), kind="hazard", pick_role="feature", feature_id="arcane_vent")

    shard_cells = [cell for cell in GRID["cells"] if cell["walkable"] and cell["surface"] in {"crater_slope", "shattered_talus"} and "route" not in cell["tags"]]
    RNG.shuffle(shard_cells)
    for index, cell in enumerate(shard_cells[:14]):
        x, y, z = world_point(cell)
        cone(f"MeteorShard_{index}", (x + RNG.uniform(-.22, .22), y + RNG.uniform(-.22, .22), z + .30), .13, .015, .62, "meteor", vertices=5, rotation=(RNG.uniform(-.25, .25), RNG.uniform(-.25, .25), RNG.uniform(0, math.tau)), kind="expedition_trace", pick_role="cover", detail_group="meteor_debris")

    entry_x, entry_y, entry_z = anchor_point("rim_entry")
    boxes_mesh("ExpeditionRopeStakes", [
        ((entry_x - .65, entry_y, entry_z + .38), (.10, .10, .76)),
        ((entry_x + .65, entry_y, entry_z + .38), (.10, .10, .76)),
        ((entry_x, entry_y - .30, entry_z + .08), (.74, .34, .16)),
    ], "brass", kind="expedition_trace", visibility="public", pick_role="none", detail_group="expedition_trace")


def create_materials() -> None:
    material("earth", (.14, .075, .035, 1), roughness=.95)
    material("rock", (.22, .25, .34, 1), roughness=.91, emission=.045)
    material("rock_detail", (.12, .15, .20, 1), roughness=.95)
    material("karst", (.10, .13, .17, 1), roughness=.96)
    material("cliff", (.095, .12, .16, 1), roughness=.96)
    material("moss", (.055, .20, .10, 1), roughness=.94)
    material("pine", (.025, .16, .08, 1), roughness=.93)
    material("wood", (.28, .105, .028, 1), roughness=.88)
    material("waystone", (.30, .31, .30, 1), roughness=.94)
    material("water", (.012, .27, .52, 1), roughness=.22, metallic=.12, emission=.48, alpha=.88)
    material("waterfall", (.16, .58, .92, 1), roughness=.12, emission=1.15, alpha=.66)
    material("route", (.29, .18, .08, 1), roughness=.88)
    material("route_mark", (.72, .39, .08, 1), roughness=.42, emission=.65)
    material("brick", (.34, .17, .085, 1), roughness=.91, emission=.08)
    material("sewer_wall", (.19, .25, .22, 1), roughness=.94, emission=.045)
    material("secret_wall", (.35, .025, .42, 1), roughness=.70, emission=.25)
    material("brick_trim", (.42, .22, .11, 1), roughness=.88, emission=.04)
    material("sewage", (.018, .38, .14, 1), roughness=.36, emission=1.05, alpha=.91)
    material("iron", (.10, .14, .16, 1), roughness=.40, metallic=.78)
    material("pipe", (.11, .24, .22, 1), roughness=.36, metallic=.68)
    material("rust", (.42, .12, .028, 1), roughness=.76, metallic=.35)
    material("brass", (.47, .28, .055, 1), roughness=.30, metallic=.72, emission=.05)
    material("grate", (.065, .09, .10, 1), roughness=.45, metallic=.82)
    material("bone_ground", (.42, .36, .27, 1), roughness=.92, emission=.055)
    material("bone", (.72, .62, .45, 1), roughness=.74)
    material("bone_dark", (.38, .31, .23, 1), roughness=.84)
    material("floating_rock", (.12, .11, .20, 1), roughness=.82, emission=.08)
    material("meteor", (.34, .055, .52, 1), roughness=.34, metallic=.24, emission=.75)
    material("rift", (.18, .025, .72, 1), roughness=.20, metallic=.10, emission=3.8)
    material("shrine", (.36, .045, .08, 1), roughness=.66, emission=.42)
    material("grid", (.08, .48, .52, 1), roughness=.40, emission=.30)
    material("grid_secret", (.75, .02, .65, 1), roughness=.30, emission=1.5)
    material("anchor", (.02, .88, .42, 1), roughness=.24, emission=1.9)
    material("secret", (.92, .018, .58, 1), roughness=.22, emission=2.2)
    material("feature_semantic", (.88, .52, .04, 1), roughness=.30, emission=.72)


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def configure_scene() -> bpy.types.Object:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1500, 1100, 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = .72 if ARCHETYPE == "infrastructure_dungeon" else (.58 if ARCHETYPE == "special_site" else -.15)
    scene.world.use_nodes = True
    background = next(node for node in scene.world.node_tree.nodes if node.type == "BACKGROUND")
    palettes = {
        "wilderness": ((.018, .045, .075, 1), .30),
        "infrastructure_dungeon": ((.012, .026, .022, 1), .32),
        "special_site": ((.018, .012, .055, 1), .42),
    }
    background.inputs["Color"].default_value, background.inputs["Strength"].default_value = palettes[ARCHETYPE]
    width, height = WIDTH * CELL, HEIGHT * CELL
    max_z = max(float(cell["elevation"]) * FT for cell in GRID["cells"] if cell["surface"] != "void")
    target = (width / 2, height / 2, max_z * .35)
    lights = {
        "wilderness": [
            ("ValleySun", "SUN", (0, 0, 30), 2.0, (1.0, .62, .32), 8),
            ("ValleySky", "AREA", (width * .15, height * .85, 34), 1350, (.16, .38, 1.0), 26),
            ("ValleyBounce", "AREA", (width * .95, height * .18, 22), 900, (.16, 1.0, .52), 20),
        ],
        "infrastructure_dungeon": [
            ("SewerKey", "AREA", (width * .18, height * .12, 18), 980, (1.0, .30, .08), 18),
            ("SewerFill", "AREA", (width * .80, height * .85, 16), 820, (.04, .78, .40), 16),
            ("SewerRim", "AREA", (width * .88, height * .25, 12), 620, (.08, .28, 1.0), 14),
        ],
        "special_site": [
            ("RiftKey", "AREA", (width * .12, height * .82, 38), 1250, (.20, .18, 1.0), 25),
            ("RiftRim", "AREA", (width * .88, height * .18, 30), 1050, (1.0, .12, .36), 21),
            ("RiftMoon", "AREA", (width * .75, height * .92, 42), 700, (.16, .72, 1.0), 18),
        ],
    }
    for name, light_type, location, energy, color, size in lights[ARCHETYPE]:
        bpy.ops.object.light_add(type=light_type, location=location)
        obj = bpy.context.object
        obj.name = name
        obj.data.energy = energy
        obj.data.color = color
        if light_type == "AREA":
            obj.data.shape = "DISK"
            obj.data.size = size
            look_at(obj, target)
        else:
            obj.rotation_euler = (math.radians(28), math.radians(-18), math.radians(-32))
    if ARCHETYPE != "wilderness":
        bpy.ops.object.light_add(type="SUN", location=(0, 0, 30))
        ambient_sun = bpy.context.object
        ambient_sun.name = "DungeonReadabilitySun"
        ambient_sun.data.energy = .38 if ARCHETYPE == "infrastructure_dungeon" else .62
        ambient_sun.data.color = (.16, .28, 1.0) if ARCHETYPE == "special_site" else (.18, .38, .28)
        ambient_sun.rotation_euler = (math.radians(32), math.radians(-24), math.radians(-38))
    if ARCHETYPE == "special_site":
        vent_x, vent_y, vent_z = anchor_point("rift_vent", 2.0)
        bpy.ops.object.light_add(type="POINT", location=(vent_x, vent_y, vent_z))
        glow = bpy.context.object
        glow.name = "RiftVentGlow"
        glow.data.energy = 850
        glow.data.color = (.22, .025, 1.0)
        glow.data.shadow_soft_size = 5.5
    if ARCHETYPE == "infrastructure_dungeon":
        pump_x, pump_y, pump_z = anchor_point("pump_controls", 2.0)
        bpy.ops.object.light_add(type="POINT", location=(pump_x, pump_y, pump_z))
        glow = bpy.context.object
        glow.name = "PumpWarningLight"
        glow.data.energy = 430
        glow.data.color = (1.0, .12, .015)
        glow.data.shadow_soft_size = 3.5
    bpy.ops.object.camera_add(location=(width * 1.17, -height * .64, max(width, height) * .86 + max_z))
    camera = bpy.context.object
    camera.name = "V22SceneCamera"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(width, height) * 1.30
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
        if obj.type in {"MESH", "CURVE"}:
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


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clean_scene()
    create_materials()
    build_ground()
    build_grid()
    build_route_marks()
    build_anchors()
    build_feature_semantics()
    if ARCHETYPE == "wilderness":
        build_wilderness_details()
    elif ARCHETYPE == "infrastructure_dungeon":
        build_sewer_details()
    elif ARCHETYPE == "special_site":
        build_dragon_details()
    else:
        raise ValueError(f"unsupported Blender archetype: {ARCHETYPE}")
    camera = configure_scene()
    width, height = WIDTH * CELL, HEIGHT * CELL
    elevations = [float(cell["elevation"]) * FT for cell in GRID["cells"] if cell["surface"] != "void"]
    min_z, max_z = min(elevations), max(elevations)
    target = (width / 2, height / 2, min_z + (max_z - min_z) * .38)
    render(camera, "scene-isometric.png", (width * 1.17, -height * .64, max(width, height) * .86 + max_z), target, max(width, height) * 1.30)
    render(camera, "scene-topdown.png", (width / 2, height / 2, max(width, height) * 1.65 + max_z), (width / 2, height / 2, min_z), max(width, height) * 1.10)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "scene-prototype.blend"))
    export_glb()
    input_manifest_path = OUT / "scene.manifest.json"
    output_names = ["scene.glb", "scene-prototype.blend", "scene-isometric.png", "scene-topdown.png"]
    manifest = {
        "status": "generated",
        "schema_version": "dnd-v22-render-manifest-1.0",
        "scene_id": GRID["scene"]["id"],
        "archetype": ARCHETYPE,
        "grid_file_sha256": sha256(GRID_PATH),
        "grid_semantic_sha256": json.loads(input_manifest_path.read_text(encoding="utf-8")).get("grid_sha256", "") if input_manifest_path.exists() else "",
        "input_manifest_sha256": sha256(input_manifest_path) if input_manifest_path.exists() else "",
        "blender_version": bpy.app.version_string,
        "grid": GRID["scene"]["grid"],
        "elevation_range_ft": [min(float(cell["elevation"]) for cell in GRID["cells"]), max(float(cell["elevation"]) for cell in GRID["cells"])],
        "walkable_cells": sum(bool(cell["walkable"]) for cell in GRID["cells"]),
        "prototype_objects": len(OBJECTS),
        "estimated_draw_calls": len(OBJECTS),
        "batched_boxes": STATS["batched_boxes"],
        "mesh_vertices": STATS["mesh_vertices"],
        "object_kinds": {key[5:]: value for key, value in sorted(STATS.items()) if key.startswith("kind_")},
        "outputs": [file_record(OUT / name) for name in output_names],
    }
    (OUT / "scene.render-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
