"""Deterministic composer for outdoor and special tactical spaces.

Outdoor scenes are not forced through a room/architecture generator.  This
planner describes elevation bands, water/cliff/cave structures, traversal
routes and tactical platforms; a later terrain realizer can turn the same
profile into a grid, Blender meshes or a special-site runtime.
"""

from __future__ import annotations

import copy
import hashlib
from collections import deque
from typing import Any, Iterable, Mapping

from .rng import named_rng
from .scene_contract import canonical_bytes, resolve_scene_profile, validate_scene_brief


OUTDOOR_PROFILE_SCHEMA = "dnd-outdoor-profile-1.0"
OUTDOOR_COMPOSER_VERSION = "3.0.0-prototype.1"

SCALE_DIMENSIONS = {
    "micro": (36, 28),
    "small": (52, 40),
    "medium": (72, 52),
    "district": (88, 64),
    "city": (112, 80),
    "large": (112, 80),
    "scene": (88, 64),
}


def _fail(message: str) -> None:
    raise ValueError(message)


def _pair(value: Any, field: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        _fail(f"{field} must be an integer [row, col] pair")
    return int(value[0]), int(value[1])


def _line(points: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    anchors = list(points)
    if len(anchors) < 2:
        _fail("outdoor route requires at least two points")
    result: list[tuple[int, int]] = [anchors[0]]
    for start, end in zip(anchors, anchors[1:]):
        row, col = start
        end_row, end_col = end
        while (row, col) != (end_row, end_col):
            # Alternate axes when possible to avoid every route becoming a
            # rectilinear staircase with the same visual rhythm.
            if row != end_row and (col == end_col or abs(end_row - row) >= abs(end_col - col)):
                row += 1 if end_row > row else -1
            elif col != end_col:
                col += 1 if end_col > col else -1
            else:
                row += 1 if end_row > row else -1
            if result[-1] != (row, col):
                result.append((row, col))
    return result


def _dimensions(brief: Mapping[str, Any]) -> tuple[int, int]:
    planning = brief.get("planning", {})
    explicit = planning.get("dimensions") if isinstance(planning, Mapping) else None
    if explicit is not None:
        if not isinstance(explicit, Mapping):
            _fail("planning.dimensions must be an object")
        width, height = explicit.get("width"), explicit.get("height")
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 28 for item in (width, height)):
            _fail("planning.dimensions width and height must be integers >= 28")
        return int(width), int(height)
    return SCALE_DIMENSIONS[str(brief["scale"])]


def _band_count(brief: Mapping[str, Any]) -> int:
    requested = brief.get("planning", {}).get("elevation_bands", {})
    minimum = requested.get("minimum", 4) if isinstance(requested, Mapping) else 4
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 3:
        _fail("planning.elevation_bands.minimum must be an integer >= 3")
    return max(3, min(8, minimum))


def _polygon(row: int, col: int, width: int, height: int, notch: int) -> list[list[int]]:
    return [
        [row, col + notch],
        [row, col + width - notch],
        [row + height // 3, col + width],
        [row + height, col + width - notch],
        [row + height, col + notch],
        [row + height // 2, col],
    ]


def _bounded_polygon(polygon: Iterable[Iterable[int]], width: int, height: int) -> list[list[int]]:
    return [[max(0, min(height - 1, int(row))), max(0, min(width - 1, int(col)))] for row, col in polygon]


def _connected_route_network(routes: list[Mapping[str, Any]]) -> bool:
    graph: dict[str, set[str]] = {}
    for route in routes:
        start, end = str(route.get("from")), str(route.get("to"))
        graph.setdefault(start, set()).add(end)
        graph.setdefault(end, set()).add(start)
    if not graph:
        return False
    start = next(iter(graph))
    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbor in graph[node]:
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen == set(graph)


def compose_outdoor(brief: Mapping[str, Any]) -> dict[str, Any]:
    validate_scene_brief(brief)
    if brief.get("category") != "outdoor":
        _fail("OutdoorComposer requires an outdoor SceneBrief")
    scene_profile = resolve_scene_profile(brief)
    width, height = _dimensions(brief)
    seed = int(brief["scene"]["seed"])
    rng = named_rng(seed, "outdoor:terrain")
    bands = _band_count(brief)
    planning = brief.get("planning", {})
    traits = set(brief.get("traits", []))

    elevation_step = 12 + rng.randrange(5)
    terrain_bands: list[dict[str, Any]] = []
    for index in range(bands):
        row = max(0, index * height // bands - 3)
        band_height = height // bands + 7
        elevation = (bands - index - 1) * elevation_step
        terrain_bands.append({
            "id": f"elevation_band_{index + 1}",
            "label": ["high_ridge", "upper_slope", "mid_slope", "valley_floor", "river_basin", "subsurface_edge", "deep_chasm", "lowlands"][min(index, 7)],
            "elevation_ft": elevation,
            "polygon": _bounded_polygon(_polygon(row, (index * 7 + rng.randrange(4)) % max(1, width // 5), width - 4, band_height, 2 + index % 3), width, height),
            "cover": ["exposed_rock", "sparse_pine", "broken_boulder", "wet_grass", "shallow_water", "fungal_cover", "shadowed_rubble", "marsh"][min(index, 7)],
            "walkability": "difficult" if index in {0, bands - 1} else "normal",
        })

    landmark_items = planning.get("landmarks", [])
    if not isinstance(landmark_items, list):
        _fail("planning.landmarks must be a list")
    if not landmark_items:
        landmark_items = [{"id": "terrain_overlook", "name": "高地观景点", "role": "orientation"}]
    cave_enabled = "cave" in traits or any("cave" in str(item.get("id", "")).lower() or "洞" in str(item.get("name", "")) for item in landmark_items if isinstance(item, Mapping))
    water_enabled = "watershed" in traits or "waterfront" in traits
    secret_enabled = "secret_route" in traits

    entry_id = str((brief.get("gameplay", {}) or {}).get("entry_points", ["trailhead"])[0])
    node_ids = [entry_id]
    for item in landmark_items:
        if not isinstance(item, Mapping) or not item.get("id") or not item.get("name"):
            _fail("outdoor landmarks require id and name")
        node_ids.append(str(item["id"]))
    node_ids = list(dict.fromkeys(node_ids))

    trailhead = (height - 5, 7)
    central = (height * 2 // 3, width // 2 + rng.randint(-4, 4))
    ridge = (height // 6, width // 4 + rng.randint(-4, 4))
    cave_mouth = (height // 2, width * 3 // 4)
    landmark_positions: dict[str, tuple[int, int]] = {}
    for index, item in enumerate(landmark_items):
        item_id = str(item["id"])
        if "cave" in item_id.lower() or "洞" in str(item["name"]):
            point = cave_mouth
        elif index == 0:
            point = (height // 3, width // 2)
        else:
            point = (height // 2 + index * 3, max(3, width - 10 - index * 6))
        landmark_positions[item_id] = point

    max_elevation = elevation_step * (bands - 1)
    routes: list[dict[str, Any]] = [
        {
            "id": "valley_trail",
            "name": "谷地主径",
            "role": "primary",
            "from": entry_id,
            "to": str(landmark_items[0]["id"]),
            "traversal": "walk",
            "risk": "medium",
            "points": [[row, col] for row, col in _line([trailhead, central, landmark_positions[str(landmark_items[0]["id"])]])],
            "elevation_profile_ft": [0, elevation_step * 2, max_elevation],
        },
        {
            "id": "ridge_path",
            "name": "山脊险径",
            "role": "alternate",
            "from": entry_id,
            "to": str(landmark_items[0]["id"]),
            "traversal": "climb",
            "risk": "high",
            "points": [[row, col] for row, col in _line([trailhead, ridge, landmark_positions[str(landmark_items[0]["id"])]])],
            "elevation_profile_ft": [0, max_elevation, max_elevation],
        },
    ]
    if len(landmark_items) > 1:
        routes.append({
            "id": "landmark_loop",
            "name": "地标回环",
            "role": "loop",
            "from": str(landmark_items[0]["id"]),
            "to": str(landmark_items[1]["id"]),
            "traversal": "walk",
            "risk": "medium",
            "points": [[row, col] for row, col in _line([landmark_positions[str(landmark_items[0]["id"])], central, landmark_positions[str(landmark_items[1]["id"])]])],
            "elevation_profile_ft": [max_elevation, elevation_step * 2, elevation_step],
        })
    if secret_enabled:
        secret_target = str(next((item["id"] for item in landmark_items if "cave" in str(item["id"]).lower() or "洞" in str(item["name"])), landmark_items[-1]["id"]))
        routes.append({
            "id": "waterfall_secret",
            "name": "隐蔽水幕后路",
            "role": "secret",
            "from": str(landmark_items[0]["id"]),
            "to": secret_target,
            "visibility": "dm_only",
            "traversal": "wade_or_climb",
            "risk": "high",
            "points": [[row, col] for row, col in _line([landmark_positions[str(landmark_items[0]["id"])], (height // 2, width // 2 + 8), landmark_positions[secret_target]])],
            "elevation_profile_ft": [max_elevation, elevation_step * 2, elevation_step],
        })

    watercourses = []
    if water_enabled:
        water_points = _line([(height // 8, width // 5), (height // 3, width // 3), (height // 2, width // 2), (height * 3 // 4, width * 2 // 3), (height - 3, width * 4 // 5)])
        watercourses.append({
            "id": "silverfall_watercourse",
            "name": "主河与瀑布阶",
            "points": [[row, col] for row, col in water_points],
            "width_cells": 3 + rng.randrange(3),
            "source_elevation_ft": elevation_step * bands,
            "mouth_elevation_ft": 0,
            "crossings": [[central[0], central[1]], [height * 3 // 4, width * 2 // 3]],
        })

    cliffs = []
    for index in range(max(1, bands - 2)):
        row = (index + 1) * height // bands
        cliffs.append({
            "id": f"cliff_step_{index + 1}",
            "edge": [[row, 3], [row + rng.randint(-2, 2), width // 3], [row + rng.randint(-2, 2), width * 2 // 3], [row, width - 4]],
            "height_ft": elevation_step,
            "hazard": "fall_or_forced_movement" if index % 2 == 0 else "cover_break",
        })

    features = []
    if cave_enabled:
        features.append({"id": "echo_cave", "kind": "cave_mouth", "position": list(cave_mouth), "depth_cells": 12 + rng.randrange(10), "room_dependencies": [], "tactical_role": "flank_and_cover"})
    features.extend([
        {"id": "ridge_overlook", "kind": "elevated_platform", "position": list(ridge), "elevation_ft": max_elevation, "tactical_role": "high_ground"},
        {"id": "river_ford", "kind": "crossing", "position": list(central), "elevation_ft": elevation_step * 2, "tactical_role": "crossfire"},
    ])
    landmarks = [
        {"id": str(item["id"]), "name": str(item["name"]), "role": str(item.get("role", "orientation")), "position": list(landmark_positions[str(item["id"])]), "height_band": "high" if index == 0 else "mid"}
        for index, item in enumerate(landmark_items)
    ]
    profile = {
        "schema_version": OUTDOOR_PROFILE_SCHEMA,
        "composer_version": OUTDOOR_COMPOSER_VERSION,
        "scene": copy.deepcopy(dict(brief["scene"])),
        "category": "outdoor",
        "kind": str(brief.get("kind", "wilderness")),
        "scale": str(brief["scale"]),
        "dimensions": {"width": width, "height": height, "unit": "grid"},
        "scene_profile": scene_profile,
        "terrain": {"elevation_bands": terrain_bands, "elevation_range_ft": [0, max_elevation], "watercourses": watercourses, "cliffs": cliffs, "features": features},
        "routes": routes,
        "landmarks": landmarks,
        "tactical_platforms": [feature for feature in features if feature["kind"] in {"elevated_platform", "crossing", "cave_mouth"}],
        "entries": [{"id": entry_id, "position": list(trailhead), "route_id": "valley_trail"}],
        "quality_profile": {"views": ["far", "mid", "near", "tactical"], "required_evidence": ["terrain_shape", "elevation_readability", "water_or_geology", "tactical_landmark", "route_choice"], "room_policy": "optional_only"},
        "source_brief_sha256": hashlib.sha256(canonical_bytes(dict(brief))).hexdigest(),
    }
    validate_outdoor_profile(profile)
    return profile


def validate_outdoor_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    if profile.get("schema_version") != OUTDOOR_PROFILE_SCHEMA:
        _fail("unsupported outdoor profile schema")
    width = int(profile.get("dimensions", {}).get("width", 0))
    height = int(profile.get("dimensions", {}).get("height", 0))
    if width < 28 or height < 28:
        _fail("outdoor dimensions are too small")
    terrain = profile.get("terrain", {})
    bands = terrain.get("elevation_bands", [])
    if len(bands) < 3:
        _fail("outdoor scene requires at least three elevation bands")
    elevations = [int(band.get("elevation_ft", -1)) for band in bands]
    if elevations != sorted(elevations, reverse=True) or elevations[0] <= elevations[-1]:
        _fail("elevation bands must descend and expose a readable range")
    for band in bands:
        points = [_pair(point, f"terrain band {band.get('id')} point") for point in band.get("polygon", [])]
        if len(points) < 4 or any(not (0 <= row < height + 8 and 0 <= col < width + 8) for row, col in points):
            _fail(f"terrain band is invalid: {band.get('id')}")
    routes = profile.get("routes", [])
    if not routes or not any(route.get("role") == "primary" for route in routes) or not any(route.get("role") == "alternate" for route in routes):
        _fail("outdoor scene requires primary and alternate routes")
    if any(route.get("role") == "secret" and route.get("visibility") != "dm_only" for route in routes):
        _fail("secret outdoor routes must be DM-only")
    if not _connected_route_network(routes):
        _fail("outdoor route network is disconnected")
    for route in routes:
        points = [_pair(point, f"route {route.get('id')} point") for point in route.get("points", [])]
        if len(points) < 2 or any(not (0 <= row < height and 0 <= col < width) for row, col in points):
            _fail(f"route leaves outdoor bounds: {route.get('id')}")
    watercourses = terrain.get("watercourses", [])
    for water in watercourses:
        if int(water.get("source_elevation_ft", 0)) <= int(water.get("mouth_elevation_ft", 0)):
            _fail("watercourse must descend from source to mouth")
    if not profile.get("tactical_platforms"):
        _fail("outdoor scene requires at least one tactical platform")
    for platform in profile["tactical_platforms"]:
        row, col = _pair(platform.get("position"), f"platform {platform.get('id')} position")
        if not (0 <= row < height and 0 <= col < width):
            _fail(f"tactical platform leaves bounds: {platform.get('id')}")
    return {
        "status": "passed",
        "width": width,
        "height": height,
        "elevation_bands": len(bands),
        "elevation_range_ft": [min(elevations), max(elevations)],
        "route_count": len(routes),
        "watercourses": len(watercourses),
        "cliff_steps": len(terrain.get("cliffs", [])),
        "feature_count": len(terrain.get("features", [])),
        "tactical_platforms": len(profile["tactical_platforms"]),
    }
