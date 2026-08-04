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
SPEC_PATH = ROOT / "specs" / "church.json"
OUTPUT = ROOT / "output"
OUTPUT.mkdir(parents=True, exist_ok=True)

CELL = 1.0
FLOOR_HEIGHT = 3.4
WALL_HEIGHT = 2.35
WALL_THICKNESS = 0.12
SLAB_HEIGHT = 0.12

SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
OBJECTS: list[bpy.types.Object] = []
SECRET_DOORS: list[bpy.types.Object] = []
LEVEL_COLLECTIONS: dict[int, bpy.types.Collection] = {}
MATERIALS: dict[str, bpy.types.Material] = {}


def clean_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    metallic: float = 0.0,
    roughness: float = 0.65,
    emission_strength: float = 0.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        if emission_strength and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = color
            bsdf.inputs["Emission Strength"].default_value = emission_strength
    MATERIALS[name] = mat
    return mat


def move_to_collection(obj: bpy.types.Object, collection: bpy.types.Collection) -> None:
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)


def tag_object(
    obj: bpy.types.Object,
    *,
    level: int = 0,
    room_id: str = "",
    visibility: str = "public",
    kind: str = "geometry",
) -> bpy.types.Object:
    obj["prototype"] = True
    obj["level_index"] = level
    obj["room_id"] = room_id
    obj["prototype_visibility"] = visibility
    obj["prototype_kind"] = kind
    OBJECTS.append(obj)
    if level in LEVEL_COLLECTIONS:
        move_to_collection(obj, LEVEL_COLLECTIONS[level])
    return obj


def cube(
    name: str,
    location: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    mat: bpy.types.Material,
    *,
    level: int = 0,
    room_id: str = "",
    visibility: str = "public",
    kind: str = "geometry",
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    obj.data.materials.append(mat)
    return tag_object(obj, level=level, room_id=room_id, visibility=visibility, kind=kind)


def cylinder(
    name: str,
    location: tuple[float, float, float],
    radius: float,
    depth: float,
    mat: bpy.types.Material,
    *,
    level: int,
    room_id: str,
    visibility: str = "public",
    vertices: int = 20,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return tag_object(obj, level=level, room_id=room_id, visibility=visibility, kind="prop")


def text_label(
    text: str,
    location: tuple[float, float, float],
    *,
    size: float,
    level: int,
    room_id: str = "",
    visibility: str = "public",
    mat: bpy.types.Material | None = None,
) -> bpy.types.Object:
    bpy.ops.object.text_add(location=location)
    obj = bpy.context.object
    obj.name = f"Label_{text}_{level}"
    obj.data.body = text
    obj.data.align_x = "CENTER"
    obj.data.align_y = "CENTER"
    obj.data.size = size
    obj.data.extrude = 0.01
    if mat:
        obj.data.materials.append(mat)
    return tag_object(obj, level=level, room_id=room_id, visibility=visibility, kind="label")


def room_cells(room: dict[str, Any]) -> set[tuple[int, int]]:
    b = room["bounds"]
    return {
        (row, col)
        for row in range(b["row"], b["row"] + b["height"])
        for col in range(b["col"], b["col"] + b["width"])
    }


def boundary_key(left: tuple[int, int], right: tuple[int, int]) -> frozenset[tuple[int, int]]:
    return frozenset((left, right))


def boundary_transform(
    left: tuple[int, int], right: tuple[int, int], z: float
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    row_a, col_a = left
    row_b, col_b = right
    if row_a == row_b:
        x = max(col_a, col_b)
        y = row_a + 0.5
        return (x, y, z + WALL_HEIGHT / 2), (WALL_THICKNESS, 1.0 + WALL_THICKNESS, WALL_HEIGHT)
    y = max(row_a, row_b)
    x = col_a + 0.5
    return (x, y, z + WALL_HEIGHT / 2), (1.0 + WALL_THICKNESS, WALL_THICKNESS, WALL_HEIGHT)


def add_threshold(
    connector: dict[str, Any], level: int, z: float, secret: bool
) -> None:
    left = tuple(connector["from_cell"])
    right = tuple(connector["to_cell"])
    row_a, col_a = left
    row_b, col_b = right
    if row_a == row_b:
        dims = (0.18, 0.74, 0.035)
        loc = (max(col_a, col_b), row_a + 0.5, z + 0.09)
    else:
        dims = (0.74, 0.18, 0.035)
        loc = (col_a + 0.5, max(row_a, row_b), z + 0.09)
    cube(
        f"{'Secret' if secret else 'Door'}Threshold_{connector['id']}",
        loc,
        dims,
        MATERIALS["secret"] if secret else MATERIALS["door"],
        level=level,
        room_id=connector["to_room"],
        visibility="dm_only" if secret else "public",
        kind="secret_door" if secret else "door",
    )


def add_room_floor(level: int, room: dict[str, Any], z: float) -> None:
    b = room["bounds"]
    secret = room.get("visibility") == "dm_only"
    floor_mat = MATERIALS["secret_floor"] if secret else MATERIALS[f"floor_{level}"]
    cx = b["col"] + b["width"] / 2
    cy = b["row"] + b["height"] / 2
    cube(
        f"Floor_{room['id']}",
        (cx, cy, z - SLAB_HEIGHT / 2),
        (b["width"], b["height"], SLAB_HEIGHT),
        floor_mat,
        level=level,
        room_id=room["id"],
        visibility=room.get("visibility", "public"),
        kind="floor",
    )

    grid_visibility = room.get("visibility", "public")
    line_z = z + 0.012
    for col in range(b["col"], b["col"] + b["width"] + 1):
        cube(
            f"GridV_{room['id']}_{col}",
            (col, cy, line_z),
            (0.025, b["height"], 0.018),
            MATERIALS["grid"],
            level=level,
            room_id=room["id"],
            visibility=grid_visibility,
            kind="grid",
        )
    for row in range(b["row"], b["row"] + b["height"] + 1):
        cube(
            f"GridH_{room['id']}_{row}",
            (cx, row, line_z),
            (b["width"], 0.025, 0.018),
            MATERIALS["grid"],
            level=level,
            room_id=room["id"],
            visibility=grid_visibility,
            kind="grid",
        )
    text_label(
        room["label"],
        (cx, cy, z + 0.035),
        size=min(0.48, 3.2 / max(len(room["label"]), 1)),
        level=level,
        room_id=room["id"],
        visibility=grid_visibility,
        mat=MATERIALS["label_secret"] if secret else MATERIALS["label"],
    )


def add_walls(level_data: dict[str, Any], z: float) -> None:
    level = level_data["level_index"]
    rooms = {room["id"]: room for room in level_data["rooms"]}
    occupancy: dict[tuple[int, int], str] = {}
    for room in level_data["rooms"]:
        for cell in room_cells(room):
            occupancy[cell] = room["id"]

    connectors = {
        boundary_key(tuple(item["from_cell"]), tuple(item["to_cell"])): item
        for item in level_data["connectors"]
    }
    seen: set[frozenset[tuple[int, int]]] = set()
    directions = ((0, 1), (1, 0), (0, -1), (-1, 0))
    for cell, room_id in sorted(occupancy.items()):
        for delta_row, delta_col in directions:
            neighbor = (cell[0] + delta_row, cell[1] + delta_col)
            neighbor_room = occupancy.get(neighbor)
            if neighbor_room == room_id:
                continue
            key = boundary_key(cell, neighbor)
            if key in seen:
                continue
            seen.add(key)
            connector = connectors.get(key)
            if connector and connector["connector_type"] == "door":
                add_threshold(connector, level, z, False)
                continue

            current_secret = rooms[room_id].get("visibility") == "dm_only"
            neighbor_secret = bool(neighbor_room and rooms[neighbor_room].get("visibility") == "dm_only")
            shared_with_public = neighbor_room is not None and current_secret != neighbor_secret
            secret_wall = current_secret and not shared_with_public
            loc, dims = boundary_transform(cell, neighbor, z)
            is_secret_door = bool(connector and connector["connector_type"] == "secret_door")
            obj = cube(
                f"Wall_{level}_{cell[0]}_{cell[1]}_{neighbor[0]}_{neighbor[1]}",
                loc,
                dims,
                MATERIALS["secret_door"] if is_secret_door else MATERIALS["wall"],
                level=level,
                room_id=room_id,
                visibility="dm_only" if secret_wall else "public",
                kind="secret_door" if is_secret_door else "wall",
            )
            if is_secret_door:
                obj["dm_material"] = MATERIALS["secret_door"].name
                obj["player_material"] = MATERIALS["wall"].name
                SECRET_DOORS.append(obj)
                add_threshold(connector, level, z, True)


def add_stairs(level_data: dict[str, Any], z: float) -> None:
    level = level_data["level_index"]
    for stair in level_data["stairs"]:
        if stair["direction"] != "up":
            continue
        row, col = stair["row"], stair["col"]
        for step in range(9):
            rise = FLOOR_HEIGHT * (step + 1) / 10
            cube(
                f"Stair_{stair['id']}_{step:02d}",
                (col + 0.5, row + 0.18 + step * 0.16, z + rise / 2),
                (0.84, 0.22, rise),
                MATERIALS["stairs"],
                level=level,
                kind="stairs",
            )
        text_label(
            f"UP TO L{stair['to_level']}",
            (col + 0.5, row - 0.25, z + 0.04),
            size=0.22,
            level=level,
            mat=MATERIALS["stairs"],
        )


def add_prop_box(
    name: str,
    room: dict[str, Any],
    level: int,
    z: float,
    offset: tuple[float, float],
    dims: tuple[float, float, float],
    mat: bpy.types.Material,
) -> None:
    b = room["bounds"]
    visibility = room.get("visibility", "public")
    cube(
        name,
        (b["col"] + offset[0], b["row"] + offset[1], z + dims[2] / 2),
        dims,
        mat,
        level=level,
        room_id=room["id"],
        visibility=visibility,
        kind="prop",
    )


def add_furnishings(level_data: dict[str, Any], z: float) -> None:
    level = level_data["level_index"]
    for room in level_data["rooms"]:
        b = room["bounds"]
        room_type = room["room_type"]
        if room_type == "public_hall":
            for index, row_offset in enumerate((2.0, 4.0, 6.0, 8.0)):
                add_prop_box(f"Pew_{level}_{index}_A", room, level, z, (3.0, row_offset), (3.2, 0.42, 0.48), MATERIALS["wood"])
                add_prop_box(f"Pew_{level}_{index}_B", room, level, z, (7.0, row_offset), (3.2, 0.42, 0.48), MATERIALS["wood"])
            add_prop_box("Altar", room, level, z, (5.0, 1.0), (2.8, 0.8, 1.0), MATERIALS["altar"])
        elif room_type == "library":
            for index, offset in enumerate((1.0, 2.5, 4.0)):
                add_prop_box(f"Shelf_{level}_{index}", room, level, z, (b["width"] - 0.35, offset), (0.45, 1.4, 1.65), MATERIALS["wood"])
        elif room_type == "private":
            add_prop_box(f"Bed_{room['id']}", room, level, z, (1.6, 1.3), (2.2, 1.1, 0.55), MATERIALS["wood"])
        elif room_type == "tower":
            cylinder("Bell", (b["col"] + b["width"] / 2, b["row"] + b["height"] / 2, z + 1.25), 1.1, 1.55, MATERIALS["bell"], level=level, room_id=room["id"], vertices=24)
        elif room_type == "secret_room":
            add_prop_box(f"SecretTable_{room['id']}", room, level, z, (b["width"] / 2, b["height"] / 2), (1.4, 0.8, 0.7), MATERIALS["secret"],)


def add_level(level_data: dict[str, Any]) -> None:
    level = level_data["level_index"]
    z = (level - 1) * FLOOR_HEIGHT
    for room in level_data["rooms"]:
        add_room_floor(level, room, z)
    add_walls(level_data, z)
    add_stairs(level_data, z)
    add_furnishings(level_data, z)
    text_label(
        f"LEVEL {level}  +{round(z / CELL * 5)} FT",
        (-0.7, 1.2, z + 0.05),
        size=0.45,
        level=level,
        mat=MATERIALS["level_label"],
    )


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def create_environment() -> tuple[bpy.types.Object, bpy.types.Object]:
    world = bpy.context.scene.world or bpy.data.worlds.new("PrototypeWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.012, 0.018, 0.035, 1)
    background.inputs["Strength"].default_value = 0.32

    bpy.ops.object.light_add(type="AREA", location=(5, -8, 24))
    key = bpy.context.object
    key.name = "KeyLight"
    key.data.energy = 1900
    key.data.shape = "DISK"
    key.data.size = 11
    look_at(key, (10, 8, 4))

    bpy.ops.object.light_add(type="AREA", location=(24, 18, 14))
    fill = bpy.context.object
    fill.name = "FillLight"
    fill.data.energy = 1100
    fill.data.color = (0.34, 0.55, 1.0)
    fill.data.size = 10
    look_at(fill, (10, 8, 4))

    bpy.ops.object.light_add(type="SUN", location=(0, 0, 20))
    sun = bpy.context.object
    sun.name = "Sun"
    sun.rotation_euler = (math.radians(28), math.radians(-24), math.radians(-30))
    sun.data.energy = 1.4

    bpy.ops.object.camera_add(location=(31, -29, 26))
    camera = bpy.context.object
    camera.name = "IsometricCamera"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 29
    look_at(camera, (10, 8, 4.5))
    bpy.context.scene.camera = camera

    cube("PresentationBase", (9.8, 8.0, -0.42), (24, 20, 0.45), MATERIALS["base"], kind="base")
    return camera, key


def configure_render() -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 850
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.render.resolution_percentage = 100


def set_mode(mode: str, levels: set[int] | None = None) -> None:
    for obj in OBJECTS:
        level = int(obj.get("level_index", 0))
        hidden = bool(levels is not None and level not in levels and level != 0)
        if mode == "player" and obj.get("prototype_visibility") == "dm_only":
            hidden = True
        obj.hide_render = hidden
        obj.hide_viewport = hidden
    for obj in SECRET_DOORS:
        material_name = obj.get("player_material") if mode == "player" else obj.get("dm_material")
        if material_name and obj.data.materials:
            obj.data.materials[0] = bpy.data.materials[material_name]


def render_view(
    filename: str,
    camera: bpy.types.Object,
    *,
    mode: str,
    levels: set[int] | None,
    location: tuple[float, float, float],
    target: tuple[float, float, float],
    ortho_scale: float,
    exploded: bool = False,
) -> None:
    set_mode(mode, levels)
    original_locations: dict[str, Vector] = {}
    if exploded:
        for obj in OBJECTS:
            level = int(obj.get("level_index", 0))
            if level > 0:
                original_locations[obj.name] = obj.location.copy()
                obj.location.x += (level - 1) * 2.8
                obj.location.z += (level - 1) * 2.0
    camera.location = location
    camera.data.ortho_scale = ortho_scale
    look_at(camera, target)
    bpy.context.scene.render.filepath = str(OUTPUT / filename)
    bpy.ops.render.render(write_still=True)
    for name, location_before in original_locations.items():
        bpy.data.objects[name].location = location_before


def export_glb(filename: str, mode: str) -> None:
    set_mode(mode, None)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in OBJECTS:
        if not obj.hide_render and obj.type in {"MESH", "CURVE", "FONT"}:
            obj.select_set(True)
    props = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    kwargs: dict[str, Any] = {"filepath": str(OUTPUT / filename), "export_format": "GLB"}
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
    configure_render()

    material("wall", (0.52, 0.56, 0.63, 1), roughness=0.82)
    material("floor_1", (0.22, 0.28, 0.35, 1), roughness=0.75)
    material("floor_2", (0.18, 0.32, 0.37, 1), roughness=0.72)
    material("floor_3", (0.24, 0.24, 0.42, 1), roughness=0.72)
    material("secret_floor", (0.45, 0.025, 0.62, 1), roughness=0.55, emission_strength=0.18)
    material("grid", (0.035, 0.055, 0.075, 1), metallic=0.08, roughness=0.5)
    material("door", (0.93, 0.55, 0.12, 1), metallic=0.25, roughness=0.42)
    material("secret_door", (1.0, 0.025, 0.64, 1), metallic=0.12, roughness=0.38, emission_strength=0.35)
    material("secret", (0.72, 0.035, 0.95, 1), metallic=0.1, roughness=0.42, emission_strength=0.22)
    material("stairs", (0.22, 0.72, 0.95, 1), metallic=0.15, roughness=0.42)
    material("wood", (0.24, 0.09, 0.035, 1), roughness=0.72)
    material("altar", (0.72, 0.58, 0.29, 1), metallic=0.15, roughness=0.52)
    material("bell", (0.64, 0.34, 0.07, 1), metallic=0.78, roughness=0.28)
    material("label", (0.78, 0.9, 1.0, 1), metallic=0.05, roughness=0.4)
    material("label_secret", (1.0, 0.34, 0.83, 1), metallic=0.05, roughness=0.4)
    material("level_label", (0.25, 0.8, 1.0, 1), metallic=0.15, roughness=0.35)
    material("base", (0.018, 0.028, 0.055, 1), metallic=0.08, roughness=0.72)

    root_collection = bpy.context.scene.collection
    for level in (1, 2, 3):
        collection = bpy.data.collections.new(f"LEVEL_{level}")
        root_collection.children.link(collection)
        LEVEL_COLLECTIONS[level] = collection

    camera, _ = create_environment()
    for level_data in SPEC["levels"]:
        add_level(level_data)

    metadata = bpy.data.objects.new("PrototypeMetadata", None)
    bpy.context.scene.collection.objects.link(metadata)
    metadata["schema_version"] = SPEC["schema_version"]
    metadata["seed"] = SPEC["seed"]
    metadata["site_name"] = SPEC["site"]["name"]
    metadata["source_sha256"] = hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()

    render_view(
        "church-dm-exploded.png",
        camera,
        mode="dm",
        levels=None,
        location=(39, -34, 36),
        target=(13, 8, 7.2),
        ortho_scale=34,
        exploded=True,
    )
    render_view(
        "church-player-floor1.png",
        camera,
        mode="player",
        levels={1},
        location=(25, -23, 30),
        target=(10, 8, 0.5),
        ortho_scale=22,
    )
    for level in (1, 2, 3):
        z = (level - 1) * FLOOR_HEIGHT
        render_view(
            f"church-dm-floor{level}.png",
            camera,
            mode="dm",
            levels={level},
            location=(25, -23, z + 30),
            target=(10, 8, z + 0.5),
            ortho_scale=22,
        )

    set_mode("dm", None)
    camera.location = (31, -29, 26)
    camera.data.ortho_scale = 29
    look_at(camera, (10, 8, 4.6))
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "church-prototype.blend"))
    export_glb("church-dm.glb", "dm")
    export_glb("church-player.glb", "player")
    set_mode("dm", None)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "church-prototype.blend"))

    manifest = {
        "status": "generated",
        "schema_version": SPEC["schema_version"],
        "seed": SPEC["seed"],
        "source_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
        "levels": len(SPEC["levels"]),
        "rooms": sum(len(level["rooms"]) for level in SPEC["levels"]),
        "secret_rooms": sum(
            room.get("visibility") == "dm_only"
            for level in SPEC["levels"]
            for room in level["rooms"]
        ),
        "prototype_objects": len(OBJECTS),
        "secret_door_objects": len(SECRET_DOORS),
        "outputs": sorted(path.name for path in OUTPUT.iterdir() if path.is_file()),
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
