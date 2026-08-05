"""Deterministic room/connector constraint solver for archetype manifests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .archetype_manifest import MANIFEST_VERSION, canonical_bytes, resolve_theme, validate_manifest
from .mask import Cell, CellMask
from .rng import named_rng


ROOM_LAYOUT_SCHEMA = "dnd-room-layout-1.0"


@dataclass(frozen=True)
class Region:
    row: int
    col: int
    height: int
    width: int

    @property
    def area(self) -> int:
        return self.height * self.width


def _fail(message: str) -> None:
    raise ValueError(message)


def _room_min_span(spec: Mapping[str, Any], default: int) -> int:
    return max(1, int(spec.get("min_span", default)))


def _area_bounds(spec: Mapping[str, Any]) -> tuple[int, int]:
    return int(spec["min_area"]), int(spec["max_area"])


def _partition(region: Region, specs: list[Mapping[str, Any]], *, seed: int, stream: str, min_span: int) -> list[tuple[Mapping[str, Any], Region]]:
    """Guillotine-partition a rectangle while respecting every room's area bound."""

    if not specs:
        return []
    if len(specs) == 1:
        minimum, maximum = _area_bounds(specs[0])
        if not minimum <= region.area <= maximum:
            _fail(f"room area infeasible for {specs[0]['id']}: {region.area} not in [{minimum}, {maximum}]")
        required_span = _room_min_span(specs[0], min_span)
        if min(region.height, region.width) < required_span:
            _fail(f"room span infeasible for {specs[0]['id']}: {region.height}x{region.width}")
        return [(specs[0], region)]

    first, remainder = specs[0], specs[1:]
    remainder_min = sum(_area_bounds(spec)[0] for spec in remainder)
    remainder_max = sum(_area_bounds(spec)[1] for spec in remainder)
    orientation = "vertical" if region.width >= region.height else "horizontal"
    candidates: list[tuple[Region, Region]] = []

    if orientation == "vertical":
        first_min = max(_area_bounds(first)[0], region.area - remainder_max)
        first_max = min(_area_bounds(first)[1], region.area - remainder_min)
        lower = max(_room_min_span(first, min_span), (first_min + region.height - 1) // region.height)
        upper = min(region.width - _room_min_span(remainder[0], min_span), first_max // region.height)
        for cut in range(lower, upper + 1):
            left = Region(region.row, region.col, region.height, cut)
            right = Region(region.row, region.col + cut, region.height, region.width - cut)
            if right.width < _room_min_span(remainder[0], min_span):
                continue
            candidates.append((left, right))
    else:
        first_min = max(_area_bounds(first)[0], region.area - remainder_max)
        first_max = min(_area_bounds(first)[1], region.area - remainder_min)
        lower = max(_room_min_span(first, min_span), (first_min + region.width - 1) // region.width)
        upper = min(region.height - _room_min_span(remainder[0], min_span), first_max // region.width)
        for cut in range(lower, upper + 1):
            top = Region(region.row, region.col, cut, region.width)
            bottom = Region(region.row + cut, region.col, region.height - cut, region.width)
            if bottom.height < _room_min_span(remainder[0], min_span):
                continue
            candidates.append((top, bottom))

    if not candidates:
        # A rotated partition can make a valid room set solvable even when the
        # longer axis is too constrained by a very narrow room.
        if orientation == "vertical":
            rotated = Region(region.row, region.col, region.height, region.width)
            candidates = []
            first_min = max(_area_bounds(first)[0], region.area - remainder_max)
            first_max = min(_area_bounds(first)[1], region.area - remainder_min)
            lower = max(_room_min_span(first, min_span), (first_min + region.width - 1) // region.width)
            upper = min(region.height - _room_min_span(remainder[0], min_span), first_max // region.width)
            for cut in range(lower, upper + 1):
                top = Region(rotated.row, rotated.col, cut, rotated.width)
                bottom = Region(rotated.row + cut, rotated.col, rotated.height - cut, rotated.width)
                if bottom.height >= _room_min_span(remainder[0], min_span):
                    candidates.append((top, bottom))
        if not candidates:
            _fail(f"no feasible partition for rooms {[spec['id'] for spec in specs]} in {region}")

    rng = named_rng(seed, stream)
    left, right = candidates[rng.randrange(len(candidates))]
    return [(first, left), *_partition(right, remainder, seed=seed, stream=f"{stream}:remainder", min_span=min_span)]


def _ring_regions(width: int, height: int, specs: list[Mapping[str, Any]], *, min_span: int) -> list[tuple[Mapping[str, Any], Region]]:
    if len(specs) != 4:
        _fail("ring layout currently requires exactly four rooms")
    half_height = height // 2
    half_width = width // 2
    if min(half_height, height - half_height, half_width, width - half_width) < min_span:
        _fail("ring layout footprint is too small for its minimum span")
    regions = [
        Region(0, 0, half_height, half_width),
        Region(0, half_width, half_height, width - half_width),
        Region(half_height, half_width, height - half_height, width - half_width),
        Region(half_height, 0, height - half_height, half_width),
    ]
    for spec, region in zip(specs, regions):
        minimum, maximum = _area_bounds(spec)
        if not minimum <= region.area <= maximum:
            _fail(f"ring room area infeasible for {spec['id']}: {region.area} not in [{minimum}, {maximum}]")
    return list(zip(specs, regions))


def _cells(region: Region) -> CellMask:
    return CellMask.rect(region.row, region.col, region.height, region.width)


def _shared_edges(left: CellMask, right: CellMask) -> list[tuple[Cell, Cell]]:
    right_cells = right.cells
    edges: list[tuple[Cell, Cell]] = []
    for cell in left.sorted_cells():
        row, col = cell
        for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            if neighbor in right_cells:
                edges.append((cell, neighbor))
    return edges


def _room_record(floor: Mapping[str, Any], spec: Mapping[str, Any], region: Region) -> dict[str, Any]:
    room = {
        "id": f"{floor['id']}:{spec['id']}",
        "template_id": str(spec["id"]),
        "name": str(spec["name"]),
        "floor_id": str(floor["id"]),
        "role": str(spec["role"]),
        "visibility": str(spec.get("visibility", "dm_only" if spec["role"] == "secret" else "public")),
        "tags": sorted(str(tag) for tag in spec.get("tags", [])),
        "cell_mask": _cells(region).to_rle(),
        "area": region.area,
        "bbox": {"row": region.row, "col": region.col, "height": region.height, "width": region.width},
    }
    return room


def _connector(floor: Mapping[str, Any], left: dict[str, Any], right: dict[str, Any], kind: str = "door") -> dict[str, Any] | None:
    edges = _shared_edges(CellMask.from_rle(left["cell_mask"]), CellMask.from_rle(right["cell_mask"]))
    if not edges:
        return None
    left_cell, right_cell = edges[len(edges) // 2]
    visibility = "dm_only" if kind == "secret_door" else "public"
    return {
        "id": f"{kind}:{left['id']}->{right['id']}",
        "type": kind,
        "bidirectional": True,
        "visibility": visibility,
        "endpoints": [
            {"floor_id": floor["id"], "room_id": left["id"], "row": left_cell[0], "col": left_cell[1]},
            {"floor_id": floor["id"], "room_id": right["id"], "row": right_cell[0], "col": right_cell[1]},
        ],
    }


def _cycle_rank(nodes: Iterable[str], connectors: Iterable[Mapping[str, Any]]) -> int:
    graph = {node: set() for node in nodes}
    edges = 0
    for connector in connectors:
        endpoints = connector["endpoints"]
        left, right = endpoints[0]["room_id"], endpoints[1]["room_id"]
        if left == right:
            continue
        graph[left].add(right)
        graph[right].add(left)
        edges += 1
    seen: set[str] = set()
    components = 0
    for start in graph:
        if start in seen:
            continue
        components += 1
        stack = [start]
        seen.add(start)
        while stack:
            current = stack.pop()
            for target in graph[current]:
                if target not in seen:
                    seen.add(target)
                    stack.append(target)
    return edges - len(graph) + components


def solve_room_layout(manifest: Mapping[str, Any], *, seed: int, width: int, height: int, theme_id: str = "default") -> dict[str, Any]:
    """Solve all manifest floors into rooms, doors, stairs and secret links."""

    validate_manifest(manifest)
    if width < 8 or height < 8:
        _fail("room solver footprint must be at least 8x8 cells")
    resolved = resolve_theme(manifest, theme_id)
    solver = resolved.get("room_solver", {})
    strategy = str(solver.get("strategy", "guillotine"))
    min_span = int(solver.get("min_span", 3))
    if min_span < 2:
        _fail("room solver min_span must be at least 2")

    floors_out: list[dict[str, Any]] = []
    all_rooms: list[dict[str, Any]] = []
    all_connectors: list[dict[str, Any]] = []
    for floor_index, floor in enumerate(resolved["floors"]):
        specs = list(floor["rooms"])
        if strategy == "ring":
            pairs = _ring_regions(width, height, specs, min_span=min_span)
        elif strategy == "guillotine":
            pairs = _partition(Region(0, 0, height, width), specs, seed=seed, stream=f"room:{resolved['id']}:{floor['id']}", min_span=min_span)
        else:
            _fail(f"unsupported room solver strategy: {strategy}")
        rooms = [_room_record(floor, spec, region) for spec, region in pairs]
        room_connectors: list[dict[str, Any]] = []
        for left_index, left in enumerate(rooms):
            for right in rooms[left_index + 1:]:
                connector = _connector(floor, left, right)
                if connector:
                    room_connectors.append(connector)
        floors_out.append({
            "id": floor["id"], "label": floor.get("label", floor["id"]),
            "z_base_ft": int(floor.get("z_base_ft", floor_index * int(solver.get("floor_height_ft", 12)))),
            "height_ft": int(floor.get("height_ft", solver.get("floor_height_ft", 12))),
            "rooms": rooms, "connectors": room_connectors,
        })
        all_rooms.extend(rooms)
        all_connectors.extend(room_connectors)

    constraints = resolved.get("constraints", {})
    by_role = {role: [room for room in all_rooms if room["role"] == role] for role in {room["role"] for room in all_rooms}}
    if constraints.get("require_entry", True) and not by_role.get("entry"):
        _fail("solved layout has no entry room")
    if constraints.get("require_objective", True) and not (by_role.get("objective") or by_role.get("boss")):
        _fail("solved layout has no objective/boss room")
    if constraints.get("require_secret", False) and not by_role.get("secret"):
        _fail("solved layout has no secret room")
    if constraints.get("require_vertical_connector", False):
        for left_floor, right_floor in zip(floors_out, floors_out[1:]):
            left = next((room for room in left_floor["rooms"] if room["role"] in {"stair", "entry", "landing"}), left_floor["rooms"][0])
            right = next((room for room in right_floor["rooms"] if room["role"] in {"stair", "entry", "landing"}), right_floor["rooms"][0])
            left_mask, right_mask = CellMask.from_rle(left["cell_mask"]), CellMask.from_rle(right["cell_mask"])
            left_cell, right_cell = left_mask.sorted_cells()[len(left_mask) // 2], right_mask.sorted_cells()[len(right_mask) // 2]
            connector = {
                "id": f"stairs:{left_floor['id']}->{right_floor['id']}", "type": "stairs", "bidirectional": True, "visibility": "public",
                "endpoints": [
                    {"floor_id": left_floor["id"], "room_id": left["id"], "row": left_cell[0], "col": left_cell[1]},
                    {"floor_id": right_floor["id"], "room_id": right["id"], "row": right_cell[0], "col": right_cell[1]},
                ],
            }
            all_connectors.append(connector)
    secret_rooms = by_role.get("secret", [])
    if secret_rooms:
        for secret in secret_rooms:
            floor = next(item for item in floors_out if item["id"] == secret["floor_id"])
            candidates = [room for room in floor["rooms"] if room["id"] != secret["id"]]
            linked = next(
                (connector for room in candidates
                 for connector in [_connector(floor, room, secret, "secret_door")]
                 if connector is not None),
                None,
            )
            if linked:
                all_connectors.append(linked)
                break
        else:
            _fail("secret room has no adjacent room for a secret door")

    cycle_rank = _cycle_rank((room["id"] for room in all_rooms), all_connectors)
    required_cycles = int(constraints.get("required_cycles", 0))
    if constraints.get("require_loop", False) and cycle_rank < max(1, required_cycles):
        _fail(f"solved layout has {cycle_rank} cycles; loop required")
    if cycle_rank < required_cycles:
        _fail(f"solved layout has {cycle_rank} cycles; requires {required_cycles}")

    output: dict[str, Any] = {
        "schema_version": ROOM_LAYOUT_SCHEMA,
        "solver_version": MANIFEST_VERSION,
        "manifest_id": resolved["id"],
        "manifest_sha256": resolved["manifest_sha256"],
        "theme_id": resolved["resolved_theme_id"],
        "theme": resolved["resolved_theme"],
        "seed": int(seed), "footprint": {"width": int(width), "height": int(height)},
        "floors": floors_out,
        "connectors": sorted(all_connectors, key=lambda item: item["id"]),
        "constraints": {"status": "passed", "cycle_rank": cycle_rank, "required_cycles": required_cycles, "room_count": len(all_rooms)},
    }
    output["layout_sha256"] = hashlib.sha256(canonical_bytes(output)).hexdigest()
    return output


def validate_room_layout(layout: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    validate_manifest(manifest)
    if layout.get("schema_version") != ROOM_LAYOUT_SCHEMA:
        _fail("invalid room layout schema")
    if layout.get("manifest_id") != manifest.get("id"):
        _fail("room layout manifest mismatch")
    unsigned = dict(layout)
    claimed_hash = unsigned.pop("layout_sha256", None)
    if claimed_hash != hashlib.sha256(canonical_bytes(unsigned)).hexdigest():
        _fail("room layout hash is stale")
    rooms = [room for floor in layout.get("floors", []) for room in floor.get("rooms", [])]
    room_by_id = {room["id"]: room for room in rooms}
    cells: dict[tuple[str, int, int], str] = {}
    for room in rooms:
        mask = CellMask.from_rle(room["cell_mask"])
        if len(mask) != int(room["area"]):
            _fail(f"room area metadata is stale: {room['id']}")
        for row, col in mask.cells:
            key = (room["floor_id"], row, col)
            if key in cells:
                _fail(f"room overlap: {room['id']} with {cells[key]}")
            cells[key] = room["id"]
    connector_ids = [connector["id"] for connector in layout.get("connectors", [])]
    if len(set(connector_ids)) != len(connector_ids):
        _fail("duplicate room connector id")
    for connector in layout.get("connectors", []):
        endpoints = connector.get("endpoints", [])
        if len(endpoints) != 2:
            _fail(f"connector must have two endpoints: {connector.get('id', '<unknown>')}")
        left, right = endpoints
        left_room, right_room = room_by_id.get(left.get("room_id")), room_by_id.get(right.get("room_id"))
        if left_room is None or right_room is None:
            _fail(f"connector references missing room: {connector.get('id', '<unknown>')}")
        for endpoint, room in ((left, left_room), (right, right_room)):
            if endpoint.get("floor_id") != room["floor_id"]:
                _fail(f"connector endpoint floor mismatch: {connector['id']}")
            if (endpoint.get("row"), endpoint.get("col")) not in CellMask.from_rle(room["cell_mask"]).cells:
                _fail(f"connector endpoint is outside room: {connector['id']}")
        if connector.get("type") in {"door", "secret_door"}:
            if left["floor_id"] != right["floor_id"]:
                _fail(f"same-floor connector crosses floors: {connector['id']}")
            if abs(int(left["row"]) - int(right["row"])) + abs(int(left["col"]) - int(right["col"])) != 1:
                _fail(f"door endpoints are not adjacent: {connector['id']}")
            if connector["type"] == "secret_door" and connector.get("visibility") != "dm_only":
                _fail(f"secret door is not DM-only: {connector['id']}")
        elif connector.get("type") == "stairs":
            if left["floor_id"] == right["floor_id"]:
                _fail(f"stairs do not cross floors: {connector['id']}")
        else:
            _fail(f"unsupported room connector type: {connector.get('type')}")
    return {
        "status": "passed", "manifest_id": layout["manifest_id"], "theme_id": layout["theme_id"],
        "floors": len(layout["floors"]), "rooms": len(rooms), "connectors": len(connector_ids),
        "cycle_rank": layout["constraints"]["cycle_rank"], "layout_sha256": layout["layout_sha256"],
    }
