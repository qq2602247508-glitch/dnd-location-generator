"""Shared spatial grammar and constraint solver for V2 ScenePrograms.

The planners describe intent (zones, landmarks, routes and flows), while
realizers choose cells and meshes.  This module is the small deterministic
middle layer that prevents a believable-looking brief from becoming a
spatially incoherent map.  It deliberately returns a report instead of
mutating a program, so the existing SceneProgram hash and frozen artifacts
remain stable while every new program still passes the same constraints.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping


GRAMMAR_VERSION = "2.4.0-prototype.1"


class SpatialGrammarError(ValueError):
    """Raised when a SceneProgram violates a spatial planning constraint."""


def _fail(message: str) -> None:
    raise SpatialGrammarError(message)


def _entity_ids(program: Mapping[str, Any]) -> dict[str, set[str]]:
    groups = (
        "history_layers", "zones", "nodes", "routes", "flows", "landmarks",
        "infrastructure", "factions", "tactical_directives", "adventure_beats",
    )
    ids: dict[str, set[str]] = {}
    seen: dict[str, str] = {}
    for group in groups:
        ids[group] = set()
        for item in program.get(group, []):
            item_id = str(item.get("id", ""))
            if not item_id:
                _fail(f"spatial grammar entity in {group} has no id")
            if item_id in seen:
                _fail(f"duplicate spatial entity id: {item_id} ({seen[item_id]} and {group})")
            seen[item_id] = group
            ids[group].add(item_id)
    return ids


def _route_graph(program: Mapping[str, Any]) -> tuple[dict[str, set[str]], int]:
    node_ids = {str(node["id"]) for node in program["nodes"]}
    graph = {node_id: set() for node_id in node_ids}
    edge_count = 0
    for route in program["routes"]:
        chain = [route["from"], *route.get("via", []), route["to"]]
        if len(chain) < 2:
            _fail(f"route has no traversable span: {route.get('id', '<unknown>')}")
        for node_id in chain:
            if node_id not in node_ids:
                _fail(f"route references missing node: {route['id']} -> {node_id}")
        for left, right in zip(chain, chain[1:]):
            if left == right:
                _fail(f"route contains a zero-length hop: {route['id']}")
            graph[left].add(right)
            graph[right].add(left)
            edge_count += 1
    return graph, edge_count


def _component_count(graph: Mapping[str, set[str]]) -> int:
    seen: set[str] = set()
    components = 0
    for start in graph:
        if start in seen:
            continue
        components += 1
        seen.add(start)
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for target in graph[current]:
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
    return components


def _reachable(graph: Mapping[str, set[str]], start: str) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for target in graph[current]:
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def _check_references(program: Mapping[str, Any], ids: Mapping[str, set[str]]) -> None:
    zones, nodes, routes = ids["zones"], ids["nodes"], ids["routes"]
    for node in program["nodes"]:
        if node.get("zone_id") and node["zone_id"] not in zones:
            _fail(f"node references missing zone: {node['id']} -> {node['zone_id']}")
    for flow in program["flows"]:
        missing = set(flow.get("route_ids", [])) - routes
        if missing:
            _fail(f"flow references missing route: {flow['id']} -> {sorted(missing)}")
    for landmark in program["landmarks"]:
        node_id = landmark.get("node_id")
        if node_id and node_id not in nodes:
            _fail(f"landmark references missing node: {landmark['id']} -> {node_id}")
    for item in program["infrastructure"]:
        missing = set(item.get("node_ids", [])) - nodes
        if missing:
            _fail(f"infrastructure references missing node: {item['id']} -> {sorted(missing)}")
    for faction in program["factions"]:
        home_zone = faction.get("home_zone")
        if home_zone and home_zone not in zones:
            _fail(f"faction references missing home zone: {faction['id']} -> {home_zone}")
    for directive in program["tactical_directives"]:
        missing = set(directive.get("zones", [])) - zones
        if missing:
            _fail(f"tactical directive references missing zone: {directive['id']} -> {sorted(missing)}")


def _check_route_semantics(program: Mapping[str, Any], graph: Mapping[str, set[str]], edge_count: int) -> dict[str, Any]:
    grammar = program.get("spatial_grammar", {})
    node_roles = {node["id"]: node.get("role") for node in program["nodes"]}
    entries = [node_id for node_id, role in node_roles.items() if role == "entry"]
    objectives = [node_id for node_id, role in node_roles.items() if role in {"objective", "boss"}]
    if not entries:
        _fail("spatial grammar requires at least one entry node")
    if not objectives:
        _fail("spatial grammar requires an objective or boss node")
    reachable = _reachable(graph, entries[0])
    if not set(objectives) <= reachable:
        _fail(f"objective/boss is not connected to entry: {sorted(set(objectives) - reachable)}")

    route_roles = {str(route.get("role")) for route in program["routes"]}
    if "primary" not in route_roles:
        _fail("spatial grammar requires a primary route")
    if not route_roles & {"alternate", "loop", "service_loop"}:
        _fail("spatial grammar requires an alternate or loop route")
    secret_routes = [route for route in program["routes"] if route.get("role") == "secret"]
    if not secret_routes:
        _fail("spatial grammar requires a secret route")
    if any(route.get("visibility") != "dm_only" for route in secret_routes):
        _fail("secret routes must be DM-only")

    components = _component_count(graph)
    cycle_rank = edge_count - len(graph) + components
    required_cycles = int(grammar.get("required_cycles", 0))
    if cycle_rank < required_cycles:
        _fail(f"route graph has {cycle_rank} cycles; requires {required_cycles}")
    return {
        "entry_ids": sorted(entries),
        "objective_ids": sorted(objectives),
        "route_roles": sorted(route_roles),
        "components": components,
        "edge_count": edge_count,
        "cycle_rank": cycle_rank,
        "required_cycles": required_cycles,
    }

def _check_causal_driver(program: Mapping[str, Any]) -> dict[str, Any]:
    grammar = program.get("spatial_grammar", {})
    driver = str(grammar.get("terrain_driver", ""))
    zones = {str(zone.get("role")) for zone in program["zones"]}
    flows = program["flows"]
    flow_kinds = {str(flow.get("role")) for flow in flows}
    route_roles = {str(route.get("role")) for route in program["routes"]}
    directive_roles = {str(item.get("role")) for item in program["tactical_directives"]}
    landmark_roles = {str(item.get("role")) for item in program["landmarks"]}
    if driver == "shoreline":
        if "industry" not in zones or not flows:
            _fail("shoreline grammar requires an industry waterfront and at least one flow")
    elif driver == "watershed":
        if "water" not in flow_kinds or not any(flow.get("direction") == "high_to_low" for flow in flows):
            _fail("watershed grammar requires a high_to_low water flow")
    elif driver == "infrastructure_flow":
        if "utility" not in flow_kinds or "machine_network" not in {item.get("role") for item in program["infrastructure"]}:
            _fail("infrastructure grammar requires a utility flow and machine network")
    elif driver == "mythic_landmark":
        if "orientation" not in landmark_roles or not ({"vertical", "verticality"} & (route_roles | directive_roles)):
            _fail("mythic-landmark grammar requires an orientation landmark and vertical play")
    else:
        _fail(f"unsupported terrain driver: {driver or '<missing>'}")
    return {"terrain_driver": driver, "flow_roles": sorted(flow_kinds), "zone_roles": sorted(zones)}


def _check_archetype(program: Mapping[str, Any]) -> dict[str, Any]:
    archetype = str(program.get("archetype", ""))
    grammar = program.get("spatial_grammar", {})
    rooms = str(grammar.get("rooms", ""))
    districts = bool(grammar.get("districts", False))
    if archetype == "city_district" and (not districts or rooms != "nested"):
        _fail("city grammar requires districts=true and nested rooms")
    if archetype == "special_site" and rooms != "none":
        _fail("special-site grammar must be room-free")
    if archetype == "infrastructure_dungeon" and rooms not in {"functional_chambers", "nested"}:
        _fail("infrastructure grammar requires functional chambers")
    if archetype == "wilderness" and rooms not in {"optional_cave_chambers", "none"}:
        _fail("wilderness grammar requires optional or absent cave chambers")
    return {"archetype": archetype, "districts": districts, "rooms": rooms}


def solve_spatial_grammar(program: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and summarize the cross-archetype spatial contract.

    The returned mapping is derived only from the input program and has stable
    ordering.  It is safe to use in reports, quality gates and future adapter
    code without changing the authoritative SceneProgram bytes.
    """

    ids = _entity_ids(program)
    _check_references(program, ids)
    graph, edge_count = _route_graph(program)
    topology = _check_route_semantics(program, graph, edge_count)
    causal = _check_causal_driver(program)
    archetype = _check_archetype(program)
    return {
        "version": GRAMMAR_VERSION,
        "status": "passed",
        "topology": topology,
        "causality": causal,
        "archetype": archetype,
        "entity_counts": {group: len(values) for group, values in sorted(ids.items())},
    }
