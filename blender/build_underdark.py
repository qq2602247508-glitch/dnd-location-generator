from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.underdark_core import load_and_generate  # noqa: E402


SPEC_PATH = ROOT / "specs" / "underdark.json"
OUTPUT = ROOT / "output"
SPEC, CELLS, VALIDATION = load_and_generate(SPEC_PATH)
RNG = random.Random(int(SPEC["seed"]))

STEP_Z = 0.78
TERRAIN_BOTTOM = -0.55
OBJECTS: list[bpy.types.Object] = []
MATERIALS: dict[str, bpy.types.Material] = {}


def clean_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def make_material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    metallic: float = 0.0,
    roughness: float = 0.65,
    emission: float = 0.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        if emission and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = color
            bsdf.inputs["Emission Strength"].default_value = emission
    MATERIALS[name] = mat
    return mat


def append_box(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int, int]],
    center: tuple[float, float, float],
    dimensions: tuple[float, float, float],
) -> None:
    cx, cy, cz = center
    sx, sy, sz = (value / 2 for value in dimensions)
    base = len(vertices)
    vertices.extend(
        [
            (cx - sx, cy - sy, cz - sz),
            (cx + sx, cy - sy, cz - sz),
            (cx + sx, cy + sy, cz - sz),
            (cx - sx, cy + sy, cz - sz),
            (cx - sx, cy - sy, cz + sz),
            (cx + sx, cy - sy, cz + sz),
            (cx + sx, cy + sy, cz + sz),
            (cx - sx, cy + sy, cz + sz),
        ]
    )
    faces.extend(
        [
            (base + 0, base + 3, base + 2, base + 1),
            (base + 4, base + 5, base + 6, base + 7),
            (base + 0, base + 1, base + 5, base + 4),
            (base + 1, base + 2, base + 6, base + 5),
            (base + 2, base + 3, base + 7, base + 6),
            (base + 3, base + 0, base + 4, base + 7),
        ]
    )


def mesh_object(
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int, int]],
    mat: bpy.types.Material,
    *,
    kind: str,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(mat)
    obj["prototype"] = True
    obj["prototype_kind"] = kind
    OBJECTS.append(obj)
    return obj


def cube(
    name: str,
    location: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    mat: bpy.types.Material,
    *,
    kind: str,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    obj.data.materials.append(mat)
    obj["prototype"] = True
    obj["prototype_kind"] = kind
    OBJECTS.append(obj)
    return obj


def top_z(cell: dict[str, Any]) -> float:
    return float(cell["elevation"]) * STEP_Z


def build_terrain() -> None:
    for elevation in range(5):
        vertices: list[tuple[float, float, float]] = []
        faces: list[tuple[int, int, int, int]] = []
        for (row, col), cell in CELLS.items():
            if not cell["walkable"] or int(cell["elevation"]) != elevation:
                continue
            top = top_z(cell)
            height = top - TERRAIN_BOTTOM
            append_box(vertices, faces, (col + 0.5, row + 0.5, TERRAIN_BOTTOM + height / 2), (0.985, 0.985, height))
        mesh_object(f"Terrain_Elevation_{elevation}", vertices, faces, MATERIALS[f"terrain_{elevation}"], kind="terrain")

    grid_vertices: list[tuple[float, float, float]] = []
    grid_faces: list[tuple[int, int, int, int]] = []
    for (row, col), cell in CELLS.items():
        if not cell["walkable"]:
            continue
        z = top_z(cell) + 0.012
        append_box(grid_vertices, grid_faces, (col + 0.5, row + 0.015, z), (0.98, 0.025, 0.018))
        append_box(grid_vertices, grid_faces, (col + 0.015, row + 0.5, z), (0.025, 0.98, 0.018))
        if (row + 1, col) not in CELLS or not CELLS[(row + 1, col)]["walkable"]:
            append_box(grid_vertices, grid_faces, (col + 0.5, row + 0.985, z), (0.98, 0.025, 0.018))
        if (row, col + 1) not in CELLS or not CELLS[(row, col + 1)]["walkable"]:
            append_box(grid_vertices, grid_faces, (col + 0.985, row + 0.5, z), (0.025, 0.98, 0.018))
    mesh_object("Tactical_Grid", grid_vertices, grid_faces, MATERIALS["grid"], kind="grid")


def build_chasm() -> None:
    width, height = int(SPEC["width"]), int(SPEC["height"])
    cube(
        "Chasm_Abyss",
        (width / 2, height / 2, -2.65),
        (width + 4, height + 4, 0.22),
        MATERIALS["abyss"],
        kind="chasm",
    )
    for row in range(1, height - 1, 3):
        center = 23 + round(math.sin(row * 0.42) * 1.8)
        cube(
            f"ChasmGlow_{row}",
            (center + 0.5, row + 0.5, -2.48),
            (2.3, 2.5, 0.035),
            MATERIALS["chasm_glow"],
            kind="chasm_glow",
        )


def build_bridges() -> None:
    bridge_cells = [(point, cell) for point, cell in CELLS.items() if cell["walkable"] and cell["zone"] == "stone_bridge"]
    for (row, col), cell in bridge_cells:
        z = top_z(cell) + 0.10
        cube(f"BridgeSlab_{row}_{col}", (col + 0.5, row + 0.5, z), (0.94, 0.94, 0.16), MATERIALS["bridge"], kind="bridge")
    for bridge_row in (11, 26):
        center = 23 + round(math.sin(bridge_row * 0.42) * 1.8)
        for side_row in (bridge_row - 0.08, bridge_row + 2.08):
            cube(
                f"BridgeRail_{bridge_row}_{side_row}",
                (center + 0.5, side_row, STEP_Z + 0.48),
                (7.2, 0.09, 0.72),
                MATERIALS["bridge_rail"],
                kind="bridge_rail",
            )


def add_mushroom(row: int, col: int, index: int) -> None:
    cell = CELLS[(row, col)]
    z = top_z(cell)
    height = RNG.uniform(0.6, 1.8)
    bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=RNG.uniform(0.08, 0.16), depth=height, location=(col + 0.5, row + 0.5, z + height / 2))
    stem = bpy.context.object
    stem.name = f"MushroomStem_{index}"
    stem.data.materials.append(MATERIALS["mushroom_stem"])
    stem["prototype_kind"] = "mushroom"
    OBJECTS.append(stem)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, location=(col + 0.5, row + 0.5, z + height))
    cap = bpy.context.object
    cap.name = f"MushroomCap_{index}"
    scale = RNG.uniform(0.3, 0.62)
    cap.scale = (scale, scale, scale * 0.34)
    cap.data.materials.append(MATERIALS["mushroom_cap"])
    cap["prototype_kind"] = "mushroom"
    OBJECTS.append(cap)


def add_crystal(row: int, col: int, index: int) -> None:
    cell = CELLS[(row, col)]
    z = top_z(cell)
    height = RNG.uniform(0.8, 2.8)
    bpy.ops.mesh.primitive_cone_add(vertices=6, radius1=RNG.uniform(0.16, 0.38), radius2=0.02, depth=height, location=(col + 0.5, row + 0.5, z + height / 2))
    obj = bpy.context.object
    obj.name = f"Crystal_{index}"
    obj.rotation_euler[0] = RNG.uniform(-0.16, 0.16)
    obj.rotation_euler[1] = RNG.uniform(-0.16, 0.16)
    obj.data.materials.append(MATERIALS["crystal"])
    obj["prototype_kind"] = "crystal"
    OBJECTS.append(obj)


def add_rock(row: int, col: int, index: int) -> None:
    cell = CELLS[(row, col)]
    z = top_z(cell)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=RNG.uniform(0.25, 0.75), location=(col + 0.5, row + 0.5, z + 0.18))
    obj = bpy.context.object
    obj.name = f"Rock_{index}"
    obj.scale = (RNG.uniform(0.7, 1.3), RNG.uniform(0.7, 1.3), RNG.uniform(0.45, 1.0))
    obj.data.materials.append(MATERIALS["rock"])
    obj["prototype_kind"] = "rock"
    OBJECTS.append(obj)


def build_environment_props() -> dict[str, int]:
    basin = [point for point, cell in CELLS.items() if cell["walkable"] and cell["zone"] in {"fungal_basin", "fungal_basin"}]
    northern = [point for point, cell in CELLS.items() if cell["walkable"] and cell["zone"] == "northern_ruin"]
    central = [point for point, cell in CELLS.items() if cell["walkable"] and cell["zone"] in {"central_cavern", "western_ridge"}]
    RNG.shuffle(basin)
    RNG.shuffle(northern)
    RNG.shuffle(central)
    for index, (row, col) in enumerate(basin[:46]):
        add_mushroom(row, col, index)
    for index, (row, col) in enumerate(northern[:28]):
        add_crystal(row, col, index)
    for index, (row, col) in enumerate(central[:48]):
        add_rock(row, col, index)

    ruin_z = top_z(CELLS[(6, 35)])
    for index, (x, y) in enumerate(((32, 5), (38, 5), (32, 9), (38, 9))):
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.42, depth=3.6, location=(x + 0.5, y + 0.5, ruin_z + 1.8))
        pillar = bpy.context.object
        pillar.name = f"RuinPillar_{index}"
        pillar.data.materials.append(MATERIALS["ruin"])
        pillar["prototype_kind"] = "ruin"
        OBJECTS.append(pillar)
    cube("RuinWallNorth", (35.5, 4.8, ruin_z + 1.0), (7.5, 0.32, 2.0), MATERIALS["ruin"], kind="ruin")
    cube("RuinDais", (35.5, 7.2, ruin_z + 0.22), (5.0, 3.0, 0.44), MATERIALS["ruin_dais"], kind="ruin")

    start_row, start_col = SPEC["anchors"]["party_start"]
    start_z = top_z(CELLS[(start_row, start_col)])
    bpy.ops.mesh.primitive_torus_add(major_radius=0.65, minor_radius=0.08, major_segments=24, minor_segments=8, location=(start_col + 0.5, start_row + 0.5, start_z + 0.08))
    marker = bpy.context.object
    marker.name = "PartyStartMarker"
    marker.data.materials.append(MATERIALS["start"])
    marker["prototype_kind"] = "anchor"
    OBJECTS.append(marker)
    return {"mushrooms": 46, "crystals": 28, "rocks": 48, "ruin_pillars": 4}


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def setup_scene() -> bpy.types.Object:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1000
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.002, 0.004, 0.012, 1)
    bg.inputs["Strength"].default_value = 0.18

    bpy.ops.object.light_add(type="AREA", location=(18, -12, 34))
    key = bpy.context.object
    key.data.energy = 2600
    key.data.color = (0.23, 0.38, 1.0)
    key.data.size = 18
    look_at(key, (24, 18, 0))
    bpy.ops.object.light_add(type="AREA", location=(48, 28, 22))
    fill = bpy.context.object
    fill.data.energy = 2100
    fill.data.color = (0.55, 0.12, 1.0)
    fill.data.size = 15
    look_at(fill, (24, 18, 0))
    for index, (x, y, color) in enumerate(((40, 24, (0.05, 1.0, 0.72)), (35, 6, (0.7, 0.1, 1.0)), (23, 26, (0.15, 0.35, 1.0)))):
        bpy.ops.object.light_add(type="POINT", location=(x, y, 4.0))
        light = bpy.context.object
        light.name = f"CaveGlow_{index}"
        light.data.energy = 850
        light.data.color = color
        light.data.shadow_soft_size = 6.0

    bpy.ops.object.camera_add(location=(74, -62, 58))
    camera = bpy.context.object
    camera.name = "UnderdarkCamera"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 62
    look_at(camera, (24, 18, 0.8))
    scene.camera = camera
    return camera


def render(camera: bpy.types.Object, filename: str, location: tuple[float, float, float], target: tuple[float, float, float], ortho: float) -> None:
    camera.location = location
    camera.data.ortho_scale = ortho
    look_at(camera, target)
    bpy.context.scene.render.filepath = str(OUTPUT / filename)
    bpy.ops.render.render(write_still=True)


def export_glb() -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in OBJECTS:
        if obj.type in {"MESH", "CURVE", "FONT"}:
            obj.select_set(True)
    props = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    kwargs: dict[str, Any] = {"filepath": str(OUTPUT / "underdark-dm.glb"), "export_format": "GLB"}
    if "use_selection" in props:
        kwargs["use_selection"] = True
    elif "export_selected" in props:
        kwargs["export_selected"] = True
    if "export_extras" in props:
        kwargs["export_extras"] = True
    bpy.ops.export_scene.gltf(**kwargs)
    bpy.ops.object.select_all(action="DESELECT")


def build() -> None:
    clean_scene()
    terrain_colors = (
        (0.055, 0.11, 0.15, 1),
        (0.08, 0.12, 0.19, 1),
        (0.11, 0.12, 0.24, 1),
        (0.16, 0.12, 0.28, 1),
        (0.24, 0.14, 0.36, 1),
    )
    for index, color in enumerate(terrain_colors):
        make_material(f"terrain_{index}", color, roughness=0.86)
    make_material("grid", (0.02, 0.38, 0.48, 1), metallic=0.12, roughness=0.42, emission=0.18)
    make_material("abyss", (0.002, 0.004, 0.012, 1), metallic=0.1, roughness=0.28)
    make_material("chasm_glow", (0.13, 0.02, 0.38, 1), metallic=0.05, roughness=0.25, emission=2.0)
    make_material("bridge", (0.25, 0.23, 0.31, 1), roughness=0.78)
    make_material("bridge_rail", (0.46, 0.42, 0.52, 1), metallic=0.2, roughness=0.6)
    make_material("mushroom_stem", (0.12, 0.38, 0.42, 1), roughness=0.7, emission=0.15)
    make_material("mushroom_cap", (0.02, 0.9, 0.68, 1), roughness=0.38, emission=1.6)
    make_material("crystal", (0.58, 0.08, 1.0, 1), metallic=0.32, roughness=0.22, emission=1.1)
    make_material("rock", (0.075, 0.085, 0.12, 1), roughness=0.92)
    make_material("ruin", (0.32, 0.3, 0.42, 1), roughness=0.82)
    make_material("ruin_dais", (0.38, 0.22, 0.52, 1), roughness=0.68)
    make_material("start", (1.0, 0.45, 0.04, 1), metallic=0.2, roughness=0.32, emission=1.1)

    camera = setup_scene()
    build_chasm()
    build_terrain()
    build_bridges()
    prop_counts = build_environment_props()
    render(camera, "underdark-isometric.png", (74, -62, 58), (24, 18, 0.8), 62)
    render(camera, "underdark-topdown.png", (24, 18, 76), (24, 18, 0), 55)
    camera.location = (74, -62, 58)
    camera.data.ortho_scale = 62
    look_at(camera, (24, 18, 0.8))
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "underdark-prototype.blend"))
    export_glb()

    grid_payload = {
        "schema_version": SPEC["schema_version"],
        "width": SPEC["width"],
        "height": SPEC["height"],
        "cell_size_ft": SPEC["cell_size_ft"],
        "elevation_step_ft": SPEC["elevation_step_ft"],
        "anchors": SPEC["anchors"],
        "cells": [
            {
                "row": row,
                "col": col,
                "elevation": int(cell["elevation"]),
                "zone": cell["zone"],
                "walkable": bool(cell["walkable"]),
                "movement_cost": int(cell["movement_cost"]),
            }
            for (row, col), cell in sorted(CELLS.items())
        ],
    }
    (OUTPUT / "underdark-grid.json").write_text(
        json.dumps(grid_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    manifest = {
        "status": "generated",
        "schema_version": SPEC["schema_version"],
        "seed": SPEC["seed"],
        "source_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
        "validation": VALIDATION,
        "prototype_objects": len(OBJECTS),
        "props": prop_counts,
        "outputs": [
            "underdark-isometric.png",
            "underdark-topdown.png",
            "underdark-dm.glb",
            "underdark-prototype.blend",
            "underdark-grid.json",
        ],
    }
    (OUTPUT / "underdark-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
