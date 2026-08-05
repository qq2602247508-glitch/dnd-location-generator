"""Artifact-level V2.4 spatial and visual quality evaluation.

The evaluator is deliberately downstream of generation.  It consumes the
stable V2 plan/runtime contracts plus an optional render manifest; it neither
knows scene fixture IDs nor imports a planner or Blender.  Hard contract and
safety gates cannot be compensated by a high soft score.  Cohort evaluation
adds cross-seed layout diversity checks to the per-scene report.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


QUALITY_SCHEMA = "dnd-scene-quality-report-1.0"
COHORT_SCHEMA = "dnd-scene-quality-cohort-1.0"
POLICY_SCHEMA = "dnd-scene-quality-policy-1.0"
VISUAL_CERTIFICATE_SCHEMA = "dnd-scene-visual-certificate-1.0"
CERTIFIED_REPORT_SCHEMA = "dnd-scene-certified-quality-1.0"
EVALUATOR_VERSION = "2.4.0-prototype.1"
PROGRAMMATIC_WEIGHT = 0.70
VISUAL_WEIGHT = 0.30
VISUAL_RATING_FIELDS = (
    "silhouette_naturalness",
    "landmark_hierarchy",
    "route_level_readability",
    "lived_in_plausibility",
    "tactical_clarity",
)

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "specs" / "quality" / "v2.4-policy.json"
DIMENSIONS = (
    "diversity",
    "silhouette",
    "routes_landmarks_levels",
    "life_traces",
    "tactical_readability",
    "performance",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_policy(path: Path | None = None) -> dict[str, Any]:
    target = path or DEFAULT_POLICY_PATH
    policy = json.loads(target.read_text(encoding="utf-8"))
    validate_policy(policy)
    return policy


def validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise ValueError("unsupported scene quality policy")
    weights = policy.get("weights", {})
    if set(weights) != set(DIMENSIONS) or sum(int(value) for value in weights.values()) != 100:
        raise ValueError("quality dimension weights must cover the six dimensions and sum to 100")
    if any(not 0 < int(value) <= 100 for value in weights.values()):
        raise ValueError("quality weights must be positive")
    limits = policy.get("hard_limits", {})
    for key in ("runtime_bytes", "glb_bytes", "draw_calls", "vertices", "build_seconds"):
        if float(limits.get(key, 0)) <= 0:
            raise ValueError(f"missing positive hard limit: {key}")
    for name, thresholds in policy.get("rounds", {}).items():
        if name != "baseline" and int(thresholds.get("minimum_samples", 0)) < 2:
            raise ValueError(f"round requires at least two samples: {name}")


def _cell_id(level_id: str, row: int, col: int) -> str:
    return f"{level_id}:{row}:{col}"


def _mask_cells(mask: Mapping[str, Any]) -> set[tuple[int, int]]:
    if mask.get("encoding") != "rle-v1":
        return set()
    cells: set[tuple[int, int]] = set()
    for row, start, length in mask.get("runs", []):
        cells.update((int(row), col) for col in range(int(start), int(start) + int(length)))
    return cells


def _normalized_mask_signature(mask: Mapping[str, Any]) -> str:
    cells = _mask_cells(mask)
    if not cells:
        return "empty"
    min_row = min(row for row, _ in cells)
    min_col = min(col for _, col in cells)
    normalized = sorted((row - min_row, col - min_col) for row, col in cells)
    return sha256_bytes(canonical_bytes(normalized))[:20]


def _perimeter(cells: set[tuple[int, int]]) -> int:
    return sum(
        (row + dr, col + dc) not in cells
        for row, col in cells
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
    )


def _spur_ratio(cells: set[tuple[int, int]]) -> float:
    if not cells:
        return 0.0
    spurs = 0
    for row, col in cells:
        neighbors = sum((row + dr, col + dc) in cells for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)))
        spurs += neighbors <= 1
    return spurs / len(cells)


def _normalized_entropy(values: Iterable[Any]) -> float:
    counts = Counter(values)
    total = sum(counts.values())
    if total <= 1 or len(counts) <= 1:
        return 0.0
    entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
    return entropy / math.log(len(counts))


def _mean(values: Iterable[float], default: float = 0.0) -> float:
    items = list(values)
    return statistics.fmean(items) if items else default


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def _band_score(value: float, *, ideal_low: float, ideal_high: float, outer_low: float, outer_high: float) -> float:
    if ideal_low <= value <= ideal_high:
        return 1.0
    if value <= outer_low or value >= outer_high:
        return 0.0
    if value < ideal_low:
        return (value - outer_low) / max(ideal_low - outer_low, 1e-9)
    return (outer_high - value) / max(outer_high - ideal_high, 1e-9)


def _spatial_entropy(features: Sequence[Mapping[str, Any]], width: int, height: int) -> float:
    if len(features) < 2 or width <= 0 or height <= 0:
        return 0.0
    bins = []
    for feature in features:
        row, col = int(feature.get("row", 0)), int(feature.get("col", 0))
        bins.append((min(3, row * 4 // height), min(3, col * 4 // width)))
    # Normalize against all 16 possible spatial bins, so occupying only two
    # bins is not reported as perfect merely because both contain one feature.
    counts = Counter(bins)
    total = len(bins)
    entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
    return entropy / math.log(16)


def _infer_archetype(plan: Mapping[str, Any]) -> str:
    scene = plan.get("scene", {})
    explicit = scene.get("archetype") or plan.get("archetype") or plan.get("brief", {}).get("archetype")
    if explicit:
        return str(explicit)
    volume_kinds = {str(item.get("kind", "")) for item in plan.get("volumes", [])}
    terrain_kinds = {str(item.get("kind", "")) for item in plan.get("terrain", [])}
    if "water" in terrain_kinds and volume_kinds & {"building", "tower"}:
        return "coastal_district"
    if volume_kinds <= {"sewer", "dungeon", "cave"} and volume_kinds:
        return "infrastructure_site"
    if volume_kinds & {"building", "tower", "district"}:
        return "built_district"
    return "generic_scene"


def _layout_components(plan: Mapping[str, Any], runtime: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    volumes = {str(item.get("id", "")): item for item in plan.get("volumes", [])}
    levels = list(plan.get("levels", []))
    level_order = sorted(
        levels,
        key=lambda item: (
            float(item.get("z_base_ft", 0)),
            _normalized_mask_signature(item.get("cell_mask", {})),
            str(volumes.get(str(item.get("volume_id", "")), {}).get("kind", "")),
            str(item.get("id", "")),
        ),
    )
    level_index = {str(item.get("id", "")): index for index, item in enumerate(level_order)}
    room_lookup = {str(item.get("id", "")): item for item in plan.get("rooms", [])}

    level_records = [
        {
            "index": index,
            "z": float(level.get("z_base_ft", 0)),
            "height": float(level.get("height_ft", 0)),
            "volume_kind": str(volumes.get(str(level.get("volume_id", "")), {}).get("kind", "")),
            "mask": _normalized_mask_signature(level.get("cell_mask", {})),
            "cells": len(_mask_cells(level.get("cell_mask", {}))),
        }
        for index, level in enumerate(level_order)
    ]
    room_records = sorted(
        (
            str(room.get("role", "")),
            str(room.get("visibility", "public")),
            level_index.get(str(room.get("level_id", "")), -1),
            _normalized_mask_signature(room.get("cell_mask", {})),
        )
        for room in plan.get("rooms", [])
    )
    terrain_records = sorted(
        (
            str(item.get("kind", "")),
            level_index.get(str(item.get("level_id", "")), -1),
            _normalized_mask_signature(item.get("cell_mask", {})),
        )
        for item in plan.get("terrain", [])
    )
    connector_records = []
    for connector in plan.get("connectors", []):
        endpoints = []
        for endpoint in connector.get("endpoints", []):
            room = room_lookup.get(str(endpoint.get("room_id", "")), {})
            volume = volumes.get(str(endpoint.get("volume_id", "")), {})
            endpoints.append((
                level_index.get(str(endpoint.get("level_id", "")), -1),
                int(endpoint.get("row", 0)),
                int(endpoint.get("col", 0)),
                str(volume.get("kind", "")),
                str(room.get("role", "")),
            ))
        connector_records.append((str(connector.get("type", "")), str(connector.get("visibility", "public")), tuple(sorted(endpoints))))
    connector_records.sort()

    surface_counts = Counter(
        (
            level_index.get(str(cell.get("level_id", "")), -1),
            str(cell.get("surface", "")),
            bool(cell.get("walkable", False)),
            float(cell.get("z_base_ft", cell.get("elevation", 0))),
        )
        for cell in runtime.get("cells", [])
    )
    component = {
        "grid": {
            "width": int(plan.get("grid", {}).get("width", 0)),
            "height": int(plan.get("grid", {}).get("height", 0)),
            "cell_size_ft": int(plan.get("grid", {}).get("cell_size_ft", 0)),
        },
        "levels": level_records,
        "rooms": room_records,
        "terrain": terrain_records,
        "connectors": connector_records,
        "surfaces": sorted((key, count) for key, count in surface_counts.items()),
    }
    tokens: set[str] = set()
    for index, record in enumerate(level_records):
        tokens.add(f"level:{index}:{sha256_bytes(canonical_bytes(record))[:16]}")
    for name, records in (("room", room_records), ("terrain", terrain_records), ("connector", connector_records)):
        tokens.update(f"{name}:{sha256_bytes(canonical_bytes(record))[:16]}" for record in records)
    tokens.update(f"surface:{sha256_bytes(canonical_bytes(item))[:16]}" for item in component["surfaces"])
    return component, sorted(tokens)


def layout_fingerprint(plan: Mapping[str, Any], runtime: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Return a semantic layout hash and compact tokens for cohort distance.

    Scene name, scene ID, seed, narrative text and feature variants are omitted.
    The fingerprint therefore measures actual topology/spatial structure rather
    than allowing randomized names or dressing to masquerade as layout variety.
    """

    component, tokens = _layout_components(plan, runtime)
    return sha256_bytes(canonical_bytes(component)), tokens


def _jaccard_distance(left: Sequence[str], right: Sequence[str]) -> float:
    a, b = set(left), set(right)
    union = a | b
    return 0.0 if not union else 1.0 - len(a & b) / len(union)


def _graph(cells: Mapping[str, Mapping[str, Any]], edges: Iterable[Mapping[str, Any]], *, public_only: bool) -> dict[str, set[str]]:
    graph = {cell_id: set() for cell_id in cells}
    for edge in edges:
        if public_only and edge.get("visibility") == "dm_only":
            continue
        left, right = str(edge.get("a", "")), str(edge.get("b", ""))
        if left in graph and right in graph:
            graph[left].add(right)
            graph[right].add(left)
    return graph


def _reachable(graph: Mapping[str, set[str]], start: str) -> set[str]:
    if start not in graph:
        return set()
    seen, queue = {start}, deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in graph[current]:
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def _hard_gates(
    plan: Mapping[str, Any],
    runtime: Mapping[str, Any],
    render_manifest: Mapping[str, Any] | None,
    policy: Mapping[str, Any],
    receipts: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, evidence: Any) -> None:
        checks.append({"id": name, "passed": bool(passed), "evidence": evidence})

    scene_id = str(plan.get("scene", {}).get("id", ""))
    runtime_scene_id = str(runtime.get("scene", {}).get("id", ""))
    check("schema.plan", plan.get("schema_version") == "dnd-scene-plan-2.0", plan.get("schema_version"))
    check("schema.runtime", runtime.get("schema_version") == "dnd-scene-runtime-2.0", runtime.get("schema_version"))
    check("scene.identity", bool(scene_id) and scene_id == runtime_scene_id, {"plan": scene_id, "runtime": runtime_scene_id})

    cell_list = list(runtime.get("cells", []))
    cells = {str(cell.get("id", "")): cell for cell in cell_list}
    check("cells.unique_nonempty", bool(cells) and len(cells) == len(cell_list) and "" not in cells, len(cell_list))
    edges = list(runtime.get("nav", {}).get("edges", []))
    invalid_edges = [edge for edge in edges if str(edge.get("a", "")) not in cells or str(edge.get("b", "")) not in cells]
    check("nav.references", not invalid_edges, len(invalid_edges))
    invalid_walk_edges = []
    for edge in edges:
        if edge.get("kind") != "walk" or str(edge.get("a", "")) not in cells or str(edge.get("b", "")) not in cells:
            continue
        left, right = cells[str(edge["a"])], cells[str(edge["b"])]
        if left.get("level_id") != right.get("level_id") or abs(int(left.get("row", 0)) - int(right.get("row", 0))) + abs(int(left.get("col", 0)) - int(right.get("col", 0))) != 1:
            invalid_walk_edges.append([edge.get("a"), edge.get("b")])
    check("nav.walk_edges_are_same_level_neighbors", not invalid_walk_edges, invalid_walk_edges[:20])

    entity_ids: list[str] = []
    for group in ("terrain", "parcels", "volumes", "levels", "rooms", "connectors", "features", "anchors"):
        entity_ids.extend(str(item.get("id", "")) for item in plan.get(group, []))
    duplicate_entities = sorted(item for item, count in Counter(entity_ids).items() if not item or count > 1)
    check("entities.globally_unique", not duplicate_entities, duplicate_entities)

    anchors = list(runtime.get("anchors", []))
    anchor_cells = {
        str(anchor.get("id", "")): _cell_id(str(anchor.get("level_id", "")), int(anchor.get("row", 0)), int(anchor.get("col", 0)))
        for anchor in anchors
    }
    invalid_anchors = [anchor_id for anchor_id, target in anchor_cells.items() if target not in cells or not bool(cells[target].get("walkable", False))]
    check("anchors.walkable_cells", not invalid_anchors, invalid_anchors)
    public_anchors = [anchor for anchor in anchors if anchor.get("visibility", "public") != "dm_only"]
    starts = [anchor for anchor in public_anchors if anchor.get("kind") in {"party_start", "entry", "spawn"}]
    start = anchor_cells.get(str((starts or public_anchors or [{}])[0].get("id", "")), "")
    public_graph = _graph(cells, edges, public_only=True)
    public_reachable = _reachable(public_graph, start)
    unreachable_public = [str(anchor.get("id", "")) for anchor in public_anchors if anchor_cells.get(str(anchor.get("id", ""))) not in public_reachable]
    check("navigation.public_anchors_reachable", bool(start) and not unreachable_public, unreachable_public)
    leaked_secrets = [cell_id for cell_id in public_reachable if cells[cell_id].get("visibility") == "dm_only"]
    check("permissions.no_dm_cell_publicly_reachable", not leaked_secrets, len(leaked_secrets))
    dm_reachable = _reachable(_graph(cells, edges, public_only=False), start)
    unreachable_dm_anchors = [
        str(anchor.get("id", ""))
        for anchor in anchors
        if anchor.get("visibility") == "dm_only" and anchor_cells.get(str(anchor.get("id", ""))) not in dm_reachable
    ]
    check("permissions.dm_anchors_reachable_in_dm_graph", not unreachable_dm_anchors, unreachable_dm_anchors)

    runtime_connectors = list(runtime.get("connectors", []))
    connector_by_id = {str(item.get("id", "")): item for item in runtime_connectors}
    planned_connectors = {str(item.get("id", "")): item for item in plan.get("connectors", [])}
    check("connectors.projected", connector_by_id.keys() == planned_connectors.keys(), {
        "planned": len(planned_connectors), "runtime": len(connector_by_id),
    })
    invalid_connector_cells = []
    for connector_id, connector in connector_by_id.items():
        targets = connector.get("cell_ids", [])
        if len(targets) < 2 or any(target not in cells or not cells[target].get("walkable", False) for target in targets):
            invalid_connector_cells.append(connector_id)
    check("connectors.clear_endpoints", not invalid_connector_cells, invalid_connector_cells)

    feature_cells = []
    for feature in plan.get("features", []):
        target = _cell_id(str(feature.get("level_id", "")), int(feature.get("row", 0)), int(feature.get("col", 0)))
        if target not in cells:
            feature_cells.append(str(feature.get("id", "")))
    check("features.inside_runtime", not feature_cells, feature_cells)

    require_render = bool(policy.get("hard_gates", {}).get("require_render_manifest", True))
    check("render.manifest_present", render_manifest is not None or not require_render, bool(render_manifest))
    performance: dict[str, Any] = {}
    if render_manifest is not None:
        render_scene = str(render_manifest.get("scene_id", ""))
        check("render.scene_identity", render_scene == scene_id, {"plan": scene_id, "render": render_scene})
        declared_outputs = [item.get("path", "") if isinstance(item, Mapping) else str(item) for item in render_manifest.get("outputs", [])]
        check(
            "render.outputs_declared",
            "scene.glb" in declared_outputs and any(item.endswith(".png") for item in declared_outputs),
            declared_outputs,
        )
        expected_counts = {
            "levels": len(plan.get("levels", [])), "rooms": len(plan.get("rooms", [])),
            "connectors": len(plan.get("connectors", [])), "features": len(plan.get("features", [])),
        }
        drift = {key: [expected, render_manifest.get(key)] for key, expected in expected_counts.items() if key in render_manifest and int(render_manifest.get(key, -1)) != expected}
        check("render.semantic_counts", not drift, drift)
        if receipts:
            check("render.input_hashes", not receipts.get("hash_mismatches"), receipts.get("hash_mismatches", []))
            check("render.outputs_present", not receipts.get("missing_outputs"), receipts.get("missing_outputs", []))
        limits = policy["hard_limits"]
        performance = {
            "runtime_bytes": int((receipts or {}).get("runtime_bytes", len(canonical_bytes(runtime)))),
            "glb_bytes": int((receipts or {}).get("glb_bytes", render_manifest.get("glb_bytes", 0) or 0)),
            "draw_calls": int((receipts or {}).get("draw_calls", render_manifest.get("actual_draw_calls", render_manifest.get("estimated_draw_calls", 0)) or 0)),
            "vertices": int((receipts or {}).get("vertices", render_manifest.get("actual_vertices", render_manifest.get("mesh_vertices", 0)) or 0)),
            "build_seconds": float((receipts or {}).get("build_seconds", render_manifest.get("build_seconds", 0)) or 0),
        }
        for key, limit in limits.items():
            value = performance.get(key, 0)
            # A missing timing receipt is reported separately but does not make
            # historical manifests unusable.  Positive observations are gated.
            passed = value <= float(limit) if value > 0 else key == "build_seconds"
            check(f"performance.{key}", passed, {"value": value, "limit": limit})
    return checks, performance


def _soft_dimensions(
    plan: Mapping[str, Any],
    runtime: Mapping[str, Any],
    render_manifest: Mapping[str, Any] | None,
    performance: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    features = list(plan.get("features", []))
    cells = list(runtime.get("cells", []))
    walkable = [cell for cell in cells if cell.get("walkable", False)]
    grid = plan.get("grid", {})
    diversity_raw = {
        "feature_kind_entropy": _normalized_entropy(feature.get("kind", "") for feature in features),
        "feature_variant_entropy": _normalized_entropy(feature.get("variant", "") for feature in features if feature.get("variant")),
        "surface_entropy": _normalized_entropy(cell.get("surface", "") for cell in walkable),
        "spatial_entropy": _spatial_entropy(features, int(grid.get("width", 0)), int(grid.get("height", 0))),
    }
    diversity_values = [diversity_raw["feature_kind_entropy"], diversity_raw["surface_entropy"], diversity_raw["spatial_entropy"]]
    if any(feature.get("variant") for feature in features):
        diversity_values.append(diversity_raw["feature_variant_entropy"])
    diversity_score = 100 * _mean(diversity_values)

    shape_masks = [
        item.get("cell_mask", {})
        for group in (plan.get("levels", []), plan.get("parcels", []))
        for item in group
        if _mask_cells(item.get("cell_mask", {}))
    ]
    signatures = [_normalized_mask_signature(mask) for mask in shape_masks]
    duplicate_ratio = 0.0 if not signatures else (len(signatures) - len(set(signatures))) / len(signatures)
    spur_ratio = _mean(_spur_ratio(_mask_cells(mask)) for mask in shape_masks)
    compactness = [
        _perimeter(points) / max(4 * math.sqrt(len(points)), 1e-9)
        for mask in shape_masks
        if (points := _mask_cells(mask))
    ]
    compactness_score = _mean(
        (_band_score(value, ideal_low=1.0, ideal_high=2.5, outer_low=0.75, outer_high=5.0) for value in compactness),
        0.5,
    )
    silhouette_raw = {
        "mask_count": len(shape_masks), "duplicate_mask_ratio": duplicate_ratio,
        "single_cell_spur_ratio": spur_ratio, "mean_compactness": _mean(compactness),
    }
    silhouette_score = 100 * _mean((1 - min(1.0, duplicate_ratio / 0.6), 1 - min(1.0, spur_ratio / 0.15), compactness_score))

    anchors = list(runtime.get("anchors", []))
    connector_types = [item.get("type", "") for item in runtime.get("connectors", [])]
    levels = list(plan.get("levels", []))
    levels_with_walkable = {str(cell.get("level_id", "")) for cell in walkable}
    landmark_roles = {"objective", "boss", "vista", "social", "encounter", "junction", "state_control"}
    landmarks = [anchor for anchor in anchors if anchor.get("kind") in landmark_roles]
    level_coverage = len(levels_with_walkable) / max(1, len(levels))
    landmark_target = max(1.0, math.sqrt(max(1, len(walkable)) / 600))
    landmark_score = min(1.0, len(landmarks) / landmark_target)
    routes_raw = {
        "levels": len(levels), "walkable_level_coverage": level_coverage,
        "connector_type_entropy": _normalized_entropy(connector_types),
        "landmark_anchors": len(landmarks), "anchor_count": len(anchors),
    }
    routes_score = 100 * _mean((level_coverage, _normalized_entropy(connector_types), landmark_score, min(1.0, len(anchors) / 4)))

    feature_density = len(features) * 100 / max(1, len(walkable))
    density_cfg = policy.get("soft_thresholds", {}).get("life_trace_density_per_100_cells", {})
    density_score = _band_score(
        feature_density,
        ideal_low=float(density_cfg.get("ideal_low", 0.5)), ideal_high=float(density_cfg.get("ideal_high", 4.0)),
        outer_low=float(density_cfg.get("outer_low", 0.0)), outer_high=float(density_cfg.get("outer_high", 10.0)),
    )
    rooms = list(plan.get("rooms", []))
    occupied_rooms = {str(feature.get("room_id", "")) for feature in features if feature.get("room_id")}
    room_coverage = len(occupied_rooms) / max(1, len(rooms)) if rooms else min(1.0, len(features) / 4)
    tagged_traces = [feature for feature in features if set(feature.get("tags", [])) & {"lived_in", "life_trace", "domestic", "work", "wear", "street"}]
    trace_ratio = len(tagged_traces) / max(1, len(features))
    life_raw = {
        "feature_density_per_100_walkable_cells": feature_density,
        "feature_kind_entropy": diversity_raw["feature_kind_entropy"],
        "room_or_site_coverage": room_coverage, "explicit_trace_ratio": trace_ratio,
    }
    life_score = 100 * _mean((density_score, diversity_raw["feature_kind_entropy"], room_coverage, min(1.0, trace_ratio * 2 + 0.25)))

    edges = list(runtime.get("nav", {}).get("edges", []))
    average_degree = 2 * len(edges) / max(1, len(walkable))
    degree_score = _band_score(average_degree, ideal_low=1.4, ideal_high=3.8, outer_low=0.2, outer_high=8.0)
    blocked_ratio = 1 - len(walkable) / max(1, len(cells))
    blocking_features = sum(bool(feature.get("blocks_movement", False)) for feature in features)
    blocking_density = blocking_features / max(1, len(walkable))
    anchor_clearance = _mean(
        1.0 if _cell_id(str(anchor.get("level_id", "")), int(anchor.get("row", 0)), int(anchor.get("col", 0))) in {str(cell.get("id", "")) for cell in walkable} else 0.0
        for anchor in anchors
    )
    connector_coverage = len(runtime.get("connectors", [])) / max(1, len(plan.get("connectors", [])))
    tactical_raw = {
        "average_nav_degree": average_degree, "blocked_cell_ratio": blocked_ratio,
        "blocking_feature_density": blocking_density, "anchor_clearance": anchor_clearance,
        "connector_projection_coverage": min(1.0, connector_coverage),
    }
    tactical_score = 100 * _mean((degree_score, anchor_clearance, min(1.0, connector_coverage), 1 - min(1.0, blocking_density / 0.05)))

    limits = policy["hard_limits"]
    utilizations = {
        key: float(performance.get(key, 0)) / float(limit)
        for key, limit in limits.items()
        if float(performance.get(key, 0)) > 0
    }
    performance_score = 50.0 if not utilizations else 100 * _mean(max(0.0, 1.0 - value * value) for value in utilizations.values())
    performance_raw = {"utilization": utilizations, **{key: performance.get(key, 0) for key in limits}}

    scores = {
        "diversity": (diversity_score, diversity_raw),
        "silhouette": (silhouette_score, silhouette_raw),
        "routes_landmarks_levels": (routes_score, routes_raw),
        "life_traces": (life_score, life_raw),
        "tactical_readability": (tactical_score, tactical_raw),
        "performance": (performance_score, performance_raw),
    }
    return {
        name: {"score": round(max(0.0, min(100.0, score)), 2), "weight": int(policy["weights"][name]), "raw": raw}
        for name, (score, raw) in scores.items()
    }


def evaluate_scene(
    plan: Mapping[str, Any],
    runtime: Mapping[str, Any],
    render_manifest: Mapping[str, Any] | None = None,
    *,
    policy: Mapping[str, Any] | None = None,
    receipts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    active_policy = dict(policy) if policy is not None else load_policy()
    validate_policy(active_policy)
    checks, performance = _hard_gates(plan, runtime, render_manifest, active_policy, receipts)
    failures = [item for item in checks if not item["passed"]]
    dimensions = _soft_dimensions(plan, runtime, render_manifest, performance, active_policy)
    weighted_score = sum(item["score"] * item["weight"] / 100 for item in dimensions.values())
    minimum_ratio = float(active_policy.get("soft_thresholds", {}).get("minimum_dimension_ratio", 0.60))
    weak_dimensions = [name for name, item in dimensions.items() if item["score"] < minimum_ratio * 100]
    threshold = float(active_policy.get("soft_thresholds", {}).get("scene_score_min", 80))
    fingerprint, tokens = layout_fingerprint(plan, runtime)
    score = None if failures else round(weighted_score, 2)
    if failures:
        status = "rejected_hard_gate"
    elif score is not None and score >= threshold and not weak_dimensions:
        status = "programmatic_pass_visual_pending"
    else:
        status = "rejected_soft_score"
    report = {
        "schema_version": QUALITY_SCHEMA,
        "evaluator_version": EVALUATOR_VERSION,
        "policy_version": active_policy.get("policy_version", ""),
        "scene": {
            "id": str(plan.get("scene", {}).get("id", "")),
            "seed": int(plan.get("scene", {}).get("seed", 0)),
            "archetype": _infer_archetype(plan),
        },
        "status": status,
        "hard_gates": {"passed": not failures, "checks": checks, "failure_ids": [item["id"] for item in failures]},
        "dimensions": dimensions,
        "soft_score": score,
        "soft_threshold": threshold,
        "weak_dimensions": weak_dimensions,
        "visual_certification": "pending",
        "layout": {"fingerprint": fingerprint, "tokens": tokens},
        "inputs": dict((receipts or {}).get("inputs", {})),
    }
    report["report_sha256"] = sha256_bytes(canonical_bytes(report))
    return report


def _validate_report_hash(report: Mapping[str, Any]) -> str:
    unsigned = dict(report)
    claimed = str(unsigned.pop("report_sha256", ""))
    actual = sha256_bytes(canonical_bytes(unsigned))
    if not claimed or claimed != actual:
        raise ValueError("programmatic quality report hash is missing or stale")
    return claimed


def _is_sha256(value: Any) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def certify_quality(
    programmatic_report: Mapping[str, Any],
    visual_certificate: Mapping[str, Any],
    *,
    certificate_directory: Path | None = None,
    final_score_min: float = 80.0,
    visual_mean_min: float = 3.5,
    visual_item_min: float = 3.0,
) -> dict[str, Any]:
    """Bind a visual review receipt to a programmatic quality report.

    Certification is downstream-only: neither input is mutated and no value is
    written into a scene semantic hash.  Invalid receipt structure raises a
    ``ValueError``; a structurally valid but low-scoring review produces an
    auditable ``visual_rejected`` report.
    """

    if programmatic_report.get("schema_version") != QUALITY_SCHEMA:
        raise ValueError("unsupported programmatic quality report schema")
    source_report_sha256 = _validate_report_hash(programmatic_report)
    if visual_certificate.get("schema_version") != VISUAL_CERTIFICATE_SCHEMA:
        raise ValueError("unsupported visual certificate schema")
    scene_id = str(programmatic_report.get("scene", {}).get("id", ""))
    certificate_scene_id = str(visual_certificate.get("scene_id", ""))
    if not scene_id or certificate_scene_id != scene_id:
        raise ValueError("visual certificate scene identity does not match the programmatic report")
    if visual_certificate.get("programmatic_report_sha256") != source_report_sha256:
        raise ValueError("visual certificate is not bound to this programmatic report")

    images = visual_certificate.get("images")
    if not isinstance(images, list) or not images:
        raise ValueError("visual certificate requires at least one image receipt")
    image_paths: set[str] = set()
    normalized_images: list[dict[str, str]] = []
    for image in images:
        if not isinstance(image, Mapping):
            raise ValueError("visual certificate image receipt must be an object")
        path = str(image.get("path", ""))
        digest = str(image.get("sha256", ""))
        if not path or path in image_paths or not _is_sha256(digest):
            raise ValueError("visual certificate image paths must be unique and carry lowercase SHA-256")
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("visual certificate image path must be relative and contained")
        if certificate_directory is not None:
            target = certificate_directory / path
            if not target.is_file():
                raise ValueError(f"visual certificate image is missing: {path}")
            if sha256_bytes(target.read_bytes()) != digest:
                raise ValueError(f"visual certificate image hash is stale: {path}")
        image_paths.add(path)
        normalized_images.append({"path": path, "sha256": digest})

    ratings = visual_certificate.get("ratings")
    if not isinstance(ratings, Mapping) or set(ratings) != set(VISUAL_RATING_FIELDS):
        raise ValueError("visual certificate must contain exactly the five standard rating fields")
    normalized_ratings: dict[str, float] = {}
    for field in VISUAL_RATING_FIELDS:
        value = ratings[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1.0 <= float(value) <= 5.0:
            raise ValueError(f"visual rating must be between 1 and 5: {field}")
        normalized_ratings[field] = float(value)
    critical_defects = visual_certificate.get("critical_defects", [])
    if not isinstance(critical_defects, list) or any(not isinstance(item, str) or not item.strip() for item in critical_defects):
        raise ValueError("critical_defects must be a list of non-empty strings")

    certificate_sha256 = sha256_bytes(canonical_bytes(visual_certificate))
    hard_gates_passed = bool(programmatic_report.get("hard_gates", {}).get("passed"))
    programmatic_score_value = programmatic_report.get("soft_score")
    if programmatic_score_value is None:
        programmatic_score = None
    elif isinstance(programmatic_score_value, bool) or not isinstance(programmatic_score_value, (int, float)):
        raise ValueError("programmatic score must be a number or null")
    else:
        programmatic_score = float(programmatic_score_value)
        if not math.isfinite(programmatic_score) or not 0.0 <= programmatic_score <= 100.0:
            raise ValueError("programmatic score must be between 0 and 100")
    visual_mean = statistics.fmean(normalized_ratings.values())
    visual_score = visual_mean / 5.0 * 100.0
    final_score = None if programmatic_score is None else programmatic_score * PROGRAMMATIC_WEIGHT + visual_score * VISUAL_WEIGHT

    rejection_reasons: list[str] = []
    if not hard_gates_passed:
        rejection_reasons.append("programmatic_hard_gates_failed")
    if programmatic_score is None:
        rejection_reasons.append("programmatic_score_unavailable")
    if visual_mean < visual_mean_min:
        rejection_reasons.append("visual_mean_below_threshold")
    if min(normalized_ratings.values()) < visual_item_min:
        rejection_reasons.append("visual_item_below_threshold")
    if critical_defects:
        rejection_reasons.append("critical_defects_present")
    if final_score is None or final_score < final_score_min:
        rejection_reasons.append("final_score_below_threshold")

    result = {
        "schema_version": CERTIFIED_REPORT_SCHEMA,
        "evaluator_version": EVALUATOR_VERSION,
        "scene": dict(programmatic_report.get("scene", {})),
        "status": "certified" if not rejection_reasons else "visual_rejected",
        "source": {
            "programmatic_report_sha256": source_report_sha256,
            "visual_certificate_sha256": certificate_sha256,
        },
        "programmatic": {
            "status": programmatic_report.get("status", ""),
            "hard_gates_passed": hard_gates_passed,
            "score": programmatic_score,
            "weight": PROGRAMMATIC_WEIGHT,
        },
        "visual": {
            "mean_rating": round(visual_mean, 4),
            "score": round(visual_score, 2),
            "weight": VISUAL_WEIGHT,
            "ratings": normalized_ratings,
            "images": normalized_images,
            "critical_defects": list(critical_defects),
            "thresholds": {"mean_min": visual_mean_min, "item_min": visual_item_min},
        },
        "final_score": round(final_score, 2) if final_score is not None else None,
        "final_score_min": final_score_min,
        "rejection_reasons": rejection_reasons,
        "semantic_scene_hash_modified": False,
    }
    result["report_sha256"] = sha256_bytes(canonical_bytes(result))
    return result


def _render_manifest_path(directory: Path) -> Path | None:
    for name in ("scene-render-manifest.json", "scene.render-manifest.json"):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _read_glb_metrics(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        return {"draw_calls": 0, "vertices": 0}
    json_length = int.from_bytes(data[12:16], "little")
    document = json.loads(data[20:20 + json_length].decode("utf-8"))
    accessors = document.get("accessors", [])
    draw_calls = 0
    vertices = 0
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            draw_calls += 1
            accessor_index = primitive.get("attributes", {}).get("POSITION")
            if isinstance(accessor_index, int) and 0 <= accessor_index < len(accessors):
                vertices += int(accessors[accessor_index].get("count", 0))
    return {"draw_calls": draw_calls, "vertices": vertices}


def evaluate_paths(
    plan_path: Path,
    runtime_path: Path,
    render_manifest_path: Path | None = None,
    *,
    policy: Mapping[str, Any] | None = None,
    build_seconds: float = 0.0,
) -> dict[str, Any]:
    plan_bytes, runtime_bytes = plan_path.read_bytes(), runtime_path.read_bytes()
    plan, runtime = json.loads(plan_bytes), json.loads(runtime_bytes)
    manifest_path = render_manifest_path or _render_manifest_path(plan_path.parent)
    render_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path else None
    inputs = {
        "plan": {"path": str(plan_path), "sha256": sha256_bytes(plan_bytes)},
        "runtime": {"path": str(runtime_path), "sha256": sha256_bytes(runtime_bytes)},
    }
    hash_mismatches: list[str] = []
    missing_outputs: list[str] = []
    glb_path = plan_path.parent / "scene.glb"
    metrics = {"draw_calls": 0, "vertices": 0}
    if render_manifest is not None:
        if render_manifest.get("plan_sha256") and render_manifest["plan_sha256"] != inputs["plan"]["sha256"]:
            hash_mismatches.append("plan_sha256")
        if render_manifest.get("runtime_sha256") and render_manifest["runtime_sha256"] != inputs["runtime"]["sha256"]:
            hash_mismatches.append("runtime_sha256")
        outputs = render_manifest.get("outputs", [])
        for output in outputs:
            name = output.get("path", "") if isinstance(output, dict) else str(output)
            if not name or not (plan_path.parent / name).is_file():
                missing_outputs.append(name or "<empty>")
        if glb_path.is_file():
            metrics = _read_glb_metrics(glb_path)
            inputs["glb"] = {"path": str(glb_path), "sha256": sha256_bytes(glb_path.read_bytes())}
    receipts = {
        "inputs": inputs,
        "hash_mismatches": hash_mismatches,
        "missing_outputs": missing_outputs,
        "runtime_bytes": len(runtime_bytes),
        "glb_bytes": glb_path.stat().st_size if glb_path.is_file() else 0,
        "build_seconds": build_seconds,
        **metrics,
    }
    return evaluate_scene(plan, runtime, render_manifest, policy=policy, receipts=receipts)


def discover_scene_directories(roots: Iterable[Path]) -> list[Path]:
    directories: set[Path] = set()
    for root in roots:
        if (root / "scene.plan.json").is_file() and (root / "scene.runtime.json").is_file():
            directories.add(root.resolve())
            continue
        for plan_path in root.rglob("scene.plan.json"):
            if (plan_path.parent / "scene.runtime.json").is_file():
                directories.add(plan_path.parent.resolve())
    return sorted(directories)


def evaluate_cohort(
    reports: Sequence[Mapping[str, Any]],
    *,
    policy: Mapping[str, Any] | None = None,
    round_name: str = "baseline",
) -> dict[str, Any]:
    active_policy = dict(policy) if policy is not None else load_policy()
    validate_policy(active_policy)
    if round_name not in active_policy.get("rounds", {}):
        raise ValueError(f"unknown quality round: {round_name}")
    thresholds = active_policy["rounds"][round_name]
    fingerprints = [str(report.get("layout", {}).get("fingerprint", "")) for report in reports]
    tokens = [list(report.get("layout", {}).get("tokens", [])) for report in reports]
    distances = [_jaccard_distance(tokens[left], tokens[right]) for left in range(len(tokens)) for right in range(left + 1, len(tokens))]
    scores = [float(report["soft_score"]) for report in reports if report.get("soft_score") is not None]
    hard_failures = sum(not bool(report.get("hard_gates", {}).get("passed")) for report in reports)
    unique_count = len(set(fingerprints)) if fingerprints else 0
    unique_rate = unique_count / max(1, len(fingerprints))
    clone_rate = (len(fingerprints) - unique_count) / max(1, len(fingerprints))
    archetype_scores: dict[str, list[float]] = defaultdict(list)
    for report in reports:
        if report.get("soft_score") is not None:
            archetype_scores[str(report.get("scene", {}).get("archetype", "unknown"))].append(float(report["soft_score"]))
    per_archetype = {
        archetype: {"samples": len(values), "median_score": round(statistics.median(values), 2), "p10_score": round(_percentile(values, 0.10), 2)}
        for archetype, values in sorted(archetype_scores.items())
    }
    metrics = {
        "samples": len(reports), "hard_failure_count": hard_failures,
        "score_median": round(statistics.median(scores), 2) if scores else 0.0,
        "score_p10": round(_percentile(scores, 0.10), 2) if scores else 0.0,
        "unique_layouts": unique_count, "unique_layout_rate": round(unique_rate, 4), "clone_rate": round(clone_rate, 4),
        "pairwise_distance_median": round(statistics.median(distances), 4) if distances else 0.0,
        "pairwise_distance_p10": round(_percentile(distances, 0.10), 4) if distances else 0.0,
        "per_archetype": per_archetype,
    }
    enforced = bool(thresholds.get("enforce", True))
    failures = []
    checks = {
        "minimum_samples": len(reports) >= int(thresholds.get("minimum_samples", 1)),
        "zero_hard_failures": hard_failures == 0,
        "score_median": metrics["score_median"] >= float(thresholds.get("score_median_min", 0)),
        "score_p10": metrics["score_p10"] >= float(thresholds.get("score_p10_min", 0)),
        "unique_layout_rate": unique_rate >= float(thresholds.get("unique_layout_rate_min", 0)),
        "clone_rate": clone_rate <= float(thresholds.get("clone_rate_max", 1)),
        "pairwise_distance_median": metrics["pairwise_distance_median"] >= float(thresholds.get("pairwise_distance_median_min", 0)),
        "pairwise_distance_p10": metrics["pairwise_distance_p10"] >= float(thresholds.get("pairwise_distance_p10_min", 0)),
        "per_archetype_median": all(item["median_score"] >= float(thresholds.get("archetype_median_min", 0)) for item in per_archetype.values()),
    }
    if enforced:
        failures = [name for name, passed in checks.items() if not passed]
    status = "baseline_recorded" if not enforced else ("passed" if not failures else "rejected")
    report = {
        "schema_version": COHORT_SCHEMA, "evaluator_version": EVALUATOR_VERSION,
        "policy_version": active_policy.get("policy_version", ""), "round": round_name,
        "status": status, "thresholds_enforced": enforced, "checks": checks,
        "failure_ids": failures, "metrics": metrics,
        "samples": [
            {
                "scene_id": item.get("scene", {}).get("id", ""), "seed": item.get("scene", {}).get("seed", 0),
                "archetype": item.get("scene", {}).get("archetype", ""), "status": item.get("status", ""),
                "soft_score": item.get("soft_score"), "layout_fingerprint": item.get("layout", {}).get("fingerprint", ""),
            }
            for item in reports
        ],
    }
    report["report_sha256"] = sha256_bytes(canonical_bytes(report))
    return report
