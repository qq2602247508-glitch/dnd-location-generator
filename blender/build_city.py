from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from generator.city_core import generate_transitions, load_and_generate, room_cells  # noqa: E402

SPEC_PATH = ROOT / "specs" / "city.json"
OUTPUT = ROOT / "output"
OUTPUT.mkdir(parents=True, exist_ok=True)
SPEC, CELLS, VALIDATION = load_and_generate(SPEC_PATH)

FLOOR_Z = 3.4
WALL_H = 2.55
WALL_T = 0.12
OBJECTS: list[bpy.types.Object] = []
MATS: dict[str, bpy.types.Material] = {}


def clean_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def mat(name: str, color: tuple[float, float, float, float], *, roughness: float = 0.7, metallic: float = 0.0, emission: float = 0.0) -> bpy.types.Material:
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    bsdf = value.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        if emission and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = color
            bsdf.inputs["Emission Strength"].default_value = emission
    MATS[name] = value
    return value


def tag(obj: bpy.types.Object, *, kind: str, level: int = 0, space: str = "outdoor", area: str = "", building: str = "", room: str = "", pick: str = "none") -> bpy.types.Object:
    obj["prototype"] = True
    obj["prototype_kind"] = kind
    obj["level_index"] = level
    obj["space_kind"] = space
    obj["area_id"] = area
    obj["building_id"] = building
    obj["room_id"] = room
    obj["pick_role"] = pick
    OBJECTS.append(obj)
    return obj


def cube(name: str, location: tuple[float, float, float], dimensions: tuple[float, float, float], material: bpy.types.Material, **metadata: Any) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    obj.data.materials.append(material)
    return tag(obj, **metadata)


def mesh_boxes(name: str, boxes: list[tuple[tuple[float, float, float], tuple[float, float, float]]], material: bpy.types.Material, **metadata: Any) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for (cx, cy, cz), (sx, sy, sz) in boxes:
        base = len(vertices)
        vertices.extend([(cx + dx * sx / 2, cy + dy * sy / 2, cz + dz * sz / 2) for dx, dy, dz in (
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
        )])
        faces.extend([(base + a, base + b, base + c, base + d) for a, b, c, d in (
            (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
        )])
    data = bpy.data.meshes.new(f"{name}_Mesh")
    data.from_pydata(vertices, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(material)
    return tag(obj, **metadata)


def label(body: str, location: tuple[float, float, float], *, level: int, building: str, room: str = "") -> None:
    bpy.ops.object.text_add(location=location)
    obj = bpy.context.object
    obj.name = f"Label_{building}_{room or body}"
    obj.data.body = body
    obj.data.align_x = "CENTER"
    obj.data.align_y = "CENTER"
    obj.data.size = 0.34
    obj.data.extrude = 0.008
    obj.data.materials.append(MATS["label"])
    tag(obj, kind="label", level=level, space="interior", area=building, building=building, room=room)


def point_key(a: tuple[int, int], b: tuple[int, int]) -> frozenset[tuple[int, int]]:
    return frozenset((a, b))


def build_outdoors() -> None:
    zone_boxes: dict[str, list[tuple[tuple[float, float, float], tuple[float, float, float]]]] = {}
    grid_boxes: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    for cell in CELLS:
        if cell["space_kind"] != "outdoor":
            continue
        zone_boxes.setdefault(cell["zone"], []).append(((cell["col"] + .5, cell["row"] + .5, -.09), (.985, .985, .18)))
        row, col = cell["row"], cell["col"]
        grid_boxes.extend([
            ((col + .5, row + .015, .012), (.98, .025, .018)),
            ((col + .015, row + .5, .012), (.025, .98, .018)),
        ])
    for zone, boxes in zone_boxes.items():
        mesh_boxes(f"City_Outdoor_{zone}", boxes, MATS[f"street_{zone}"], kind="floor", level=0, space="outdoor", area=zone, pick="tactical_floor")
    mesh_boxes("City_Outdoor_Grid", grid_boxes, MATS["grid"], kind="grid", level=0, space="outdoor", area="city")


def build_floor(building: dict[str, Any], floor: dict[str, Any]) -> None:
    level = int(floor["floor_index"])
    z = (level - 1) * FLOOR_Z
    for room in floor["rooms"]:
        b = room["bounds"]
        cube(
            f"Floor_{building['id']}_L{level}_{room['id']}",
            (b["col"] + b["width"] / 2, b["row"] + b["height"] / 2, z - .06),
            (b["width"] - .04, b["height"] - .04, .12), MATS[f"floor_{level}"],
            kind="floor", level=level, space="interior", area=building["id"], building=building["id"], room=room["id"], pick="tactical_floor",
        )
        label(room["label"], (b["col"] + b["width"] / 2, b["row"] + b["height"] / 2, z + .014), level=level, building=building["id"], room=room["id"])
        lines = []
        for col in range(b["col"], b["col"] + b["width"] + 1):
            lines.append(((col, b["row"] + b["height"] / 2, z + .018), (.022, b["height"], .015)))
        for row in range(b["row"], b["row"] + b["height"] + 1):
            lines.append(((b["col"] + b["width"] / 2, row, z + .018), (b["width"], .022, .015)))
        mesh_boxes(f"Grid_{building['id']}_L{level}_{room['id']}", lines, MATS["grid"], kind="grid", level=level, space="interior", area=building["id"], building=building["id"], room=room["id"])


def wall_for_edge(name: str, cell: tuple[int, int], neighbor: tuple[int, int], z: float, material: bpy.types.Material, **metadata: Any) -> None:
    row, col = cell
    nr, nc = neighbor
    if row == nr:
        loc, dims = (max(col, nc), row + .5, z + WALL_H / 2), (WALL_T, 1.0, WALL_H)
    else:
        loc, dims = (col + .5, max(row, nr), z + WALL_H / 2), (1.0, WALL_T, WALL_H)
    cube(name, loc, dims, material, kind="wall", **metadata)


def build_walls(building: dict[str, Any], floor: dict[str, Any]) -> None:
    level = int(floor["floor_index"])
    z = (level - 1) * FLOOR_Z
    b = building["bounds"]
    footprint = {(row, col) for row in range(b["row"], b["row"] + b["height"]) for col in range(b["col"], b["col"] + b["width"])}
    doors = {tuple((entry["row"], entry["col"])) for entry in building["entrances"]} if level == 1 else set()
    room_at: dict[tuple[int, int], str] = {}
    for room in floor["rooms"]:
        for point in room_cells(room):
            room_at[point] = room["id"]
    connector_edges = {point_key(tuple(c["from_cell"]), tuple(c["to_cell"])) for c in floor["connectors"]}
    seen: set[frozenset[tuple[int, int]]] = set()
    for point, room_id in room_at.items():
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbor = (point[0] + dr, point[1] + dc)
            edge = point_key(point, neighbor)
            if edge in seen:
                continue
            seen.add(edge)
            other = room_at.get(neighbor)
            if other == room_id or edge in connector_edges:
                continue
            # An indicated exterior entrance stays open at its outside-facing edge.
            if point in doors and neighbor not in footprint:
                continue
            if other is None or other != room_id:
                wall_for_edge(f"Wall_{building['id']}_L{level}_{point[0]}_{point[1]}_{neighbor[0]}_{neighbor[1]}", point, neighbor, z, MATS["wall"], level=level, space="interior", area=building["id"], building=building["id"], room=room_id)
    # A thin, hideable roof rim hints at volume without hiding tactical interiors.
    roof_z = z + WALL_H + .08
    cube(f"RoofNorth_{building['id']}_L{level}", (b["col"] + b["width"] / 2, b["row"] + .06, roof_z), (b["width"] + .35, .22, .16), MATS["roof"], kind="roof", level=level, space="interior", area=building["id"], building=building["id"], pick="hideable")
    cube(f"RoofSouth_{building['id']}_L{level}", (b["col"] + b["width"] / 2, b["row"] + b["height"] - .06, roof_z), (b["width"] + .35, .22, .16), MATS["roof"], kind="roof", level=level, space="interior", area=building["id"], building=building["id"], pick="hideable")


def add_stairs(building: dict[str, Any], floor: dict[str, Any]) -> None:
    level = int(floor["floor_index"])
    for stair in floor["stairs"]:
        if stair["direction"] != "up":
            continue
        row, col = stair["row"], stair["col"]
        z = (level - 1) * FLOOR_Z
        for step in range(8):
            rise = FLOOR_Z * (step + 1) / 9
            cube(f"Stair_{building['id']}_{level}_{step}", (col + .5, row + .16 + step * .085, z + rise / 2), (.76, .22, rise), MATS["stairs"], kind="stairs", level=level, space="interior", area=building["id"], building=building["id"], pick="transition")


def build_buildings() -> None:
    for building in SPEC["buildings"]:
        for floor in building["floors"]:
            build_floor(building, floor)
            build_walls(building, floor)
            add_stairs(building, floor)
        b = building["bounds"]
        for index, entry in enumerate(building["entrances"]):
            on_horizontal_edge = entry["row"] in {b["row"], b["row"] + b["height"] - 1}
            door_dimensions = (.56, .12, 1.55) if on_horizontal_edge else (.12, .56, 1.55)
            cube(f"Door_{building['id']}_{index}", (entry["col"] + .5, entry["row"] + .5, .78), door_dimensions, MATS["door"], kind="door", level=1, space="interior", area=building["id"], building=building["id"], room=entry["room_id"], pick="transition")
        # Simplified distinguishing prop per building: still deliberately lightweight architecture.
        cx, cy = b["col"] + b["width"] / 2, b["row"] + b["height"] / 2
        if building["building_type"] == "smithy":
            bpy.ops.mesh.primitive_torus_add(major_radius=.42, minor_radius=.09, location=(cx, cy, .25))
            obj = bpy.context.object; obj.name = "SmithyAnvil"; obj.data.materials.append(MATS["metal"]); tag(obj, kind="prop", level=1, space="interior", area=building["id"], building=building["id"])
        elif building["building_type"] == "market":
            for offset in (-2.0, 0.0, 2.0):
                cube(f"MarketStall_{offset}", (cx + offset, cy, .34), (1.4, 1.1, .62), MATS["wood"], kind="prop", level=1, space="interior", area=building["id"], building=building["id"])
        elif building["building_type"] == "shrine":
            cube("ShrineAltar", (cx, cy, .42), (1.4, .8, .78), MATS["altar"], kind="prop", level=1, space="interior", area=building["id"], building=building["id"])


def props() -> dict[str, int]:
    cube("PlazaWell", (16.5, 13.5, .28), (1.7, 1.7, .55), MATS["stone"], kind="prop", level=0, space="outdoor", area="market_plaza")
    for index, (x, y) in enumerate(((11, 12), (21, 12), (12, 16), (21, 16), (15, 9), (18, 19))):
        bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=.11, depth=2.0, location=(x + .5, y + .5, 1.0))
        post = bpy.context.object; post.name = f"StreetLantern_{index}"; post.data.materials.append(MATS["metal"]); tag(post, kind="lantern", level=0, space="outdoor", area="city")
        bpy.ops.mesh.primitive_uv_sphere_add(segments=10, ring_count=6, radius=.19, location=(x + .5, y + .5, 2.0))
        glow = bpy.context.object; glow.name = f"LanternGlow_{index}"; glow.data.materials.append(MATS["lantern"]); tag(glow, kind="lantern", level=0, space="outdoor", area="city")
    row, col = SPEC["anchors"]["party_start"]
    bpy.ops.mesh.primitive_torus_add(major_radius=.52, minor_radius=.075, major_segments=24, minor_segments=8, location=(col + .5, row + .5, .075))
    start = bpy.context.object; start.name = "PartyStartMarker"; start.data.materials.append(MATS["start"]); tag(start, kind="anchor", level=0, space="outdoor", area="city", pick="anchor")
    return {"street_lanterns": 6, "plaza_well": 1, "building_props": 3}


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def setup_scene() -> bpy.types.Object:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1400, 1000, 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = 1.35
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (.035, .055, .10, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = .48
    for name, location, energy, color, size in (
        ("SunKey", (10, -15, 35), 2600, (1.0, .66, .38), 18),
        ("BlueFill", (38, 22, 24), 1450, (.26, .46, 1.0), 14),
    ):
        bpy.ops.object.light_add(type="AREA", location=location)
        lamp = bpy.context.object; lamp.name = name; lamp.data.energy = energy; lamp.data.color = color; lamp.data.shape = "DISK"; lamp.data.size = size; look_at(lamp, (16, 14, 1.5))
    bpy.ops.object.camera_add(location=(48, -38, 42))
    camera = bpy.context.object; camera.name = "CityCamera"; camera.data.type = "ORTHO"; camera.data.ortho_scale = 48; look_at(camera, (16, 14, 1.7)); scene.camera = camera
    return camera


def render(camera: bpy.types.Object, filename: str, location: tuple[float, float, float], target: tuple[float, float, float], scale: float) -> None:
    camera.location = location; camera.data.ortho_scale = scale; look_at(camera, target)
    bpy.context.scene.render.filepath = str(OUTPUT / filename)
    bpy.ops.render.render(write_still=True)


def export_glb() -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in OBJECTS:
        if obj.type in {"MESH", "FONT", "CURVE"}:
            obj.select_set(True)
    properties = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    kwargs: dict[str, Any] = {"filepath": str(OUTPUT / "city-dm.glb"), "export_format": "GLB"}
    if "use_selection" in properties: kwargs["use_selection"] = True
    elif "export_selected" in properties: kwargs["export_selected"] = True
    if "export_extras" in properties: kwargs["export_extras"] = True
    bpy.ops.export_scene.gltf(**kwargs)


def build() -> None:
    clean_scene()
    for name, color, roughness, metallic, emission in (
        ("street_main_street", (.17, .22, .29, 1), .8, .0, .0), ("street_market_plaza", (.28, .25, .20, 1), .82, .0, .0),
        ("street_alley", (.12, .16, .20, 1), .88, .0, .0), ("street_side_street", (.10, .13, .17, 1), .92, .0, .0),
        ("floor_1", (.29, .17, .09, 1), .74, .0, .0), ("floor_2", (.19, .31, .37, 1), .7, .0, .0),
        ("wall", (.39, .38, .42, 1), .86, .0, .0), ("roof", (.48, .16, .09, 1), .72, .0, .0),
        ("grid", (.025, .43, .56, 1), .38, .15, .17), ("label", (.86, .95, 1.0, 1), .4, .05, .05),
        ("door", (.88, .46, .10, 1), .42, .15, .0), ("stairs", (.28, .75, .96, 1), .34, .18, .08),
        ("wood", (.22, .075, .025, 1), .72, .0, .0), ("stone", (.32, .34, .39, 1), .82, .0, .0),
        ("metal", (.25, .29, .35, 1), .35, .65, .0), ("altar", (.72, .57, .22, 1), .45, .1, .0),
        ("lantern", (1.0, .47, .08, 1), .25, .1, 1.5), ("start", (.16, .95, .73, 1), .3, .1, 1.0),
    ):
        mat(name, color, roughness=roughness, metallic=metallic, emission=emission)
    camera = setup_scene()
    build_outdoors(); build_buildings(); prop_counts = props()
    render(camera, "city-isometric.png", (48, -38, 42), (16, 14, 1.7), 48)
    render(camera, "city-topdown.png", (16, 14, 72), (16, 14, 0), 39)
    camera.location = (48, -38, 42); camera.data.ortho_scale = 48; look_at(camera, (16, 14, 1.7))
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "city-prototype.blend"))
    export_glb()
    payload = {"schema_version": SPEC["schema_version"], "name": SPEC["name"], "seed": SPEC["seed"], "width": SPEC["width"], "height": SPEC["height"], "cell_size_ft": SPEC["cell_size_ft"], "floor_height_ft": SPEC["floor_height_ft"], "anchors": SPEC["anchors"], "cells": CELLS, "transitions": generate_transitions(SPEC)}
    (OUTPUT / "city-grid.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    manifest = {"status": "generated", "schema_version": SPEC["schema_version"], "seed": SPEC["seed"], "source_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(), "validation": VALIDATION, "prototype_objects": len(OBJECTS), "props": prop_counts, "outputs": ["city-isometric.png", "city-topdown.png", "city-dm.glb", "city-prototype.blend", "city-grid.json"]}
    (OUTPUT / "city-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
