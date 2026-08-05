"""Render a shared profile-visual input without changing legacy Blender builders.

This is the first Blender bridge for the V3 planners.  It intentionally uses a
small, renderer-neutral geometry vocabulary (ground, road, lot, facade, roof,
terrain band, water, cliff, connector and feature) so a new district/building/
outdoor kind does not require a new Blender branch.
"""

from __future__ import annotations

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


INPUT = Path(argument("--input", str(ROOT / "output" / "profile-visual" / "harbor_district.json"))).expanduser().resolve()
OUT = Path(argument("--out-dir", str(INPUT.parent))).expanduser().resolve()
DOCUMENT = json.loads(INPUT.read_text(encoding="utf-8"))
PROFILE = DOCUMENT["profile"]
VISUAL = DOCUMENT["visual_plan"]
CATEGORY = str(DOCUMENT["category"])
SCENE = PROFILE.get("scene", {})
DIMENSIONS = PROFILE.get("dimensions", {"width": 32, "height": 24})
WIDTH = int(DIMENSIONS.get("width", 32))
HEIGHT = int(DIMENSIONS.get("height", 24))
CELL = 0.25 if max(WIDTH, HEIGHT) > 80 else 0.32
Z_SCALE = 0.055
OBJECTS: list[bpy.types.Object] = []
MATERIALS: dict[str, bpy.types.Material] = {}
VERTICES = 0
RNG = random.Random(int(SCENE.get("seed", 0)))
# Outdoor composition is resolved into a shared height field.  Keeping it in
# the renderer (rather than branching on a scene name) lets any watershed,
# canyon, tundra or cavern reuse the same floor/cliff/route vocabulary.
TERRAIN_HEIGHTS: dict[tuple[int, int], float] = {}
TERRAIN_COVERS: dict[tuple[int, int], str] = {}
ORIGINAL_SCENE: bpy.types.Scene | None = None
PROFILE_SCENE: bpy.types.Scene | None = None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mat(name: str, color: tuple[float, float, float, float], *, roughness: float = 0.78, metallic: float = 0.0, emission: float = 0.0) -> bpy.types.Material:
    value = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
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


def tag(obj: bpy.types.Object, kind: str, material_id: str, **extras: Any) -> bpy.types.Object:
    obj["prototype"] = True
    obj["schema_version"] = "dnd-profile-visual-input-1.0"
    obj["scene_id"] = str(SCENE.get("id", "profile_scene"))
    obj["profile_category"] = CATEGORY
    obj["prototype_kind"] = kind
    obj["material_id"] = material_id
    for key, value in extras.items():
        if isinstance(value, (dict, list, tuple, set)):
            value = json.dumps(list(value) if isinstance(value, set) else value, ensure_ascii=False, separators=(",", ":"))
        obj[key] = value
    OBJECTS.append(obj)
    return obj


def clean() -> None:
    # Render into a dedicated scene.  This is important when the generator is
    # called from Blender MCP: clearing the global datablock would otherwise
    # delete an unrelated unsaved campaign scene.
    global ORIGINAL_SCENE, PROFILE_SCENE
    ORIGINAL_SCENE = bpy.context.scene
    scene_name = f"ProfileRender_{str(SCENE.get('id', 'scene'))[:48]}"
    PROFILE_SCENE = bpy.data.scenes.get(scene_name) or bpy.data.scenes.new(scene_name)
    if bpy.context.window:
        bpy.context.window.scene = PROFILE_SCENE
    for obj in list(PROFILE_SCENE.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    PROFILE_SCENE.world = bpy.data.worlds.get(f"{scene_name}_World") or bpy.data.worlds.new(f"{scene_name}_World")


def point(row: float, col: float, z: float = 0.0) -> tuple[float, float, float]:
    return ((float(col) + 0.5) * CELL, -(float(row) + 0.5) * CELL, float(z))


def box(name: str, center: tuple[float, float, float], size: tuple[float, float, float], material_id: str, kind: str, **extras: Any) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=center)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    obj.data.materials.append(MATERIALS[material_id])
    if kind not in {"ground", "road", "lot", "terrain_band", "grid"}:
        bevel = min(max(min(size) * 0.07, 0.008), 0.06)
        modifier = obj.modifiers.new("SoftenedEdges", "BEVEL")
        modifier.width = bevel
        modifier.segments = 2
    for polygon in obj.data.polygons:
        polygon.use_smooth = kind in {"pipe", "watercourse", "equipment", "landmark"}
    return tag(obj, kind, material_id, **extras)


def cylinder(name: str, center: tuple[float, float, float], radius: float, depth: float, material_id: str, kind: str, **extras: Any) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=radius, depth=depth, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(MATERIALS[material_id])
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return tag(obj, kind, material_id, **extras)


def cone(name: str, center: tuple[float, float, float], radius1: float, radius2: float, depth: float, material_id: str, kind: str, *, vertices: int = 12, **extras: Any) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius1, radius2=radius2, depth=depth, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(MATERIALS[material_id])
    for polygon in obj.data.polygons:
        polygon.use_smooth = kind in {"landmark", "rock_formation", "vegetation"}
    return tag(obj, kind, material_id, **extras)


def ico_rock(name: str, center: tuple[float, float, float], scale: tuple[float, float, float], material_id: str = "stone_light", **extras: Any) -> bpy.types.Object:
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1.0, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(MATERIALS[material_id])
    return tag(obj, "rock_formation", material_id, **extras)


def cylinder_between(name: str, start: tuple[float, float, float], end: tuple[float, float, float], radius: float, material_id: str, kind: str, **extras: Any) -> bpy.types.Object:
    a, b = Vector(start), Vector(end)
    delta = b - a
    obj = cylinder(name, ((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2), radius, max(0.02, delta.length), material_id, kind, **extras)
    obj.rotation_euler = delta.to_track_quat("Z", "Y").to_euler()
    return obj


def curve(name: str, points: list[tuple[float, float, float]], material_id: str, kind: str, *, bevel: float = 0.035, **extras: Any) -> bpy.types.Object | None:
    if len(points) < 2:
        return None
    data = bpy.data.curves.new(f"{name}_Curve", "CURVE")
    data.dimensions = "3D"
    data.resolution_u = 2
    data.bevel_depth = bevel
    data.bevel_resolution = 2
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for bezier, value in zip(spline.bezier_points, points):
        bezier.co = value
        bezier.handle_left_type = "AUTO"
        bezier.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    data.materials.append(MATERIALS[material_id])
    return tag(obj, kind, material_id, **extras)


def ribbon_mesh(name: str, points: list[tuple[float, float, float]], widths: list[float] | float, material_id: str, kind: str, **extras: Any) -> bpy.types.Object | None:
    """Create a low, walkable strip that follows a route or watercourse.

    Curves are useful for markers and pipes, but a river rendered as a thick
    tube reads like a cable.  A ribbon keeps the same renderer-neutral input
    while exposing width, banks and a continuous tactical surface.
    """
    if len(points) < 2:
        return None
    if isinstance(widths, (int, float)):
        width_values = [float(widths)] * len(points)
    else:
        width_values = [float(value) for value in widths]
        if len(width_values) != len(points):
            width_values = [width_values[min(index, len(width_values) - 1)] for index in range(len(points))]
    left: list[tuple[float, float, float]] = []
    right: list[tuple[float, float, float]] = []
    for index, (x, y, z) in enumerate(points):
        before = points[max(0, index - 1)]
        after = points[min(len(points) - 1, index + 1)]
        dx, dy = after[0] - before[0], after[1] - before[1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        half = max(.025, width_values[index] / 2)
        left.append((x + nx * half, y + ny * half, z))
        right.append((x - nx * half, y - ny * half, z))
    vertices = left + right
    faces: list[tuple[int, int, int, int]] = []
    for index in range(len(points) - 1):
        faces.append((index, index + 1, len(points) + index + 1, len(points) + index))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(MATERIALS[material_id])
    return tag(obj, kind, material_id, **extras)


def prism_polygon(name: str, polygon: list[list[int]], top_z: float, bottom_z: float, material_id: str, kind: str, **extras: Any) -> None:
    """Create a solid extruded polygon so terrain and lots have readable sides."""
    if len(polygon) < 3:
        return
    top = [(float(col) * CELL, -float(row) * CELL, top_z) for row, col in polygon]
    bottom = [(x, y, bottom_z) for x, y, _ in top]
    vertices = bottom + top
    count = len(polygon)
    faces: list[tuple[int, ...]] = [tuple(range(count - 1, -1, -1)), tuple(range(count, count * 2))]
    for index in range(count):
        next_index = (index + 1) % count
        faces.append((index, next_index, count + next_index, count + index))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(MATERIALS[material_id])
    tag(obj, kind, material_id, **extras)


def point_in_polygon(row: float, col: float, polygon: list[list[int]]) -> bool:
    inside = False
    if len(polygon) < 3:
        return False
    previous_row, previous_col = polygon[-1]
    for current_row, current_col in polygon:
        crosses = ((current_row > row) != (previous_row > row)) and (col < (previous_col - current_col) * (row - current_row) / ((previous_row - current_row) or 1e-9) + current_col)
        if crosses:
            inside = not inside
        previous_row, previous_col = current_row, current_col
    return inside


def terrain_cell_mesh(name: str, cells: list[tuple[int, int, float]], material_id: str, **extras: Any) -> None:
    """Build thin tactical surface tiles; vertical faces are added separately."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for row, col, top_z in cells:
        x, y = (col + .5) * CELL, -(row + .5) * CELL
        bottom_z = top_z - .12
        base = len(vertices)
        half = CELL * .48
        vertices.extend([(x - half, y - half, bottom_z), (x + half, y - half, bottom_z), (x + half, y + half, bottom_z), (x - half, y + half, bottom_z),
                         (x - half, y - half, top_z), (x + half, y - half, top_z), (x + half, y + half, top_z), (x - half, y + half, top_z)])
        faces.extend([(base, base + 3, base + 2, base + 1), (base + 4, base + 5, base + 6, base + 7),
                      (base, base + 1, base + 5, base + 4), (base + 1, base + 2, base + 6, base + 5),
                      (base + 2, base + 3, base + 7, base + 6), (base + 3, base, base + 4, base + 7)])
    if not vertices:
        return
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(MATERIALS[material_id])
    tag(obj, "terrain_band", material_id, **extras)


def terrain_cliff_mesh(name: str, walls: list[tuple[float, float, tuple[float, float], tuple[float, float]]], material_id: str, **extras: Any) -> None:
    """Create only the exposed faces between adjacent height cells.

    The old prototype made every terrain cell a tall pillar.  That read as a
    set of giant slabs.  A tactical surface should remain thin, while the
    height difference is communicated by these shared edge walls.
    """
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for low, high, p1, p2 in walls:
        base = len(vertices)
        vertices.extend([(p1[0], p1[1], low), (p2[0], p2[1], low), (p2[0], p2[1], high), (p1[0], p1[1], high)])
        faces.append((base, base + 1, base + 2, base + 3))
    if not vertices:
        return
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(MATERIALS[material_id])
    tag(obj, "cliff", material_id, **extras)


def strip_mesh(name: str, boxes: list[tuple[tuple[float, float, float], tuple[float, float, float]]], material_id: str, kind: str, **extras: Any) -> None:
    """Batch many small tactical rectangles into one mesh."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for (cx, cy, cz), (sx, sy, sz) in boxes:
        base = len(vertices)
        vertices.extend([(cx - sx / 2, cy - sy / 2, cz - sz / 2), (cx + sx / 2, cy - sy / 2, cz - sz / 2),
                         (cx + sx / 2, cy + sy / 2, cz - sz / 2), (cx - sx / 2, cy + sy / 2, cz - sz / 2),
                         (cx - sx / 2, cy - sy / 2, cz + sz / 2), (cx + sx / 2, cy - sy / 2, cz + sz / 2),
                         (cx + sx / 2, cy + sy / 2, cz + sz / 2), (cx - sx / 2, cy + sy / 2, cz + sz / 2)])
        faces.extend([(base, base + 3, base + 2, base + 1), (base + 4, base + 5, base + 6, base + 7),
                      (base, base + 1, base + 5, base + 4), (base + 1, base + 2, base + 6, base + 5),
                      (base + 2, base + 3, base + 7, base + 6), (base + 3, base, base + 4, base + 7)])
    if not vertices:
        return
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(MATERIALS[material_id])
    tag(obj, kind, material_id, **extras)


def create_materials() -> None:
    palette = VISUAL.get("palette", {})
    base = str(palette.get("base", "warm_gray"))
    if base == "blue_gray":
        colors = {"ground": (.08, .11, .14, 1), "road": (.16, .19, .20, 1), "wall": (.29, .32, .34, 1), "roof": (.08, .12, .17, 1), "accent": (.08, .42, .40, 1), "water": (.02, .26, .50, 1)}
    elif base == "basalt":
        colors = {"ground": (.05, .06, .08, 1), "road": (.10, .12, .14, 1), "wall": (.16, .18, .21, 1), "roof": (.04, .04, .06, 1), "accent": (.19, .55, .50, 1), "water": (.02, .22, .30, 1)}
    elif base == "slate":
        colors = {"ground": (.17, .20, .24, 1), "road": (.25, .24, .22, 1), "wall": (.34, .37, .39, 1), "roof": (.10, .13, .18, 1), "accent": (.34, .58, .52, 1), "water": (.05, .32, .54, 1)}
    else:
        colors = {"ground": (.15, .12, .10, 1), "road": (.25, .22, .18, 1), "wall": (.40, .32, .25, 1), "roof": (.18, .11, .08, 1), "accent": (.66, .34, .10, 1), "water": (.03, .25, .45, 1)}
    for name, color in colors.items():
        mat(name, color, roughness=.88 if name in {"ground", "wall"} else .62, metallic=.22 if name == "accent" else 0, emission=.22 if name == "accent" else 0)
    # Shared detail vocabulary: profiles select packs, while these materials
    # remain reusable across districts, buildings and wilderness scenes.
    mat("trim", (.48, .43, .36, 1), roughness=.58)
    mat("stone_light", (.56, .52, .45, 1), roughness=.82)
    mat("dark", (.025, .032, .042, 1), roughness=.92)
    mat("wood", (.24, .12, .055, 1), roughness=.82)
    mat("metal", (.18, .22, .24, 1), roughness=.34, metallic=.78)
    mat("green", (.08, .22, .14, 1), roughness=.9)
    mat("foam", (.62, .88, .92, 1), roughness=.22, emission=.26)
    mat("sand", (.44, .34, .20, 1), roughness=.95)
    mat("window", (.15, .55, .75, 1), roughness=.15, metallic=.16, emission=.3)
    mat("water_edge", (.03, .18, .25, 1), roughness=.34, metallic=.12)
    mat("grid", (.035, .28, .34, 1), roughness=.48, emission=.10)
    mat("secret", (.82, .12, .60, 1), roughness=.30, emission=.65)
    mat("feature", (.86, .48, .08, 1), roughness=.48, emission=.35)
    mat("glass", (.22, .62, .78, 1), roughness=.18, metallic=.08, emission=.35)
    mat("water", colors["water"], roughness=.23, metallic=.18, emission=.38)


def add_ground() -> None:
    if CATEGORY == "building":
        footprint_by_grammar = {"compact_tapered": (6, 6), "channel_adjacent_split_level": (10, 7), "courtyard_or_l": (9, 7), "axial_nave_and_side_aisles": (11, 7), "tunnel_chambers_and_shaft": (8, 8)}
        fw, fh = footprint_by_grammar.get(str(PROFILE.get("footprint")), (8, 6))
        ground_width = max(4.8, fw * CELL * 1.8)
        ground_depth = max(4.2, fh * CELL * 1.9)
        box("ProfileGround", (WIDTH * CELL / 2, -HEIGHT * CELL / 2, -.10), (ground_width, ground_depth, .20), "ground", "ground", category=CATEGORY)
    else:
        box("ProfileGround", (WIDTH * CELL / 2, -HEIGHT * CELL / 2, -.10), (WIDTH * CELL, HEIGHT * CELL, .20), "ground", "ground", category=CATEGORY)


def add_gable_roof(name: str, center: tuple[float, float, float], width: float, depth: float, height: float, material_id: str, *, ridge_axis: str = "y", **extras: Any) -> bpy.types.Object:
    """Low-poly roof with a readable silhouette instead of a flat cap."""
    cx, cy, z = center
    if ridge_axis == "x":
        vertices = [(cx - width / 2, cy - depth / 2, z), (cx + width / 2, cy - depth / 2, z),
                    (cx + width / 2, cy + depth / 2, z), (cx - width / 2, cy + depth / 2, z),
                    (cx, cy - depth / 2, z + height), (cx, cy + depth / 2, z + height)]
        faces = [(0, 1, 4), (1, 2, 5, 4), (2, 3, 5), (3, 0, 4, 5), (0, 3, 2, 1)]
    else:
        vertices = [(cx - width / 2, cy - depth / 2, z), (cx + width / 2, cy - depth / 2, z),
                    (cx + width / 2, cy + depth / 2, z), (cx - width / 2, cy + depth / 2, z),
                    (cx - width / 2, cy, z + height), (cx + width / 2, cy, z + height)]
        faces = [(0, 1, 5, 4), (1, 2, 5), (2, 3, 4, 5), (3, 0, 4), (0, 3, 2, 1)]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(MATERIALS[material_id])
    return tag(obj, "roof", material_id, **extras)


def add_window_row(prefix: str, center: tuple[float, float, float], width: float, height: float, count: int, material_id: str = "window", **extras: Any) -> None:
    if count <= 0:
        return
    spacing = width / count
    for index in range(count):
        x = center[0] - width / 2 + spacing * (index + .5)
        box(f"{prefix}_{index}", (x, center[1], center[2]), (max(.08, spacing * .46), .035, height), material_id, "window", **extras)


def add_lamp_post(name: str, position: tuple[float, float, float], height: float = .9, **extras: Any) -> None:
    post_extras = {"dressing_role": "lantern_post", **extras}
    glow_extras = {"dressing_role": "lantern", **extras}
    cylinder(name, position, .035, height, "metal", "street_dressing", **post_extras)
    cylinder(f"{name}_Glow", (position[0], position[1], position[2] + height / 2), .10, .08, "feature", "street_dressing", **glow_extras)


def add_crate_stack(name: str, position: tuple[float, float, float], count: int, **extras: Any) -> None:
    crate_extras = {"dressing_role": "crates", **extras}
    base_z = float(position[2])
    for index in range(count):
        offset_x = (index % 2) * .16
        offset_y = (index // 2) * .16
        box(f"{name}_{index}", (position[0] + offset_x, position[1] + offset_y, base_z + .09 + (index // 4) * .18), (.22, .22, .16), "wood", "street_dressing", **crate_extras)


def rotated_offset(dx: float, dy: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees % 360)
    return (dx * math.cos(angle) - dy * math.sin(angle), dx * math.sin(angle) + dy * math.cos(angle))


def add_battlements(prefix: str, center: tuple[float, float, float], width: float, depth: float, z: float, material_id: str, **extras: Any) -> None:
    """Reusable landmark roof language for towers, keeps and signal houses."""
    for index, (dx, dy) in enumerate(((-.42, -.42), (.42, -.42), (-.42, .42), (.42, .42))):
        cylinder(f"{prefix}_Merlon_{index}", (center[0] + dx * width, center[1] + dy * depth, z), .07, .28, material_id, "roof_detail", **extras)


def add_room_shell(prefix: str, center: tuple[float, float], width: float, depth: float, z: float, material_id: str = "wall", **extras: Any) -> None:
    """Add a readable room boundary without blocking the cutaway view.

    Full-height interior walls made the first generic buildings look like
    empty boxes from the isometric camera.  Waist-high split walls retain the
    room plan, doorway gap and cover information while keeping furniture and
    vertical connectors visible across every floor.
    """
    cx, cy = center
    wall_h, wall_t = .22, .055
    box(f"{prefix}_North", (cx, cy + depth * .46, z + wall_h / 2), (width, wall_t, wall_h), material_id, "room_partition", **extras)
    box(f"{prefix}_West", (cx - width * .46, cy, z + wall_h / 2), (wall_t, depth * .46, wall_h), material_id, "room_partition", **extras)
    box(f"{prefix}_East", (cx + width * .46, cy, z + wall_h / 2), (wall_t, depth * .46, wall_h), material_id, "room_partition", **extras)
    # A short return on the south side implies the doorway rather than sealing
    # the room with a fourth wall.
    box(f"{prefix}_SouthL", (cx - width * .31, cy - depth * .46, z + wall_h / 2), (width * .30, wall_t, wall_h), material_id, "room_partition", **extras)
    box(f"{prefix}_SouthR", (cx + width * .31, cy - depth * .46, z + wall_h / 2), (width * .30, wall_t, wall_h), material_id, "room_partition", **extras)


def add_window_lights(prefix: str, center: tuple[float, float], width: float, depth: float, z: float, count: int, *, material_id: str = "window", **extras: Any) -> None:
    """Place paired facade lights on two sides of a generic building floor."""
    count = max(1, int(count))
    for index in range(count):
        ratio = (index + 1) / (count + 1)
        x = center[0] - width * .42 + width * .84 * ratio
        box(f"{prefix}_Front_{index}", (x, center[1] - depth * .485, z), (width * .065, .025, .11), material_id, "window_light", **extras)
        box(f"{prefix}_Back_{index}", (x, center[1] + depth * .485, z), (width * .065, .025, .11), material_id, "window_light", **extras)
    for side in (-1, 1):
        for index in range(max(1, count // 2)):
            ratio = (index + 1) / (max(1, count // 2) + 1)
            y = center[1] - depth * .38 + depth * .76 * ratio
            box(f"{prefix}_Side_{side}_{index}", (center[0] + side * width * .485, y, z), (.025, depth * .065, .11), material_id, "window_light", **extras)


def add_arch_ribs(prefix: str, center: tuple[float, float], width: float, depth: float, z: float, count: int, *, material_id: str = "stone_light", **extras: Any) -> None:
    """Cross-ribs and hanging lamps give tunnels a volume, not a flat stripe."""
    for index in range(max(2, int(count))):
        ratio = index / max(1, count - 1)
        y = center[1] - depth * .38 + depth * .76 * ratio
        cylinder_between(f"{prefix}_Rib_{index}", (center[0] - width * .43, y, z), (center[0] + width * .43, y, z), .035, material_id, "arch_rib", **extras)
        add_lamp_post(f"{prefix}_Lamp_{index}", (center[0], y, z - .20), .22, **extras)


def add_road_surfaces() -> None:
    boxes: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    for road in PROFILE.get("roads", []):
        width_cells = max(1, int(road.get("width", 1)))
        for row, col in road.get("points", []):
            x, y, _ = point(row, col, .025)
            boxes.append(((x, y, .025), (CELL * (0.82 + .48 * width_cells), CELL * (0.82 + .48 * width_cells), .05)))
    strip_mesh("RoadSurfaces", boxes, "road", "road", surface="cobble")


def add_tactical_grid(cells: Iterable[tuple[int, int, float]], prefix: str, *, opacity_scale: float = 1.0) -> None:
    """A restrained grid that follows actual floors instead of the canvas."""
    boxes: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    for row, col, z in cells:
        x, y, _ = point(row, col, z + .012)
        half = CELL * .47
        thickness = .012 * opacity_scale
        boxes.extend([((x, y - half, z + .012), (CELL * .92, thickness, .018)),
                      ((x - half, y, z + .012), (thickness, CELL * .92, .018))])
    strip_mesh(prefix, boxes, "grid", "grid", cell_count=len(boxes) // 2)


def add_district_building(building: dict[str, Any]) -> None:
    row, col = building["position"]
    fw, fh = building["footprint"]["width"], building["footprint"]["height"]
    floor_policy = building.get("floor_policy", {})
    floors = int(floor_policy.get("value", floor_policy.get("minimum", 1)))
    floors = max(1, min(6, floors))
    orientation = float(building.get("orientation_deg", 0))
    building_type = str(building.get("type", "building"))
    width, depth = fw * CELL * .86, fh * CELL * .86
    if int(orientation) % 180 == 90:
        width, depth = depth, width
    height = floors * .68
    center = ((col + fw / 2) * CELL, -(row + fh / 2) * CELL, 0.0)
    building_id = str(building["id"])
    landmark = bool(building.get("is_landmark"))
    style = {
        "tower": {"wall": "stone_light", "roof": "roof", "roof_kind": "battlement", "accent": "accent"},
        "lighthouse": {"wall": "stone_light", "roof": "roof", "roof_kind": "battlement", "accent": "window"},
        "fortress": {"wall": "stone_light", "roof": "roof", "roof_kind": "battlement", "accent": "accent"},
        "warehouse": {"wall": "wall", "roof": "roof", "roof_kind": "gable", "accent": "wood"},
        "workshop": {"wall": "stone_light", "roof": "roof", "roof_kind": "gable", "accent": "wood"},
        "inn": {"wall": "stone_light", "roof": "roof", "roof_kind": "gable", "accent": "wood"},
        "tavern": {"wall": "stone_light", "roof": "roof", "roof_kind": "gable", "accent": "wood"},
        "pump_house": {"wall": "wall", "roof": "roof", "roof_kind": "flat", "accent": "metal"},
    }.get(building_type, {"wall": "wall", "roof": "roof", "roof_kind": "gable", "accent": "wood"})
    # A low plinth and four perimeter wall runs create a building volume while
    # leaving the roofline and frontage legible in the tactical view.
    box(f"Plinth_{building_id}", (center[0], center[1], .10), (width * 1.04, depth * 1.04, .20), "road", "building_plinth", building_id=building_id, building_type=building_type)
    for floor in range(floors):
        z = .18 + floor * .68
        wall_h = .42 if building_type in {"tower", "lighthouse", "fortress", "manor", "church", "temple"} else .52
        wall_t = .10
        box(f"FrontWall_{building_id}_{floor}", (center[0], center[1] - depth / 2 + wall_t / 2, z + wall_h / 2), (width, wall_t, wall_h), style["wall"], "facade", building_id=building_id, building_type=building_type, floor=floor + 1)
        box(f"BackWall_{building_id}_{floor}", (center[0], center[1] + depth / 2 - wall_t / 2, z + wall_h / 2), (width, wall_t, wall_h), style["wall"], "facade", building_id=building_id, building_type=building_type, floor=floor + 1)
        box(f"SideWallL_{building_id}_{floor}", (center[0] - width / 2 + wall_t / 2, center[1], z + wall_h / 2), (wall_t, depth * .76, wall_h), style["wall"], "facade", building_id=building_id, building_type=building_type, floor=floor + 1)
        box(f"SideWallR_{building_id}_{floor}", (center[0] + width / 2 - wall_t / 2, center[1], z + wall_h / 2), (wall_t, depth * .76, wall_h), style["wall"], "facade", building_id=building_id, building_type=building_type, floor=floor + 1)
        box(f"FloorBand_{building_id}_{floor}", (center[0], center[1], z), (width * .92, depth * .92, .08), style["accent"], "floor_band", building_id=building_id, floor=floor + 1)
        add_window_row(f"Windows_{building_id}_{floor}", (center[0], center[1] - depth / 2 - .012, z + .26), width * .70, .16, max(2, int(fw // 2)), building_id=building_id, floor=floor + 1)
        add_window_lights(f"WindowLights_{building_id}_{floor}", center[:2], width, depth, z + .28, max(2, int(fw // 2)), building_id=building_id, floor=floor + 1)
    # Entrance, loading frontage and type-neutral dressing packs.
    box(f"Door_{building_id}", (center[0], center[1] - depth / 2 - .025, .30), (max(.20, width * .18), .08, .42), "wood", "door", building_id=building_id, building_type=building_type)
    if building_type in {"warehouse", "workshop", "pump_house"}:
        box(f"LoadingAwning_{building_id}", (center[0], center[1] - depth * .60, .58), (width * .58, .28, .08), "wood", "facade_detail", building_id=building_id, role="loading")
        add_crate_stack(f"Cargo_{building_id}", (center[0] - width * .34, center[1] - depth * .68, .08), 4, building_id=building_id)
    if style["roof_kind"] == "gable":
        add_gable_roof(f"Roof_{building_id}", (center[0], center[1], height + .18), width * 1.08, depth * 1.08, max(.18, min(.48, width * .17)), style["roof"], ridge_axis="x" if int(orientation) % 180 == 0 else "y", building_id=building_id, building_type=building_type, landmark=landmark)
    elif style["roof_kind"] == "battlement":
        box(f"Roof_{building_id}", (center[0], center[1], height + .12), (width * 1.06, depth * 1.06, .16), style["roof"], "roof", building_id=building_id, building_type=building_type)
        add_battlements(f"Roof_{building_id}", center, width, depth, height + .34, style["accent"], building_id=building_id)
    else:
        box(f"Roof_{building_id}", (center[0], center[1], height + .12), (width * 1.06, depth * 1.06, .16), style["roof"], "roof", building_id=building_id, building_type=building_type)
    if landmark or building_type in {"tower", "lighthouse", "fortress"}:
        cylinder(f"LandmarkCap_{building_id}", (center[0], center[1], height + .56), max(.13, min(width, depth) * .18), .60, "accent", "landmark", building_id=building_id, role="orientation")
        add_lamp_post(f"LandmarkLamp_{building_id}", (center[0], center[1] - depth * .58, .55), .92, building_id=building_id)


def add_district() -> None:
    add_ground()
    # Fill lots before roads so the street network remains the readable top
    # layer; arbitrary polygon shapes are supplied by the planner.
    for lot in PROFILE.get("lots", []):
        polygon = lot.get("polygon", [])
        if len(polygon) >= 3:
            prism_polygon(f"LotSurface_{lot['id']}", polygon, .018, -.015, "ground", "lot_surface", lot_shape=lot.get("shape"), frontage=lot.get("frontage"))
    add_road_surfaces()
    for road in PROFILE.get("roads", []):
        points = [point(row, col, .04) for row, col in road.get("points", [])]
        # The surface is already a flat batched mesh; this thin line is only a
        # route seam.  A thick curve made streets look like pipes.
        curve(f"Road_{road['id']}", points, "trim", "road", bevel=.018, road_role=road.get("role"), traffic=road.get("traffic"))
    for lot in PROFILE.get("lots", []):
        poly = [point(row, col, .065) for row, col in lot.get("polygon", [])]
        curve(f"Lot_{lot['id']}", poly + poly[:1], "accent", "lot", bevel=.018, lot_shape=lot.get("shape"), frontage=lot.get("frontage"))
    for building in PROFILE.get("buildings", []):
        add_district_building(building)
    # Shared district packs add civic and waterfront anchors without knowing a
    # particular city name.  The planner supplies positions and flow roles.
    if "water_edge" in VISUAL.get("packs", []) or "dockside" in VISUAL.get("packs", []):
        water_y = -(HEIGHT - 3) * CELL
        water_center_x = WIDTH * CELL * .70
        box("DistrictWaterEdge", (water_center_x, water_y, .005), (WIDTH * CELL * .58, CELL * 5.0, .04), "water", "water", pack="water_edge")
        for index in range(6):
            x = water_center_x - WIDTH * CELL * .24 + index * WIDTH * CELL * .10
            cylinder(f"WaterMooring_{index}", (x, water_y + CELL * .12, .16), .055, .32, "wood", "dock_detail", pack="dockside")
            box(f"DockPlank_{index}", (x, water_y - CELL * .35, .12), (CELL * 2.2, CELL * .42, .10), "wood", "dock_detail", pack="dockside")
    for landmark in PROFILE.get("landmarks", []):
        if landmark.get("role") != "junction":
            continue
        row, col = landmark["position"]
        x, y, _ = point(row, col, .04)
        box(f"CivicPlaza_{landmark['id']}", (x, y, .045), (CELL * 5.2, CELL * 4.2, .09), "stone_light", "plaza", landmark_id=landmark["id"], role="junction")
        cylinder(f"PlazaFountain_{landmark['id']}", (x, y, .18), .20, .18, "water", "plaza_feature", landmark_id=landmark["id"])
        for side in (-1, 1):
            add_lamp_post(f"PlazaLamp_{landmark['id']}_{side}", (x + side * CELL * 1.8, y, .10), .55, landmark_id=landmark["id"])
    add_tactical_grid([(row, col, .012) for row in range(0, HEIGHT, 1) for col in range(0, WIDTH, 1)], "DistrictTacticalGrid", opacity_scale=.22)
    # Dressing is driven by the shared visual pack budget, not by a scene id.
    dressing_budget = int(VISUAL.get("dressing", {}).get("budget", 0))
    for index in range(min(24, max(0, dressing_budget))):
        row = RNG.randrange(max(1, HEIGHT))
        col = RNG.randrange(max(1, WIDTH))
        x, y, _ = point(row, col, 0)
        if index % 3 == 0:
            add_lamp_post(f"StreetLamp_{index}", (x, y, .04), .65, dressing_role="lanterns")
        elif index % 3 == 1:
            add_crate_stack(f"StreetCrates_{index}", (x, y, .04), RNG.randint(2, 5), dressing_role="crates")
        else:
            cylinder(f"MooringPost_{index}", (x, y, .12), .06, .26, "wood", "street_dressing", dressing_role="mooring_posts")


def polygon_mesh(name: str, polygon: list[list[int]], z: float, material_id: str, kind: str, **extras: Any) -> None:
    prism_polygon(name, polygon, z, z - .90, material_id, kind, **extras)


def add_outdoor() -> None:
    add_ground()
    bands = PROFILE.get("terrain", {}).get("elevation_bands", [])
    # Resolve arbitrary planner polygons into a shared height field.  Surfaces
    # stay thin; only exposed edges become cliffs, so a valley reads as terrain
    # rather than a stack of giant rectangular pillars.
    ranked_bands = sorted(bands, key=lambda band: float(band.get("elevation_ft", 0)), reverse=True)
    cells_by_band: dict[str, list[tuple[int, int, float]]] = {str(band["id"]): [] for band in bands}
    TERRAIN_HEIGHTS.clear()
    TERRAIN_COVERS.clear()
    seed = int(SCENE.get("seed", 0))
    # Domain-warp the planner's polygons before sampling them.  A straight
    # elevation polygon is a planning intent, not a literal contour line;
    # cross-axis terms make the same grammar work for valleys, tundra, karst
    # and volcanic shelves without hard-coded scene names.
    for row in range(HEIGHT):
        for col in range(WIDTH):
            warp_row = row + .5
            warp_row += math.sin((col + seed % 101) * .085 + row * .035) * 8.2
            warp_row += math.sin((row + col + seed % 37) * .17) * 2.15
            warp_row += math.cos((row - col + seed % 53) * .075) * 1.65
            warp_col = col + .5
            warp_col += math.cos((row + seed % 79) * .080 + col * .028) * 7.0
            warp_col += math.cos((row - col + seed % 43) * .16) * 1.85
            warp_col += math.sin((row + col + seed % 67) * .065) * 1.55
            selected = next((band for band in ranked_bands if point_in_polygon(warp_row, warp_col, band.get("polygon", []))), None)
            if selected is None:
                selected = next((band for band in ranked_bands if point_in_polygon(row + .5, col + .5, band.get("polygon", []))), None)
            if not selected:
                continue
            base_z = float(selected.get("elevation_ft", 0)) * Z_SCALE
            # Low-frequency deterministic relief breaks the unnaturally straight
            # planner bands without changing their intended elevation tiers.
            cover = str(selected.get("cover", ""))
            relief = 0.0 if cover == "shallow_water" else (
                math.sin((col + seed % 97) * .105 + row * .023)
                + math.cos((row + seed % 83) * .082 - col * .019)
                + math.sin((row + col + seed % 31) * .19) * .45
            ) * .032
            # Rock shelves and talus catch more light and should not look like
            # perfectly level coloured carpets from the far camera.
            if cover in {"exposed_rock", "broken_boulder"}:
                relief += math.sin((row - col + seed % 47) * .14) * .025
            top_z = base_z + relief
            cells_by_band[str(selected["id"])].append((row, col, top_z))
            TERRAIN_HEIGHTS[(row, col)] = top_z
            TERRAIN_COVERS[(row, col)] = cover
    # Ease only the cells adjacent to a tier boundary.  This turns a hard
    # stack of rectangular shelves into a readable tactical slope while
    # retaining clear height differences in the far view.
    raw_heights = dict(TERRAIN_HEIGHTS)
    for (row, col), top_z in raw_heights.items():
        neighbours = [raw_heights.get((row + dr, col + dc)) for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))]
        neighbours = [value for value in neighbours if value is not None]
        if not neighbours:
            continue
        average = sum(neighbours) / len(neighbours)
        delta = average - top_z
        if abs(delta) > .12:
            TERRAIN_HEIGHTS[(row, col)] = top_z + delta * .34
    cover_material = {
        "exposed_rock": "stone_light", "sparse_pine": "ground", "broken_boulder": "wall",
        "wet_grass": "green", "shallow_water": "water", "pine_forest": "green",
    }
    for band in bands:
        band_id = str(band["id"])
        cover = str(band.get("cover", ""))
        terrain_cell_mesh(f"TerrainBand_{band_id}", cells_by_band.get(band_id, []), cover_material.get(cover, "ground"), elevation_ft=band.get("elevation_ft"), cover=cover)
    # Exposed height changes are shared across all outdoor themes.  Emit one
    # wall mesh per material so cliffs remain cheap even on large maps.
    cliff_groups: dict[str, list[tuple[float, float, tuple[float, float], tuple[float, float]]]] = defaultdict(list)
    for (row, col), top_z in TERRAIN_HEIGHTS.items():
        for dr, dc, side in ((-1, 0, "north"), (1, 0, "south"), (0, -1, "west"), (0, 1, "east")):
            neighbour = TERRAIN_HEIGHTS.get((row + dr, col + dc), top_z - .72)
            if top_z - neighbour < .20:
                continue
            x, y, _ = point(row, col, top_z)
            if side == "north":
                p1, p2 = (x - CELL * .48, y - CELL * .48), (x + CELL * .48, y - CELL * .48)
            elif side == "south":
                p1, p2 = (x + CELL * .48, y + CELL * .48), (x - CELL * .48, y + CELL * .48)
            elif side == "west":
                p1, p2 = (x - CELL * .48, y + CELL * .48), (x - CELL * .48, y - CELL * .48)
            else:
                p1, p2 = (x + CELL * .48, y - CELL * .48), (x + CELL * .48, y + CELL * .48)
            cliff_groups["stone_light" if TERRAIN_COVERS.get((row, col)) in {"exposed_rock", "broken_boulder"} else "wall"].append((neighbour, top_z, p1, p2))
    for material_id, walls in cliff_groups.items():
        terrain_cliff_mesh(f"TerrainCliffs_{material_id}", walls, material_id, wall_count=len(walls), pick_role="height_boundary")
    grid_cells = [(row, col, z) for (row, col), z in TERRAIN_HEIGHTS.items() if TERRAIN_COVERS.get((row, col)) != "shallow_water"]
    # Keep the square grid available for tactical play, but let the far view
    # read rock, vegetation and water first.  Buildings retain their stronger
    # deck grid because it is part of the architectural grammar.
    add_tactical_grid(grid_cells, "OutdoorTacticalGrid", opacity_scale=.32)
    for water in PROFILE.get("terrain", {}).get("watercourses", []):
        points = []
        point_count = max(1, len(water.get("points", [])) - 1)
        source = float(water.get("source_elevation_ft", 0))
        mouth = float(water.get("mouth_elevation_ft", 0))
        for index, (row, col) in enumerate(water.get("points", [])):
            z = (source + (mouth - source) * index / point_count) * Z_SCALE + .08
            points.append(point(row, col, z))
        width = max(CELL * 1.25, int(water.get("width_cells", 3)) * CELL * .72)
        # The ribbon is the playable river surface.  Keep a fine centreline
        # only as flow evidence; the old all-tube representation looked like a
        # string of pipes at overview scale.
        ribbon_mesh(f"Water_{water['id']}", points, width, "water", "watercourse", width_cells=water.get("width_cells", 3), source_elevation_ft=source, mouth_elevation_ft=mouth)
        bank_left: list[tuple[float, float, float]] = []
        bank_right: list[tuple[float, float, float]] = []
        for index, (x, y, z) in enumerate(points):
            before = points[max(0, index - 1)]
            after = points[min(len(points) - 1, index + 1)]
            dx, dy = after[0] - before[0], after[1] - before[1]
            length = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / length, dx / length
            bank_left.append((x + nx * width * .48, y + ny * width * .48, z + .028))
            bank_right.append((x - nx * width * .48, y - ny * width * .48, z + .032))
        curve(f"WaterBankL_{water['id']}", bank_left, "water_edge", "bank", bevel=.028, side="left", water_id=water["id"])
        curve(f"WaterBankR_{water['id']}", bank_right, "water_edge", "bank", bevel=.028, side="right", water_id=water["id"])
        curve(f"WaterFlow_{water['id']}", points, "foam", "flow_detail", bevel=.018, water_id=water["id"])
        for index, (x, y, z) in enumerate(points[::max(1, len(points) // 8)]):
            cylinder(f"Foam_{water['id']}_{index}", (x, y, z + .045), .045, .022, "foam", "flow_detail", water_id=water["id"])
        # A large elevation drop should read as a waterfall, even when the
        # planner gives a long interpolated profile rather than explicit drop
        # points.  The curtain is placed on the first steep third so it becomes
        # a landmark instead of a generic blue line.
        if abs(source - mouth) >= 18 and len(points) >= 4:
            drop_index = max(1, min(len(points) - 2, len(points) // 3))
            wx, wy, wz = points[drop_index]
            before, after = points[drop_index - 1], points[drop_index + 1]
            angle = math.atan2(after[1] - before[1], after[0] - before[0])
            curtain_height = max(.55, abs(source - mouth) * Z_SCALE * .22)
            curtain = box(f"WaterfallCurtain_{water['id']}", (wx, wy, wz + curtain_height * .42), (width * 1.15, .10, curtain_height), "water", "waterfall", water_id=water["id"], drop_ft=abs(source - mouth) / 3)
            curtain.rotation_euler[2] = angle
            cylinder(f"WaterfallPool_{water['id']}", (wx, wy, wz + .035), width * .36, .06, "foam", "flow_detail", water_id=water["id"], role="fall_pool")
        for index, (before, after) in enumerate(zip(points, points[1:])):
            if abs(before[2] - after[2]) > .16:
                cylinder_between(f"Waterfall_{water['id']}_{index}", before, after, .10, "water", "waterfall", water_id=water["id"])
    for cliff in PROFILE.get("terrain", {}).get("cliffs", []):
        edge = cliff.get("edge", [])
        for index, (start, end) in enumerate(zip(edge, edge[1:])):
            r1, c1 = start
            r2, c2 = end
            a = point(r1, c1, float(cliff.get("height_ft", 12)) * Z_SCALE / 2)
            b = point(r2, c2, float(cliff.get("height_ft", 12)) * Z_SCALE / 2)
            length = max(.10, math.dist(a[:2], b[:2]))
            center = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, a[2])
            wall = box(f"Cliff_{cliff['id']}_{index}", center, (length, .10, float(cliff.get("height_ft", 12)) * Z_SCALE), "wall", "cliff", cliff_id=cliff["id"], hazard=cliff.get("hazard"))
            wall.rotation_euler[2] = math.atan2(b[1] - a[1], b[0] - a[0])
    for route in PROFILE.get("routes", []):
        route_points = route.get("points", [])
        profile = [float(value) for value in route.get("elevation_profile_ft", [])]
        if len(profile) <= 1:
            elevations = [profile[0] if profile else 0.0] * len(route_points)
        else:
            elevations = []
            for index in range(len(route_points)):
                position = index / max(1, len(route_points) - 1) * (len(profile) - 1)
                left = min(len(profile) - 1, int(position))
                right = min(len(profile) - 1, left + 1)
                mix = position - left
                elevations.append(profile[left] * (1 - mix) + profile[right] * mix)
        points = [point(row, col, elevation * Z_SCALE + .14) for (row, col), elevation in zip(route_points, elevations)]
        if route.get("role") == "primary":
            # A route needs a physical surface for tactical play, not only an
            # emissive line.  Width is derived from traversal and remains
            # reusable for a ridge trail, cavern ledge or forest track.
            ribbon_mesh(f"TrailSurface_{route['id']}", [(x, y, z - .045) for x, y, z in points], CELL * .52, "sand", "trail_surface", route_role=route.get("role"), traversal=route.get("traversal"))
            for index, (before, after) in enumerate(zip(points, points[1:])):
                if abs(before[2] - after[2]) > .07 and index % 3 == 0:
                    midpoint = tuple((before[axis] + after[axis]) / 2 for axis in range(3))
                    step = box(f"TrailStep_{route['id']}_{index}", (midpoint[0], midpoint[1], midpoint[2]), (CELL * .48, CELL * .30, .045), "stone_light", "stair", route_id=route["id"], step_index=index)
                    step.rotation_euler[2] = math.atan2(after[1] - before[1], after[0] - before[0])
        curve(f"Route_{route['id']}", points, "secret" if route.get("role") == "secret" else "accent", "route", bevel=.028, route_role=route.get("role"), risk=route.get("risk"), visibility=route.get("visibility", "public"))
        if route.get("role") == "primary" and len(points) > 4:
            for index, (x, y, z) in enumerate(points[::max(1, len(points) // 6)]):
                add_lamp_post(f"TrailMarker_{route['id']}_{index}", (x, y, z), .38, route_id=route["id"], dressing_role="signage")
    for platform in PROFILE.get("tactical_platforms", []):
        row, col = platform["position"]
        z = float(platform.get("elevation_ft", 0)) * Z_SCALE + .12
        px, py, _ = point(row, col, z)
        box(f"Platform_{platform['id']}", (px, py, z), (CELL * 3.2, CELL * 2.5, .20), "feature", "tactical_platform", tactical_role=platform.get("tactical_role"), platform_kind=platform.get("kind"))
        for side in (-1, 1):
            cylinder_between(f"PlatformRail_{platform['id']}_{side}", (px - CELL * 1.2, py + side * CELL * 1.2, z + .08), (px + CELL * 1.2, py + side * CELL * 1.2, z + .08), .025, "metal", "railing", platform_id=platform["id"])
        if platform.get("kind") == "cave_mouth":
            for side in (-1, 1):
                cylinder(f"CaveMouthPillar_{platform['id']}_{side}", (px + side * CELL * 1.0, py, z + .48), .16, .95, "wall", "cave", platform_id=platform["id"])
            add_gable_roof(f"CaveMouthArch_{platform['id']}", (px, py, z + .80), CELL * 2.5, CELL * 1.4, .55, "wall", ridge_axis="x", platform_id=platform["id"])
    # Feature packs provide a generic visual realization for planners that
    # describe a cave, overlook or crossing without an explicit platform.
    platform_ids = {str(item.get("id")) for item in PROFILE.get("tactical_platforms", [])}
    for feature in PROFILE.get("terrain", {}).get("features", []):
        feature_id = str(feature.get("id", "feature"))
        if feature_id in platform_ids:
            continue
        row, col = feature.get("position", [0, 0])
        elevation = float(feature.get("elevation_ft", TERRAIN_HEIGHTS.get((int(row), int(col)), 0) / Z_SCALE))
        z = elevation * Z_SCALE + .12
        px, py, _ = point(row, col, z)
        kind = str(feature.get("kind", "feature"))
        if kind == "cave_mouth":
            box(f"FeatureCaveFloor_{feature_id}", (px, py, z), (CELL * 3.4, CELL * 2.0, .16), "dark", "cave", feature_id=feature_id, tactical_role=feature.get("tactical_role"))
            for side in (-1, 1):
                cylinder(f"FeatureCavePillar_{feature_id}_{side}", (px + side * CELL * 1.2, py, z + .48), .16, .92, "stone_light", "cave", feature_id=feature_id)
            add_gable_roof(f"FeatureCaveArch_{feature_id}", (px, py, z + .84), CELL * 3.0, CELL * 1.5, .68, "stone_light", ridge_axis="x", feature_id=feature_id)
        elif kind in {"elevated_platform", "overlook"}:
            box(f"FeatureOverlook_{feature_id}", (px, py, z), (CELL * 3.2, CELL * 2.6, .18), "feature", "tactical_platform", feature_id=feature_id, tactical_role=feature.get("tactical_role"))
            cylinder_between(f"FeatureOverlookRail_{feature_id}", (px - CELL * 1.2, py - CELL * 1.0, z + .16), (px + CELL * 1.2, py - CELL * 1.0, z + .16), .025, "metal", "railing", feature_id=feature_id)
        elif kind in {"crossing", "ford"}:
            for step in range(-2, 3):
                box(f"FeatureFordStone_{feature_id}_{step}", (px + step * CELL * .55, py, z + .06), (CELL * .42, CELL * .70, .12), "stone_light", "crossing", feature_id=feature_id)
    for landmark in PROFILE.get("landmarks", []):
        row, col = landmark["position"]
        z = float(landmark.get("elevation_ft", 18)) * Z_SCALE + .25
        x, y, _ = point(row, col, z)
        cylinder(f"Landmark_{landmark['id']}", (x, y, z + .5), .30, 1.0, "accent", "landmark", landmark_id=landmark["id"], role=landmark.get("role"))
        cylinder(f"LandmarkGlow_{landmark['id']}", (x, y, z + 1.08), .12, .18, "feature", "landmark_detail", landmark_id=landmark["id"])
    # Seeded dressing is anchored to the resolved height field, never to a
    # random world Z (which previously produced floating trees and rocks).
    candidates = list(TERRAIN_HEIGHTS)
    RNG.shuffle(candidates)
    dressing_count = max(120, int(VISUAL.get("dressing", {}).get("budget", 0)) * 16)
    for index, (row, col) in enumerate(candidates[:dressing_count]):
        cover = TERRAIN_COVERS.get((row, col), "")
        if cover == "shallow_water":
            continue
        x, y, _ = point(row, col, TERRAIN_HEIGHTS[(row, col)] + .04)
        z = TERRAIN_HEIGHTS[(row, col)] + .12
        if cover in {"sparse_pine", "pine_forest"} and index % 2 == 0:
            cylinder(f"PineTrunk_{index}", (x, y, z + .28), .035, .55, "wood", "vegetation", dressing_role="pines")
            bpy.ops.mesh.primitive_cone_add(vertices=7, radius1=.22, radius2=.025, depth=.65, location=(x, y, z + .66))
            tree = bpy.context.object
            tree.name = f"PineCrown_{index}"
            tree.data.materials.append(MATERIALS["green"])
            tag(tree, "vegetation", "green", dressing_role="pines")
        elif cover in {"exposed_rock", "broken_boulder"} or index % 3 == 0:
            cylinder(f"Boulder_{index}", (x, y, z), RNG.uniform(.10, .24), RNG.uniform(.18, .42), "stone_light", "vegetation", dressing_role="boulders")
        elif cover == "wet_grass" and index % 2 == 0:
            cylinder(f"Reed_{index}", (x, y, z + .18), .025, .36, "green", "vegetation", dressing_role="reeds")
        else:
            cylinder(f"Shrub_{index}", (x, y, z), RNG.uniform(.07, .14), RNG.uniform(.18, .38), "green", "vegetation", dressing_role="shrubs")


def add_building_detail_pack(building_type: str, center: tuple[float, float], width: float, depth: float, floors: int, spacing: float, top_z: float, building_id: str) -> None:
    """Resolve reusable architectural packs from the building recipe.

    The factory can name new building families without forcing the renderer to
    know a scene id.  These modules make a tower, manor, civic hall, sewer or
    mine read as its own structure while preserving the same floor/room/grid
    contract used by the pump house.
    """
    cx, cy = center
    if building_type in {"tower", "lighthouse", "fortress"}:
        for floor in range(floors):
            z = .25 + floor * spacing
            cylinder(f"TowerCore_{floor}", (cx, cy, z + .22), .16, .42, "stone_light", "support", building_id=building_id, floor=floor + 1, role="central_shaft")
            for side in (-1, 1):
                cylinder_between(f"TowerLandingRail_{floor}_{side}", (cx - width * .28, cy + side * depth * .18, z + .20), (cx + width * .28, cy + side * depth * .18, z + .20), .022, "metal", "railing", building_id=building_id, floor=floor + 1)
            # A visible landing slab and a pair of vertical windows make the
            # staircase legible even when the camera is not aligned to the
            # stair run.
            box(f"TowerLanding_{building_id}_{floor}", (cx, cy - depth * .24, z + .17), (width * .54, depth * .22, .08), "wood", "platform", building_id=building_id, floor=floor + 1)
            add_lamp_post(f"TowerLamp_{building_id}_{floor}", (cx, cy - depth * .34, z + .18), .30, building_id=building_id, floor=floor + 1)
        cylinder(f"TowerBell_{building_id}", (cx, cy, top_z + .34), .20, .30, "accent", "landmark", building_id=building_id, role="lantern_room" if building_type == "lighthouse" else "bell_chamber")
        for side in (-1, 1):
            box(f"TowerButtress_{building_id}_{side}", (cx + side * width * .44, cy, top_z * .50), (.16, depth * .44, top_z), "stone_light", "buttress", building_id=building_id)
        if building_type == "lighthouse":
            cylinder(f"LighthouseBeacon_{building_id}", (cx, cy, top_z + .60), .08, .12, "window", "landmark_detail", building_id=building_id, role="beacon")
            add_battlements(f"LighthouseLantern_{building_id}", (cx, cy, top_z + .66), width * .62, depth * .62, top_z + .80, "metal", building_id=building_id)
            # A tapered lantern roof and a continuous outer gallery turn the
            # generic vertical stack into a recognizable coastal landmark.
            cone(f"LighthouseRoof_{building_id}", (cx, cy, top_z + 1.02), width * .34, .04, .50, "roof", "roof", vertices=12, building_id=building_id, role="lantern_roof")
            for side in (-1, 1):
                cylinder_between(f"LighthouseGalleryRail_{building_id}_{side}", (cx - width * .36, cy + side * depth * .35, top_z + .72), (cx + width * .36, cy + side * depth * .35, top_z + .72), .024, "metal", "railing", building_id=building_id, role="gallery")
        if building_type == "fortress":
            for side in (-1, 1):
                box(f"FortressWallWalk_{building_id}_{side}", (cx + side * width * .35, cy, top_z + .10), (width * .20, depth * .86, .12), "stone_light", "wall_walk", building_id=building_id)
            # Four corner keeps and a heavier gatehouse provide a defensive
            # silhouette without sealing the cutaway floors.
            for corner, (dx, dy) in enumerate(((-.42, -.42), (.42, -.42), (-.42, .42), (.42, .42))):
                keep_h = top_z + .62 + (corner % 2) * .16
                cylinder(f"FortressKeep_{building_id}_{corner}", (cx + dx * width, cy + dy * depth, keep_h / 2), width * .12, keep_h, "stone_light", "keep", vertices=10, building_id=building_id, role="corner_tower")
                add_battlements(f"FortressKeepCap_{building_id}_{corner}", (cx + dx * width, cy + dy * depth, keep_h), width * .12, depth * .12, keep_h + .12, "stone_light", building_id=building_id)
            box(f"FortressGate_{building_id}", (cx, cy - depth * .48, .64), (width * .46, .12, .88), "stone_light", "gate", building_id=building_id, role="gatehouse")
            box(f"FortressGateOpening_{building_id}", (cx, cy - depth * .55, .58), (width * .18, .035, .58), "dark", "gate", building_id=building_id, role="portcullis")
    elif building_type in {"church", "temple"}:
        # Processional axis + side aisles remain legible from above and give
        # the same grammar enough identity for chapels, crypts and sanctums.
        box(f"Nave_{building_id}", (cx, cy, .27), (width * .42, depth * .72, .10), "road", "nave", building_id=building_id)
        for side in (-1, 1):
            for index in range(max(2, floors + 1)):
                py = cy - depth * .32 + index * depth * .22
                cylinder(f"AisleColumn_{building_id}_{side}_{index}", (cx + side * width * .28, py, .52), .075, 1.0, "stone_light", "support", building_id=building_id, role="aisle")
        box(f"Altar_{building_id}", (cx, cy + depth * .28, .38), (width * .30, depth * .16, .24), "stone_light", "altar", building_id=building_id)
        box(f"CryptHatch_{building_id}", (cx, cy - depth * .28, .20), (width * .22, depth * .15, .06), "dark", "secret_detail", building_id=building_id, role="crypt")
        # A raised nave, clerestory lights and a side bell tower are shared
        # by churches and temples but remain independent of any scene name.
        # Keep the nave identity as a slim ridge rather than a solid roof: the
        # viewer is a cutaway tactical scene and must still see the upper
        # rooms, stairs and altar from above.
        box(f"NaveSpine_{building_id}", (cx, cy, top_z + .20), (.12, depth * .84, .18), "roof", "roof_detail", building_id=building_id, role="nave_ridge")
        for floor in range(floors):
            z = .35 + floor * spacing
            for side in (-1, 1):
                for index in range(3):
                    py = cy - depth * .28 + index * depth * .28
                    cylinder(f"Clerestory_{building_id}_{floor}_{side}_{index}", (cx + side * width * .20, py, z + .40), .045, .32, "window", "window_detail", building_id=building_id, floor=floor + 1)
        bell_x = cx + width * .38
        box(f"BellTower_{building_id}", (bell_x, cy + depth * .20, top_z * .48), (width * .22, depth * .22, top_z * .94), "wall", "bell_tower", building_id=building_id)
        cone(f"BellRoof_{building_id}", (bell_x, cy + depth * .20, top_z + .58), width * .18, .02, .42, "roof", "roof", vertices=4, building_id=building_id, role="bell_roof")
        cone(f"SanctumSpire_{building_id}", (cx, cy + depth * .28, top_z + .84), .12, .015, .62, "accent", "landmark", vertices=8, building_id=building_id, role="sanctum_spire")
        if building_type == "temple":
            for side in (-1, 1):
                box(f"TempleProcessional_{building_id}_{side}", (cx + side * width * .32, cy - depth * .04, .34), (width * .12, depth * .62, .08), "stone_light", "aisle", building_id=building_id, role="side_aisle")
        else:
            box(f"ChurchRoseWindow_{building_id}", (cx, cy - depth * .49, top_z * .48), (width * .22, .04, width * .22), "window", "window_detail", building_id=building_id, role="rose_window")
        for floor in range(floors):
            z = .25 + floor * spacing
            for index in range(4):
                py = cy - depth * .34 + index * depth * .23
                cylinder(f"ProcessionalPillar_{building_id}_{floor}_{index}", (cx, py, z + .30), .055, .56, "stone_light", "support", building_id=building_id, floor=floor + 1, role="processional_pillar")
            box(f"SanctumRunner_{building_id}_{floor}", (cx, cy + depth * .10, z + .13), (width * .12, depth * .46, .04), "accent", "floor_dressing", building_id=building_id, floor=floor + 1, role="processional_runner")
    elif building_type == "manor":
        for floor in range(floors):
            z = .25 + floor * spacing
            box(f"ManorHall_{building_id}_{floor}", (cx, cy, z + .10), (width * .18, depth * .66, .08), "wood", "room_function", building_id=building_id, floor=floor + 1, role="gallery")
            box(f"ManorWing_{building_id}_{floor}", (cx - width * .28, cy + depth * .08, z + .10), (width * .26, depth * .18, .08), "feature", "room_function", building_id=building_id, floor=floor + 1, role="salon")
            cylinder(f"ManorFireplace_{building_id}_{floor}", (cx + width * .28, cy + depth * .16, z + .28), .13, .30, "accent", "equipment", building_id=building_id, floor=floor + 1, role="fireplace")
        box(f"ManorCourtyard_{building_id}", (cx, cy - depth * .30, .20), (width * .42, depth * .25, .06), "green", "courtyard", building_id=building_id)
        for side in (-1, 1):
            cylinder(f"ManorGatePost_{building_id}_{side}", (cx + side * width * .34, cy - depth * .45, .42), .09, .78, "stone_light", "support", building_id=building_id, role="formal_entry")
        # An L-shaped service wing prevents the manor from reading as a plain
        # rectangular stack and creates a courtyard route for encounters.
        box(f"ManorServiceWing_{building_id}", (cx - width * .34, cy + depth * .18, .34), (width * .28, depth * .62, .16), "wall", "wing", building_id=building_id, role="service")
        box(f"ManorCourtyardGate_{building_id}", (cx + width * .30, cy - depth * .30, .44), (.10, depth * .24, .72), "stone_light", "gate", building_id=building_id, role="courtyard")
        add_lamp_post(f"ManorCourtyardLamp_{building_id}", (cx, cy - depth * .30, .16), .42, building_id=building_id)
    elif building_type in {"library", "barracks", "tavern", "inn"}:
        for floor in range(floors):
            z = .25 + floor * spacing
            add_room_shell(f"CivicRoom_{building_id}_{floor}", (cx, cy), width * .62, depth * .70, z, "wall", building_id=building_id, floor=floor + 1, role=building_type)
            if building_type == "library":
                for shelf in range(3):
                    box(f"LibraryShelf_{building_id}_{floor}_{shelf}", (cx - width * .24 + shelf * width * .24, cy + depth * .20, z + .24), (width * .16, .07, .42), "wood", "furniture", building_id=building_id, floor=floor + 1, role="archive")
            elif building_type == "barracks":
                for bunk in range(2):
                    box(f"Bunk_{building_id}_{floor}_{bunk}", (cx - width * .18 + bunk * width * .36, cy - depth * .18, z + .14), (width * .22, depth * .14, .11), "wood", "furniture", building_id=building_id, floor=floor + 1, role="quarters")
                box(f"ArmoryRack_{building_id}_{floor}", (cx + width * .26, cy + depth * .20, z + .30), (width * .12, .08, .46), "wood", "furniture", building_id=building_id, floor=floor + 1, role="weapon_rack")
                for spear in range(3):
                    cylinder_between(f"Spear_{building_id}_{floor}_{spear}", (cx + width * (.20 + spear * .06), cy + depth * .20, z + .34), (cx + width * (.20 + spear * .06), cy + depth * .20, z + .72), .018, "metal", "equipment", building_id=building_id, floor=floor + 1, role="spear")
            else:
                box(f"CivicTable_{building_id}_{floor}", (cx, cy, z + .22), (width * .34, depth * .16, .12), "wood", "furniture", building_id=building_id, floor=floor + 1, role="public")
                add_lamp_post(f"CivicLamp_{building_id}_{floor}", (cx, cy - depth * .22, z + .20), .36, building_id=building_id, floor=floor + 1)
                for barrel in range(2):
                    cylinder(f"CivicBarrel_{building_id}_{floor}_{barrel}", (cx - width * .28 + barrel * width * .18, cy + depth * .24, z + .18), .10, .26, "wood", "furniture", vertices=10, building_id=building_id, floor=floor + 1, role="barrel")
                if building_type == "tavern":
                    box(f"TavernStage_{building_id}_{floor}", (cx + width * .24, cy + depth * .26, z + .18), (width * .26, depth * .15, .12), "wood", "platform", building_id=building_id, floor=floor + 1, role="stage")
                else:
                    box(f"InnReception_{building_id}_{floor}", (cx + width * .24, cy + depth * .26, z + .18), (width * .22, depth * .12, .12), "wood", "furniture", building_id=building_id, floor=floor + 1, role="reception")
    elif building_type in {"sewer", "sewer_main", "drainage"}:
        channel_x = cx - width * .10
        box(f"SewerChannel_{building_id}", (channel_x, cy, .18), (width * .30, depth * .80, .10), "water", "water_channel", building_id=building_id, role="waste_flow")
        for side in (-1, 1):
            box(f"SewerWalkway_{building_id}_{side}", (cx + side * width * .28, cy, .22), (width * .22, depth * .78, .08), "stone_light", "walkway", building_id=building_id)
        for index in range(max(2, floors + 1)):
            py = cy - depth * .32 + index * depth * .24
            cylinder_between(f"SewerPipe_{building_id}_{index}", (cx + width * .25, py, .48), (cx + width * .25, py + depth * .18, .48), .055, "metal", "pipe", building_id=building_id)
            box(f"SewerGrate_{building_id}_{index}", (cx - width * .10, py, .25), (width * .22, .12, .03), "metal", "grate", building_id=building_id)
        add_arch_ribs(f"SewerArch_{building_id}", (cx, cy), width, depth, .78, max(3, floors + 2), material_id="stone_light", building_id=building_id, role="culvert")
        for side in (-1, 1):
            box(f"SewerBranch_{building_id}_{side}", (cx + side * width * .34, cy + depth * .12, .32), (width * .20, depth * .28, .14), "dark", "culvert_branch", building_id=building_id, role="side_route")
            cylinder(f"SewerLadder_{building_id}_{side}", (cx + side * width * .34, cy - depth * .14, .62), .06, .78, "metal", "ladder", building_id=building_id, role="inspection")
    elif building_type == "cavern":
        # The same cutaway building contract can host a natural chamber: dark
        # ledges, a pool and a rope bridge stand in for straight room walls.
        box(f"CavernPool_{building_id}", (cx + width * .20, cy, .20), (width * .34, depth * .40, .06), "water", "water", building_id=building_id, role="underground_lake")
        for index, (dx, dy, sx, sy, sz) in enumerate(((-.42, .36, .25, .22, .85), (-.28, .12, .18, .16, .62), (.34, .28, .22, .18, .74), (.44, -.22, .16, .20, .58), (-.06, .43, .14, .16, .52))):
            ico_rock(f"CavernWallRock_{building_id}_{index}", (cx + dx * width, cy + dy * depth, sz * .42), (sx, sy, sz), building_id=building_id, role="cave_wall")
            cone(f"CavernStalactite_{building_id}_{index}", (cx + dx * width, cy + dy * depth, top_z - .18), sx * .54, .025, max(.24, sz * .75), "stone_light", "rock_formation", vertices=8, building_id=building_id, role="stalactite")
        cylinder_between(f"CavernBridge_{building_id}", (cx - width * .34, cy - depth * .10, .55), (cx + width * .20, cy - depth * .10, .55), .045, "wood", "bridge", building_id=building_id)
        box(f"CavernLedge_{building_id}", (cx - width * .20, cy + depth * .26, .92), (width * .42, depth * .20, .10), "stone_light", "platform", building_id=building_id, role="upper_ledge")
        cylinder_between(f"CavernRopeRail_{building_id}", (cx - width * .40, cy - depth * .10, .72), (cx + width * .25, cy - depth * .10, .72), .022, "wood", "railing", building_id=building_id)
    elif building_type == "ruin":
        # Ruins are intentionally incomplete: offset wall fragments and
        # collapsed slabs create negative space rather than another intact
        # rectangular building.
        for index, (dx, dy, sx, sy, sz, rot) in enumerate(((-.40, .28, .16, .72, 1.10, 0), (.38, .28, .18, .54, .82, 0), (-.25, -.38, .62, .14, .54, 12), (.20, -.12, .42, .12, .30, -18))):
            obj = box(f"RuinWall_{building_id}_{index}", (cx + dx * width, cy + dy * depth, sz / 2), (sx * width, sy * depth, sz), "stone_light", "ruin_wall", building_id=building_id, role="broken_wall")
            obj.rotation_euler[2] = math.radians(rot)
        for index, (dx, dy, scale) in enumerate(((-.30, -.26, .16), (.08, -.34, .12), (.36, .16, .14), (-.08, .34, .10), (.25, -.02, .08))):
            ico_rock(f"RuinRubble_{building_id}_{index}", (cx + dx * width, cy + dy * depth, scale * .55), (scale, scale * .72, scale * .55), building_id=building_id, role="collapsed_masonry")
        box(f"RuinFoundation_{building_id}", (cx, cy, .17), (width * .84, depth * .78, .08), "stone_light", "foundation", building_id=building_id, role="exposed_foundation")
        cylinder_between(f"RuinClimbBeam_{building_id}", (cx - width * .30, cy - depth * .22, .44), (cx + width * .20, cy + depth * .16, 1.08), .045, "wood", "bridge", building_id=building_id, role="climb_route")
        for index, (dx, dy, length, angle) in enumerate(((-.34, -.06, .52, 0), (-.10, .20, .44, 24), (.26, -.26, .34, -18), (.40, .24, .28, 12), (-.24, .40, .24, -8))):
            start_x, start_y = cx + dx * width, cy + dy * depth
            end_dx, end_dy = rotated_offset(length, 0, angle)
            cylinder_between(f"RuinTimber_{building_id}_{index}", (start_x, start_y, .32 + index * .05), (start_x + end_dx, start_y + end_dy, .52 + index * .05), .035, "wood", "support", building_id=building_id, role="collapsed_timber")
    elif building_type == "workshop":
        for floor in range(floors):
            z = .25 + floor * spacing
            box(f"ForgeBed_{building_id}_{floor}", (cx - width * .18, cy + depth * .10, z + .19), (width * .24, depth * .20, .16), "stone_light", "equipment", building_id=building_id, floor=floor + 1, role="forge")
            cone(f"ForgeFlue_{building_id}_{floor}", (cx - width * .18, cy + depth * .10, z + .48), .10, .07, .32, "metal", "equipment", vertices=8, building_id=building_id, floor=floor + 1, role="chimney")
            add_crate_stack(f"WorkshopMaterials_{building_id}_{floor}", (cx + width * .22, cy - depth * .20, z + .10), 3, building_id=building_id, floor=floor + 1, dressing_role="materials")
        cylinder_between(f"WorkshopHoist_{building_id}", (cx + width * .28, cy - depth * .25, .30), (cx + width * .28, cy - depth * .25, top_z + .10), .035, "metal", "equipment", building_id=building_id, role="hoist")
        box(f"WorkshopBeam_{building_id}", (cx + width * .28, cy - depth * .25, top_z + .14), (width * .46, .10, .10), "wood", "support", building_id=building_id, role="hoist_beam")
        for index in range(4):
            x = cx - width * .30 + index * width * .20
            cylinder(f"WorkshopTool_{building_id}_{index}", (x, cy - depth * .28, .40), .035, .28, "metal", "equipment", building_id=building_id, role="hanging_tool")
            box(f"WorkshopBench_{building_id}_{index}", (x, cy + depth * .24, .22), (width * .15, .12, .12), "wood", "furniture", building_id=building_id, role="workbench")
    elif building_type == "warehouse":
        for floor in range(floors):
            z = .25 + floor * spacing
            for shelf in range(3):
                box(f"WarehouseRack_{building_id}_{floor}_{shelf}", (cx - width * .28 + shelf * width * .28, cy + depth * .16, z + .28), (width * .16, .10, .52), "wood", "furniture", building_id=building_id, floor=floor + 1, role="cargo_rack")
            add_crate_stack(f"WarehouseCargo_{building_id}_{floor}", (cx + width * .20, cy - depth * .20, z + .10), 4, building_id=building_id, floor=floor + 1, dressing_role="cargo")
        box(f"WarehouseLoadingDock_{building_id}", (cx, cy - depth * .50, .28), (width * .58, .24, .16), "wood", "platform", building_id=building_id, role="loading_dock")
        cylinder_between(f"WarehouseCrane_{building_id}", (cx + width * .30, cy - depth * .42, .38), (cx + width * .30, cy - depth * .42, top_z + .30), .04, "metal", "equipment", building_id=building_id, role="gantry")
        for index in range(4):
            x = cx - width * .30 + index * width * .20
            cylinder_between(f"WarehouseHoist_{building_id}_{index}", (x, cy - depth * .36, .36), (x, cy - depth * .36, top_z + .10), .025, "metal", "equipment", building_id=building_id, role="cargo_hoist")
            add_lamp_post(f"WarehouseLamp_{building_id}_{index}", (x, cy - depth * .44, .24), .28, building_id=building_id, dressing_role="loading_lamp")
    elif building_type == "mine":
        box(f"MineShaft_{building_id}", (cx, cy, .18), (width * .30, depth * .30, .08), "dark", "shaft", building_id=building_id)
        for side in (-1, 1):
            cylinder(f"MineSupport_{building_id}_{side}", (cx + side * width * .32, cy, .60), .08, 1.2, "wood", "support", building_id=building_id)
        add_gable_roof(f"MineTimber_{building_id}", (cx, cy - depth * .40, .78), width * .78, depth * .26, .30, "wood", ridge_axis="x", building_id=building_id, role="adit")
        for index in range(5):
            cylinder(f"OrePile_{building_id}_{index}", (cx + (index - 2) * width * .13, cy + depth * .20, .27), .12, .20, "stone_light", "rock", building_id=building_id, role="ore")


def add_building() -> None:
    add_ground()
    building = PROFILE.get("building", {})
    footprint_by_grammar = {"compact_tapered": (6, 6), "channel_adjacent_split_level": (10, 7), "courtyard_or_l": (9, 7), "axial_nave_and_side_aisles": (11, 7), "tunnel_chambers_and_shaft": (8, 8)}
    fw, fh = footprint_by_grammar.get(str(PROFILE.get("footprint")), (8, 6))
    policy = PROFILE.get("floor_policy", {})
    floors = int(policy.get("value", policy.get("minimum", 2)))
    floors = max(1, min(6, floors))
    building_id = str(building.get("id", "building"))
    building_type = str(building.get("type", PROFILE.get("kind", "building")))
    center = (WIDTH * CELL / 2, -HEIGHT * CELL / 2)
    width, depth = fw * CELL, fh * CELL
    # Slightly taller, separated decks make vertical play readable from both
    # the far isometric view and a close tactical view.  The value is shared by
    # every building recipe; only the requested floor count changes.
    spacing = 1.04
    top_z = .18 + floors * spacing
    # Open floor plates and corner columns preserve line-of-sight between
    # levels, unlike stacked opaque boxes.  The same deck grammar works for a
    # tower, shrine, pump house or sewer chamber; room packs only choose props.
    natural_space = building_type in {"cavern", "ruin"}
    for floor in range(floors):
        z = .16 + floor * spacing
        if natural_space:
            # Natural/ruined profiles do not inherit the civic floor stack.
            # Give only the lower chamber a walkable base and let the detail
            # pack supply broken ledges, rubble and cave walls.
            if floor == 0:
                box(f"NaturalFloor_{building_id}", (center[0], center[1], z), (width * .86, depth * .82, .10), "road", "terrain_band", floor=1, building_id=building_id)
            continue
        material_id = "dark" if floor else "road"
        box(f"BuildingFloor_{floor + 1}", (center[0], center[1], z), (width, depth, .14), material_id, "building_floor", floor=floor + 1, building_id=building_id)
        # Grid strips are clipped to each deck, making the vertical stack
        # playable without hiding the architectural silhouette.
        for grid_index in range(1, max(2, int(fw // 2))):
            gx = center[0] - width / 2 + grid_index * width / max(2, int(fw // 2))
            box(f"DeckGridV_{floor}_{grid_index}", (gx, center[1], z + .076), (.012, depth * .90, .018), "grid", "grid", floor=floor + 1, building_id=building_id)
        for grid_index in range(1, max(2, int(fh // 2))):
            gy = center[1] - depth / 2 + grid_index * depth / max(2, int(fh // 2))
            box(f"DeckGridH_{floor}_{grid_index}", (center[0], gy, z + .076), (width * .90, .012, .018), "grid", "grid", floor=floor + 1, building_id=building_id)
        for side_x in (-1, 1):
            for side_y in (-1, 1):
                cylinder(f"Column_{floor + 1}_{side_x}_{side_y}", (center[0] + side_x * width * .46, center[1] + side_y * depth * .46, z + spacing / 2), .085, spacing, "stone_light", "support", floor=floor + 1, building_id=building_id)
        # Split, waist-high facade runs preserve silhouette and cover while
        # leaving a central sightline into the rooms.  A single tall slab was
        # the main reason the first universal tower/manor reads as a box.
        wall_h = .38 if building_type in {"pump_house", "sewer", "sewer_main", "drainage", "mine"} else .30
        wall_z = z + .17 + wall_h / 2
        for wall_side in (-1, 1):
            box(f"BackWall_{floor + 1}_{wall_side}", (center[0] + wall_side * width * .25, center[1] + depth * .47, wall_z), (width * .42, .10, wall_h), "wall", "wall", floor=floor + 1, building_id=building_id)
        box(f"SideWall_{floor + 1}", (center[0] - width * .47, center[1] + depth * .10, wall_z), (.10, depth * .46, wall_h), "wall", "wall", floor=floor + 1, building_id=building_id)
        # Shared low partitions give every new room grammar a spatial shape.
        add_room_shell(f"FloorRooms_{building_id}_{floor}", (center[0], center[1]), width * .72, depth * .72, z + .10, "wall", floor=floor + 1, building_id=building_id)
        add_window_lights(f"FloorWindows_{building_id}_{floor}", center, width, depth, z + .44, max(2, int(fw // 2)), floor=floor + 1, building_id=building_id)
    # The functional room grammar controls what is placed on each level;
    # every room type is implemented by the same reusable visual modules.
    rooms = [str(room) for room in PROFILE.get("room_grammar", [])]
    room_slots = [(-.26, -.28), (.26, -.28), (-.26, .28), (.26, .28), (0.0, -.05), (0.0, .34)]
    for index, room in enumerate(rooms):
        floor = 0 if natural_space else min(floors - 1, index % floors)
        z = .25 + floor * spacing
        slot_x, slot_y = room_slots[index % len(room_slots)]
        x = center[0] + slot_x * width
        y = center[1] + slot_y * depth
        room_width, room_depth = width * (.28 if len(rooms) > 5 else .34), depth * (.24 if len(rooms) > 5 else .30)
        if not natural_space:
            add_room_shell(f"RoomShell_{room}_{index}", (x, y), room_width, room_depth, z + .10, "wall", room=room, floor=floor + 1, building_id=building_id)
        box(f"Room_{room}_{index}", (x, y, z + .16), (room_width * .78, room_depth * .76, .08), "feature", "room_function", room=room, floor=floor + 1, building_id=building_id)
        if room in {"intake", "collector", "channel", "sewage_channel", "underground_lake"}:
            box(f"WaterBasin_{index}", (x, y + depth * .10, z + .12), (width * .24, depth * .22, .05), "water", "water_channel", room=room, floor=floor + 1, building_id=building_id)
            cylinder(f"ValveWheel_{index}", (x, y - depth * .10, z + .35), .12, .06, "metal", "equipment", equipment="valve", room=room, building_id=building_id)
            cylinder_between(f"IntakePipe_{index}", (x, y + depth * .22, z + .18), (x, y + depth * .10, z + .18), .045, "metal", "pipe", room=room, building_id=building_id)
        elif room in {"pump_hall", "machine", "control", "pump_controls", "command"}:
            cylinder(f"PumpCore_{index}", (x, y, z + .34), .20, .42, "metal", "equipment", equipment="pump", room=room, building_id=building_id)
            cylinder(f"PumpWheel_{index}", (x, y, z + .57), .16, .035, "accent", "equipment", equipment="flywheel", room=room, building_id=building_id)
            for gauge in range(2):
                cylinder(f"Gauge_{index}_{gauge}", (x + (gauge - .5) * .18, y - .13, z + .42), .045, .025, "feature", "equipment", equipment="gauge", room=room, building_id=building_id)
            cylinder_between(f"PumpDischarge_{index}", (x, y + .16, z + .40), (x + width * .20, y + .16, z + .40), .035, "metal", "pipe", room=room, building_id=building_id)
        elif room in {"maintenance_loop", "landing", "archive", "gallery", "reading_hall", "collapsed_hall"}:
            for rail_side in (-1, 1):
                cylinder_between(f"Rail_{index}_{rail_side}", (x - width * .14, y + rail_side * depth * .12, z + .30), (x + width * .14, y + rail_side * depth * .12, z + .30), .025, "metal", "railing", room=room, building_id=building_id)
            if room in {"archive", "reading_hall"}:
                for shelf in range(2):
                    box(f"Shelf_{room}_{index}_{shelf}", (x - room_width * .22 + shelf * room_width * .44, y + room_depth * .28, z + .28), (room_width * .22, .06, .42), "wood", "furniture", room=room, building_id=building_id)
        elif "shrine" in room or room in {"secret", "buried_shrine", "vault", "crypt"}:
            box(f"ShrineAltar_{index}", (x, y, z + .24), (.34, .24, .22), "stone_light", "secret_detail", room=room, building_id=building_id)
            cylinder(f"ShrineGlow_{index}", (x, y, z + .48), .08, .12, "secret", "secret_detail", room=room, building_id=building_id)
        elif room in {"entry", "guard", "taproom", "salon", "gallery", "nave", "forecourt", "gatehouse", "mess", "stage", "courtyard"}:
            box(f"Table_{room}_{index}", (x, y, z + .22), (width * .18, depth * .12, .12), "wood", "furniture", room=room, building_id=building_id)
            cylinder(f"Lantern_{room}_{index}", (x, y, z + .46), .06, .10, "feature", "room_dressing", room=room, building_id=building_id)
        elif room in {"archive", "library", "quarters", "bedchamber", "guest_room", "service", "keeper_quarters", "barracks", "armory", "scriptorium"}:
            box(f"Shelf_{room}_{index}", (x, y + depth * .12, z + .28), (width * .24, .08, .42), "wood", "furniture", room=room, building_id=building_id)
            box(f"Bed_{room}_{index}", (x - width * .08, y - depth * .06, z + .16), (width * .20, depth * .18, .12), "feature", "furniture", room=room, building_id=building_id)
        elif room in {"junction", "pump_controls", "sewage_channel", "channel"}:
            box(f"ControlPanel_{room}_{index}", (x, y, z + .24), (width * .22, .12, .22), "metal", "equipment", room=room, building_id=building_id)
            cylinder(f"Valve_{room}_{index}", (x, y - depth * .12, z + .44), .08, .05, "accent", "equipment", room=room, building_id=building_id)
        else:
            # Unknown room roles still receive a small readable footprint;
            # adding a new recipe never silently produces an empty floor.
            box(f"RoomMarker_{index}", (x, y, z + .16), (width * .18, depth * .14, .10), "feature", "room_dressing", room=room, building_id=building_id)
    # A small deterministic dressing pass keeps a newly registered room
    # recipe from becoming a row of empty floors.  The same pack vocabulary is
    # shared by towers, estates, utilities and future building types.
    for floor in range(floors):
        z = .25 + floor * spacing
        if building_type in {"tower", "lighthouse", "fortress"}:
            for side in (-1, 1):
                box(f"Banner_{building_id}_{floor}_{side}", (center[0] + side * width * .38, center[1] + depth * .18, z + .44), (.05, .16, .30), "accent", "wall_dressing", floor=floor + 1, building_id=building_id)
            add_crate_stack(f"TowerCrates_{building_id}_{floor}", (center[0] - width * .28, center[1] + depth * .23, z + .10), 2 + (floor % 2), building_id=building_id, floor=floor + 1, dressing_role="storage")
            # Alternating exterior landings break the repeated square stack
            # and give the tower a route that can be read from outside.
            balcony_side = -1 if floor % 2 == 0 else 1
            balcony_x = center[0] + balcony_side * width * .44
            box(f"TowerBalcony_{building_id}_{floor}", (balcony_x, center[1] - depth * .08, z + .14), (width * .28, depth * .34, .07), "wood", "platform", floor=floor + 1, building_id=building_id, role="external_landing")
            for post_side in (-1, 1):
                post_x = balcony_x + post_side * width * .10
                cylinder(f"TowerBalconyPost_{building_id}_{floor}_{post_side}", (post_x, center[1] - depth * .08, z + .32), .025, .36, "metal", "railing", floor=floor + 1, building_id=building_id)
            cylinder_between(f"TowerBalconyRail_{building_id}_{floor}", (balcony_x - width * .11, center[1] - depth * .22, z + .34), (balcony_x + width * .11, center[1] - depth * .22, z + .34), .022, "metal", "railing", floor=floor + 1, building_id=building_id)
        elif building_type == "manor" or building_type in {"library", "tavern", "inn", "barracks"}:
            box(f"Rug_{building_id}_{floor}", (center[0] + width * .08, center[1] - depth * .02, z + .11), (width * .34, depth * .22, .025), "accent", "floor_dressing", floor=floor + 1, building_id=building_id)
            add_lamp_post(f"HangingLamp_{building_id}_{floor}", (center[0], center[1] + depth * .08, z + .48), .34, floor=floor + 1, building_id=building_id)
        elif building_type in {"sewer", "sewer_main", "drainage", "pump_house", "mine"}:
            for side in (-1, 1):
                cylinder(f"GaugeCluster_{building_id}_{floor}_{side}", (center[0] + side * width * .33, center[1] - depth * .16, z + .38), .055, .06, "feature", "equipment", floor=floor + 1, building_id=building_id)
            add_crate_stack(f"UtilityCrates_{building_id}_{floor}", (center[0] + width * .27, center[1] - depth * .24, z + .10), 2, building_id=building_id, floor=floor + 1, dressing_role="maintenance")
        else:
            add_lamp_post(f"GenericLamp_{building_id}_{floor}", (center[0], center[1] - depth * .22, z + .20), .30, floor=floor + 1, building_id=building_id)
    # A continuous stair zig-zag links all decks.
    for floor in range(floors - 1):
        start_z = .25 + floor * spacing
        for step in range(9):
            t = step / 8
            side = -1 if floor % 2 == 0 else 1
            box(f"Stair_{floor}_{step}", (center[0] + side * (-width * .34 + t * width * .42), center[1] - depth * .34, start_z + t * spacing), (.24, .44, .07), "wood", "stair", floor=floor + 1, building_id=building_id)
        cylinder_between(f"StairRail_{floor}", (center[0] - width * .40, center[1] - depth * .56, start_z + .20), (center[0] + width * .10, center[1] - depth * .56, start_z + spacing + .20), .028, "metal", "railing", building_id=building_id)
    add_building_detail_pack(building_type, center, width, depth, floors, spacing, top_z, building_id)
    utility_types = {"pump_house", "sewer", "sewer_main", "drainage", "mine"}
    if building_type in utility_types:
        # Service layer is shared, but only infrastructure recipes receive a
        # visible channel and pipe manifold; it must not turn every manor or
        # church into a pump station.
        channel_x = center[0] - width * .28
        box("MainWaterChannel", (channel_x, center[1], .10), (.36, depth * .78, .06), "water", "water_channel", building_id=building_id)
        for pipe_index, pipe_x in enumerate((center[0] + width * .28, center[0] + width * .36)):
            cylinder_between(f"VerticalPipe_{pipe_index}", (pipe_x, center[1] + depth * .20, .20), (pipe_x, center[1] + depth * .20, top_z + .25), .045, "metal", "pipe", building_id=building_id)
            for floor in range(floors):
                z = .30 + floor * spacing
                cylinder_between(f"HorizontalPipe_{pipe_index}_{floor}", (pipe_x, center[1] + depth * .20, z), (channel_x + .12, center[1] + depth * .20, z), .035, "metal", "pipe", floor=floor + 1, building_id=building_id)
        roof_z = top_z + .16
        box("RoofNorth", (center[0], center[1] + depth * .46, roof_z), (width * 1.05, .10, .16), "roof", "roof", building_id=building_id, building_type=building_type)
        box("RoofSouth", (center[0], center[1] - depth * .46, roof_z), (width * 1.05, .10, .16), "roof", "roof", building_id=building_id, building_type=building_type)
        box("RoofWest", (center[0] - width * .46, center[1], roof_z), (.10, depth * .90, .16), "roof", "roof", building_id=building_id, building_type=building_type)
        box("RoofEast", (center[0] + width * .46, center[1], roof_z), (.10, depth * .90, .16), "roof", "roof", building_id=building_id, building_type=building_type)
        cylinder("BuildingVerticalLandmark", (center[0], center[1], top_z + .54), .20, .72, "metal", "landmark", building_id=building_id)
        cylinder("RoofVentCap", (center[0] + width * .22, center[1] - depth * .18, top_z + .42), .11, .20, "accent", "equipment", equipment="vent", building_id=building_id)
    elif building_type in {"ruin", "cavern"}:
        # Natural and collapsed spaces use their own negative-space silhouette
        # from add_building_detail_pack; an intact roof frame would erase the
        # very incompleteness that makes these profiles useful.
        pass
    else:
        roof_z = top_z + .16
        # Profile renders are cutaway tactical views: a solid roof would hide
        # the very rooms and connectors the player needs to read.  Use a
        # silhouette frame instead, with a shallow ridge only where it helps
        # identify a civic/manor roofline.
        if building_type in {"tower", "lighthouse", "fortress"}:
            box(f"TowerEaveNorth_{building_id}", (center[0], center[1] + depth * .47, roof_z), (width * 1.05, .10, .14), "roof", "roof", building_id=building_id, building_type=building_type)
            box(f"TowerEaveSouth_{building_id}", (center[0], center[1] - depth * .47, roof_z), (width * 1.05, .10, .14), "roof", "roof", building_id=building_id, building_type=building_type)
            box(f"TowerEaveWest_{building_id}", (center[0] - width * .47, center[1], roof_z), (.10, depth * .90, .14), "roof", "roof", building_id=building_id, building_type=building_type)
            box(f"TowerEaveEast_{building_id}", (center[0] + width * .47, center[1], roof_z), (.10, depth * .90, .14), "roof", "roof", building_id=building_id, building_type=building_type)
            add_battlements(f"TowerRoof_{building_id}", center, width, depth, top_z + .38, "stone_light", building_id=building_id, building_type=building_type)
        else:
            box(f"RoofEaveNorth_{building_id}", (center[0], center[1] + depth * .47, roof_z), (width * 1.05, .10, .14), "roof", "roof", building_id=building_id, building_type=building_type)
            box(f"RoofEaveSouth_{building_id}", (center[0], center[1] - depth * .47, roof_z), (width * 1.05, .10, .14), "roof", "roof", building_id=building_id, building_type=building_type)
            box(f"RoofEaveWest_{building_id}", (center[0] - width * .47, center[1], roof_z), (.10, depth * .90, .14), "roof", "roof", building_id=building_id, building_type=building_type)
            box(f"RoofEaveEast_{building_id}", (center[0] + width * .47, center[1], roof_z), (.10, depth * .90, .14), "roof", "roof", building_id=building_id, building_type=building_type)
            if building_type in {"church", "temple", "manor", "library", "tavern", "inn"}:
                box(f"RoofRidge_{building_id}", (center[0], center[1], roof_z + .18), (.10, depth * .84, .20), "roof", "roof_detail", building_id=building_id, building_type=building_type)


def configure_scene() -> bpy.types.Object:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1200, 900, 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = .55 if CATEGORY == "outdoor" else (.42 if CATEGORY == "building" else .30)
    scene.world.use_nodes = True
    background = next((node for node in scene.world.node_tree.nodes if node.type == "BACKGROUND"), None)
    if background is None:
        background = scene.world.node_tree.nodes.new("ShaderNodeBackground")
        output = next((node for node in scene.world.node_tree.nodes if node.type == "WORLD"), None)
        if output is None:
            output = scene.world.node_tree.nodes.new("ShaderNodeOutputWorld")
        scene.world.node_tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    background.inputs["Color"].default_value = (.022, .036, .065, 1) if CATEGORY != "outdoor" else (.055, .085, .12, 1)
    background.inputs["Strength"].default_value = .48
    width, height = WIDTH * CELL, HEIGHT * CELL
    target = (width / 2, -height / 2, 1.2)
    for name, location, energy, color, size in [
        ("ProfileKey", (width * .25, -height * .25, 25), 1800, (1.0, .64, .36), 20),
        ("ProfileFill", (width * .82, -height * .78, 18), 1350, (.22, .50, 1.0), 18),
        ("ProfileRim", (width * .70, -height * .12, 20), 950, (.20, 1.0, .65), 14),
    ]:
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.name = name
        light.data.energy = energy
        light.data.color = color
        light.data.shape = "DISK"
        light.data.size = size
        light.rotation_euler = (Vector(target) - light.location).to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.camera_add(location=(width * 1.08, -height * .72, max(width, height) * .95 + 8))
    camera = bpy.context.object
    camera.name = "ProfileSceneCamera"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(width, height) * (.98 if CATEGORY == "building" else 1.12)
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera
    return camera


def render(camera: bpy.types.Object, name: str, location: tuple[float, float, float], target: tuple[float, float, float], scale: float) -> None:
    camera.location = location
    camera.data.ortho_scale = scale
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.render.filepath = str(OUT / name)
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
    if "export_extras" in properties:
        kwargs["export_extras"] = True
    bpy.ops.export_scene.gltf(**kwargs)
    bpy.ops.object.select_all(action="DESELECT")


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clean()
    create_materials()
    if CATEGORY == "district":
        add_district()
    elif CATEGORY == "outdoor":
        add_outdoor()
    else:
        add_building()
    camera = configure_scene()
    width, height = WIDTH * CELL, HEIGHT * CELL
    frame_width = width * .62 if CATEGORY == "building" else width
    frame_height = height * .64 if CATEGORY == "building" else height
    vertical_span = 0.0
    if CATEGORY == "building":
        policy = PROFILE.get("floor_policy", {})
        floors = int(policy.get("value", policy.get("minimum", 2)))
        vertical_span = .18 + max(1, min(6, floors)) * 1.04 + .95
    frame_span = max(frame_width, frame_height, vertical_span)
    target = (width / 2, -height / 2, 1.65 if CATEGORY == "building" else 1.0)
    scale = frame_span * (1.15 if CATEGORY == "building" else 1.12)
    render(camera, "scene-isometric.png", (target[0] + frame_width * 1.10, target[1] - frame_height * .68, frame_span * .88 + 5.0), target, scale)
    render(camera, "scene-topdown.png", (target[0], target[1], frame_span * 1.75 + 5.0), target, frame_span * (.78 if CATEGORY == "building" else 1.02))
    export_glb()
    # Write only the isolated profile scene.  wm.save_as_mainfile would include
    # every unrelated scene open in the host Blender session.
    bpy.data.libraries.write(str(OUT / "scene-prototype.blend"), {PROFILE_SCENE}, path_remap="RELATIVE", fake_user=True, compress=True)
    # Leave the user's currently open scene selected after the artifact is
    # saved; the generated .blend still contains the isolated profile scene.
    if ORIGINAL_SCENE is not None and bpy.context.window:
        bpy.context.window.scene = ORIGINAL_SCENE
    outputs = []
    for name in ("scene.glb", "scene-prototype.blend", "scene-isometric.png", "scene-topdown.png"):
        path = OUT / name
        outputs.append({"path": name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "schema_version": "dnd-profile-render-manifest-1.0",
        "scene": SCENE,
        "category": CATEGORY,
        "profile_hash": hashlib.sha256(json.dumps(PROFILE, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "visual_plan_hash": hashlib.sha256(json.dumps(VISUAL, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "prototype_objects": len(OBJECTS),
        "mesh_vertices": sum(len(obj.data.vertices) for obj in OBJECTS if obj.type == "MESH"),
        "outputs": outputs,
        "visual_evidence_views": ["far", "mid", "near", "tactical"],
    }
    (OUT / "scene.render-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


build()
