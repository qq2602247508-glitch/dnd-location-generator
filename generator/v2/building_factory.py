"""Planner-facing building factory contract.

This module does not render Blender geometry yet.  It resolves a building brief
into a reusable architectural recipe that can be placed by a district composer
or used as a standalone tactical location.  The recipe is intentionally richer
than a room count: silhouette, frontage, vertical grammar, room grammar and
visual packs are separate so a future building type can reuse the same core.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

from .scene_contract import PACK_REGISTRY, TRAIT_REGISTRY, canonical_bytes


BUILDING_BRIEF_SCHEMA = "dnd-building-brief-1.0"
BUILDING_FACTORY_VERSION = "3.0.0-prototype.1"

# These are registry recipes, not generator branches.  Each recipe declares
# which architectural grammar it needs; the eventual geometry builder consumes
# the same fields for every type.
BUILDING_CATALOG: dict[str, dict[str, Any]] = {
    "tower": {
        "family": "vertical_landmark",
        "footprint": "compact_tapered",
        "frontage": "single_gate",
        "vertical_grammar": "central_stair_and_landing",
        "room_grammar": ["entry", "guard", "landing", "archive", "quarters", "objective", "secret"],
        "default_traits": ["multi_level", "vertical_landmark", "interior_rooms"],
        "default_packs": ["vertical_connections", "landmark_detail", "room_dressing"],
        "floor_policy": {"mode": "derived", "minimum": 3, "maximum": 6},
    },
    "manor": {
        "family": "domestic_estate",
        "footprint": "courtyard_or_l",
        "frontage": "formal_entry_and_service_lane",
        "vertical_grammar": "main_stair_plus_service_stair",
        "room_grammar": ["entry", "salon", "gallery", "bedchamber", "library", "service", "secret"],
        "default_traits": ["multi_level", "domestic", "interior_rooms", "secret_route"],
        "default_packs": ["room_dressing", "lived_in_detail", "vertical_connections"],
        "floor_policy": {"mode": "derived", "minimum": 2, "maximum": 4},
    },
    "church": {
        "family": "processional_civic",
        "footprint": "axial_nave_and_side_aisles",
        "frontage": "processional_forecourt",
        "vertical_grammar": "bell_tower_and_roof_walk",
        "room_grammar": ["nave", "aisle", "chapel", "vestry", "crypt", "bell_chamber"],
        "default_traits": ["multi_level", "interior_rooms", "vertical_landmark"],
        "default_packs": ["masonry_defense", "vertical_connections", "room_dressing"],
        "floor_policy": {"mode": "derived", "minimum": 2, "maximum": 4},
    },
    "inn": {
        "family": "street_front_commerce",
        "footprint": "street_front_courtyard",
        "frontage": "main_street",
        "vertical_grammar": "public_stair_to_rooms",
        "room_grammar": ["taproom", "kitchen", "stable", "guest_room", "cellar", "back_room"],
        "default_traits": ["domestic", "interior_rooms"],
        "default_packs": ["room_dressing", "lived_in_detail"],
        "floor_policy": {"mode": "derived", "minimum": 1, "maximum": 3},
    },
    "workshop": {
        "family": "industrial_craft",
        "footprint": "yard_attached",
        "frontage": "service_lane",
        "vertical_grammar": "mezzanine_and_lift",
        "room_grammar": ["work_floor", "store", "office", "yard", "hazard_room"],
        "default_traits": ["infrastructure", "interior_rooms"],
        "default_packs": ["utility_detail", "room_dressing", "vertical_connections"],
        "floor_policy": {"mode": "derived", "minimum": 1, "maximum": 3},
    },
    "warehouse": {
        "family": "logistics_span",
        "footprint": "large_span_with_loading_yard",
        "frontage": "cargo_route",
        "vertical_grammar": "gantry_and_roof_access",
        "room_grammar": ["loading_floor", "storage", "office", "hidden_cache"],
        "default_traits": ["infrastructure", "interior_rooms", "secret_route"],
        "default_packs": ["utility_detail", "room_dressing", "secret_detail"],
        "floor_policy": {"mode": "derived", "minimum": 1, "maximum": 2},
    },
    "pump_house": {
        "family": "water_infrastructure",
        "footprint": "channel_adjacent_split_level",
        "frontage": "maintenance_access",
        "vertical_grammar": "low_channel_catwalk_pump_deck",
        "room_grammar": ["intake", "collector", "pump_hall", "maintenance_loop", "control", "buried_shrine"],
        "default_traits": ["infrastructure", "water_flow", "maintenance_loop", "multi_level", "secret_route"],
        "default_packs": ["hydrology", "utility_detail", "vertical_connections", "secret_detail"],
        "floor_policy": {"mode": "derived", "minimum": 2, "maximum": 4},
    },
    "mine": {
        "family": "subterranean_extraction",
        "footprint": "tunnel_chambers_and_shaft",
        "frontage": "adit",
        "vertical_grammar": "shaft_ladders_and_lifts",
        "room_grammar": ["adit", "ore_face", "support_chamber", "lift", "collapsed_branch", "cache"],
        "default_traits": ["cave", "infrastructure", "multi_level", "secret_route"],
        "default_packs": ["rock_formation", "utility_detail", "vertical_connections", "secret_detail"],
        "floor_policy": {"mode": "derived", "minimum": 2, "maximum": 5},
    },
    "temple": {
        "family": "ritual_complex",
        "footprint": "forecourt_axis_and_crypt",
        "frontage": "ceremonial_steps",
        "vertical_grammar": "sanctum_gallery_and_crypt",
        "room_grammar": ["forecourt", "nave", "sanctum", "side_chapel", "crypt", "secret_vault"],
        "default_traits": ["interior_rooms", "multi_level", "secret_route", "vertical_landmark"],
        "default_packs": ["room_dressing", "vertical_connections", "secret_detail", "landmark_detail"],
        "floor_policy": {"mode": "derived", "minimum": 2, "maximum": 4},
    },
}


def building_brief_sha256(brief: Mapping[str, Any]) -> str:
    unsigned = copy.deepcopy(dict(brief))
    unsigned.pop("brief_sha256", None)
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


def _fail(message: str) -> None:
    raise ValueError(message)


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        _fail(f"{field} must be a list")
    values = [str(item) for item in value]
    if any(not item for item in values) or len(set(values)) != len(values):
        _fail(f"{field} must contain unique non-empty values")
    return values


def validate_building_brief(brief: Mapping[str, Any]) -> dict[str, Any]:
    if brief.get("schema_version") != BUILDING_BRIEF_SCHEMA:
        _fail("unsupported building brief schema")
    building = brief.get("building")
    if not isinstance(building, Mapping):
        _fail("building brief requires a building object")
    for field in ("id", "name", "type"):
        if not isinstance(building.get(field), str) or not building[field]:
            _fail(f"building.{field} must be a non-empty string")
    if building["type"] not in BUILDING_CATALOG:
        _fail(f"unknown building type: {building['type']}; register a recipe first")
    if not isinstance(building.get("seed"), int) or isinstance(building.get("seed"), bool):
        _fail("building.seed must be an integer")
    scale = brief.get("scale", "small")
    if scale not in {"micro", "small", "medium", "large"}:
        _fail("building scale must be micro, small, medium or large")
    traits = _string_list(brief.get("traits", []), "traits")
    for trait in traits:
        if trait not in TRAIT_REGISTRY or "building" not in TRAIT_REGISTRY[trait]["categories"]:
            _fail(f"trait {trait} is not valid for a building")
    packs = _string_list(brief.get("packs", []), "packs")
    for pack in packs:
        if pack not in PACK_REGISTRY or "building" not in PACK_REGISTRY[pack]["categories"]:
            _fail(f"pack {pack} is not valid for a building")
    floor_request = brief.get("floors", {"mode": "derived"})
    if not isinstance(floor_request, Mapping) or floor_request.get("mode", "derived") not in {"derived", "target"}:
        _fail("floors.mode must be derived or target")
    if floor_request.get("mode") == "target" and (not isinstance(floor_request.get("value"), int) or floor_request["value"] < 1):
        _fail("target floors require a positive integer value")
    room_mix = brief.get("room_mix", [])
    if not isinstance(room_mix, list) or any(not isinstance(item, str) or not item for item in room_mix):
        _fail("room_mix must be a list of non-empty strings")
    return {
        "status": "passed",
        "schema_version": BUILDING_BRIEF_SCHEMA,
        "building_id": str(building["id"]),
        "building_type": str(building["type"]),
        "traits": sorted(traits),
        "packs": sorted(packs),
        "brief_sha256": building_brief_sha256(brief),
    }


def resolve_building_profile(brief: Mapping[str, Any]) -> dict[str, Any]:
    validate_building_brief(brief)
    building = brief["building"]
    recipe = BUILDING_CATALOG[str(building["type"])]
    traits = sorted(set(recipe["default_traits"]) | set(brief.get("traits", [])))
    packs = sorted(set(recipe["default_packs"]) | set(brief.get("packs", [])) | {
        pack for trait in traits for pack in TRAIT_REGISTRY[trait]["packs"]
    })
    policy = recipe["floor_policy"]
    floor_request = brief.get("floors", {"mode": "derived"})
    if floor_request.get("mode", "derived") == "target":
        floor_policy = {"mode": "target", "value": int(floor_request["value"])}
    else:
        floor_policy = {**policy, "mode": "derived"}
    room_mix = list(brief.get("room_mix", [])) or list(recipe["room_grammar"])
    return {
        "schema_version": "dnd-building-profile-1.0",
        "factory_version": BUILDING_FACTORY_VERSION,
        "building": copy.deepcopy(dict(building)),
        "scale": str(brief.get("scale", "small")),
        "family": recipe["family"],
        "footprint": recipe["footprint"],
        "frontage": recipe["frontage"],
        "vertical_grammar": recipe["vertical_grammar"],
        "floor_policy": floor_policy,
        "room_grammar": room_mix,
        "traits": traits,
        "packs": packs,
        "quality_profile": {
            "views": ["far", "mid", "near", "tactical"],
            "required_evidence": ["exterior_silhouette", "interior_function", "vertical_connection"],
            "count_policy": "single_or_composed_instance",
        },
        "source_brief_sha256": building_brief_sha256(brief),
    }

