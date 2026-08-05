"""Shared visual-pack resolver for district, building and outdoor profiles.

Visual packs are reusable roles, not scene generators.  The resolver produces
Blender/Viewer-facing material, dressing and camera intent while preserving a
deterministic seed stream.  Geometry remains owned by the category realizer.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Mapping

from .rng import named_rng
from .scene_contract import PACK_REGISTRY, canonical_bytes


VISUAL_PLAN_SCHEMA = "dnd-visual-plan-1.0"
VISUAL_PACK_VERSION = "3.0.0-prototype.1"

PACK_RECIPES: dict[str, dict[str, Any]] = {
    "street_network": {"roles": ["road", "alley", "square"], "materials": ["worn_cobble", "mud_edge", "drain_channel"], "dressing": ["puddles", "cart_tracks", "street_signs"], "semantic_kinds": ["road", "alley", "junction"]},
    "urban_facades": {"roles": ["facade", "roofline", "streetscape"], "materials": ["weathered_plaster", "dark_timber", "aged_brick"], "dressing": ["awnings", "laundry", "shutters"], "semantic_kinds": ["facade", "roof", "street_dressing"]},
    "water_edge": {"roles": ["shoreline", "bank", "bridge"], "materials": ["wet_stone", "river_silt", "water_surface"], "dressing": ["reeds", "mooring_posts", "spray"], "semantic_kinds": ["water", "bank", "bridge"]},
    "dockside": {"roles": ["dock", "cargo", "crane"], "materials": ["tarred_wood", "rusted_iron", "salt_stained_rope"], "dressing": ["crates", "nets", "cargo_hooks"], "semantic_kinds": ["dock", "cargo", "crane"]},
    "landmark_detail": {"roles": ["landmark", "vista"], "materials": ["accent_stone", "signal_metal", "weathered_banner"], "dressing": ["signage", "lanterns", "focal_props"], "semantic_kinds": ["landmark", "vista"]},
    "vertical_connections": {"roles": ["stairs", "bridge", "ladder", "platform"], "materials": ["step_stone", "iron_grate", "rope_rail"], "dressing": ["handrails", "wear_marks", "fall_edges"], "semantic_kinds": ["stairs", "bridge", "ladder", "platform"]},
    "room_dressing": {"roles": ["furniture", "room_function"], "materials": ["wood", "cloth", "ceramic"], "dressing": ["tables", "shelves", "functional_props"], "semantic_kinds": ["furniture", "room_prop"]},
    "lived_in_detail": {"roles": ["wear", "storage", "lighting"], "materials": ["patched_wood", "scuffed_plaster", "warm_lamp"], "dressing": ["personal_items", "stacked_goods", "mess"], "semantic_kinds": ["storage", "light", "wear"]},
    "masonry_defense": {"roles": ["wall", "gate", "battlement"], "materials": ["cut_stone", "iron_gate", "moss_mortar"], "dressing": ["crenels", "arrow_slits", "guard_lanterns"], "semantic_kinds": ["wall", "gate", "battlement"]},
    "utility_detail": {"roles": ["pipe", "machine", "sluice", "maintenance"], "materials": ["oxidized_iron", "wet_brick", "blackened_bronze"], "dressing": ["valves", "gauges", "service_ladders"], "semantic_kinds": ["pipe", "machine", "sluice"]},
    "hydrology": {"roles": ["channel", "water", "flow"], "materials": ["dark_water", "slick_stone", "lime_scale"], "dressing": ["foam", "drips", "water_marks"], "semantic_kinds": ["channel", "water", "flow"]},
    "rock_formation": {"roles": ["cave", "cliff", "strata"], "materials": ["layered_rock", "fractured_slate", "mineral_streak"], "dressing": ["stalactites", "talus", "moss"], "semantic_kinds": ["cave", "cliff", "strata"]},
    "terrain_detail": {"roles": ["ground", "vegetation", "cover"], "materials": ["soil", "grass", "exposed_gravel"], "dressing": ["shrubs", "fallen_logs", "boulders"], "semantic_kinds": ["ground", "vegetation", "cover"]},
    "ruin_detail": {"roles": ["collapse", "debris", "weathering"], "materials": ["broken_masonry", "dust", "rust"], "dressing": ["rubble", "fallen_beams", "ash"], "semantic_kinds": ["collapse", "debris", "weathering"]},
    "secret_detail": {"roles": ["hidden_door", "clue", "cache"], "materials": ["concealed_stone", "wax_seal", "dark_wood"], "dressing": ["scratches", "false_panels", "coded_marks"], "semantic_kinds": ["hidden_door", "clue", "cache"]},
}

PALETTES = {
    "harbor": {"base": "blue_gray", "accent": "verdigris", "light": "amber"},
    "inland": {"base": "warm_gray", "accent": "ochre", "light": "lantern"},
    "underdark": {"base": "basalt", "accent": "fungal_teal", "light": "cold_violet"},
    "highland": {"base": "slate", "accent": "silver_moss", "light": "overcast"},
}


def _fail(message: str) -> None:
    raise ValueError(message)


def _category(profile: Mapping[str, Any]) -> str:
    category = str(profile.get("category", ""))
    if category not in {"district", "building", "outdoor"}:
        _fail("visual resolver requires a district, building or outdoor profile")
    return category


def _packs(profile: Mapping[str, Any], category: str) -> list[str]:
    scene_profile = profile.get("scene_profile", {})
    packs = profile.get("packs") or scene_profile.get("packs") or []
    if not packs and category == "building":
        packs = ["room_dressing", "vertical_connections"]
    if not packs:
        _fail("visual profile has no packs")
    result = sorted({str(pack) for pack in packs})
    for pack in result:
        if pack not in PACK_RECIPES or pack not in PACK_REGISTRY or category not in PACK_REGISTRY[pack]["categories"]:
            _fail(f"pack {pack} is not valid for visual category {category}")
    return result


def resolve_visual_plan(profile: Mapping[str, Any]) -> dict[str, Any]:
    category = _category(profile)
    packs = _packs(profile, category)
    scene = profile.get("scene", {})
    seed = int(scene.get("seed", 0))
    rng = named_rng(seed, f"visual:{category}")
    kind = str(profile.get("kind", ""))
    if category == "outdoor" or any(token in kind.lower() for token in ("valley", "wilderness", "rift", "underdark")):
        palette_name = "highland" if category == "outdoor" else "underdark"
    elif "harbor" in kind.lower() or "port" in kind.lower():
        palette_name = "harbor"
    else:
        palette_name = ["inland", "harbor", "highland"][rng.randrange(3)]
    recipes = [PACK_RECIPES[pack] for pack in packs]
    material_roles = sorted({material for recipe in recipes for material in recipe["materials"]})
    dressing_roles = sorted({dressing for recipe in recipes for dressing in recipe["dressing"]})
    semantic_kinds = sorted({kind_name for recipe in recipes for kind_name in recipe["semantic_kinds"]})
    count_hint = len(profile.get("buildings", [])) or len(profile.get("terrain", {}).get("features", [])) or len(profile.get("room_grammar", [])) or 1
    density = {"district": 1.0, "building": 1.15, "outdoor": 0.75}[category]
    dressing_budget = max(6, round(count_hint * density * max(1, len(packs) / 2)))
    return {
        "schema_version": VISUAL_PLAN_SCHEMA,
        "visual_pack_version": VISUAL_PACK_VERSION,
        "scene": copy.deepcopy(dict(scene)),
        "category": category,
        "kind": kind,
        "packs": packs,
        "palette": {"id": palette_name, **PALETTES[palette_name]},
        "materials": material_roles,
        "dressing": {"roles": dressing_roles, "budget": dressing_budget, "variation": "seeded_sparse_and_dense_clusters"},
        "semantic_kinds": semantic_kinds,
        "camera_presets": {
            "far": {"purpose": "silhouette_and_composition", "exposure": "broad", "show_grid": False},
            "mid": {"purpose": "routes_and_frontage", "exposure": "balanced", "show_grid": False},
            "near": {"purpose": "material_and_function", "exposure": "detail", "show_grid": False},
            "tactical": {"purpose": "cover_height_and_connectors", "exposure": "readable", "show_grid": True},
        },
        "evidence": {
            "required_views": ["far", "mid", "near", "tactical"],
            "required_semantic_kinds": semantic_kinds[:],
            "score_dimensions": ["composition", "silhouette", "material_coherence", "vertical_readability", "tactical_legibility"],
            "minimum_score": 3.0,
        },
        "source_profile_sha256": hashlib.sha256(canonical_bytes(dict(profile))).hexdigest(),
    }


def validate_visual_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("schema_version") != VISUAL_PLAN_SCHEMA:
        _fail("unsupported visual plan schema")
    category = _category(plan)
    packs = _packs(plan, category)
    if len(plan.get("camera_presets", {})) != 4 or set(plan["camera_presets"]) != {"far", "mid", "near", "tactical"}:
        _fail("visual plan requires far, mid, near and tactical cameras")
    if not plan.get("materials") or not plan.get("dressing", {}).get("roles"):
        _fail("visual plan has no reusable material or dressing roles")
    if float(plan.get("evidence", {}).get("minimum_score", 0)) < 1 or float(plan["evidence"]["minimum_score"]) > 5:
        _fail("visual evidence minimum_score must be between 1 and 5")
    return {"status": "passed", "category": category, "packs": len(packs), "materials": len(plan["materials"]), "dressing_budget": int(plan["dressing"]["budget"]), "camera_views": sorted(plan["camera_presets"]), "minimum_score": plan["evidence"]["minimum_score"]}

