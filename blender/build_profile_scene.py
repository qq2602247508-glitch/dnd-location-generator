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
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in list(bpy.data.materials):
        bpy.data.materials.remove(block)


def point(row: float, col: float, z: float = 0.0) -> tuple[float, float, float]:
    return ((float(col) + 0.5) * CELL, -(float(row) + 0.5) * CELL, float(z))


def box(name: str, center: tuple[float, float, float], size: tuple[float, float, float], material_id: str, kind: str, **extras: Any) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=center)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    obj.data.materials.append(MATERIALS[material_id])
    return tag(obj, kind, material_id, **extras)


def cylinder(name: str, center: tuple[float, float, float], radius: float, depth: float, material_id: str, kind: str, **extras: Any) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=radius, depth=depth, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(MATERIALS[material_id])
    return tag(obj, kind, material_id, **extras)


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
    mat("grid", (.08, .65, .78, 1), roughness=.35, emission=.45)
    mat("secret", (.82, .12, .60, 1), roughness=.30, emission=.65)
    mat("feature", (.86, .48, .08, 1), roughness=.48, emission=.35)
    mat("glass", (.22, .62, .78, 1), roughness=.18, metallic=.08, emission=.35)
    mat("water", colors["water"], roughness=.23, metallic=.18, emission=.38)


def add_ground() -> None:
    box("ProfileGround", (WIDTH * CELL / 2, -HEIGHT * CELL / 2, -.10), (WIDTH * CELL, HEIGHT * CELL, .20), "ground", "ground", category=CATEGORY)


def add_district() -> None:
    add_ground()
    for road in PROFILE.get("roads", []):
        points = [point(row, col, .04) for row, col in road.get("points", [])]
        curve(f"Road_{road['id']}", points, "road", "road", bevel=max(.06, float(road.get("width", 1)) * CELL * .30), road_role=road.get("role"), traffic=road.get("traffic"))
    for lot in PROFILE.get("lots", []):
        poly = [point(row, col, .065) for row, col in lot.get("polygon", [])]
        curve(f"Lot_{lot['id']}", poly + poly[:1], "accent", "lot", bevel=.018, lot_shape=lot.get("shape"), frontage=lot.get("frontage"))
    for building in PROFILE.get("buildings", []):
        row, col = building["position"]
        fw, fh = building["footprint"]["width"], building["footprint"]["height"]
        floor_policy = building.get("floor_policy", {})
        floors = int(floor_policy.get("value", floor_policy.get("minimum", 1)))
        floors = max(1, min(6, floors))
        height = floors * .72
        center = ((col + fw / 2) * CELL, -(row + fh / 2) * CELL, height / 2 + .08)
        material_id = "accent" if building.get("is_landmark") else "wall"
        box(f"Building_{building['id']}", center, (fw * CELL * .86, fh * CELL * .86, height), material_id, "facade", building_id=building["id"], building_type=building.get("type"), floor_count=floors, orientation_deg=building.get("orientation_deg", 0))
        box(f"Roof_{building['id']}", (center[0], center[1], height + .16), (fw * CELL * .92, fh * CELL * .92, .22), "roof", "roof", building_id=building["id"], landmark=bool(building.get("is_landmark")))
        # Window/lighting bands make floor count legible from the near view.
        for floor in range(floors):
            z = .28 + floor * .72
            box(f"WindowBand_{building['id']}_{floor}", (center[0], center[1] - fh * CELL * .44, z), (max(.12, fw * CELL * .48), .025, .09), "glass", "window_band", building_id=building["id"], floor=floor + 1)
        if building.get("is_landmark"):
            cylinder(f"LandmarkCap_{building['id']}", (center[0], center[1], height + .60), max(.13, fw * CELL * .24), .85, "accent", "landmark", building_id=building["id"])


def polygon_mesh(name: str, polygon: list[list[int]], z: float, material_id: str, kind: str, **extras: Any) -> None:
    vertices = [(float(col) * CELL, -float(row) * CELL, z) for row, col in polygon]
    if len(vertices) < 3:
        return
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], [tuple(range(len(vertices)))])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(MATERIALS[material_id])
    tag(obj, kind, material_id, **extras)


def add_outdoor() -> None:
    add_ground()
    bands = PROFILE.get("terrain", {}).get("elevation_bands", [])
    for band in bands:
        z = float(band.get("elevation_ft", 0)) * Z_SCALE
        polygon_mesh(f"TerrainBand_{band['id']}", band.get("polygon", []), z, "wall" if band.get("cover") == "exposed_rock" else "ground", "terrain_band", elevation_ft=band.get("elevation_ft"), cover=band.get("cover"))
    for water in PROFILE.get("terrain", {}).get("watercourses", []):
        points = []
        point_count = max(1, len(water.get("points", [])) - 1)
        source = float(water.get("source_elevation_ft", 0))
        mouth = float(water.get("mouth_elevation_ft", 0))
        for index, (row, col) in enumerate(water.get("points", [])):
            z = (source + (mouth - source) * index / point_count) * Z_SCALE + .08
            points.append(point(row, col, z))
        curve(f"Water_{water['id']}", points, "water", "watercourse", bevel=max(.09, int(water.get("width_cells", 3)) * CELL * .18), source_elevation_ft=source, mouth_elevation_ft=mouth)
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
        points = [point(row, col, float(elevation) * Z_SCALE + .14) for (row, col), elevation in zip(route.get("points", []), route.get("elevation_profile_ft", []) + [0] * len(route.get("points", [])))]
        curve(f"Route_{route['id']}", points, "secret" if route.get("role") == "secret" else "accent", "route", bevel=.028, route_role=route.get("role"), risk=route.get("risk"), visibility=route.get("visibility", "public"))
    for platform in PROFILE.get("tactical_platforms", []):
        row, col = platform["position"]
        z = float(platform.get("elevation_ft", 0)) * Z_SCALE + .12
        box(f"Platform_{platform['id']}", point(row, col, z), (CELL * 2.2, CELL * 2.2, .20), "feature", "tactical_platform", tactical_role=platform.get("tactical_role"))
    for landmark in PROFILE.get("landmarks", []):
        row, col = landmark["position"]
        z = float(landmark.get("elevation_ft", 18)) * Z_SCALE + .25
        cylinder(f"Landmark_{landmark['id']}", point(row, col, z), .24, .8, "accent", "landmark", landmark_id=landmark["id"], role=landmark.get("role"))


def add_building() -> None:
    add_ground()
    building = PROFILE.get("building", {})
    footprint_by_grammar = {"compact_tapered": (6, 6), "channel_adjacent_split_level": (10, 7), "courtyard_or_l": (9, 7), "axial_nave_and_side_aisles": (11, 7), "tunnel_chambers_and_shaft": (8, 8)}
    fw, fh = footprint_by_grammar.get(str(PROFILE.get("footprint")), (8, 6))
    policy = PROFILE.get("floor_policy", {})
    floors = int(policy.get("value", policy.get("minimum", 2)))
    floors = max(1, min(6, floors))
    center = (WIDTH * CELL / 2, -HEIGHT * CELL / 2, .5)
    for floor in range(floors):
        z = .36 + floor * .78
        box(f"BuildingFloor_{floor + 1}", (center[0], center[1], z), (fw * CELL, fh * CELL, .65), "wall" if floor % 2 else "accent", "building_floor", floor=floor + 1, building_id=building.get("id", "building"))
        for room_index, room in enumerate(PROFILE.get("room_grammar", [])[:6]):
            box(f"RoomPad_{floor + 1}_{room_index}", (center[0] + (room_index % 3 - 1) * .54, center[1] + (room_index // 3 - .5) * .54, z + .34), (.38, .28, .05), "feature", "room_function", room=room, floor=floor + 1)
    for step in range(floors * 4):
        box(f"Stair_{step}", (center[0] - fw * CELL * .30 + step * .12, center[1] - fh * CELL * .35, .22 + step * .16), (.28, .54, .08), "accent", "stair", floor=(step // 4) + 1)
    cylinder("BuildingVerticalLandmark", (center[0], center[1], floors * .78 + .54), .34, .86, "accent", "landmark", building_id=building.get("id", "building"))


def configure_scene() -> bpy.types.Object:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1200, 900, 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = .35 if CATEGORY == "outdoor" else .15
    scene.world.use_nodes = True
    background = next(node for node in scene.world.node_tree.nodes if node.type == "BACKGROUND")
    background.inputs["Color"].default_value = (.015, .025, .045, 1) if CATEGORY != "outdoor" else (.035, .055, .085, 1)
    background.inputs["Strength"].default_value = .35
    width, height = WIDTH * CELL, HEIGHT * CELL
    target = (width / 2, -height / 2, 1.2)
    for name, location, energy, color, size in [
        ("ProfileKey", (width * .25, -height * .25, 25), 1100, (1.0, .64, .36), 20),
        ("ProfileFill", (width * .82, -height * .78, 18), 900, (.22, .50, 1.0), 18),
        ("ProfileRim", (width * .70, -height * .12, 20), 650, (.20, 1.0, .65), 14),
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
    camera.data.ortho_scale = max(width, height) * 1.22
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
    target = (width / 2, -height / 2, 1.0)
    render(camera, "scene-isometric.png", (width * 1.10, -height * .68, max(width, height) * .88 + 8), target, max(width, height) * 1.22)
    render(camera, "scene-topdown.png", (width / 2, -height / 2, max(width, height) * 1.75 + 8), target, max(width, height) * 1.08)
    export_glb()
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "scene-prototype.blend"))
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

