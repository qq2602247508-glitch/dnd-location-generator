"""Extensible contract for the three top-level scene families.

The contract deliberately stops before geometry.  A brief selects a family,
traits and visual packs; later planners and realizers decide how many buildings,
rooms or terrain cells are appropriate for the requested scale.  This keeps
"district", "building" and "outdoor" as extensible composition families
instead of turning each first example into a hard-coded generator.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping


SCENE_BRIEF_SCHEMA = "dnd-scene-brief-1.0"
SCENE_CONTRACT_VERSION = "3.0.0-prototype.1"

CATEGORIES = ("district", "building", "outdoor")
SCALES = ("micro", "small", "medium", "district", "city", "large", "scene")
VISUAL_VIEWS = ("far", "mid", "near", "tactical")

# Registry entries describe capabilities, not scene-specific implementation.
# A new building or landscape can be composed from these traits without adding
# another branch to the core generator.
TRAIT_REGISTRY: dict[str, dict[str, Any]] = {
    "urban_density": {"categories": ["district"], "packs": ["street_network", "urban_facades"]},
    "waterfront": {"categories": ["district", "outdoor"], "packs": ["water_edge", "dockside"]},
    "landmark": {"categories": ["district", "building", "outdoor"], "packs": ["landmark_detail"]},
    "street_network": {"categories": ["district"], "packs": ["street_network"]},
    "mixed_buildings": {"categories": ["district"], "packs": ["urban_facades"]},
    "multi_level": {"categories": ["building", "outdoor"], "packs": ["vertical_connections"]},
    "vertical_landmark": {"categories": ["building", "district"], "packs": ["vertical_connections", "landmark_detail"]},
    "interior_rooms": {"categories": ["building"], "packs": ["room_dressing"]},
    "domestic": {"categories": ["building"], "packs": ["room_dressing", "lived_in_detail"]},
    "fortification": {"categories": ["building", "district"], "packs": ["masonry_defense", "vertical_connections"]},
    "infrastructure": {"categories": ["building", "outdoor"], "packs": ["utility_detail"]},
    "water_flow": {"categories": ["building", "outdoor"], "packs": ["hydrology", "utility_detail"]},
    "maintenance_loop": {"categories": ["building", "outdoor"], "packs": ["utility_detail", "vertical_connections"]},
    "cave": {"categories": ["outdoor", "building"], "packs": ["rock_formation", "terrain_detail"]},
    "terrain_elevation": {"categories": ["outdoor"], "packs": ["terrain_detail", "vertical_connections"]},
    "open_terrain": {"categories": ["outdoor"], "packs": ["terrain_detail"]},
    "watershed": {"categories": ["outdoor"], "packs": ["hydrology", "terrain_detail"]},
    "ruin": {"categories": ["outdoor", "building"], "packs": ["ruin_detail", "terrain_detail"]},
    "secret_route": {"categories": ["district", "building", "outdoor"], "packs": ["secret_detail"]},
}

PACK_REGISTRY: dict[str, dict[str, Any]] = {
    "street_network": {"categories": ["district"], "roles": ["road", "alley", "square"]},
    "urban_facades": {"categories": ["district"], "roles": ["facade", "roofline", "streetscape"]},
    "water_edge": {"categories": ["district", "outdoor"], "roles": ["shoreline", "bank", "bridge"]},
    "dockside": {"categories": ["district"], "roles": ["dock", "cargo", "crane"]},
    "landmark_detail": {"categories": ["district", "building", "outdoor"], "roles": ["landmark", "vista"]},
    "vertical_connections": {"categories": ["district", "building", "outdoor"], "roles": ["stairs", "bridge", "ladder", "platform"]},
    "room_dressing": {"categories": ["building"], "roles": ["furniture", "room_function"]},
    "lived_in_detail": {"categories": ["building"], "roles": ["wear", "storage", "lighting"]},
    "masonry_defense": {"categories": ["building", "district"], "roles": ["wall", "gate", "battlement"]},
    "utility_detail": {"categories": ["building", "outdoor"], "roles": ["pipe", "machine", "sluice", "maintenance"]},
    "hydrology": {"categories": ["building", "outdoor"], "roles": ["channel", "water", "flow"]},
    "rock_formation": {"categories": ["outdoor", "building"], "roles": ["cave", "cliff", "strata"]},
    "terrain_detail": {"categories": ["outdoor", "building"], "roles": ["ground", "vegetation", "cover"]},
    "ruin_detail": {"categories": ["outdoor", "building"], "roles": ["collapse", "debris", "weathering"]},
    "secret_detail": {"categories": ["district", "building", "outdoor"], "roles": ["hidden_door", "clue", "cache"]},
}

DEFAULT_PACKS = {
    "district": ["street_network", "urban_facades", "landmark_detail"],
    "building": ["room_dressing", "vertical_connections", "landmark_detail"],
    "outdoor": ["terrain_detail", "landmark_detail", "vertical_connections"],
}

QUALITY_PROFILES = {
    "district": {
        "views": list(VISUAL_VIEWS),
        "required_evidence": ["street_network", "landmark", "building_mix", "far_silhouette"],
        "count_policy": "derived_from_scale_and_planning",
    },
    "building": {
        "views": list(VISUAL_VIEWS),
        "required_evidence": ["exterior_silhouette", "interior_function", "vertical_connection"],
        "count_policy": "single_or_composed_instance",
    },
    "outdoor": {
        "views": list(VISUAL_VIEWS),
        "required_evidence": ["terrain_shape", "elevation_readability", "tactical_landmark"],
        "count_policy": "derived_from_scale_and_terrain",
    },
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def scene_brief_sha256(brief: Mapping[str, Any]) -> str:
    unsigned = copy.deepcopy(dict(brief))
    unsigned.pop("brief_sha256", None)
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


def _fail(message: str) -> None:
    raise ValueError(message)


def _string_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        _fail(f"{field} must be a {'non-empty ' if not allow_empty else ''}list")
    result = [str(item) for item in value]
    if any(not item for item in result):
        _fail(f"{field} cannot contain empty values")
    if len(set(result)) != len(result):
        _fail(f"{field} contains duplicates")
    return result


def _validate_named_items(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        _fail(f"{field} must be a list")
    for item in value:
        if not isinstance(item, Mapping) or not item.get("id") or not item.get("name"):
            _fail(f"{field} entries require id and name")


def resolve_scene_profile(brief: Mapping[str, Any]) -> dict[str, Any]:
    validate_scene_brief(brief)
    category = str(brief["category"])
    traits = [str(item) for item in brief["traits"]]
    explicit_packs = [str(item) for item in brief.get("packs", [])]
    derived_packs = [pack for trait in traits for pack in TRAIT_REGISTRY[trait]["packs"]]
    packs = sorted(set(DEFAULT_PACKS[category]) | set(explicit_packs) | set(derived_packs))
    return {
        "contract_version": SCENE_CONTRACT_VERSION,
        "scene": copy.deepcopy(dict(brief["scene"])),
        "category": category,
        "kind": str(brief.get("kind", category)),
        "scale": str(brief["scale"]),
        "traits": sorted(traits),
        "packs": packs,
        "planning": copy.deepcopy(dict(brief.get("planning", {}))),
        "gameplay": copy.deepcopy(dict(brief.get("gameplay", {}))),
        "quality_profile": copy.deepcopy(QUALITY_PROFILES[category]),
        "source_brief_sha256": scene_brief_sha256(brief),
    }


def validate_scene_brief(brief: Mapping[str, Any]) -> dict[str, Any]:
    if brief.get("schema_version") != SCENE_BRIEF_SCHEMA:
        _fail("unsupported scene brief schema")
    scene = brief.get("scene")
    if not isinstance(scene, Mapping):
        _fail("scene brief requires a scene object")
    if not isinstance(scene.get("id"), str) or not scene["id"]:
        _fail("scene.id must be a non-empty string")
    if not isinstance(scene.get("name"), str) or not scene["name"]:
        _fail("scene.name must be a non-empty string")
    if not isinstance(scene.get("seed"), int) or isinstance(scene.get("seed"), bool):
        _fail("scene.seed must be an integer")
    category = brief.get("category")
    if category not in CATEGORIES:
        _fail(f"scene category must be one of: {', '.join(CATEGORIES)}")
    scale = brief.get("scale")
    if scale not in SCALES:
        _fail(f"scene scale must be one of: {', '.join(SCALES)}")
    traits = _string_list(brief.get("traits"), "traits", allow_empty=False)
    for trait in traits:
        if trait not in TRAIT_REGISTRY:
            _fail(f"unknown trait: {trait}; register it before generation")
        if category not in TRAIT_REGISTRY[trait]["categories"]:
            _fail(f"trait {trait} is not valid for category {category}")
    packs = _string_list(brief.get("packs", []), "packs")
    for pack in packs:
        if pack not in PACK_REGISTRY:
            _fail(f"unknown visual pack: {pack}; register it before generation")
        if category not in PACK_REGISTRY[pack]["categories"]:
            _fail(f"pack {pack} is not valid for category {category}")
    planning = brief.get("planning", {})
    gameplay = brief.get("gameplay", {})
    if not isinstance(planning, Mapping) or not isinstance(gameplay, Mapping):
        _fail("planning and gameplay must be objects")
    _validate_named_items(planning.get("landmarks"), "planning.landmarks")
    _validate_named_items(planning.get("building_mix"), "planning.building_mix")
    if "building_count" in planning:
        count = planning["building_count"]
        if not isinstance(count, Mapping) or count.get("mode", "derived") not in {"derived", "target"}:
            _fail("planning.building_count.mode must be derived or target")
        if count.get("mode") == "target" and (not isinstance(count.get("value"), int) or count["value"] < 1):
            _fail("target building_count requires a positive integer value")
    return {
        "status": "passed",
        "schema_version": SCENE_BRIEF_SCHEMA,
        "scene_id": str(scene["id"]),
        "category": str(category),
        "scale": str(scale),
        "traits": sorted(traits),
        "packs": sorted(packs),
        "brief_sha256": scene_brief_sha256(brief),
    }

