"""Deterministic district-level composition planner.

The composer owns the *city layer*: roads, lots, landmark hierarchy and the
placement of independent BuildingFactory instances.  It deliberately stops at
planner geometry.  Blender and the existing plan/runtime realizer can consume
the profile later without learning how a district was arranged.
"""

from __future__ import annotations

import copy
import hashlib
import math
from collections import Counter, deque
from typing import Any, Iterable, Mapping

from .building_factory import BUILDING_CATALOG, resolve_building_profile
from .rng import named_rng
from .scene_contract import canonical_bytes, resolve_scene_profile, validate_scene_brief


DISTRICT_PROFILE_SCHEMA = "dnd-district-profile-1.0"
DISTRICT_COMPOSER_VERSION = "3.0.0-prototype.1"

SCALE_DIMENSIONS = {
    "micro": (32, 24),
    "small": (48, 36),
    "medium": (64, 48),
    "district": (80, 60),
    "city": (112, 80),
    "large": (128, 96),
    "scene": (80, 60),
}

FOOTPRINT_SIZES = {
    "compact_tapered": (6, 6),
    "courtyard_or_l": (10, 8),
    "axial_nave_and_side_aisles": (12, 8),
    "street_front_courtyard": (8, 7),
    "yard_attached": (8, 6),
    "large_span_with_loading_yard": (12, 8),
    "channel_adjacent_split_level": (11, 8),
    "tunnel_chambers_and_shaft": (9, 9),
    "forecourt_axis_and_crypt": (11, 8),
}

DENSITY_FACTORS = {"sparse": 0.70, "varied": 1.00, "dense": 1.30}


def _fail(message: str) -> None:
    raise ValueError(message)


def _int_pair(value: Any, field: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        _fail(f"{field} must be a [row, col] pair")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        _fail(f"{field} must contain integers")
    return int(value[0]), int(value[1])


def _dimensions(brief: Mapping[str, Any]) -> tuple[int, int]:
    planning = brief.get("planning", {})
    explicit = planning.get("dimensions") if isinstance(planning, Mapping) else None
    if explicit is not None:
        if not isinstance(explicit, Mapping):
            _fail("planning.dimensions must be an object")
        width, height = explicit.get("width"), explicit.get("height")
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 24 for item in (width, height)):
            _fail("planning.dimensions width and height must be integers >= 24")
        return int(width), int(height)
    return SCALE_DIMENSIONS[str(brief["scale"])]


def _line_points(points: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sample a Manhattan polyline without depending on a rendering backend."""
    anchors = list(points)
    if len(anchors) < 2:
        _fail("road needs at least two anchor points")
    result: list[tuple[int, int]] = []
    for start, end in zip(anchors, anchors[1:]):
        row, col = start
        end_row, end_col = end
        if not result:
            result.append((row, col))
        while (row, col) != (end_row, end_col):
            if row != end_row:
                row += 1 if end_row > row else -1
            elif col != end_col:
                col += 1 if end_col > col else -1
            if result[-1] != (row, col):
                result.append((row, col))
    return result


def _corridor(points: Iterable[tuple[int, int]], width: int) -> set[tuple[int, int]]:
    radius = max(0, (int(width) - 1) // 2)
    cells: set[tuple[int, int]] = set()
    for row, col in points:
        for d_row in range(-radius, radius + 1):
            for d_col in range(-radius, radius + 1):
                if abs(d_row) + abs(d_col) <= radius + 1:
                    cells.add((row + d_row, col + d_col))
    return cells


def _connected(cells: set[tuple[int, int]]) -> bool:
    if not cells:
        return False
    seen = {next(iter(cells))}
    queue = deque(seen)
    while queue:
        row, col = queue.popleft()
        for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            if neighbor in cells and neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen == cells


def _rect_cells(row: int, col: int, width: int, height: int) -> set[tuple[int, int]]:
    return {(row + d_row, col + d_col) for d_row in range(height) for d_col in range(width)}


def _polygon(row: int, col: int, width: int, height: int, shape: str) -> list[list[int]]:
    if shape == "corner_cut":
        cut = max(1, min(width, height) // 3)
        return [[row, col], [row, col + width - cut], [row + cut, col + width], [row + height, col + width], [row + height, col]]
    if shape == "wedge":
        return [[row, col + 1], [row, col + width - 1], [row + height, col + width], [row + height, col]]
    return [[row, col], [row, col + width], [row + height, col + width], [row + height, col]]


def _density(brief: Mapping[str, Any]) -> str:
    planning = brief.get("planning", {})
    count = planning.get("building_count", {}) if isinstance(planning, Mapping) else {}
    value = count.get("density", "varied") if isinstance(count, Mapping) else "varied"
    if value not in DENSITY_FACTORS:
        _fail("planning.building_count.density must be sparse, varied or dense")
    return str(value)


def _derived_count(width: int, height: int, density: str) -> int:
    # Count follows area and density, then remains bounded by the available
    # frontage.  It is intentionally not tied to any fixture's building count.
    frontage_budget = max(5, (width + height) // 8)
    area_budget = max(5, round((width * height) / 500 * DENSITY_FACTORS[density]))
    return max(5, min(36, max(frontage_budget // 2, area_budget)))


def _mix(brief: Mapping[str, Any]) -> list[tuple[str, str, int]]:
    raw = brief.get("planning", {}).get("building_mix", [])
    if not isinstance(raw, list) or not raw:
        raw = [{"id": "inn", "name": "旅店", "weight": 1}, {"id": "workshop", "name": "工坊", "weight": 1}]
    result: list[tuple[str, str, int]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            _fail("planning.building_mix entries must be objects")
        building_type = str(item.get("type", item.get("id", "")))
        if building_type not in BUILDING_CATALOG:
            _fail(f"district mix references unknown building type: {building_type}")
        name = str(item.get("name", building_type))
        weight = item.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
            _fail(f"building mix weight must be a positive integer: {building_type}")
        result.append((building_type, name, int(weight)))
    return result


def _landmark_type(item: Mapping[str, Any]) -> str | None:
    explicit = item.get("building_type", item.get("type"))
    if explicit:
        value = str(explicit)
        if value not in BUILDING_CATALOG:
            _fail(f"landmark references unknown building type: {value}")
        return value
    text = f"{item.get('id', '')} {item.get('name', '')}".lower()
    for token, building_type in (("tower", "tower"), ("塔", "tower"), ("church", "church"), ("教堂", "church"), ("temple", "temple"), ("神殿", "temple")):
        if token in text:
            return building_type
    return None


def _road_specs(width: int, height: int, seed: int) -> list[dict[str, Any]]:
    rng = named_rng(seed, "district:roads")
    bend_a = rng.randint(-height // 10, height // 10)
    bend_b = rng.randint(-height // 10, height // 10)
    center_col = width // 2 + rng.randint(-width // 10, width // 10)
    specs = [
        ("main_spine", "primary", 3, [(height // 2, 1), (height // 2 + bend_a, width // 3), (height // 2 + bend_b, width * 2 // 3), (height // 2, width - 2)], "people"),
        ("cross_spine", "secondary", 3, [(1, center_col), (height // 3, center_col - 3), (height * 2 // 3, center_col + 2), (height - 2, center_col)], "people"),
        # These branches deliberately start on cross_spine waypoints.  They
        # make the route graph connected while still bending away into a
        # service waterfront and two irregular residential alleys.
        ("waterfront_route", "service", 3, [(height * 2 // 3, center_col + 2), (height - 6, width // 3), (height - 5, width * 2 // 3), (height - 3, width - 2)], "cargo"),
        ("north_alley", "alley", 1, [(height // 3, center_col - 3), (height // 4 + 2, width // 4), (height // 4, 2)], "residents"),
        ("south_alley", "alley", 1, [(height * 2 // 3, center_col + 2), (height * 3 // 4 - 2, width * 3 // 4), (height * 2 // 3, width - 3)], "residents"),
    ]
    result = []
    for road_id, role, road_width, anchors, traffic in specs:
        points = _line_points(anchors)
        result.append({
            "id": road_id,
            "role": role,
            "width": road_width,
            "traffic": traffic,
            "anchors": [[row, col] for row, col in anchors],
            "points": [[row, col] for row, col in points],
            "surface": "cobble" if role != "service" else "packed_stone",
        })
    return result


def _candidate_lots(width: int, height: int, road_cells: set[tuple[int, int]], seed: int) -> list[dict[str, Any]]:
    rng = named_rng(seed, "district:lots")
    candidates: list[dict[str, Any]] = []
    for row in range(3, height - 12, 5):
        for col in range(3, width - 14, 5):
            # A lot is a block-sized reservation; the building is placed inside
            # it later, so roads never become accidental building foundations.
            lot_width = 12 if (row + col) % 3 else 14
            lot_height = 10 if (row * 2 + col) % 4 else 12
            cells = _rect_cells(row, col, lot_width, lot_height)
            if cells & road_cells:
                continue
            distance = abs((row + lot_height // 2) - height // 2) + abs((col + lot_width // 2) - width // 2)
            candidates.append({
                "row": row,
                "col": col,
                "width": lot_width,
                "height": lot_height,
                "cells": cells,
                "distance": distance,
                "shape": ("corner_cut", "rectangle", "wedge", "courtyard")[len(candidates) % 4],
            })
    rng.shuffle(candidates)
    # Interleave near and far candidates so the skyline is not a center-packed
    # chessboard while retaining deterministic seed variation.
    candidates.sort(key=lambda item: (item["distance"] // 8, item["row"] % 3, item["col"] % 4))
    return candidates


def _choose_types(mix: list[tuple[str, str, int]], count: int, seed: int, landmark_types: list[str]) -> list[tuple[str, str, bool]]:
    rng = named_rng(seed, "district:building-mix")
    weighted = [entry for entry in mix for _ in range(entry[2])]
    selected: list[tuple[str, str, bool]] = []
    for index, building_type in enumerate(landmark_types):
        label = next((name for kind, name, _ in mix if kind == building_type), building_type)
        selected.append((building_type, label, True))
    remaining = max(0, count - len(selected))
    for index in range(remaining):
        choice = weighted[(index + rng.randrange(len(weighted))) % len(weighted)]
        selected.append((choice[0], choice[1], False))
    return selected


def compose_district(brief: Mapping[str, Any]) -> dict[str, Any]:
    validate_scene_brief(brief)
    if brief.get("category") != "district":
        _fail("DistrictComposer requires a district SceneBrief")
    scene_profile = resolve_scene_profile(brief)
    width, height = _dimensions(brief)
    density = _density(brief)
    planning = brief.get("planning", {})
    requested_count = planning.get("building_count", {}).get("value") if isinstance(planning.get("building_count", {}), Mapping) else None
    if planning.get("building_count", {}).get("mode", "derived") == "target":
        if isinstance(requested_count, bool) or not isinstance(requested_count, int) or requested_count < 1:
            _fail("target building_count requires a positive integer value")
        building_count = requested_count
        count_mode = "target"
    else:
        building_count = _derived_count(width, height, density)
        count_mode = "derived"

    landmarks = planning.get("landmarks", [])
    if not isinstance(landmarks, list):
        _fail("planning.landmarks must be a list")
    landmark_types = [kind for item in landmarks if isinstance(item, Mapping) for kind in [_landmark_type(item)] if kind]
    building_count = max(building_count, len(landmark_types))
    mix = _mix(brief)
    selected_types = _choose_types(mix, building_count, int(brief["scene"]["seed"]), landmark_types)

    roads = _road_specs(width, height, int(brief["scene"]["seed"]))
    road_cells = set().union(*(_corridor((tuple(point) for point in road["points"]), road["width"]) for road in roads))
    candidates = _candidate_lots(width, height, road_cells, int(brief["scene"]["seed"]))
    occupied: set[tuple[int, int]] = set()
    lots: list[dict[str, Any]] = []
    buildings: list[dict[str, Any]] = []
    rng = named_rng(int(brief["scene"]["seed"]), "district:facades")
    for index, (building_type, label, is_landmark) in enumerate(selected_types):
        recipe = BUILDING_CATALOG[building_type]
        base_width, base_height = FOOTPRINT_SIZES[recipe["footprint"]]
        scale_factor = {"micro": 0.80, "small": 0.90, "medium": 1.00, "district": 1.05, "city": 1.10, "large": 1.20, "scene": 1.05}[str(brief["scale"])]
        footprint_width = max(4, round(base_width * scale_factor))
        footprint_height = max(4, round(base_height * scale_factor))
        chosen = None
        for candidate in candidates:
            if candidate["cells"] & occupied:
                continue
            margin_row = candidate["row"] + (candidate["height"] - footprint_height) // 2
            margin_col = candidate["col"] + (candidate["width"] - footprint_width) // 2
            footprint = _rect_cells(margin_row, margin_col, footprint_width, footprint_height)
            if footprint & road_cells or footprint & occupied or any(row < 1 or col < 1 or row >= height - 1 or col >= width - 1 for row, col in footprint):
                continue
            chosen = (candidate, margin_row, margin_col, footprint)
            break
        if chosen is None:
            _fail(f"unable to place building {index + 1}; increase district dimensions or reduce density")
        candidate, row, col, footprint = chosen
        occupied.update(candidate["cells"])
        lot_id = f"lot_{len(lots) + 1:02d}"
        lots.append({
            "id": lot_id,
            "shape": candidate["shape"],
            "polygon": _polygon(candidate["row"], candidate["col"], candidate["width"], candidate["height"], candidate["shape"]),
            "frontage": roads[(index + rng.randrange(len(roads))) % len(roads)]["id"],
            "capacity": {"width": candidate["width"], "height": candidate["height"]},
        })
        instance_brief = {
            "schema_version": "dnd-building-brief-1.0",
            "building": {"id": f"{building_type}_{index + 1:02d}", "name": label, "type": building_type, "seed": int(brief["scene"]["seed"]) + index + 1},
            "scale": str(brief["scale"] if brief["scale"] in {"micro", "small", "medium"} else "medium"),
            "traits": [],
            "packs": [],
            "floors": {"mode": "derived"},
        }
        profile = resolve_building_profile(instance_brief)
        buildings.append({
            "id": instance_brief["building"]["id"],
            "name": label,
            "type": building_type,
            "lot_id": lot_id,
            "position": [row, col],
            "footprint": {"width": footprint_width, "height": footprint_height, "shape": recipe["footprint"]},
            "footprint_cells": [[r, c] for r, c in sorted(footprint)],
            "orientation_deg": [0, 90, 180, 270][(index + rng.randrange(4)) % 4],
            "is_landmark": is_landmark,
            "family": profile["family"],
            "vertical_grammar": profile["vertical_grammar"],
            "floor_policy": profile["floor_policy"],
            "room_grammar": profile["room_grammar"],
            "packs": profile["packs"],
            "source_building_profile_sha256": profile["source_brief_sha256"],
        })

    landmark_records: list[dict[str, Any]] = []
    for index, item in enumerate(landmarks):
        if not isinstance(item, Mapping):
            _fail("planning.landmarks entries must be objects")
        host = next((building for building in buildings if building["is_landmark"] and building["type"] == _landmark_type(item)), None)
        if host is None and buildings:
            host = buildings[index % len(buildings)]
        position = [host["position"][0] + host["footprint"]["height"] // 2, host["position"][1] + host["footprint"]["width"] // 2] if host else [height // 2, width // 2]
        landmark_records.append({
            "id": str(item["id"]),
            "name": str(item["name"]),
            "role": str(item.get("role", "orientation")),
            "position": position,
            "host_building_id": host["id"] if host else "",
            "height_band": "high" if host and host["type"] in {"tower", "church", "temple"} else "mid",
        })

    profile = {
        "schema_version": DISTRICT_PROFILE_SCHEMA,
        "composer_version": DISTRICT_COMPOSER_VERSION,
        "scene": copy.deepcopy(dict(brief["scene"])),
        "category": "district",
        "kind": str(brief.get("kind", "city_district")),
        "scale": str(brief["scale"]),
        "dimensions": {"width": width, "height": height, "unit": "grid"},
        "scene_profile": scene_profile,
        "planning": {
            "building_count": {"mode": count_mode, "requested": requested_count, "resolved": len(buildings), "density": density},
            "building_mix": [{"type": kind, "name": name, "weight": weight} for kind, name, weight in mix],
            "lot_policy": "derived_from_frontage_and_road_clearance",
        },
        "roads": roads,
        "lots": lots,
        "buildings": buildings,
        "landmarks": landmark_records,
        "skyline": {
            "dominant_landmark_id": next((item["id"] for item in landmark_records if item["height_band"] == "high"), landmark_records[0]["id"] if landmark_records else ""),
            "tiers": ["low_facade", "mid_roofline", "high_landmark" if any(item["height_band"] == "high" for item in landmark_records) else "mid_roofline"],
            "variation": "mixed_heights_and_orientations",
        },
        "entries": [
            {"id": "landward_gate", "road_id": "main_spine", "position": roads[0]["points"][0], "flow": "people"},
            {"id": "dock", "road_id": "waterfront_route", "position": roads[2]["points"][0], "flow": "cargo"},
        ],
        "quality_profile": {
            "views": ["far", "mid", "near", "tactical"],
            "required_evidence": ["street_network", "landmark_hierarchy", "building_mix", "irregular_lots", "skyline_variation"],
            "count_policy": "derived_from_scale_density_frontage",
        },
        "source_brief_sha256": hashlib.sha256(canonical_bytes(dict(brief))).hexdigest(),
    }
    validate_district_profile(profile)
    return profile


def validate_district_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    if profile.get("schema_version") != DISTRICT_PROFILE_SCHEMA:
        _fail("unsupported district profile schema")
    dimensions = profile.get("dimensions", {})
    width, height = int(dimensions.get("width", 0)), int(dimensions.get("height", 0))
    if width < 24 or height < 24:
        _fail("district dimensions are too small")
    roads = profile.get("roads", [])
    if len(roads) < 3:
        _fail("district needs at least three road roles")
    road_cells: set[tuple[int, int]] = set()
    for road in roads:
        points = [_int_pair(point, f"road {road.get('id')} point") for point in road.get("points", [])]
        if len(points) < 2 or any(not (0 <= row < height and 0 <= col < width) for row, col in points):
            _fail(f"road is invalid or leaves bounds: {road.get('id')}")
        road_cells |= _corridor(points, int(road.get("width", 1)))
    road_cells = {(row, col) for row, col in road_cells if 0 <= row < height and 0 <= col < width}
    if not _connected(road_cells):
        _fail("district road network is disconnected")
    buildings = profile.get("buildings", [])
    occupied: set[tuple[int, int]] = set()
    orientations: set[int] = set()
    for building in buildings:
        if building.get("type") not in BUILDING_CATALOG:
            _fail(f"unknown composed building type: {building.get('type')}")
        cells = {_int_pair(point, f"building {building.get('id')} cell") for point in building.get("footprint_cells", [])}
        if not cells or cells & occupied or cells & road_cells:
            _fail(f"building overlaps another building or road: {building.get('id')}")
        if any(not (0 <= row < height and 0 <= col < width) for row, col in cells):
            _fail(f"building leaves district bounds: {building.get('id')}")
        occupied |= cells
        orientations.add(int(building.get("orientation_deg", 0)) % 360)
    if len(orientations) < 2 and len(buildings) > 1:
        _fail("district facade orientations lack variation")
    lots = profile.get("lots", [])
    if len(lots) != len(buildings) or len({lot.get("id") for lot in lots}) != len(lots):
        _fail("each composed building must have one unique lot")
    landmarks = profile.get("landmarks", [])
    if not landmarks:
        _fail("district requires at least one landmark")
    for landmark in landmarks:
        row, col = _int_pair(landmark.get("position"), f"landmark {landmark.get('id')} position")
        if not (0 <= row < height and 0 <= col < width):
            _fail(f"landmark leaves district bounds: {landmark.get('id')}")
    return {
        "status": "passed",
        "width": width,
        "height": height,
        "road_count": len(roads),
        "road_cells": len(road_cells),
        "lot_count": len(lots),
        "building_count": len(buildings),
        "building_types": dict(sorted(Counter(item["type"] for item in buildings).items())),
        "landmark_count": len(landmarks),
        "orientation_count": len(orientations),
    }
