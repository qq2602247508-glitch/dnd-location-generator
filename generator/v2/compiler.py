from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from pathlib import Path
from typing import Any

from .mask import Cell, CellMask, neighbors
from .rng import named_rng, named_seed

GENERATOR_VERSION = "2.1.0-prototype.1"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema_version") != "dnd-scene-spec-2.0":
        raise ValueError("unsupported scene spec schema")
    scene, grid = spec.get("scene", {}), spec.get("grid", {})
    if not scene.get("id") or not scene.get("name") or not isinstance(scene.get("seed"), int):
        raise ValueError("scene requires stable id, name and integer seed")
    if int(grid.get("width", 0)) < 24 or int(grid.get("height", 0)) < 24 or int(grid.get("cell_size_ft", 0)) <= 0:
        raise ValueError("grid dimensions/cell size are invalid")
    if spec.get("brief", {}).get("archetype") != "harbor_district":
        raise ValueError("prototype.1 currently ships only the harbor_district archetype pack")
    packs = spec.get("packs")
    if not isinstance(packs, list) or not packs or any(not item.get("id") or not item.get("version") for item in packs):
        raise ValueError("every scene must pin at least one versioned generation pack")


def cell_id(level_id: str, cell: Cell) -> str:
    return f"{level_id}:{cell[0]}:{cell[1]}"


def endpoint(level_id: str, cell: Cell, *, volume_id: str = "", room_id: str = "") -> dict[str, Any]:
    return {"level_id": level_id, "row": cell[0], "col": cell[1], "volume_id": volume_id, "room_id": room_id}


def first_shared_edge(left: CellMask, right: CellMask) -> tuple[Cell, Cell]:
    for point in left.sorted_cells():
        for neighbor in neighbors(point):
            if neighbor in right.cells:
                return point, neighbor
    raise ValueError("masks do not share a cell edge")


def closest_cell(mask: CellMask, target: Cell) -> Cell:
    return min(mask.cells, key=lambda point: (abs(point[0] - target[0]) + abs(point[1] - target[1]), point))


def split_mask(mask: CellMask, axis: str = "col") -> tuple[CellMask, CellMask]:
    values = sorted(point[1 if axis == "col" else 0] for point in mask.cells)
    pivot = values[len(values) // 2]
    if axis == "col":
        left = CellMask.from_cells(point for point in mask.cells if point[1] < pivot)
    else:
        left = CellMask.from_cells(point for point in mask.cells if point[0] < pivot)
    right = mask - left
    if not left.cells or not right.cells:
        ordered = mask.sorted_cells()
        left = CellMask.from_cells(ordered[: len(ordered) // 2])
        right = mask - left
    return left, right


def l_shape(row: int, col: int, height: int, width: int, notch_h: int = 2, notch_w: int = 2) -> CellMask:
    whole = CellMask.rect(row, col, height, width)
    notch = CellMask.rect(row + height - notch_h, col + width - notch_w, notch_h, notch_w)
    return whole - notch


def _hero(spec: dict[str, Any], volume_id: str) -> dict[str, Any]:
    value = spec.get("heroes", {}).get(volume_id, {})
    if not isinstance(value, dict):
        raise ValueError(f"hero metadata must be an object: {volume_id}")
    return value


def _room_profile(spec: dict[str, Any], blueprint: dict[str, Any], level_index: int, slot: int) -> dict[str, Any]:
    configured = _hero(spec, blueprint["id"]).get("room_program", [])
    if configured:
        level = configured[level_index - 1]
        return dict(level["rooms"][slot])
    defaults: dict[str, list[tuple[str, str, list[str]]]] = {
        "warehouse": [("收货厅", "receiving", ["cargo", "work"]), ("仓储间", "storage", ["cargo", "private"])],
        "shrine": [("潮声礼拜堂", "nave", ["sacred", "public"]), ("祭具间", "vestry", ["sacred", "service"])],
        "manor": [("蓝灯会客厅", "salon", ["domestic", "public"]), ("私室", "private_room", ["domestic", "private"])],
        "market": [("鱼市售卖厅", "market_hall", ["trade", "public"]), ("处理间", "preparation", ["trade", "service"])],
        "watchhouse": [("巡守值勤厅", "duty_room", ["watch", "public"]), ("器械拘留间", "holding", ["watch", "secure"])],
        "shop": [("船具铺面", "salesfloor", ["trade", "public"]), ("绳具工坊", "workshop", ["trade", "work"])]
    }
    pair = defaults.get(blueprint["archetype"], [("前厅", "public_hall", ["public"]), ("后间", "service_room", ["service"])])
    name, role, tags = pair[slot]
    if level_index > 1:
        name = f"{name} · 上层"
        tags = [*tags, "upper_floor"]
    return {"name": name, "role": role, "tags": tags}


def _shortest_path(mask: CellMask, start: Cell, goal: Cell) -> list[Cell]:
    if start == goal:
        return [start]
    queue = deque([start])
    previous: dict[Cell, Cell | None] = {start: None}
    while queue:
        current = queue.popleft()
        for target in neighbors(current):
            if target not in mask.cells or target in previous:
                continue
            previous[target] = current
            if target == goal:
                path = [goal]
                while path[-1] != start:
                    parent = previous[path[-1]]
                    assert parent is not None
                    path.append(parent)
                return list(reversed(path))
            queue.append(target)
    raise AssertionError(f"no internal room path: {start} -> {goal}")


FEATURE_RECIPES: dict[str, list[tuple[str, bool, tuple[int, int, int], list[str]]]] = {
    "guard_post": [("guard_desk", True, (5, 3, 3), ["furniture", "watch"]), ("weapon_rack", True, (5, 2, 6), ["storage", "watch"]), ("chair", False, (2, 2, 3), ["furniture"])],
    "equipment_store": [("supply_shelf", True, (5, 2, 6), ["storage"]), ("signal_crate", True, (5, 5, 4), ["cargo"])],
    "sleeping_quarters": [("bunk_bed", True, (5, 8, 5), ["bed", "domestic"]), ("footlocker", True, (3, 2, 2), ["storage"]), ("washstand", False, (2, 2, 3), ["furniture"])],
    "living_landing": [("mess_table", True, (5, 5, 3), ["table", "domestic"]), ("bench", False, (5, 2, 3), ["furniture"])],
    "machinery": [("signal_winch", True, (8, 8, 7), ["machinery", "hero"]), ("gear_rack", True, (5, 2, 6), ["machinery"]), ("tool_table", True, (5, 3, 3), ["table", "work"])],
    "signal_room": [("signal_chart_table", True, (5, 5, 3), ["table", "signal"]), ("shutter_controls", False, (3, 2, 5), ["machinery", "signal"])],
    "beacon_chamber": [("harbor_beacon", True, (8, 8, 9), ["beacon", "hero", "light"]), ("oil_reservoir", True, (4, 4, 5), ["fuel", "machinery"])],
    "observation_gallery": [("brass_telescope", False, (5, 3, 5), ["signal", "vista"]), ("signal_flag_rack", True, (5, 2, 6), ["signal", "storage"])],
    "tavern": [("bar_counter", True, (10, 3, 4), ["bar", "furniture"]), ("tavern_table", True, (5, 5, 3), ["table"]), ("stool_cluster", False, (4, 4, 3), ["seating"]), ("ale_barrel", True, (3, 3, 4), ["barrel", "storage"])],
    "kitchen_store": [("prep_table", True, (5, 4, 3), ["table", "kitchen"]), ("pantry_shelf", True, (5, 2, 6), ["shelf", "storage"]), ("wine_barrel", True, (3, 3, 4), ["barrel", "storage"])],
    "guest_room": [("guest_bed", True, (5, 8, 4), ["bed", "domestic"]), ("bedside_table", False, (2, 2, 2), ["table"]), ("travel_chest", True, (4, 3, 3), ["storage"])],
    "guest_corridor": [("corridor_bench", False, (5, 2, 3), ["seating"]), ("wall_lantern", False, (1, 1, 5), ["light"])],
    "sewer_main": [("sewer_pipe", True, (5, 3, 4), ["pipe", "infrastructure"]), ("maintenance_bridge", False, (5, 10, 1), ["bridge", "crossing"]), ("fungus_patch", False, (4, 4, 1), ["fungus", "damp"]), ("rat_tracks", False, (2, 4, 1), ["rats", "clue"])],
    "sewage_channel": [("drain_pipe", False, (4, 4, 4), ["pipe", "sewage"]), ("floating_debris", False, (4, 4, 1), ["sewage", "debris"]), ("rat_tracks", False, (2, 4, 1), ["rats", "clue"])],
    "secret_cistern": [("sealed_cache", True, (5, 5, 4), ["secret", "storage"]), ("ritual_table", True, (5, 5, 3), ["table", "secret"]), ("luminous_fungus", False, (3, 3, 2), ["fungus", "light"])]
}


def _volume_presentation(spec: dict[str, Any], blueprint: dict[str, Any]) -> dict[str, Any]:
    hero = _hero(spec, blueprint["id"])
    defaults = {
        "style": {"family": "working_harbor", "condition": "salt_weathered"},
        "roof": {"shape": "pitched", "material": "dark_tile"},
        "facade": {"primary": "gray_stone", "accents": ["dark_timber"]},
    }
    return {key: hero.get(key, value) for key, value in defaults.items()}


def _surface_layout(height: int, width: int, seed: int) -> dict[str, CellMask]:
    shore_rng = named_rng(seed, "terrain:shoreline")
    phases = [shore_rng.uniform(-0.8, 0.8) for _ in range(3)]
    water_cells: set[Cell] = set()
    for row in range(height):
        shoreline = round(width * 0.81 + 2.2 * math.sin(row / 6.0 + phases[0]) + 1.2 * math.sin(row / 2.8 + phases[1]))
        for col in range(max(0, shoreline), width):
            water_cells.add((row, col))
    water = CellMask.from_cells(water_cells)
    main_road = CellMask.path([(0, 30), (10, 27), (21, 31), (34, 27), (45, 31), (height - 1, 29)], radius=2).clipped(height, width)
    alleys = (
        CellMask.path([(10, 4), (10, 28), (12, 51)], radius=1)
        | CellMask.path([(27, 3), (26, 29), (29, 55)], radius=1)
        | CellMask.path([(45, 6), (43, 30), (46, 56)], radius=1)
    ).clipped(height, width)
    docks = CellMask.path([(7, 55), (18, 56), (33, 55), (48, 56)], radius=1).clipped(height, width) - water
    return {"water": water, "main_road": main_road, "alleys": alleys, "docks": docks}


def _volume_blueprints() -> list[dict[str, Any]]:
    return [
        {"id": "signal_tower", "name": "潮钟信号塔", "kind": "tower", "archetype": "signal_tower", "base": CellMask.rect(4, 7, 7, 7), "levels": 4},
        {"id": "harbor_inn", "name": "盐风旅店", "kind": "building", "archetype": "inn", "base": l_shape(3, 18, 8, 8, 3, 3), "levels": 2},
        {"id": "rope_warehouse", "name": "七索仓库", "kind": "building", "archetype": "warehouse", "base": l_shape(14, 4, 8, 9, 3, 3), "levels": 1},
        {"id": "tide_temple", "name": "潮汐小圣堂", "kind": "building", "archetype": "shrine", "base": CellMask.rect(15, 17, 7, 7), "levels": 1},
        {"id": "lantern_manor", "name": "蓝灯宅邸", "kind": "building", "archetype": "manor", "base": l_shape(31, 5, 9, 10, 4, 4), "levels": 2},
        {"id": "fish_market", "name": "银鳞鱼市", "kind": "building", "archetype": "market", "base": l_shape(32, 18, 8, 9, 3, 3), "levels": 1},
        {"id": "harbor_watch", "name": "港务巡守所", "kind": "building", "archetype": "watchhouse", "base": CellMask.rect(46, 5, 7, 8), "levels": 2},
        {"id": "chandlery", "name": "灰鲸船具店", "kind": "building", "archetype": "shop", "base": l_shape(45, 18, 8, 9, 3, 3), "levels": 1},
        {"id": "dock_store", "name": "东堤货栈", "kind": "building", "archetype": "warehouse", "base": l_shape(17, 42, 8, 10, 3, 4), "levels": 1},
    ]


def compile_plan(spec: dict[str, Any]) -> dict[str, Any]:
    validate_spec(spec)
    scene = spec["scene"]
    seed = int(scene["seed"])
    width, height = int(spec["grid"]["width"]), int(spec["grid"]["height"])
    bounds = CellMask.rect(0, 0, height, width)
    layout = _surface_layout(height, width, seed)
    water = layout["water"]
    routes = layout["main_road"] | layout["alleys"] | layout["docks"]

    volumes: list[dict[str, Any]] = []
    levels: list[dict[str, Any]] = []
    rooms: list[dict[str, Any]] = []
    connectors: list[dict[str, Any]] = []
    parcels: list[dict[str, Any]] = []
    surface_footprints = CellMask.empty()

    for blueprint in _volume_blueprints():
        volume_id = blueprint["id"]
        base: CellMask = blueprint["base"]
        surface_footprints = surface_footprints | base
        parcel_mask = base.dilate(1).clipped(height, width)
        parcels.append({"id": f"parcel_{volume_id}", "cell_mask": parcel_mask.to_rle(), "street_access": True})
        level_ids: list[str] = []
        previous_mask = base
        for index in range(1, int(blueprint["levels"]) + 1):
            if blueprint["kind"] == "tower" and index > 1:
                rows = [p[0] for p in previous_mask.cells]
                cols = [p[1] for p in previous_mask.cells]
                previous_mask = CellMask.rect(min(rows), min(cols), max(rows) - min(rows), max(cols) - min(cols))
            level_id = f"{volume_id}_l{index}"
            level_ids.append(level_id)
            room_a, room_b = split_mask(previous_mask, "row" if index % 2 else "col")
            profile_a = _room_profile(spec, blueprint, index, 0)
            profile_b = _room_profile(spec, blueprint, index, 1)
            room_a_id, room_b_id = f"{level_id}_{profile_a['role']}", f"{level_id}_{profile_b['role']}"
            rooms.extend([
                {"id": room_a_id, "name": profile_a["name"], "level_id": level_id, "volume_id": volume_id, "role": profile_a["role"], "tags": profile_a["tags"], "visibility": "public", "cell_mask": room_a.to_rle()},
                {"id": room_b_id, "name": profile_b["name"], "level_id": level_id, "volume_id": volume_id, "role": profile_b["role"], "tags": profile_b["tags"], "visibility": "public", "cell_mask": room_b.to_rle()},
            ])
            levels.append({"id": level_id, "volume_id": volume_id, "label": f"L{index}", "z_base_ft": (index - 1) * 15, "height_ft": 15, "cell_mask": previous_mask.to_rle()})
            door_a, door_b = first_shared_edge(room_a, room_b)
            connectors.append({
                "id": f"door_{level_id}_rooms", "type": "door", "bidirectional": True, "visibility": "public",
                "endpoints": [endpoint(level_id, door_a, volume_id=volume_id, room_id=room_a_id), endpoint(level_id, door_b, volume_id=volume_id, room_id=room_b_id)],
            })
            if index > 1:
                prior_id = level_ids[index - 2]
                shared = previous_mask & CellMask.from_rle(levels[-2]["cell_mask"])
                stair = closest_cell(shared, min(shared.cells))
                connectors.append({
                    "id": f"stairs_{volume_id}_{index - 1}_{index}", "type": "stairs", "bidirectional": True, "visibility": "public",
                    "endpoints": [endpoint(prior_id, stair, volume_id=volume_id), endpoint(level_id, stair, volume_id=volume_id)],
                })
        volumes.append({
            "id": volume_id, "name": blueprint["name"], "kind": blueprint["kind"], "archetype": blueprint["archetype"],
            "parcel_id": f"parcel_{volume_id}", "level_ids": level_ids, **_volume_presentation(spec, blueprint),
        })

        ground_level = level_ids[0]
        ground_rooms = [room for room in rooms if room["level_id"] == ground_level]
        room_masks = [(room, CellMask.from_rle(room["cell_mask"])) for room in ground_rooms]
        candidates: list[tuple[Cell, Cell, dict[str, Any]]] = []
        for room, room_mask in room_masks:
            for inside, outside in room_mask.boundary_edges():
                if outside in bounds.cells and outside not in water.cells and outside not in surface_footprints.cells:
                    candidates.append((inside, outside, room))
        inside, outside, entry_room = min(candidates, key=lambda item: (abs(item[1][1] - 29), item[1]))
        connectors.append({
            "id": f"entrance_{volume_id}", "type": "door", "bidirectional": True, "visibility": "public",
            "endpoints": [endpoint("surface", outside), endpoint(ground_level, inside, volume_id=volume_id, room_id=entry_room["id"])],
        })

    surface_ground = bounds - water - surface_footprints
    surface_routes = routes & surface_ground
    surface_plain = surface_ground - surface_routes

    sewer_ring = CellMask.path([(12, 14), (12, 52), (43, 52), (43, 14), (12, 14)], radius=1)
    sewer_branches = (
        CellMask.path([(18, 20), (18, 30), (12, 30)], radius=1)
        | CellMask.path([(36, 45), (36, 52)], radius=1)
        | CellMask.path([(8, 10), (8, 14), (16, 14)], radius=1)
    )
    secret_room_mask = CellMask.rect(39, 54, 5, 5)
    sewer_public_mask = (sewer_ring | sewer_branches).clipped(height, width)
    sewage = CellMask.path([(12, 16), (12, 50), (41, 52)], radius=0) & sewer_public_mask
    sewer_dry_mask = sewer_public_mask - sewage
    sewer_mask = sewer_public_mask | secret_room_mask
    sewer_level = "sewer_main"
    sewer_volume = "undertide_sewer"
    sewer_room = "sewer_dry_main"
    sewer_channel_room = "sewer_sewage_channel"
    secret_room = "sealed_cistern"
    sewer_hero = _hero(spec, sewer_volume)
    volumes.append({
        "id": sewer_volume, "name": "潮下排水网", "kind": "sewer", "archetype": "ring_sewer", "parcel_id": "", "level_ids": [sewer_level],
        "style": sewer_hero.get("style", {"family": "undertide_masonry", "condition": "damp"}),
        "roof": sewer_hero.get("roof", {"shape": "barrel_vault", "material": "brick"}),
        "facade": sewer_hero.get("facade", {"primary": "wet_brick", "accents": ["iron_pipe"]}),
    })
    levels.append({"id": sewer_level, "volume_id": sewer_volume, "label": "B1 · -15 ft", "z_base_ft": -15, "height_ft": 12, "cell_mask": sewer_mask.to_rle()})
    rooms.extend([
        {"id": sewer_room, "name": "潮下干道", "level_id": sewer_level, "volume_id": sewer_volume, "role": "sewer_main", "tags": ["circulation", "dry_ledge", "maintenance"], "navigation_group": "sewer_public", "visibility": "public", "cell_mask": sewer_dry_mask.to_rle()},
        {"id": sewer_channel_room, "name": "黑水污水渠", "level_id": sewer_level, "volume_id": sewer_volume, "role": "sewage_channel", "tags": ["sewage", "hazard", "damp"], "navigation_group": "sewer_public", "visibility": "public", "cell_mask": sewage.to_rle()},
        {"id": secret_room, "name": "封闭暗池", "level_id": sewer_level, "volume_id": sewer_volume, "role": "secret_cistern", "tags": ["secret", "dm_clue", "sealed"], "visibility": "dm_only", "cell_mask": secret_room_mask.to_rle()},
    ])
    secret_a, secret_b = first_shared_edge(sewer_public_mask, secret_room_mask)
    secret_source_room = sewer_channel_room if secret_a in sewage.cells else sewer_room
    connectors.append({
        "id": "secret_door_sealed_cistern", "type": "secret_door", "bidirectional": True, "visibility": "dm_only",
        "endpoints": [endpoint(sewer_level, secret_a, volume_id=sewer_volume, room_id=secret_source_room), endpoint(sewer_level, secret_b, volume_id=sewer_volume, room_id=secret_room)],
    })
    for index, hatch_cell in enumerate(((18, 30), (36, 45)), 1):
        if hatch_cell not in surface_ground.cells or hatch_cell not in sewer_public_mask.cells:
            raise AssertionError(f"invalid sewer hatch cell {hatch_cell}")
        connectors.append({
            "id": f"hatch_sewer_{index}", "type": "hatch", "bidirectional": True, "visibility": "public",
            "endpoints": [endpoint("surface", hatch_cell), endpoint(sewer_level, hatch_cell, volume_id=sewer_volume, room_id=sewer_channel_room if hatch_cell in sewage.cells else sewer_room)],
        })
    tower_cell = (8, 10)
    tower_room_id = next(room["id"] for room in rooms if room["level_id"] == "signal_tower_l1" and tower_cell in CellMask.from_rle(room["cell_mask"]).cells)
    tower_sewer_room = sewer_channel_room if tower_cell in sewage.cells else sewer_room
    connectors.append({
        "id": "tower_cellar_secret_hatch", "type": "secret_door", "bidirectional": True, "visibility": "dm_only",
        "endpoints": [endpoint("signal_tower_l1", tower_cell, volume_id="signal_tower", room_id=tower_room_id), endpoint(sewer_level, tower_cell, volume_id=sewer_volume, room_id=tower_sewer_room)],
    })

    anchors = [
        {"id": "party_start", "kind": "party_start", "level_id": "surface", "row": 52, "col": 29, "visibility": "public"},
        {"id": "tower_roof", "kind": "vista", "level_id": "signal_tower_l4", "row": 5, "col": 8, "visibility": "public"},
        {"id": "sewer_junction", "kind": "encounter", "level_id": sewer_level, "row": 12, "col": 30, "visibility": "public"},
        {"id": "sealed_cistern_clue", "kind": "secret", "level_id": sewer_level, "row": 41, "col": 56, "visibility": "dm_only"},
    ]

    feature_rng = named_rng(seed, "features:harbor_dressing")
    protected_by_level: dict[str, set[Cell]] = {}
    for connector in connectors:
        for ep in connector["endpoints"]:
            protected_by_level.setdefault(ep["level_id"], set()).add((ep["row"], ep["col"]))
    for anchor in anchors:
        protected_by_level.setdefault(anchor["level_id"], set()).add((anchor["row"], anchor["col"]))
    room_masks = {room["id"]: CellMask.from_rle(room["cell_mask"]) for room in rooms}
    for room in rooms:
        endpoints = [
            (ep["row"], ep["col"])
            for connector in connectors for ep in connector["endpoints"]
            if ep.get("room_id") == room["id"]
        ]
        endpoints.extend((anchor["row"], anchor["col"]) for anchor in anchors if anchor["level_id"] == room["level_id"] and (anchor["row"], anchor["col"]) in room_masks[room["id"]].cells)
        if endpoints:
            root = endpoints[0]
            for target in endpoints[1:]:
                protected_by_level.setdefault(room["level_id"], set()).update(_shortest_path(room_masks[room["id"]], root, target))

    protected_surface = protected_by_level.get("surface", set())
    feature_candidates = [cell for cell in (layout["docks"] | surface_routes).sorted_cells() if cell not in protected_surface and cell in surface_ground.cells]
    feature_rng.shuffle(feature_candidates)
    features: list[dict[str, Any]] = []
    feature_kinds = ["cargo_cluster", "rope_coil", "harbor_lantern", "fish_basket"]
    for index, point in enumerate(feature_candidates[:32]):
        features.append({
            "id": f"harbor_feature_{index:02d}", "kind": feature_kinds[index % len(feature_kinds)], "level_id": "surface",
            "row": point[0], "col": point[1], "volume_id": "", "room_id": "", "rotation_deg": (index % 4) * 90,
            "dimensions_ft": [4, 4, 4 if index % 2 else 6], "variant": "salt_weathered", "blocks_movement": False,
            "visibility": "public", "tags": ["working_harbor", "street_dressing"],
        })
    occupied: set[tuple[str, Cell]] = set()
    for room in rooms:
        recipes = FEATURE_RECIPES.get(room["role"], [])
        if not recipes:
            continue
        room_rng = named_rng(seed, f"features:room:{room['id']}")
        candidates = [cell for cell in room_masks[room["id"]].sorted_cells() if cell not in protected_by_level.get(room["level_id"], set())]
        room_rng.shuffle(candidates)
        for recipe_index, (kind, blocks, dimensions, tags) in enumerate(recipes):
            point = next((cell for cell in candidates if (room["level_id"], cell) not in occupied), None)
            if point is None:
                if blocks:
                    continue
                point = closest_cell(room_masks[room["id"]], min(room_masks[room["id"]].cells))
            occupied.add((room["level_id"], point))
            features.append({
                "id": f"{room['id']}_feature_{recipe_index:02d}", "kind": kind, "level_id": room["level_id"],
                "row": point[0], "col": point[1], "volume_id": room["volume_id"], "room_id": room["id"],
                "rotation_deg": room_rng.choice((0, 90, 180, 270)), "dimensions_ft": list(dimensions),
                "variant": room_rng.choice(("weathered", "used", "well_kept")), "blocks_movement": blocks,
                "visibility": room["visibility"], "tags": tags,
            })

    plan = {
        "schema_version": "dnd-scene-plan-2.0",
        "generator_version": GENERATOR_VERSION,
        "scene": {"id": scene["id"], "name": scene["name"], "seed": seed},
        "grid": {**spec["grid"], "coordinate_contract": "cell(row,col)->world_ft(col*5,-row*5,z_base_ft)"},
        "pack_contract_sha256": sha256_value(spec["packs"]),
        "seed_streams": {name: named_seed(seed, name) for name in ("terrain:shoreline", "routes:surface", "parcels", "features:harbor_dressing")},
        "terrain": [
            {"id": "surface_ground", "level_id": "surface", "kind": "ground", "walkable": True, "cell_mask": surface_plain.to_rle()},
            {"id": "surface_routes", "level_id": "surface", "kind": "road", "walkable": True, "cell_mask": surface_routes.to_rle()},
            {"id": "harbor_water", "level_id": "surface", "kind": "water", "walkable": False, "cell_mask": water.to_rle()},
            {"id": "sewer_channel", "level_id": sewer_level, "kind": "sewage", "walkable": True, "cell_mask": sewage.to_rle()},
        ],
        "parcels": parcels,
        "volumes": volumes,
        "levels": [{"id": "surface", "volume_id": "", "label": "Surface", "z_base_ft": 0, "height_ft": 0, "cell_mask": surface_ground.to_rle()}] + levels,
        "rooms": rooms,
        "connectors": connectors,
        "features": features,
        "anchors": anchors,
    }
    return plan


def compile_runtime(plan: dict[str, Any]) -> dict[str, Any]:
    level_masks = {level["id"]: CellMask.from_rle(level["cell_mask"]) for level in plan["levels"]}
    level_meta = {level["id"]: level for level in plan["levels"]}
    room_by_cell: dict[tuple[str, int, int], dict[str, Any]] = {}
    for room in plan["rooms"]:
        for row, col in CellMask.from_rle(room["cell_mask"]).cells:
            key = (room["level_id"], row, col)
            if key in room_by_cell:
                raise AssertionError(f"overlapping rooms at {key}")
            room_by_cell[key] = room
    terrain_by_cell: dict[tuple[str, int, int], dict[str, Any]] = {}
    for terrain in plan["terrain"]:
        for row, col in CellMask.from_rle(terrain["cell_mask"]).cells:
            terrain_by_cell[(terrain["level_id"], row, col)] = terrain
    blocked_by_cell = {
        (feature["level_id"], feature["row"], feature["col"])
        for feature in plan["features"] if feature.get("blocks_movement")
    }

    cells: list[dict[str, Any]] = []
    cell_lookup: dict[str, dict[str, Any]] = {}
    for level in plan["levels"]:
        level_id = level["id"]
        for point in level_masks[level_id].sorted_cells():
            room = room_by_cell.get((level_id, *point))
            terrain = terrain_by_cell.get((level_id, *point))
            surface = terrain["kind"] if terrain else ("interior" if room else "ground")
            cost = 2 if surface == "sewage" else 1
            item = {
                "id": cell_id(level_id, point), "level_id": level_id, "row": point[0], "col": point[1],
                "z_base_ft": level["z_base_ft"], "walkable": (level_id, *point) not in blocked_by_cell, "surface": surface,
                "volume_id": level.get("volume_id", ""), "room_id": room["id"] if room else "",
                "navigation_group": room.get("navigation_group", room["id"]) if room else "",
                "visibility": room["visibility"] if room else "public", "movement": {"walk": cost},
            }
            cells.append(item)
            cell_lookup[item["id"]] = item

    nav_edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str]] = set()
    for level_id, mask in level_masks.items():
        for point in mask.sorted_cells():
            source = cell_id(level_id, point)
            if not cell_lookup[source]["walkable"]:
                continue
            source_group = cell_lookup[source]["navigation_group"]
            for target_point in neighbors(point):
                target = cell_id(level_id, target_point)
                if target not in cell_lookup or not cell_lookup[target]["walkable"]:
                    continue
                target_group = cell_lookup[target]["navigation_group"]
                if source_group != target_group:
                    continue
                key = tuple(sorted((source, target)))
                if key in edge_keys:
                    continue
                edge_keys.add(key)
                nav_edges.append({"a": key[0], "b": key[1], "kind": "walk", "cost": max(cell_lookup[key[0]]["movement"]["walk"], cell_lookup[key[1]]["movement"]["walk"])})

    runtime_connectors: list[dict[str, Any]] = []
    for connector in plan["connectors"]:
        left, right = connector["endpoints"]
        a = cell_id(left["level_id"], (left["row"], left["col"]))
        b = cell_id(right["level_id"], (right["row"], right["col"]))
        if a not in cell_lookup or b not in cell_lookup:
            raise AssertionError(f"connector endpoint missing runtime cell: {connector['id']}")
        if not cell_lookup[a]["walkable"] or not cell_lookup[b]["walkable"]:
            raise AssertionError(f"blocking feature occupies connector endpoint: {connector['id']}")
        runtime_connectors.append({**connector, "cell_ids": [a, b]})
        key = tuple(sorted((a, b)))
        if key not in edge_keys:
            edge_keys.add(key)
            nav_edges.append({"a": key[0], "b": key[1], "kind": connector["type"], "connector_id": connector["id"], "cost": 1, "interaction_required": True, "visibility": connector["visibility"]})

    nav_edges.sort(key=lambda edge: (edge["a"], edge["b"], edge["kind"]))
    runtime = {
        "schema_version": "dnd-scene-runtime-2.0",
        "generator_version": GENERATOR_VERSION,
        "scene": {**plan["scene"], "grid": plan["grid"], "levels": [{key: level[key] for key in ("id", "label", "z_base_ft", "height_ft", "volume_id")} for level in plan["levels"]]},
        "volumes": [{key: volume[key] for key in ("id", "name", "kind", "archetype", "level_ids", "style", "roof", "facade")} for volume in plan["volumes"]],
        "rooms": [{key: room[key] for key in ("id", "name", "role", "level_id", "volume_id", "visibility", "tags")} for room in plan["rooms"]],
        "cells": cells,
        "nav": {"mode": "explicit", "edges": nav_edges},
        "connectors": runtime_connectors,
        "features": plan["features"],
        "anchors": plan["anchors"],
    }
    return runtime


def _reachable(start: str, edges: list[dict[str, Any]], *, include_dm: bool = True) -> set[str]:
    graph: dict[str, set[str]] = {}
    for edge in edges:
        if not include_dm and edge.get("visibility") == "dm_only":
            continue
        graph.setdefault(edge["a"], set()).add(edge["b"])
        graph.setdefault(edge["b"], set()).add(edge["a"])
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for target in graph.get(current, ()):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def validate(plan: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    cells = {cell["id"]: cell for cell in runtime["cells"]}
    if len(cells) != len(runtime["cells"]):
        raise AssertionError("duplicate runtime cell id")
    ids: set[str] = set()
    for group in (plan["terrain"], plan["parcels"], plan["volumes"], plan["levels"], plan["rooms"], plan["connectors"], plan["features"], plan["anchors"]):
        for item in group:
            if item["id"] in ids:
                raise AssertionError(f"duplicate entity id: {item['id']}")
            ids.add(item["id"])
    for edge in runtime["nav"]["edges"]:
        if edge["a"] not in cells or edge["b"] not in cells:
            raise AssertionError("nav edge references missing cell")
        left, right = cells[edge["a"]], cells[edge["b"]]
        if edge["kind"] == "walk":
            if left["level_id"] != right["level_id"] or abs(left["row"] - right["row"]) + abs(left["col"] - right["col"]) != 1:
                raise AssertionError("ordinary nav edge must be same-level four-neighbor")
    party = next(anchor for anchor in runtime["anchors"] if anchor["id"] == "party_start")
    start = cell_id(party["level_id"], (party["row"], party["col"]))
    reachable_dm = _reachable(start, runtime["nav"]["edges"], include_dm=True)
    reachable_player = _reachable(start, runtime["nav"]["edges"], include_dm=False)
    for anchor in runtime["anchors"]:
        target = cell_id(anchor["level_id"], (anchor["row"], anchor["col"]))
        if anchor["visibility"] == "public" and target not in reachable_player:
            raise AssertionError(f"public anchor unreachable: {anchor['id']}")
    connector_cells = {
        cell_id(ep["level_id"], (ep["row"], ep["col"]))
        for connector in plan["connectors"] for ep in connector["endpoints"]
    }
    anchor_cells = {cell_id(anchor["level_id"], (anchor["row"], anchor["col"])) for anchor in plan["anchors"]}
    required_feature_fields = {
        "id", "kind", "level_id", "row", "col", "volume_id", "room_id", "rotation_deg",
        "dimensions_ft", "variant", "blocks_movement", "visibility", "tags",
    }
    blocking_features = []
    for feature in plan["features"]:
        if not required_feature_fields <= feature.keys():
            raise AssertionError(f"feature metadata incomplete: {feature['id']}")
        target = cell_id(feature["level_id"], (feature["row"], feature["col"]))
        if target not in cells:
            raise AssertionError(f"feature is outside runtime cells: {feature['id']}")
        if feature["blocks_movement"]:
            blocking_features.append(feature)
            if target in connector_cells or target in anchor_cells:
                raise AssertionError(f"blocking feature occupies protected navigation cell: {feature['id']}")
            if cells[target]["walkable"]:
                raise AssertionError(f"blocking feature did not update runtime walkability: {feature['id']}")
    runtime_rooms = {room["id"]: room for room in runtime.get("rooms", [])}
    for room in plan["rooms"]:
        if not room.get("name") or not room.get("role") or not isinstance(room.get("tags"), list):
            raise AssertionError(f"room semantic metadata incomplete: {room['id']}")
        projected = runtime_rooms.get(room["id"])
        if not projected or projected["name"] != room["name"] or projected["role"] != room["role"]:
            raise AssertionError(f"room runtime projection is stale: {room['id']}")
    secret_cells = {cell["id"] for cell in runtime["cells"] if cell["room_id"] == "sealed_cistern" and cell["walkable"]}
    if secret_cells & reachable_player:
        raise AssertionError("secret room reachable without DM-only connector")
    if not secret_cells <= reachable_dm:
        raise AssertionError("secret room unreachable for DM graph")
    sewer_hatches = [connector for connector in runtime["connectors"] if connector["type"] == "hatch"]
    if len(sewer_hatches) < 2:
        raise AssertionError("sewer requires two independent surface hatches")
    non_rectangular = 0
    for volume in plan["volumes"]:
        if volume["kind"] not in {"building", "tower"}:
            continue
        mask = CellMask.from_rle(next(level["cell_mask"] for level in plan["levels"] if level["id"] == volume["level_ids"][0]))
        rows, cols = [p[0] for p in mask.cells], [p[1] for p in mask.cells]
        if len(mask) < (max(rows) - min(rows) + 1) * (max(cols) - min(cols) + 1):
            non_rectangular += 1
    if non_rectangular < 4:
        raise AssertionError("pressure scene needs at least four non-rectangular buildings")
    report = {
        "status": "passed", "cells": len(cells), "nav_edges": len(runtime["nav"]["edges"]),
        "volumes": len(plan["volumes"]), "levels": len(plan["levels"]), "rooms": len(plan["rooms"]),
        "connectors": len(plan["connectors"]), "features": len(plan["features"]),
        "blocking_features": len(blocking_features), "semantic_rooms": len(runtime_rooms),
        "non_rectangular_buildings": non_rectangular, "sewer_hatches": len(sewer_hatches),
        "runtime_bytes": len(canonical_bytes(runtime)),
    }
    if report["runtime_bytes"] >= 10_000_000:
        raise AssertionError("runtime exceeds 10 MB prototype budget")
    return report


def generate(spec_path: Path, output_dir: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    validate_spec(spec)
    plan = compile_plan(spec)
    runtime = compile_runtime(plan)
    report = validate(plan, runtime)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "scene.plan.json"
    runtime_path = output_dir / "scene.runtime.json"
    plan_path.write_bytes(canonical_bytes(plan))
    runtime_path.write_bytes(canonical_bytes(runtime))
    manifest = {
        "schema_version": "dnd-scene-manifest-2.0", "status": "generated",
        "scene_id": plan["scene"]["id"], "generator_version": GENERATOR_VERSION,
        "pack_contract_sha256": plan["pack_contract_sha256"],
        "source_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "runtime_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
        "validation": report,
    }
    (output_dir / "scene.manifest.json").write_bytes(canonical_bytes(manifest))
    return manifest
