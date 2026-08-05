"""Deterministic V2.3 one-click location planning.

This layer turns a short LocationBrief into a resolved set of composable packs
and a hierarchical LocationProgram.  Language models may author the brief in a
future adapter, but pack selection, topology and quality gates stay local and
deterministic.
"""

from __future__ import annotations

import hashlib
from collections import deque
from typing import Any, Iterable

from .program import canonical_bytes


BRIEF_SCHEMA = "dnd-location-brief-1.0"
LOCATION_SCHEMA = "dnd-location-program-1.0"
LOCATION_VERSION = "2.3.0-prototype.1"


PACKS: dict[str, dict[str, Any]] = {
    "core.fantasy_district": {
        "version": "1.0.0", "priority": 0, "requires": [],
        "provides": ["district", "landmark", "public_entry", "primary_route"],
    },
    "theme.deepwater_old_quarter": {
        "version": "1.0.0", "priority": 10, "requires": ["core.fantasy_district"],
        "provides": ["deepwater_style", "mixed_use_zones", "civic_history"],
    },
    "circulation.irregular_streets": {
        "version": "1.0.0", "priority": 20, "requires": ["core.fantasy_district"],
        "provides": ["irregular_streets", "alley_network", "route_loop"],
    },
    "building.clock_tower": {
        "version": "1.0.0", "priority": 30, "requires": ["core.fantasy_district"],
        "provides": ["clock_tower", "three_level_building", "vertical_landmark"],
    },
    "building.inn": {
        "version": "1.0.0", "priority": 31, "requires": ["core.fantasy_district"],
        "provides": ["inn", "two_level_building", "social_hub"],
    },
    "district.market": {
        "version": "1.0.0", "priority": 40, "requires": ["core.fantasy_district"],
        "provides": ["market", "crowd_flow", "stall_cover"],
    },
    "route.rooftop": {
        "version": "1.0.0", "priority": 50, "requires": ["building.clock_tower", "building.inn"],
        "provides": ["roof_route", "vertical_route", "alternate_route"],
    },
    "underground.sewer": {
        "version": "1.0.0", "priority": 60, "requires": ["core.fantasy_district"],
        "provides": ["sewer", "underground_level", "maintenance_loop"],
    },
    "secret.smuggler_den": {
        "version": "1.0.0", "priority": 70, "requires": ["underground.sewer"],
        "provides": ["smuggler_route", "dm_only_secret", "secret_reward"],
    },
    "dressing.lived_in": {
        "version": "1.0.0", "priority": 80, "requires": ["core.fantasy_district"],
        "provides": ["lived_in_dressing", "wear_patterns", "regional_lighting"],
    },
    "adventure.standard_slots": {
        "version": "1.0.0", "priority": 90, "requires": ["core.fantasy_district"],
        "provides": ["npc_slots", "encounter_slots", "reward_slots", "hook_slots"],
    },
}

DEFAULT_CAPABILITIES = {
    "district", "deepwater_style", "irregular_streets", "clock_tower", "inn",
    "market", "roof_route", "sewer", "smuggler_route", "lived_in_dressing",
    "npc_slots", "encounter_slots", "reward_slots", "hook_slots",
}

KEYWORD_CAPABILITIES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("深水城", "deepwater", "旧城区", "old quarter"), ("deepwater_style",)),
    (("不规则", "弯曲", "irregular"), ("irregular_streets",)),
    (("钟楼", "clock tower", "tower"), ("clock_tower",)),
    (("旅店", "酒馆", "inn", "tavern"), ("inn",)),
    (("市场", "market"), ("market",)),
    (("屋顶", "rooftop", "roof route"), ("roof_route",)),
    (("下水道", "排水道", "sewer"), ("sewer",)),
    (("走私", "smuggler"), ("smuggler_route",)),
    (("生活痕迹", "烟火气", "lived in"), ("lived_in_dressing",)),
)


def _entity(entity_id: str, name: str, role: str, **extras: Any) -> dict[str, Any]:
    return {"id": entity_id, "name": name, "role": role, **extras}


def _floor(floor_id: str, label: str, z_base_ft: int, rooms: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return {"id": floor_id, "label": label, "z_base_ft": z_base_ft, "height_ft": 15, "rooms": list(rooms)}


def _room(room_id: str, name: str, role: str, *, visibility: str = "public", tags: Iterable[str] = ()) -> dict[str, Any]:
    return {"id": room_id, "name": name, "role": role, "visibility": visibility, "tags": list(tags)}


def infer_capabilities(prompt: str) -> set[str]:
    lowered = prompt.casefold()
    capabilities = {"district", "npc_slots", "encounter_slots", "reward_slots", "hook_slots"}
    for keywords, provided in KEYWORD_CAPABILITIES:
        if any(keyword.casefold() in lowered for keyword in keywords):
            capabilities.update(provided)
    return capabilities


def validate_brief(brief: dict[str, Any]) -> None:
    if brief.get("schema_version") != BRIEF_SCHEMA:
        raise ValueError("unsupported location brief schema")
    scene = brief.get("scene", {})
    if not scene.get("id") or not scene.get("name") or not isinstance(scene.get("seed"), int):
        raise ValueError("location brief scene requires id, name and integer seed")
    grid = brief.get("grid", {})
    if int(grid.get("width", 0)) < 32 or int(grid.get("height", 0)) < 32 or int(grid.get("cell_size_ft", 0)) != 5:
        raise ValueError("V2.3 prototype requires a grid of at least 32x32 using five-foot cells")
    if not isinstance(brief.get("prompt", ""), str):
        raise ValueError("location brief prompt must be text")
    required = brief.get("required_capabilities", [])
    if not isinstance(required, list) or any(not isinstance(item, str) or not item for item in required):
        raise ValueError("required_capabilities must be a list of stable capability ids")
    party = brief.get("content_profile", {})
    if not 1 <= int(party.get("party_level", 0)) <= 20 or not 1 <= int(party.get("party_size", 0)) <= 8:
        raise ValueError("content profile party level/size is invalid")


def resolve_packs(brief: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    validate_brief(brief)
    requested = set(brief.get("required_capabilities") or infer_capabilities(brief.get("prompt", "")))
    requested.update({"district", "npc_slots", "encounter_slots", "reward_slots", "hook_slots"})
    selected: set[str] = set()
    provided: set[str] = set()

    def select(pack_id: str) -> None:
        if pack_id in selected:
            return
        for dependency in PACKS[pack_id]["requires"]:
            select(dependency)
        selected.add(pack_id)
        provided.update(PACKS[pack_id]["provides"])

    while not requested <= provided:
        missing = requested - provided
        candidates = [
            (int(pack["priority"]), pack_id)
            for pack_id, pack in PACKS.items()
            if pack_id not in selected and missing.intersection(pack["provides"])
        ]
        if not candidates:
            raise ValueError(f"no installed generation pack provides: {', '.join(sorted(missing))}")
        select(min(candidates)[1])

    records = [
        {"id": pack_id, "version": PACKS[pack_id]["version"], "provides": sorted(PACKS[pack_id]["provides"])}
        for pack_id in sorted(selected, key=lambda item: (int(PACKS[item]["priority"]), item))
    ]
    return records, sorted(requested)


def _old_clock_hierarchy() -> dict[str, Any]:
    buildings = [
        {
            "id": "old_clock_tower", "name": "旧钟塔", "kind": "tower", "archetype": "clock_tower", "enterable": True,
            "floors": [
                _floor("clock_l1", "L1", 0, [_room("clock_entry", "守钟人前厅", "guard_post"), _room("clock_weights", "配重机井", "machinery")]),
                _floor("clock_l2", "L2", 15, [_room("clock_gears", "齿轮机械层", "machinery"), _room("clock_archive", "报时档案间", "archive")]),
                _floor("clock_l3", "L3", 30, [_room("clock_belfry", "钟室与瞭望环", "belfry"), _room("clock_cache", "封砖密藏", "secret_cache", visibility="dm_only", tags=["secret"])]),
            ],
        },
        {
            "id": "crooked_bell_inn", "name": "歪钟旅店", "kind": "building", "archetype": "inn", "enterable": True,
            "floors": [
                _floor("inn_l1", "L1", 0, [_room("inn_taproom", "壁炉酒馆大厅", "tavern"), _room("inn_kitchen", "后厨与酒窖口", "kitchen_store")]),
                _floor("inn_l2", "L2", 15, [_room("inn_rooms", "旅客卧房", "guest_room"), _room("inn_gallery", "临街木廊", "guest_corridor")]),
            ],
        },
        {"id": "scribes_guild", "name": "抄写员行会", "kind": "building", "archetype": "guildhall", "enterable": False, "floors": []},
        {"id": "copper_shrine", "name": "铜雨小祠", "kind": "building", "archetype": "shrine", "enterable": False, "floors": []},
        {"id": "locksmith_row", "name": "锁匠铺", "kind": "building", "archetype": "shop", "enterable": False, "floors": []},
        {"id": "leaning_tenement", "name": "斜檐公寓", "kind": "building", "archetype": "tenement", "enterable": False, "floors": []},
        {"id": "ward_post", "name": "旧钟岗亭", "kind": "building", "archetype": "watchhouse", "enterable": False, "floors": []},
    ]
    underground = {
        "id": "old_clock_underworks", "name": "钟影排水网", "kind": "sewer", "archetype": "ring_sewer", "enterable": True,
        "floors": [_floor("sewer_b1", "B1", -15, [
            _room("sewer_walkway", "旧砖检修道", "maintenance_loop"),
            _room("sewer_channel", "黑水排污渠", "sewage_channel"),
            _room("smuggler_den", "封墙走私窝点", "smuggler_den", visibility="dm_only", tags=["secret", "reward"]),
        ])],
    }
    return {"district_id": "old_clock_quarter", "buildings": buildings, "underground": [underground]}


def compile_location(brief: dict[str, Any]) -> dict[str, Any]:
    packs, requested = resolve_packs(brief)
    scene = dict(brief["scene"])
    hierarchy = _old_clock_hierarchy()
    program: dict[str, Any] = {
        "schema_version": LOCATION_SCHEMA,
        "compiler_version": LOCATION_VERSION,
        "scene": scene,
        "grid": dict(brief["grid"]),
        "prompt": brief.get("prompt", ""),
        "theme": brief.get("theme", "deepwater_old_quarter"),
        "requested_capabilities": requested,
        "resolved_packs": packs,
        "history_layers": [
            _entity("old_wall_foundation", "旧城墙根基", "foundation", evidence=["被街屋吞没的墙基", "封死的射孔"]),
            _entity("clock_ward_growth", "钟楼市集时期", "expansion", evidence=["环钟市场", "通往旅店的窄巷"]),
            _entity("smuggler_reuse", "排水网走私化", "current_conflict", evidence=["假封墙", "不合时宜的码头货箱"]),
        ],
        "zones": [
            _entity("clock_square", "旧钟广场", "civic_market", density="crowded"),
            _entity("inn_lane", "歪檐巷", "hospitality", density="tight"),
            _entity("guild_row", "行会石街", "craft", density="mixed"),
            _entity("roofscape", "连续屋脊", "vertical_route", density="open"),
            _entity("underworks", "钟影排水网", "infrastructure", density="subterranean"),
        ],
        "hierarchy": hierarchy,
        "anchors": [
            _entity("south_gate", "南侧旧门", "entry", zone_id="guild_row"),
            _entity("market_well", "旧钟井", "junction", zone_id="clock_square"),
            _entity("clock_objective", "钟室", "objective", volume_id="old_clock_tower", level_id="clock_l3"),
            _entity("inn_hub", "歪钟旅店", "social", volume_id="crooked_bell_inn", level_id="inn_l1"),
            _entity("sewer_junction", "三向检修口", "junction", volume_id="old_clock_underworks", level_id="sewer_b1"),
            _entity("smuggler_cache", "封墙走私窝点", "secret", volume_id="old_clock_underworks", level_id="sewer_b1", visibility="dm_only"),
        ],
        "routes": [
            {"id": "clock_street", "name": "钟盘主街", "role": "primary", "from": "south_gate", "to": "clock_objective", "via": ["market_well"], "traversal": "walk", "visibility": "public"},
            {"id": "market_loop", "name": "市集回环", "role": "loop", "from": "market_well", "to": "inn_hub", "via": [], "traversal": "walk", "visibility": "public"},
            {"id": "crooked_alley", "name": "歪檐巷侧路", "role": "alternate", "from": "south_gate", "to": "inn_hub", "via": [], "traversal": "walk", "visibility": "public"},
            {"id": "roof_chase", "name": "钟影屋脊线", "role": "vertical", "from": "inn_hub", "to": "clock_objective", "via": [], "traversal": "climb", "visibility": "public"},
            {"id": "sewer_loop", "name": "旧砖检修环", "role": "underground_loop", "from": "market_well", "to": "sewer_junction", "via": [], "traversal": "hatch", "visibility": "public"},
            {"id": "smuggler_cut", "name": "封墙走私线", "role": "secret", "from": "sewer_junction", "to": "smuggler_cache", "via": [], "traversal": "secret_door", "visibility": "dm_only"},
        ],
        "flows": [
            _entity("market_crowd", "市集人流", "people", route_ids=["clock_street", "market_loop"]),
            _entity("watch_patrol", "岗亭巡逻", "security", route_ids=["clock_street", "crooked_alley"]),
            _entity("roof_runners", "信使与盗贼", "vertical_people", route_ids=["roof_chase"]),
            _entity("storm_water", "雨水排流", "utility", route_ids=["sewer_loop"]),
            _entity("contraband", "走私货流", "covert", route_ids=["smuggler_cut", "crooked_alley"]),
        ],
        "tactical_directives": [
            _entity("market_cover", "摊位、板车与雨棚形成可变掩体", "cover_field", zones=["clock_square"]),
            _entity("clock_verticality", "钟楼三层与配重井形成垂直战场", "verticality", zones=["clock_square"]),
            _entity("roof_falls", "错位屋脊与跨巷跳跃", "fall_hazard", zones=["roofscape"]),
            _entity("sewer_state", "闸门与黑水渠改变地下路线", "state_change", zones=["underworks"]),
        ],
        "dressing_directives": [
            _entity("wear", "人流路径的车辙、磨损与积水", "wear_pattern"),
            _entity("trade", "摊位、木箱、麻袋、晃动招牌与收摊垃圾", "market_clutter"),
            _entity("domestic", "晾衣绳、烟囱、窗灯与屋檐排水", "domestic_trace"),
            _entity("underground", "湿砖、铜绿管线、滴水与发光菌斑", "sewer_trace"),
        ],
        "content_profile": dict(brief["content_profile"]),
        "content_slots": {
            "population": [
                {"id": "npc_bell_keeper", "anchor_id": "clock_objective", "role": "clue_keeper", "resolution_status": "slot"},
                {"id": "npc_innkeeper", "anchor_id": "inn_hub", "role": "social_hub", "resolution_status": "slot"},
                {"id": "npc_watch_patrol", "zone_id": "guild_row", "role": "authority", "resolution_status": "slot"},
            ],
            "encounters": [
                {"id": "enc_market", "anchor_id": "market_well", "difficulty": "medium", "resolution_status": "slot"},
                {"id": "enc_rooftop", "route_id": "roof_chase", "difficulty": "hard", "resolution_status": "slot"},
                {"id": "enc_smuggler", "anchor_id": "smuggler_cache", "difficulty": "hard", "visibility": "dm_only", "resolution_status": "slot"},
            ],
            "rewards": [
                {"id": "reward_clock_archive", "anchor_id": "clock_objective", "tier": brief["content_profile"].get("reward_tier", 2), "resolution_status": "slot"},
                {"id": "reward_smuggler_cache", "anchor_id": "smuggler_cache", "tier": brief["content_profile"].get("reward_tier", 2), "visibility": "dm_only", "resolution_status": "slot"},
            ],
            "hooks": [
                {"id": "hook_stopped_clock", "target_anchor_id": "clock_objective", "role": "investigate", "resolution_status": "slot"},
                {"id": "hook_contraband", "target_anchor_id": "smuggler_cache", "role": "expose_or_control", "resolution_status": "slot"},
            ],
        },
    }
    program["location_sha256"] = hashlib.sha256(canonical_bytes(program)).hexdigest()
    return program


def _reachable(program: dict[str, Any], start: str) -> set[str]:
    graph = {anchor["id"]: set() for anchor in program["anchors"]}
    for route in program["routes"]:
        chain = [route["from"], *route.get("via", []), route["to"]]
        for left, right in zip(chain, chain[1:]):
            graph[left].add(right)
            graph[right].add(left)
    seen, queue = {start}, deque([start])
    while queue:
        current = queue.popleft()
        for target in graph[current]:
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def validate_location(program: dict[str, Any]) -> dict[str, Any]:
    if program.get("schema_version") != LOCATION_SCHEMA:
        raise AssertionError("invalid location program schema")
    pack_capabilities = {capability for pack in program["resolved_packs"] for capability in pack["provides"]}
    if not set(program["requested_capabilities"]) <= pack_capabilities:
        raise AssertionError("resolved packs do not cover every requested capability")
    groups = ["history_layers", "zones", "anchors", "routes", "flows", "tactical_directives", "dressing_directives"]
    ids: set[str] = set()
    for group in groups:
        for item in program[group]:
            if item["id"] in ids:
                raise AssertionError(f"duplicate location entity: {item['id']}")
            ids.add(item["id"])
    anchors = {item["id"] for item in program["anchors"]}
    routes = {item["id"] for item in program["routes"]}
    for route in program["routes"]:
        if any(item not in anchors for item in [route["from"], *route.get("via", []), route["to"]]):
            raise AssertionError(f"route references missing anchor: {route['id']}")
    for flow in program["flows"]:
        if not set(flow["route_ids"]) <= routes:
            raise AssertionError(f"flow references missing route: {flow['id']}")
    entry = next((item["id"] for item in program["anchors"] if item["role"] == "entry"), None)
    objective = next((item["id"] for item in program["anchors"] if item["role"] == "objective"), None)
    if not entry or not objective or objective not in _reachable(program, entry):
        raise AssertionError("location objective is unreachable from its public entry")

    buildings = program["hierarchy"]["buildings"]
    tower = next((item for item in buildings if item["archetype"] == "clock_tower"), None)
    inn = next((item for item in buildings if item["archetype"] == "inn"), None)
    underground = program["hierarchy"]["underground"]
    rooms = [room for volume in [*buildings, *underground] for floor in volume["floors"] for room in floor["rooms"]]
    if len(buildings) < 5 or tower is None or len(tower["floors"]) != 3 or inn is None or len(inn["floors"]) != 2:
        raise AssertionError("old-clock pressure program lacks required building hierarchy")
    if not underground or not any(room["visibility"] == "dm_only" for room in rooms):
        raise AssertionError("location requires an underground DM-only secret")
    route_roles = {route["role"] for route in program["routes"]}
    if not {"primary", "alternate", "loop", "vertical", "secret"} <= route_roles:
        raise AssertionError("location route topology lacks a required tactical option")
    if any(not program["content_slots"].get(kind) for kind in ("population", "encounters", "rewards", "hooks")):
        raise AssertionError("location content adapter boundary is incomplete")

    quality = 0
    quality += 15 if len(program["history_layers"]) >= 3 else 0
    quality += 15 if len(program["zones"]) >= 5 else 0
    quality += 15 if len(buildings) >= 5 else 0
    quality += 15 if tower and inn else 0
    quality += 15 if {"alternate", "loop", "vertical", "secret"} <= route_roles else 0
    quality += 10 if underground else 0
    quality += 10 if len(program["dressing_directives"]) >= 4 else 0
    quality += 5 if all(program["content_slots"].get(kind) for kind in ("population", "encounters", "rewards", "hooks")) else 0
    if quality < 90:
        raise AssertionError(f"location quality score too low: {quality}")
    return {
        "status": "passed", "scene_id": program["scene"]["id"], "quality_score": quality,
        "packs": len(program["resolved_packs"]), "capabilities": len(program["requested_capabilities"]),
        "buildings": len(buildings), "enterable_buildings": sum(bool(item["enterable"]) for item in buildings),
        "floors": sum(len(item["floors"]) for item in [*buildings, *underground]),
        "rooms": len(rooms), "routes": len(program["routes"]), "content_slots": sum(len(items) for items in program["content_slots"].values()),
        "location_sha256": program["location_sha256"],
    }

