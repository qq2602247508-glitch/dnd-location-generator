"""V2.3 LocationProgram -> generic V2 plan/runtime realization.

The first pack realization is the Old Clock Quarter pressure fixture.  It uses
the existing V2 plan/runtime contracts so Blender, Viewer and the future DND
adapter continue to share one navigation truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .compiler import (
    canonical_bytes,
    compile_runtime,
    endpoint,
    first_shared_edge,
    sha256_value,
    split_mask,
    validate,
)
from .location import LOCATION_SCHEMA, validate_location
from .mask import Cell, CellMask
from .rng import named_rng, named_seed


REALIZER_VERSION = "2.3.0-prototype.1"


def _room(room_id: str, name: str, level_id: str, volume_id: str, role: str, mask: CellMask, *,
          visibility: str = "public", tags: list[str] | None = None, navigation_group: str | None = None) -> dict[str, Any]:
    item = {
        "id": room_id, "name": name, "level_id": level_id, "volume_id": volume_id,
        "role": role, "tags": tags or [], "visibility": visibility, "cell_mask": mask.to_rle(),
    }
    if navigation_group:
        item["navigation_group"] = navigation_group
    return item


def _presentation(archetype: str) -> dict[str, Any]:
    styles = {
        "clock_tower": (
            {"family": "deepwater_clock_tower", "condition": "rain_weathered"},
            {"shape": "copper_belfry", "material": "verdigris_copper", "hero_feature": "clock_faces"},
            {"primary": "blue_gray_stone", "accents": ["iron_bands", "gold_clock_hands"]},
        ),
        "inn": (
            {"family": "crooked_old_quarter_inn", "condition": "warm_and_busy"},
            {"shape": "crooked_gable", "material": "dark_shingle", "details": ["chimney", "hanging_sign"]},
            {"primary": "dark_timber", "accents": ["cream_plaster", "red_shutters"]},
        ),
        "ring_sewer": (
            {"family": "old_clock_underworks", "condition": "wet_and_corroded"},
            {"shape": "brick_barrel_vault", "material": "soaked_brick"},
            {"primary": "wet_brick", "accents": ["verdigris_pipe", "black_water"]},
        ),
        "roof_route": (
            {"family": "old_quarter_roofscape", "condition": "patched"},
            {"shape": "walkable_roofline", "material": "mixed_tile"},
            {"primary": "dark_tile", "accents": ["plank_bridge", "laundry"]},
        ),
    }
    style, roof, facade = styles.get(archetype, (
        {"family": "old_quarter_masonry", "condition": "lived_in"},
        {"shape": "pitched", "material": "mixed_tile"},
        {"primary": "gray_stone", "accents": ["dark_timber", "faded_plaster"]},
    ))
    return {"style": style, "roof": roof, "facade": facade}


def _feature(feature_id: str, kind: str, level_id: str, point: Cell, *, volume_id: str = "", room_id: str = "",
             dimensions: tuple[int, int, int] = (4, 4, 4), rotation: int = 0, blocks: bool = False,
             visibility: str = "public", tags: list[str] | None = None, variant: str = "weathered") -> dict[str, Any]:
    return {
        "id": feature_id, "kind": kind, "level_id": level_id, "row": point[0], "col": point[1],
        "volume_id": volume_id, "room_id": room_id, "rotation_deg": rotation,
        "dimensions_ft": list(dimensions), "variant": variant, "blocks_movement": blocks,
        "visibility": visibility, "tags": tags or [],
    }


def _contains(mask: CellMask, point: Cell, label: str) -> Cell:
    if point not in mask.cells:
        raise AssertionError(f"{label} point is outside its mask: {point}")
    return point


def _notched_footprint(row: int, col: int, height: int, width: int, notch_height: int, notch_width: int,
                        corner: str) -> CellMask:
    """Return a connected irregular footprint with a deterministic corner notch."""
    if not 0 < notch_height < height or not 0 < notch_width < width:
        raise ValueError("building notch must be smaller than its footprint")
    whole = CellMask.rect(row, col, height, width)
    starts = {
        "nw": (row, col),
        "ne": (row, col + width - notch_width),
        "sw": (row + height - notch_height, col),
        "se": (row + height - notch_height, col + width - notch_width),
    }
    if corner not in starts:
        raise ValueError(f"unsupported building notch corner: {corner}")
    notch_row, notch_col = starts[corner]
    return whole - CellMask.rect(notch_row, notch_col, notch_height, notch_width)


def _mask_center(mask: CellMask) -> Cell:
    if not mask.cells:
        raise ValueError("cannot find the center of an empty mask")
    rows, cols = zip(*mask.cells)
    return ((min(rows) + max(rows)) // 2, (min(cols) + max(cols)) // 2)


def _nearest_cell(mask: CellMask, target: Cell, *, exclude: set[Cell] | None = None) -> Cell:
    excluded = exclude or set()
    candidates = [point for point in mask.cells if point not in excluded]
    if not candidates:
        raise ValueError("no eligible cell in mask")
    return min(candidates, key=lambda point: (abs(point[0] - target[0]) + abs(point[1] - target[1]), point))


def _entry_connection(base: CellMask, bounds: CellMask, occupied: CellMask, target: Cell) -> tuple[Cell, Cell]:
    """Pick a stable outside/inside door pair on an unobstructed building edge."""
    candidates = [
        (inside, outside)
        for inside, outside in base.boundary_edges()
        if outside in bounds.cells and outside not in occupied.cells
    ]
    if not candidates:
        raise AssertionError("building has no free surface edge for a public entrance")
    inside, outside = min(
        candidates,
        key=lambda item: (
            abs(item[1][0] - target[0]) + abs(item[1][1] - target[1]),
            item[1], item[0],
        ),
    )
    return outside, inside


def _old_clock_layout(seed: int, width: int, height: int) -> dict[str, Any]:
    """Build the macro geometry before room realization.

    The named streams deliberately keep streets, footprints, roofs and sewers
    independent.  This lets a dressing change stay cosmetic while every seed
    still receives a materially different navigable district.
    """
    if width < 64 or height < 60:
        raise ValueError("old-clock layout requires a grid of at least 64x60 cells")

    bounds = CellMask.rect(0, 0, height, width)
    macro_rng = named_rng(seed, "location:old_clock:macro")
    street_rng = named_rng(seed, "location:old_clock:streets")
    building_rng = named_rng(seed, "location:old_clock:buildings")
    roof_rng = named_rng(seed, "location:old_clock:roof")
    sewer_rng = named_rng(seed, "location:old_clock:sewer")

    def irregular(row: int, col: int, rows: int, cols: int) -> CellMask:
        return _notched_footprint(
            row,
            col,
            rows,
            cols,
            3 + building_rng.randrange(2),
            3 + building_rng.randrange(3),
            building_rng.choice(("nw", "ne", "sw", "se")),
        )

    tower = CellMask.rect(
        6 + building_rng.randrange(3),
        27 + building_rng.randrange(4),
        7 + building_rng.randrange(3),
        7 + building_rng.randrange(3),
    )
    inn = irregular(
        19 + building_rng.randrange(4),
        43 + building_rng.randrange(3),
        9 + building_rng.randrange(3),
        11 + building_rng.randrange(3),
    )
    scribes = irregular(
        17 + building_rng.randrange(3),
        12 + building_rng.randrange(3),
        8 + building_rng.randrange(3),
        10 + building_rng.randrange(3),
    )
    shrine = irregular(
        32 + building_rng.randrange(3),
        14 + building_rng.randrange(3),
        7 + building_rng.randrange(3),
        8 + building_rng.randrange(3),
    )
    locksmith = irregular(
        35 + building_rng.randrange(3),
        45 + building_rng.randrange(3),
        7 + building_rng.randrange(3),
        9 + building_rng.randrange(3),
    )
    tenement = irregular(
        46 + building_rng.randrange(3),
        13 + building_rng.randrange(4),
        9 + building_rng.randrange(3),
        11 + building_rng.randrange(3),
    )
    ward_post = CellMask.rect(
        49 + building_rng.randrange(3),
        44 + building_rng.randrange(3),
        7 + building_rng.randrange(3),
        8 + building_rng.randrange(3),
    )
    blueprints = [
        {"id": "old_clock_tower", "name": "旧钟塔", "kind": "tower", "archetype": "clock_tower", "base": tower, "levels": 3},
        {"id": "crooked_bell_inn", "name": "歪钟旅店", "kind": "building", "archetype": "inn", "base": inn, "levels": 2},
        {"id": "scribes_guild", "name": "抄写员行会", "kind": "building", "archetype": "guildhall", "base": scribes, "levels": 1},
        {"id": "copper_shrine", "name": "铜雨小祠", "kind": "building", "archetype": "shrine", "base": shrine, "levels": 1},
        {"id": "locksmith_row", "name": "锁匠铺", "kind": "building", "archetype": "shop", "base": locksmith, "levels": 1},
        {"id": "leaning_tenement", "name": "斜檐公寓", "kind": "building", "archetype": "tenement", "base": tenement, "levels": 1},
        {"id": "ward_post", "name": "旧钟岗亭", "kind": "building", "archetype": "watchhouse", "base": ward_post, "levels": 1},
    ]
    footprints = CellMask.empty()
    for blueprint in blueprints:
        base = blueprint["base"]
        if not base.cells <= bounds.cells:
            raise AssertionError(f"building footprint escapes the grid: {blueprint['id']}")
        if footprints.cells & base.cells:
            raise AssertionError(f"building footprints overlap: {blueprint['id']}")
        footprints = footprints | base

    tower_entry_out, tower_entry_in = _entry_connection(
        tower,
        bounds,
        footprints,
        (max(point[0] for point in tower.cells) + 3, _mask_center(tower)[1]),
    )
    inn_entry_out, inn_entry_in = _entry_connection(
        inn,
        bounds,
        footprints,
        (_mask_center(inn)[0], min(point[1] for point in inn.cells) - 3),
    )

    market_row = 24 + macro_rng.randrange(4)
    market_col = 27 + macro_rng.randrange(3)
    market = CellMask.rect(market_row, market_col, 9 + macro_rng.randrange(3), 12 + macro_rng.randrange(3))
    market_center = _mask_center(market)
    party_start = (height - 3, 30 + street_rng.randrange(9))
    main_street = CellMask.path([
        party_start,
        (height - 10, party_start[1] + street_rng.randrange(-4, 5)),
        (height - 19, market_center[1] + street_rng.randrange(-5, 6)),
        (market_center[0] + 6, market_center[1] + street_rng.randrange(-3, 4)),
        market_center,
        (tower_entry_out[0] + 3, tower_entry_out[1] + street_rng.randrange(-2, 3)),
        tower_entry_out,
    ], radius=1 + macro_rng.randrange(2)).clipped(height, width)
    crooked_alley = CellMask.path([
        (height - 10, party_start[1] + street_rng.randrange(-2, 3)),
        (height - 16, 38 + street_rng.randrange(-3, 4)),
        (40 + street_rng.randrange(-2, 3), inn_entry_out[1] - 3),
        inn_entry_out,
    ], radius=1).clipped(height, width)
    guild_lane = CellMask.path([
        (market_center[0] + 5, market_center[1] - 3),
        (32 + street_rng.randrange(-2, 3), 26 + street_rng.randrange(-3, 4)),
        (min(point[0] for point in scribes.cells) + 3, max(point[1] for point in scribes.cells) + 1),
    ], radius=1).clipped(height, width)
    east_lane = CellMask.path([
        (height - 19, market_center[1] + 2),
        (43 + street_rng.randrange(-2, 3), min(point[1] for point in locksmith.cells) - 2),
        (min(point[0] for point in locksmith.cells) + 3, min(point[1] for point in locksmith.cells) - 1),
    ], radius=1).clipped(height, width)
    routes = (main_street | market | crooked_alley | guild_lane | east_lane) - footprints
    surface_ground = bounds - footprints
    plain_ground = surface_ground - routes

    tower_roof = _nearest_cell(tower, _mask_center(inn))
    inn_roof = _nearest_cell(inn, _mask_center(tower))
    roof_midpoint = ((tower_roof[0] + inn_roof[0]) // 2, (tower_roof[1] + inn_roof[1]) // 2)
    roof_mask = CellMask.path([
        inn_roof,
        (inn_roof[0] + roof_rng.randrange(-2, 3), inn_roof[1] - roof_rng.randrange(2, 6)),
        (roof_midpoint[0] + roof_rng.randrange(-3, 4), roof_midpoint[1] + roof_rng.randrange(-3, 4)),
        (tower_roof[0] + roof_rng.randrange(1, 4), tower_roof[1] + roof_rng.randrange(-2, 3)),
        tower_roof,
    ], radius=1).clipped(height, width)
    roof_vantage = _nearest_cell(roof_mask, roof_midpoint, exclude={tower_roof, inn_roof})

    ring_top = 16 + sewer_rng.randrange(3)
    ring_bottom = 49 + sewer_rng.randrange(3)
    ring_left = 18 + sewer_rng.randrange(3)
    ring_right = 50 + sewer_rng.randrange(3)
    sewer_ring = CellMask.path([
        (ring_top, ring_left), (ring_top, ring_right), (ring_bottom, ring_right),
        (ring_bottom, ring_left), (ring_top, ring_left),
    ], radius=1).clipped(height, width)
    upper_hatch = (market_center[0] + sewer_rng.randrange(-2, 3), market_center[1] + sewer_rng.randrange(-2, 3))
    lower_hatch = (46 + sewer_rng.randrange(4), 31 + sewer_rng.randrange(7))
    upper_turn = (upper_hatch[0] + sewer_rng.randrange(-3, 4), ring_right - sewer_rng.randrange(3, 8))
    lower_turn = (lower_hatch[0] - sewer_rng.randrange(1, 5), ring_left + sewer_rng.randrange(3, 8))
    sewer_branches = (
        CellMask.path([upper_hatch, upper_turn, (upper_turn[0], ring_right)], radius=1)
        | CellMask.path([lower_hatch, lower_turn, (lower_turn[0], ring_left)], radius=1)
    ).clipped(height, width)
    sewer_public = sewer_ring | sewer_branches
    sewage = CellMask.path([
        (ring_top + 1, ring_left + 1), (ring_top + 1, ring_right - 1),
        (ring_bottom - 1, ring_right - 1),
    ], radius=0) & sewer_public
    sewer_dry = sewer_public - sewage
    secret_height = 5 + sewer_rng.randrange(2)
    secret_width = 5 + sewer_rng.randrange(2)
    secret_mask = CellMask.rect(ring_bottom - 7 - sewer_rng.randrange(3), ring_right + 2, secret_height, secret_width)
    sewer_junction = (upper_turn[0], ring_right)
    smuggler_cache = _nearest_cell(secret_mask, _mask_center(secret_mask))

    for label, mask, point in (
        ("party_start", surface_ground, party_start),
        ("market_well", surface_ground, _nearest_cell(market & surface_ground, market_center)),
        ("tower_entry", surface_ground, tower_entry_out),
        ("inn_entry", surface_ground, inn_entry_out),
        ("hatch_one", surface_ground, upper_hatch),
        ("hatch_two", surface_ground, lower_hatch),
        ("sewer_junction", sewer_public, sewer_junction),
    ):
        _contains(mask, point, label)

    return {
        "blueprints": blueprints,
        "footprints": footprints,
        "market": market,
        "routes": routes,
        "surface_ground": surface_ground,
        "plain_ground": plain_ground,
        "tower_entry_out": tower_entry_out,
        "tower_entry_in": tower_entry_in,
        "inn_entry_out": inn_entry_out,
        "inn_entry_in": inn_entry_in,
        "tower_roof": tower_roof,
        "inn_roof": inn_roof,
        "roof_mask": roof_mask,
        "roof_vantage": roof_vantage,
        "sewer_public": sewer_public,
        "sewage": sewage,
        "sewer_dry": sewer_dry,
        "secret_mask": secret_mask,
        "hatches": (upper_hatch, lower_hatch),
        "party_start": party_start,
        "market_well": _nearest_cell(market & surface_ground, market_center),
        "clock_objective": sorted(tower.cells)[len(tower.cells) // 2],
        "inn_hub": inn_entry_in,
        "sewer_junction": sewer_junction,
        "smuggler_cache": smuggler_cache,
    }


def compile_location_plan(location: dict[str, Any]) -> dict[str, Any]:
    validate_location(location)
    if location.get("schema_version") != LOCATION_SCHEMA or location["scene"]["id"] != "old_clock_quarter_v23":
        raise ValueError("prototype.1 realizes only the old_clock_quarter_v23 location pack")
    seed = int(location["scene"]["seed"])
    width, height = int(location["grid"]["width"]), int(location["grid"]["height"])
    layout = _old_clock_layout(seed, width, height)
    blueprints: list[dict[str, Any]] = layout["blueprints"]
    market: CellMask = layout["market"]
    routes: CellMask = layout["routes"]
    surface_ground: CellMask = layout["surface_ground"]
    plain_ground: CellMask = layout["plain_ground"]

    volumes: list[dict[str, Any]] = []
    levels: list[dict[str, Any]] = []
    rooms: list[dict[str, Any]] = []
    connectors: list[dict[str, Any]] = []
    parcels: list[dict[str, Any]] = []
    level_masks: dict[str, CellMask] = {}

    room_names: dict[str, list[tuple[str, str]]] = {
        "old_clock_tower": [("守钟人前厅", "guard_post"), ("配重机井", "machinery"), ("齿轮机械层", "machinery"), ("报时档案间", "archive"), ("钟室", "belfry"), ("瞭望环廊", "observation_gallery")],
        "crooked_bell_inn": [("壁炉酒馆大厅", "tavern"), ("后厨与酒窖口", "kitchen_store"), ("旅客卧房", "guest_room"), ("临街木廊", "guest_corridor")],
    }
    shell_roles = {
        "scribes_guild": ("缮卷作坊", "guildhall"), "copper_shrine": ("铜雨礼堂", "shrine"),
        "locksmith_row": ("锁具工坊", "workshop"), "leaning_tenement": ("住家院", "tenement"),
        "ward_post": ("巡逻值房", "watchhouse"),
    }
    for blueprint in blueprints:
        volume_id = blueprint["id"]
        base = blueprint["base"]
        parcels.append({"id": f"parcel_{volume_id}", "cell_mask": base.dilate(1).clipped(height, width).to_rle(), "street_access": True})
        level_ids: list[str] = []
        for index in range(1, int(blueprint["levels"]) + 1):
            level_id = f"{volume_id}_l{index}"
            level_ids.append(level_id)
            level_masks[level_id] = base
            levels.append({"id": level_id, "volume_id": volume_id, "label": f"L{index}", "z_base_ft": (index - 1) * 15, "height_ft": 15, "cell_mask": base.to_rle()})
            if volume_id in room_names:
                left, right = split_mask(base, "row" if index % 2 else "col")
                name_a, role_a = room_names[volume_id][(index - 1) * 2]
                name_b, role_b = room_names[volume_id][(index - 1) * 2 + 1]
                room_a_id, room_b_id = f"{level_id}_{role_a}_a", f"{level_id}_{role_b}_b"
                rooms.extend([
                    _room(room_a_id, name_a, level_id, volume_id, role_a, left, tags=["interior", "hero"]),
                    _room(room_b_id, name_b, level_id, volume_id, role_b, right, tags=["interior", "hero"]),
                ])
                door_a, door_b = first_shared_edge(left, right)
                connectors.append({
                    "id": f"door_{level_id}_rooms", "type": "door", "bidirectional": True, "visibility": "public",
                    "endpoints": [endpoint(level_id, door_a, volume_id=volume_id, room_id=room_a_id), endpoint(level_id, door_b, volume_id=volume_id, room_id=room_b_id)],
                })
            else:
                name, role = shell_roles[volume_id]
                rooms.append(_room(f"{level_id}_{role}", name, level_id, volume_id, role, base, tags=["shell", "background_building"]))
        for index in range(1, len(level_ids)):
            stair = sorted(base.cells)[len(base.cells) // 2]
            connectors.append({
                "id": f"stairs_{volume_id}_{index}_{index + 1}", "type": "stairs", "bidirectional": True, "visibility": "public",
                "endpoints": [endpoint(level_ids[index - 1], stair, volume_id=volume_id), endpoint(level_ids[index], stair, volume_id=volume_id)],
            })
        volumes.append({
            "id": volume_id, "name": blueprint["name"], "kind": blueprint["kind"], "archetype": blueprint["archetype"],
            "parcel_id": f"parcel_{volume_id}", "level_ids": level_ids, **_presentation(blueprint["archetype"]),
        })

    def room_at(level_id: str, point: Cell) -> str:
        for room in rooms:
            if room["level_id"] == level_id and point in CellMask.from_rle(room["cell_mask"]).cells:
                return str(room["id"])
        raise AssertionError(f"no room at {level_id}:{point}")

    tower_entry_out, tower_entry_in = layout["tower_entry_out"], layout["tower_entry_in"]
    inn_entry_out, inn_entry_in = layout["inn_entry_out"], layout["inn_entry_in"]
    for connector_id, volume_id, level_id, outside, inside in (
        ("entrance_old_clock_tower", "old_clock_tower", "old_clock_tower_l1", tower_entry_out, tower_entry_in),
        ("entrance_crooked_bell_inn", "crooked_bell_inn", "crooked_bell_inn_l1", inn_entry_out, inn_entry_in),
    ):
        _contains(surface_ground, outside, connector_id)
        _contains(level_masks[level_id], inside, connector_id)
        connectors.append({
            "id": connector_id, "type": "door", "bidirectional": True, "visibility": "public",
            "endpoints": [endpoint("surface", outside), endpoint(level_id, inside, volume_id=volume_id, room_id=room_at(level_id, inside))],
        })

    roof_mask: CellMask = layout["roof_mask"]
    inn_roof: Cell = layout["inn_roof"]
    tower_roof: Cell = layout["tower_roof"]
    roof_level = "old_clock_roof_route"
    roof_volume = "old_clock_roofscape"
    levels.append({"id": roof_level, "volume_id": roof_volume, "label": "Roof Route · +30 ft", "z_base_ft": 30, "height_ft": 5, "cell_mask": roof_mask.to_rle()})
    level_masks[roof_level] = roof_mask
    rooms.append(_room("roof_walkway", "钟影屋脊线", roof_level, roof_volume, "roof_route", roof_mask, tags=["outdoor", "roof", "tactical_route"], navigation_group="roof_public"))
    volumes.append({"id": roof_volume, "name": "旧钟屋脊", "kind": "roof_route", "archetype": "roof_route", "parcel_id": "", "level_ids": [roof_level], **_presentation("roof_route")})
    connectors.extend([
        {"id": "ladder_inn_to_roof", "type": "ladder", "bidirectional": True, "visibility": "public", "endpoints": [
            endpoint("crooked_bell_inn_l2", inn_roof, volume_id="crooked_bell_inn", room_id=room_at("crooked_bell_inn_l2", inn_roof)),
            endpoint(roof_level, inn_roof, volume_id=roof_volume, room_id="roof_walkway"),
        ]},
        {"id": "bridge_roof_to_tower", "type": "bridge", "bidirectional": True, "visibility": "public", "endpoints": [
            endpoint(roof_level, tower_roof, volume_id=roof_volume, room_id="roof_walkway"),
            endpoint("old_clock_tower_l3", tower_roof, volume_id="old_clock_tower", room_id=room_at("old_clock_tower_l3", tower_roof)),
        ]},
    ])

    sewer_public: CellMask = layout["sewer_public"]
    sewage: CellMask = layout["sewage"]
    sewer_dry: CellMask = layout["sewer_dry"]
    secret_mask: CellMask = layout["secret_mask"]
    sewer_mask = sewer_public | secret_mask
    sewer_level, sewer_volume = "old_clock_sewer_b1", "old_clock_underworks"
    levels.append({"id": sewer_level, "volume_id": sewer_volume, "label": "B1 · -15 ft", "z_base_ft": -15, "height_ft": 12, "cell_mask": sewer_mask.to_rle()})
    level_masks[sewer_level] = sewer_mask
    rooms.extend([
        _room("sewer_walkway", "旧砖检修环", sewer_level, sewer_volume, "maintenance_loop", sewer_dry, tags=["circulation", "damp"], navigation_group="sewer_public"),
        _room("sewer_channel", "黑水排污渠", sewer_level, sewer_volume, "sewage_channel", sewage, tags=["hazard", "sewage"], navigation_group="sewer_public"),
        _room("sealed_cistern", "封墙走私窝点", sewer_level, sewer_volume, "smuggler_den", secret_mask, visibility="dm_only", tags=["secret", "reward"]),
    ])
    volumes.append({"id": sewer_volume, "name": "钟影排水网", "kind": "sewer", "archetype": "ring_sewer", "parcel_id": "", "level_ids": [sewer_level], **_presentation("ring_sewer")})
    secret_a, secret_b = first_shared_edge(sewer_public, secret_mask)
    secret_source = "sewer_channel" if secret_a in sewage.cells else "sewer_walkway"
    connectors.append({
        "id": "secret_door_sealed_cistern", "type": "secret_door", "bidirectional": True, "visibility": "dm_only",
        "endpoints": [endpoint(sewer_level, secret_a, volume_id=sewer_volume, room_id=secret_source), endpoint(sewer_level, secret_b, volume_id=sewer_volume, room_id="sealed_cistern")],
    })
    for index, hatch_cell in enumerate(layout["hatches"], 1):
        _contains(surface_ground, hatch_cell, f"hatch_{index}")
        _contains(sewer_public, hatch_cell, f"hatch_{index}")
        sewer_room = "sewer_channel" if hatch_cell in sewage.cells else "sewer_walkway"
        connectors.append({
            "id": f"hatch_old_clock_{index}", "type": "hatch", "bidirectional": True, "visibility": "public",
            "endpoints": [endpoint("surface", hatch_cell), endpoint(sewer_level, hatch_cell, volume_id=sewer_volume, room_id=sewer_room)],
        })

    party_start: Cell = layout["party_start"]
    market_well: Cell = layout["market_well"]
    clock_objective: Cell = layout["clock_objective"]
    inn_hub: Cell = layout["inn_hub"]
    roof_vantage: Cell = layout["roof_vantage"]
    sewer_junction: Cell = layout["sewer_junction"]
    smuggler_cache: Cell = layout["smuggler_cache"]
    anchors = [
        {"id": "party_start", "kind": "party_start", "level_id": "surface", "row": party_start[0], "col": party_start[1], "visibility": "public"},
        {"id": "market_well", "kind": "social", "level_id": "surface", "row": market_well[0], "col": market_well[1], "visibility": "public"},
        {"id": "clock_objective", "kind": "objective", "level_id": "old_clock_tower_l3", "row": clock_objective[0], "col": clock_objective[1], "visibility": "public"},
        {"id": "inn_hub", "kind": "social", "level_id": "crooked_bell_inn_l1", "row": inn_hub[0], "col": inn_hub[1], "visibility": "public"},
        {"id": "roof_vantage", "kind": "encounter", "level_id": roof_level, "row": roof_vantage[0], "col": roof_vantage[1], "visibility": "public"},
        {"id": "sewer_junction", "kind": "encounter", "level_id": sewer_level, "row": sewer_junction[0], "col": sewer_junction[1], "visibility": "public"},
        {"id": "smuggler_cache", "kind": "secret", "level_id": sewer_level, "row": smuggler_cache[0], "col": smuggler_cache[1], "visibility": "dm_only"},
    ]

    protected = {(ep["level_id"], ep["row"], ep["col"]) for connector in connectors for ep in connector["endpoints"]}
    protected.update((anchor["level_id"], anchor["row"], anchor["col"]) for anchor in anchors)
    features: list[dict[str, Any]] = []
    surface_rng = named_rng(seed, "location:old_clock:surface_dressing")
    market_candidates = [point for point in market.sorted_cells() if point in surface_ground.cells and ("surface", *point) not in protected]
    surface_rng.shuffle(market_candidates)
    market_kinds = ["market_stall", "canvas_awning", "handcart", "crate_cluster", "produce_basket"]
    for index, point in enumerate(market_candidates[:24]):
        features.append(_feature(
            f"market_trace_{index:02d}", market_kinds[index % len(market_kinds)], "surface", point,
            dimensions=(5, 5, 6 if index % 2 else 4), rotation=(index % 4) * 90,
            tags=["market", "lived_in", "soft_cover"], variant=surface_rng.choice(("used", "rain_stained", "patched")),
        ))
    street_candidates = [point for point in routes.sorted_cells() if ("surface", *point) not in protected and point not in market.cells]
    surface_rng.shuffle(street_candidates)
    street_kinds = ["puddle", "wheel_rut", "notice_board", "barrel", "laundry_line", "drain_grate"]
    for index, point in enumerate(street_candidates[:22]):
        features.append(_feature(
            f"street_trace_{index:02d}", street_kinds[index % len(street_kinds)], "surface", point,
            dimensions=(4, 4, 1 if index % 3 < 2 else 5), rotation=(index % 4) * 90,
            tags=["street", "life_trace"], variant=surface_rng.choice(("wet", "worn", "patched")),
        ))

    room_recipes: dict[str, list[tuple[str, tuple[int, int, int], bool]]] = {
        "guard_post": [("guard_desk", (5, 3, 3), True), ("bell_rope", (2, 2, 10), False)],
        "machinery": [("clock_gear_bank", (8, 5, 8), True), ("counterweight", (4, 4, 10), True)],
        "archive": [("archive_shelf", (6, 2, 7), True), ("ledger_table", (5, 4, 3), True)],
        "belfry": [("great_bell", (10, 10, 12), True), ("bell_hammer", (5, 3, 8), False)],
        "observation_gallery": [("brass_telescope", (5, 3, 5), False), ("signal_lantern", (2, 2, 5), False)],
        "tavern": [("bar_counter", (10, 3, 4), True), ("tavern_table", (5, 5, 3), True), ("hearth", (5, 3, 6), True)],
        "kitchen_store": [("prep_table", (5, 4, 3), True), ("ale_barrel", (3, 3, 4), True)],
        "guest_room": [("guest_bed", (5, 8, 4), True), ("travel_chest", (4, 3, 3), True)],
        "guest_corridor": [("corridor_bench", (5, 2, 3), False), ("wall_lantern", (1, 1, 5), False)],
    }
    for room in rooms:
        recipes = room_recipes.get(room["role"], [])
        if not recipes:
            continue
        mask = CellMask.from_rle(room["cell_mask"])
        candidates = [point for point in mask.sorted_cells() if (room["level_id"], *point) not in protected]
        rng = named_rng(seed, f"location:old_clock:room:{room['id']}")
        rng.shuffle(candidates)
        for index, (kind, dimensions, blocks) in enumerate(recipes):
            if not candidates:
                break
            point = candidates.pop()
            features.append(_feature(
                f"{room['id']}_feature_{index:02d}", kind, room["level_id"], point,
                volume_id=room["volume_id"], room_id=room["id"], dimensions=dimensions,
                rotation=rng.choice((0, 90, 180, 270)), blocks=blocks, visibility=room["visibility"],
                tags=["interior", "hero"], variant=rng.choice(("used", "well_kept", "dusty")),
            ))
    sewer_candidates = [point for point in sewer_public.sorted_cells() if (sewer_level, *point) not in protected]
    surface_rng.shuffle(sewer_candidates)
    for index, point in enumerate(sewer_candidates[:12]):
        features.append(_feature(
            f"sewer_trace_{index:02d}", ["verdigris_pipe", "fungus_patch", "rat_tracks", "maintenance_debris"][index % 4], sewer_level, point,
            volume_id=sewer_volume, room_id="sewer_channel" if point in sewage.cells else "sewer_walkway",
            dimensions=(4, 4, 3), rotation=(index % 4) * 90, tags=["sewer", "life_trace"], variant="wet",
        ))
    secret_feature_cells = [
        point for point in secret_mask.sorted_cells()
        if (sewer_level, *point) not in protected
    ]
    if len(secret_feature_cells) < 2:
        raise AssertionError("sealed cistern has no safe cells for its reward dressing")
    smuggler_crates = secret_feature_cells[-1]
    smuggler_table = secret_feature_cells[len(secret_feature_cells) // 2]
    features.extend([
        _feature("smuggler_crates", "sealed_cache", sewer_level, smuggler_crates, volume_id=sewer_volume, room_id="sealed_cistern", dimensions=(8, 5, 5), blocks=True, visibility="dm_only", tags=["secret", "reward"]),
        _feature("smuggler_table", "contraband_table", sewer_level, smuggler_table, volume_id=sewer_volume, room_id="sealed_cistern", dimensions=(5, 5, 3), visibility="dm_only", tags=["secret", "clue"]),
    ])

    plan = {
        "schema_version": "dnd-scene-plan-2.0", "generator_version": REALIZER_VERSION,
        "scene": dict(location["scene"]),
        "grid": {**location["grid"], "origin_ft": [0, 0, 0], "coordinate_contract": "cell(row,col)->world_ft(col*5,-row*5,z_base_ft)"},
        "pack_contract_sha256": sha256_value(location["resolved_packs"]),
        "location_program_sha256": location["location_sha256"],
        "seed_streams": {name: named_seed(seed, name) for name in (
            "location:old_clock:macro", "location:old_clock:streets", "location:old_clock:buildings",
            "location:old_clock:roof", "location:old_clock:sewer", "location:old_clock:surface_dressing",
            "location:old_clock:rooms",
        )},
        "terrain": [
            {"id": "surface_ground", "level_id": "surface", "kind": "ground", "walkable": True, "cell_mask": plain_ground.to_rle()},
            {"id": "old_clock_streets", "level_id": "surface", "kind": "road", "walkable": True, "cell_mask": routes.to_rle()},
            {"id": "roof_route_surface", "level_id": roof_level, "kind": "roof", "walkable": True, "cell_mask": roof_mask.to_rle()},
            {"id": "sewer_sewage", "level_id": sewer_level, "kind": "sewage", "walkable": True, "cell_mask": sewage.to_rle()},
        ],
        "parcels": parcels,
        "volumes": volumes,
        "levels": [{"id": "surface", "volume_id": "", "label": "Old Clock District", "z_base_ft": 0, "height_ft": 0, "cell_mask": surface_ground.to_rle()}] + levels,
        "rooms": rooms, "connectors": connectors, "features": features, "anchors": anchors,
        "content_slots": location["content_slots"],
        "presentation": {"presets": [
            {"id": "district_overview", "label": "街区总览", "focus": "surface", "level_id": "surface", "experience": "theatre"},
            {"id": "clock_exploration", "label": "钟楼勘探", "focus": "old_clock_tower", "level_id": "old_clock_tower_l1", "experience": "exploration"},
            {"id": "roof_showdown", "label": "屋顶对峙", "focus": roof_volume, "level_id": roof_level, "experience": "tactical"},
            {"id": "underworks_pursuit", "label": "地下追踪", "focus": sewer_volume, "level_id": sewer_level, "experience": "tactical"},
        ]},
    }
    return plan


def validate_old_clock(plan: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    base = validate(plan, runtime)
    volumes = {item["id"]: item for item in plan["volumes"]}
    levels = {item["id"]: item for item in plan["levels"]}
    if len(volumes) != 9 or len(volumes["old_clock_tower"]["level_ids"]) != 3 or len(volumes["crooked_bell_inn"]["level_ids"]) != 2:
        raise AssertionError("old-clock volume hierarchy regressed")
    for required in ("surface", "old_clock_roof_route", "old_clock_sewer_b1"):
        if required not in levels:
            raise AssertionError(f"old-clock focus level missing: {required}")
    connector_types = {item["type"] for item in plan["connectors"]}
    if not {"door", "stairs", "ladder", "bridge", "hatch", "secret_door"} <= connector_types:
        raise AssertionError("old-clock transitions are incomplete")
    public_anchors = [item for item in runtime["anchors"] if item["visibility"] == "public"]
    if len(public_anchors) < 6:
        raise AssertionError("old-clock public tactical anchors regressed")
    presets = plan.get("presentation", {}).get("presets", [])
    if {item["id"] for item in presets} != {"district_overview", "clock_exploration", "roof_showdown", "underworks_pursuit"}:
        raise AssertionError("old-clock one-click presentation presets are incomplete")
    if len(plan["features"]) > 90:
        raise AssertionError("old-clock gameplay feature budget exceeded")
    return {
        **base,
        "scene_id": plan["scene"]["id"],
        "roof_cells": len(CellMask.from_rle(levels["old_clock_roof_route"]["cell_mask"])),
        "underground_cells": len(CellMask.from_rle(levels["old_clock_sewer_b1"]["cell_mask"])),
        "public_anchors": len(public_anchors),
        "presets": len(presets),
        "location_program_sha256": plan["location_program_sha256"],
    }


def generate_location_scene(location_path: Path, output_dir: Path) -> dict[str, Any]:
    location = json.loads(location_path.read_text(encoding="utf-8"))
    plan = compile_location_plan(location)
    runtime = compile_runtime(plan)
    report = validate_old_clock(plan, runtime)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path, runtime_path = output_dir / "scene.plan.json", output_dir / "scene.runtime.json"
    plan_path.write_bytes(canonical_bytes(plan))
    runtime_path.write_bytes(canonical_bytes(runtime))
    manifest = {
        "schema_version": "dnd-scene-manifest-2.0", "status": "generated",
        "scene_id": plan["scene"]["id"], "generator_version": REALIZER_VERSION,
        "source_sha256": hashlib.sha256(location_path.read_bytes()).hexdigest(),
        "location_program_sha256": location["location_sha256"],
        "pack_contract_sha256": plan["pack_contract_sha256"],
        "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "runtime_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
        "validation": report,
    }
    (output_dir / "scene.manifest.json").write_bytes(canonical_bytes(manifest))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Realize a V2.3 LocationProgram as V2 plan/runtime")
    parser.add_argument("location", type=Path, nargs="?", default=Path("output/locations/old_clock_quarter.location.json"))
    parser.add_argument("--out", type=Path, default=Path("output/old-clock-v23"))
    args = parser.parse_args()
    print(json.dumps(generate_location_scene(args.location, args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
