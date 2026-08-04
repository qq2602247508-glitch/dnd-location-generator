from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path
from typing import Any, Callable

from .rng import named_rng


PROGRAM_VERSION = "2.2.0-prototype.1"
PROGRAM_SCHEMA = "dnd-scene-program-1.0"
SUPPORTED_ARCHETYPES = {"city_district", "wilderness", "infrastructure_dungeon", "special_site"}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _entity(entity_id: str, name: str, role: str, **extras: Any) -> dict[str, Any]:
    return {"id": entity_id, "name": name, "role": role, **extras}


def _route(route_id: str, name: str, role: str, start: str, end: str, *, via: list[str] | None = None,
           visibility: str = "public", traversal: str = "walk", risk: str = "low") -> dict[str, Any]:
    return {
        "id": route_id, "name": name, "role": role, "from": start, "to": end,
        "via": via or [], "visibility": visibility, "traversal": traversal, "risk": risk,
    }


def _base(spec: dict[str, Any]) -> dict[str, Any]:
    scene, brief = spec["scene"], spec["brief"]
    return {
        "schema_version": PROGRAM_SCHEMA,
        "planner_version": PROGRAM_VERSION,
        "scene": dict(scene),
        "archetype": brief["archetype"],
        "experience": {
            "tone": brief.get("tone", "adventurous"),
            "scale": brief.get("scale", "large"),
            "verticality": brief.get("verticality", "medium"),
            "exploration_density": brief.get("exploration_density", "medium"),
        },
        "history_layers": [], "zones": [], "nodes": [], "routes": [], "flows": [],
        "landmarks": [], "infrastructure": [], "factions": [], "tactical_directives": [],
        "adventure_beats": [], "spatial_grammar": {},
    }


def _city_program(spec: dict[str, Any]) -> dict[str, Any]:
    program = _base(spec)
    rng = named_rng(int(spec["scene"]["seed"]), "program:city")
    program["history_layers"] = [
        _entity("old_quay", "旧潮堤", "foundation", evidence=["低矮旧石堤", "被新仓库包围的系缆柱"]),
        _entity("merchant_expansion", "商港扩建", "expansion", evidence=["拓宽货运路", "行会仓储带"]),
        _entity("present_tension", "走私与港务冲突", "current_conflict", evidence=["封闭巷口", "秘密排水口"]),
    ]
    program["zones"] = [
        _entity("waterfront", "作业码头", "industry", density="open", dominant_flow="cargo"),
        _entity("market_quarter", "潮汐市场", "commerce", density="crowded", dominant_flow="people"),
        _entity("civic_spine", "港务脊线", "administration", density="formal", dominant_flow="watch"),
        _entity("residential_lanes", "盐风住区", "residential", density="tight", dominant_flow="residents"),
        _entity("underworks", "潮下设施", "infrastructure", density="subterranean", dominant_flow="sewage"),
    ]
    program["nodes"] = [
        _entity("landward_gate", "陆侧入口", "entry", zone_id="residential_lanes"),
        _entity("tide_square", "潮钟广场", "junction", zone_id="market_quarter"),
        _entity("beacon_tower", "潮钟信号塔", "objective", zone_id="civic_spine"),
        _entity("cargo_yard", "联合货场", "service", zone_id="waterfront"),
        _entity("sewer_exchange", "排水交换井", "secret_junction", zone_id="underworks"),
    ]
    program["routes"] = [
        _route("public_spine", "潮钟大道", "primary", "landward_gate", "beacon_tower", via=["tide_square"]),
        _route("freight_loop", "货运环道", "service_loop", "tide_square", "cargo_yard", via=["beacon_tower"], risk="medium"),
        _route("dock_return", "沿岸回路", "alternate", "cargo_yard", "landward_gate", risk="medium"),
        _route("smuggler_cut", "潮下走私线", "secret", "sewer_exchange", "cargo_yard", visibility="dm_only", traversal="crawl", risk="high"),
        _route("sewer_access", "检修下行线", "vertical", "tide_square", "sewer_exchange", traversal="hatch", risk="medium"),
    ]
    program["flows"] = [
        _entity("pedestrian_flow", "居民与访客", "people", route_ids=["public_spine", "dock_return"]),
        _entity("cargo_flow", "卸货与仓储", "goods", route_ids=["freight_loop"]),
        _entity("watch_flow", "港务巡逻", "security", route_ids=["public_spine", "freight_loop"]),
        _entity("waste_flow", "排污", "utility", route_ids=["sewer_access", "smuggler_cut"]),
    ]
    program["landmarks"] = [
        _entity("beacon_landmark", "潮钟信号塔", "orientation", node_id="beacon_tower", visibility_radius="district", silhouette=rng.choice(["tapered", "stepped"])),
        _entity("market_landmark", "风帆拱门", "local_anchor", node_id="tide_square", visibility_radius="quarter"),
    ]
    program["infrastructure"] = [
        _entity("storm_drain", "雨污合流系统", "sewer", node_ids=["tide_square", "sewer_exchange", "cargo_yard"]),
        _entity("cargo_cranes", "岸吊与栈桥", "logistics", node_ids=["cargo_yard"]),
    ]
    program["factions"] = [
        _entity("harbor_watch", "港务巡守", "authority", home_zone="civic_spine"),
        _entity("dock_guild", "装卸行会", "labor", home_zone="waterfront"),
        _entity("undertide_ring", "潮下走私网", "covert", home_zone="underworks"),
    ]
    program["tactical_directives"] = [
        _entity("roofline_play", "屋顶追逐", "vertical_route", zones=["market_quarter", "residential_lanes"]),
        _entity("cargo_cover", "可移动货物掩体", "cover_field", zones=["waterfront"]),
        _entity("tower_control", "信号塔制高点", "high_ground", zones=["civic_spine"]),
    ]
    program["adventure_beats"] = [
        _entity("arrival", "从陆侧进入拥挤港区", "arrival", node_id="landward_gate"),
        _entity("first_choice", "大道、货道或屋顶", "route_choice", node_id="tide_square"),
        _entity("reveal", "发现排污系统被走私者利用", "revelation", node_id="sewer_exchange"),
        _entity("climax", "控制信号塔或货场", "climax", node_id="beacon_tower"),
    ]
    program["spatial_grammar"] = {"districts": True, "rooms": "nested", "terrain_driver": "shoreline", "required_cycles": 1}
    return program


def _wilderness_program(spec: dict[str, Any]) -> dict[str, Any]:
    program = _base(spec)
    program["history_layers"] = [
        _entity("glacial_cut", "古冰川切谷", "geology", evidence=["U形谷", "悬挂支谷"]),
        _entity("river_erosion", "河流下切", "erosion", evidence=["浅滩", "瀑布阶地"]),
        _entity("pilgrim_use", "旧朝圣路线", "human_use", evidence=["风化路标", "山洞祭坛"]),
    ]
    program["zones"] = [
        _entity("western_ridge", "西侧山脊", "highland", elevation_band="high"),
        _entity("river_valley", "银瀑河谷", "watershed", elevation_band="low"),
        _entity("pine_slope", "黑松缓坡", "forest", elevation_band="mid"),
        _entity("cave_karst", "裂岩洞系", "cave", elevation_band="mixed"),
        _entity("waterfall_basin", "瀑布盆地", "hazard", elevation_band="low"),
    ]
    program["nodes"] = [
        _entity("trailhead", "南侧山道", "entry", zone_id="pine_slope"),
        _entity("river_ford", "碎石浅滩", "junction", zone_id="river_valley"),
        _entity("high_pass", "风啸山口", "vista", zone_id="western_ridge"),
        _entity("cave_mouth", "回声洞口", "objective", zone_id="cave_karst"),
        _entity("hidden_shrine", "水幕后祭坛", "secret", zone_id="waterfall_basin"),
    ]
    program["routes"] = [
        _route("valley_trail", "河谷主道", "primary", "trailhead", "cave_mouth", via=["river_ford"]),
        _route("ridge_path", "山脊险径", "alternate", "trailhead", "cave_mouth", via=["high_pass"], traversal="climb", risk="high"),
        _route("ford_loop", "浅滩回环", "loop", "river_ford", "high_pass", risk="medium"),
        _route("waterfall_secret", "瀑幕后路", "secret", "river_ford", "hidden_shrine", visibility="dm_only", traversal="wade", risk="high"),
    ]
    program["flows"] = [
        _entity("watershed", "山溪与主河", "water", route_ids=["valley_trail"], direction="high_to_low"),
        _entity("animal_migration", "兽群迁徙", "wildlife", route_ids=["ford_loop"]),
        _entity("traveler_flow", "旅人与朝圣者", "people", route_ids=["valley_trail"]),
    ]
    program["landmarks"] = [
        _entity("silver_fall", "银瀑", "orientation", node_id="hidden_shrine", visibility_radius="valley"),
        _entity("split_peak", "双角峰", "horizon", node_id="high_pass", visibility_radius="scene"),
    ]
    program["infrastructure"] = [_entity("old_waystones", "旧路标", "navigation", node_ids=["trailhead", "river_ford", "cave_mouth"])]
    program["factions"] = [
        _entity("valley_rangers", "河谷巡林者", "guardian", home_zone="pine_slope"),
        _entity("cave_brood", "洞穴兽群", "predator", home_zone="cave_karst"),
    ]
    program["tactical_directives"] = [
        _entity("ford_crossfire", "浅滩两岸交叉火力", "crossfire", zones=["river_valley"]),
        _entity("ridge_fall", "山脊坠落风险", "fall_hazard", zones=["western_ridge"]),
        _entity("water_control", "河流推移与困难地形", "moving_hazard", zones=["waterfall_basin"]),
    ]
    program["adventure_beats"] = [
        _entity("arrival", "看见银瀑与双角峰", "arrival", node_id="trailhead"),
        _entity("choice", "河谷安全路或山脊险径", "route_choice", node_id="river_ford"),
        _entity("secret", "穿过瀑布发现旧祭坛", "discovery", node_id="hidden_shrine"),
        _entity("climax", "洞口前的立体战场", "climax", node_id="cave_mouth"),
    ]
    program["spatial_grammar"] = {"districts": False, "rooms": "optional_cave_chambers", "terrain_driver": "watershed", "required_cycles": 1}
    return program


def _dungeon_program(spec: dict[str, Any]) -> dict[str, Any]:
    program = _base(spec)
    program["history_layers"] = [
        _entity("first_cistern", "旧城蓄水池", "original_use", evidence=["厚重拱券", "沉淀池"]),
        _entity("sewer_conversion", "雨污管网改造", "conversion", evidence=["新旧砖色", "铸铁闸门"]),
        _entity("cult_occupation", "暗流教团占据", "occupation", evidence=["私设祭台", "封死检修门"]),
    ]
    program["zones"] = [
        _entity("intake", "地表检修入口", "entry", function="access"),
        _entity("collector", "主汇流渠", "circulation", function="sewage"),
        _entity("pump_hall", "排污泵房", "machinery", function="control"),
        _entity("maintenance_ring", "环形检修廊", "loop", function="service"),
        _entity("overflow_cistern", "溢流蓄水池", "hazard", function="storage"),
        _entity("buried_shrine", "被埋旧祠", "secret", function="occupation"),
    ]
    program["nodes"] = [
        _entity("north_hatch", "北检修井", "entry", zone_id="intake"),
        _entity("fourway_junction", "四向汇流口", "junction", zone_id="collector"),
        _entity("pump_controls", "主泵控制台", "objective", zone_id="pump_hall"),
        _entity("overflow_gate", "溢流闸", "state_control", zone_id="overflow_cistern"),
        _entity("shrine_altar", "暗流祭台", "boss", zone_id="buried_shrine"),
        _entity("south_outfall", "南侧排水口", "exit", zone_id="collector"),
    ]
    program["routes"] = [
        _route("collector_spine", "主汇流线", "primary", "north_hatch", "south_outfall", via=["fourway_junction", "pump_controls"]),
        _route("maintenance_loop_a", "东检修环", "service_loop", "fourway_junction", "pump_controls", via=["overflow_gate"], risk="medium"),
        _route("maintenance_loop_b", "西检修环", "alternate", "pump_controls", "north_hatch", risk="medium"),
        _route("overflow_shortcut", "溢流捷径", "stateful_shortcut", "overflow_gate", "south_outfall", traversal="wade", risk="high"),
        _route("cult_breach", "破墙密道", "secret", "overflow_gate", "shrine_altar", visibility="dm_only", traversal="crawl", risk="high"),
    ]
    program["flows"] = [
        _entity("sewage_flow", "污水汇流", "utility", route_ids=["collector_spine", "overflow_shortcut"], direction="intake_to_outfall"),
        _entity("maintenance_flow", "检修人员", "people", route_ids=["maintenance_loop_a", "maintenance_loop_b"]),
        _entity("cult_patrol", "教团巡逻", "hostile", route_ids=["cult_breach", "maintenance_loop_a"]),
    ]
    program["landmarks"] = [
        _entity("pump_landmark", "双轮排污泵", "orientation", node_id="pump_controls", visibility_radius="zone"),
        _entity("junction_landmark", "四向汇流井", "navigation", node_id="fourway_junction", visibility_radius="network"),
    ]
    program["infrastructure"] = [
        _entity("pump_system", "泵机与闸门", "machine_network", node_ids=["pump_controls", "overflow_gate"]),
        _entity("sewer_network", "主渠与溢流渠", "fluid_network", node_ids=["north_hatch", "fourway_junction", "south_outfall"]),
    ]
    program["factions"] = [
        _entity("city_maintenance", "城市检修队", "former_operator", home_zone="intake"),
        _entity("undertide_cult", "暗流教团", "occupier", home_zone="buried_shrine"),
        _entity("sewer_vermin", "污渠兽群", "wildlife", home_zone="overflow_cistern"),
    ]
    program["tactical_directives"] = [
        _entity("gate_state", "闸门改变水位和路线", "state_change", zones=["pump_hall", "overflow_cistern"]),
        _entity("junction_choice", "四向路口提供可读选择", "route_choice", zones=["collector"]),
        _entity("reinforcement_loop", "敌人可沿检修环增援", "reinforcement", zones=["maintenance_ring"]),
    ]
    program["adventure_beats"] = [
        _entity("arrival", "从检修井下降", "arrival", node_id="north_hatch"),
        _entity("choice", "在四向汇流口选择路线", "route_choice", node_id="fourway_junction"),
        _entity("control", "启动或破坏主泵", "state_change", node_id="pump_controls"),
        _entity("climax", "旧祠首领遭遇", "climax", node_id="shrine_altar"),
    ]
    program["spatial_grammar"] = {"districts": False, "rooms": "functional_chambers", "terrain_driver": "infrastructure_flow", "required_cycles": 2}
    return program


def _special_program(spec: dict[str, Any]) -> dict[str, Any]:
    program = _base(spec)
    rng = named_rng(int(spec["scene"]["seed"]), "program:special")
    program["history_layers"] = [
        _entity("meteor_fall", "星陨冲击", "cataclysm", evidence=["环形断崖", "玻璃化岩层"]),
        _entity("dragon_death", "远古巨龙陨落", "mythic_event", evidence=["完整脊骨", "魔力浸染骨骼"]),
        _entity("rift_awakened", "位面裂隙苏醒", "current_change", evidence=["漂浮岩", "奥术喷口"]),
    ]
    program["zones"] = [
        _entity("crater_rim", "星坑外缘", "high_ground", elevation_band="high"),
        _entity("bonefield", "龙骨原", "cover_field", elevation_band="mid"),
        _entity("rift_floor", "裂谷底", "hazard", elevation_band="low"),
        _entity("skull_arena", "龙首台地", "climax", elevation_band="high"),
        _entity("floating_steps", "浮岩群", "vertical_route", elevation_band="variable"),
    ]
    program["nodes"] = [
        _entity("rim_entry", "南侧星坑缘", "entry", zone_id="crater_rim"),
        _entity("spine_bridge", "龙脊骨桥", "junction", zone_id="bonefield"),
        _entity("rift_vent", "奥术喷口", "hazard_control", zone_id="rift_floor"),
        _entity("dragon_skull", "远古龙首", "boss", zone_id="skull_arena"),
        _entity("marrow_cache", "骨髓秘藏", "secret", zone_id="bonefield"),
        _entity("float_anchor", "浮岩锚点", "vertical", zone_id="floating_steps"),
    ]
    program["routes"] = [
        _route("rim_descent", "断崖缓降路", "primary", "rim_entry", "dragon_skull", via=["spine_bridge"]),
        _route("bone_ridge", "龙脊高路", "alternate", "spine_bridge", "dragon_skull", traversal="balance", risk="high"),
        _route("floating_path", "浮岩跃迁线", "vertical", "float_anchor", "dragon_skull", traversal="jump_or_fly", risk="high"),
        _route("rift_loop", "裂谷底回环", "loop", "spine_bridge", "float_anchor", via=["rift_vent"], risk="medium"),
        _route("marrow_secret", "骨髓裂隙", "secret", "spine_bridge", "marrow_cache", visibility="dm_only", traversal="crawl", risk="medium"),
    ]
    program["flows"] = [
        _entity("arcane_current", "位面能流", "hazard", route_ids=["rift_loop", "floating_path"]),
        _entity("predator_route", "飞行猎食者巡弋", "hostile", route_ids=["bone_ridge", "floating_path"]),
    ]
    program["landmarks"] = [
        _entity("skull_landmark", "远古龙首", "orientation", node_id="dragon_skull", visibility_radius="scene", silhouette=rng.choice(["horned", "shattered_horn"])),
        _entity("rift_landmark", "星辉裂隙", "vertical_axis", node_id="rift_vent", visibility_radius="scene"),
    ]
    program["infrastructure"] = []
    program["factions"] = [
        _entity("rift_scavengers", "裂隙拾荒者", "explorer", home_zone="crater_rim"),
        _entity("star_spawn", "星界孳生体", "predator", home_zone="rift_floor"),
    ]
    program["tactical_directives"] = [
        _entity("five_bands", "至少五档战术高度", "verticality", zones=["crater_rim", "rift_floor", "skull_arena"]),
        _entity("rib_cover", "肋骨形成方向性掩体", "cover_field", zones=["bonefield"]),
        _entity("collapse_bridge", "骨桥可坍塌", "destructible", zones=["bonefield"]),
        _entity("large_creature", "首领区支持巨型生物", "scale", zones=["skull_arena"]),
    ]
    program["adventure_beats"] = [
        _entity("arrival", "从坑缘俯瞰龙骨与裂隙", "arrival", node_id="rim_entry"),
        _entity("choice", "缓降、龙脊或浮岩路线", "route_choice", node_id="spine_bridge"),
        _entity("secret", "进入骨髓裂隙", "discovery", node_id="marrow_cache"),
        _entity("climax", "龙首台地立体首领战", "climax", node_id="dragon_skull"),
    ]
    program["spatial_grammar"] = {"districts": False, "rooms": "none", "terrain_driver": "mythic_landmark", "required_cycles": 1}
    return program


PLANNERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "city_district": _city_program,
    "wilderness": _wilderness_program,
    "infrastructure_dungeon": _dungeon_program,
    "special_site": _special_program,
}


def validate_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema_version") != "dnd-scene-program-spec-1.0":
        raise ValueError("unsupported scene program spec")
    scene, brief = spec.get("scene", {}), spec.get("brief", {})
    if not scene.get("id") or not scene.get("name") or not isinstance(scene.get("seed"), int):
        raise ValueError("program scene requires id, name and integer seed")
    if brief.get("archetype") not in SUPPORTED_ARCHETYPES:
        raise ValueError(f"unsupported program archetype: {brief.get('archetype')}")


def compile_program(spec: dict[str, Any]) -> dict[str, Any]:
    validate_spec(spec)
    program = PLANNERS[spec["brief"]["archetype"]](spec)
    program["program_sha256"] = hashlib.sha256(canonical_bytes(program)).hexdigest()
    return program


def _reachable(nodes: set[str], routes: list[dict[str, Any]], start: str) -> set[str]:
    graph = {node: set() for node in nodes}
    for route in routes:
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


def validate_program(program: dict[str, Any]) -> dict[str, Any]:
    if program.get("schema_version") != PROGRAM_SCHEMA:
        raise AssertionError("invalid program schema")
    groups = ["history_layers", "zones", "nodes", "routes", "flows", "landmarks", "infrastructure", "factions", "tactical_directives", "adventure_beats"]
    ids: set[str] = set()
    for group in groups:
        for item in program[group]:
            if item["id"] in ids:
                raise AssertionError(f"duplicate program entity: {item['id']}")
            ids.add(item["id"])
    nodes = {item["id"] for item in program["nodes"]}
    zones = {item["id"] for item in program["zones"]}
    routes = program["routes"]
    for route in routes:
        if any(node not in nodes for node in [route["from"], *route.get("via", []), route["to"]]):
            raise AssertionError(f"route references missing node: {route['id']}")
    for node in program["nodes"]:
        if node.get("zone_id") and node["zone_id"] not in zones:
            raise AssertionError(f"node references missing zone: {node['id']}")
    entries = [item["id"] for item in program["nodes"] if item["role"] == "entry"]
    objectives = [item["id"] for item in program["nodes"] if item["role"] in {"objective", "boss"}]
    if not entries or not objectives:
        raise AssertionError("program requires entry and objective/boss")
    reachable = _reachable(nodes, routes, entries[0])
    if not set(objectives) <= reachable:
        raise AssertionError("program objective is unreachable")
    route_roles = {item["role"] for item in routes}
    if "primary" not in route_roles or not route_roles & {"alternate", "loop", "service_loop"} or "secret" not in route_roles:
        raise AssertionError("program needs primary, alternate/loop and secret routes")
    if len(program["history_layers"]) < 2 or not program["landmarks"] or len(program["adventure_beats"]) < 4:
        raise AssertionError("program lacks history, landmark or adventure pacing")
    route_ids = {item["id"] for item in routes}
    for flow in program["flows"]:
        if not set(flow.get("route_ids", [])) <= route_ids:
            raise AssertionError(f"flow references missing route: {flow['id']}")
    score = 0
    score += min(20, len(program["history_layers"]) * 7)
    score += min(20, len(program["zones"]) * 4)
    score += 20 if {"primary", "secret"} <= route_roles else 0
    score += 15 if route_roles & {"alternate", "loop", "service_loop"} else 0
    score += min(15, len(program["tactical_directives"]) * 4)
    score += min(10, len(program["landmarks"]) * 5)
    if score < 85:
        raise AssertionError(f"program quality score too low: {score}")
    if program["archetype"] == "special_site" and program["spatial_grammar"].get("rooms") != "none":
        raise AssertionError("special site must not depend on rooms")
    return {
        "status": "passed", "scene_id": program["scene"]["id"], "archetype": program["archetype"],
        "history_layers": len(program["history_layers"]), "zones": len(program["zones"]),
        "nodes": len(program["nodes"]), "routes": len(routes), "flows": len(program["flows"]),
        "landmarks": len(program["landmarks"]), "tactical_directives": len(program["tactical_directives"]),
        "quality_score": score, "program_sha256": program["program_sha256"],
    }


def generate_program(spec_path: Path, output_path: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    program = compile_program(spec)
    report = validate_program(program)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical_bytes(program))
    report_path = output_path.with_suffix(".verification.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
