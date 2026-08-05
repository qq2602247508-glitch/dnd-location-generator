"""Bridge the three planner families into one Blender/Viewer visual input."""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Mapping

from .building_factory import resolve_building_profile
from .district_composer import compose_district
from .outdoor_composer import compose_outdoor
from .scene_contract import canonical_bytes
from .visual_packs import resolve_visual_plan


PROFILE_VISUAL_INPUT_SCHEMA = "dnd-profile-visual-input-1.0"
PROFILE_VISUAL_INPUT_VERSION = "3.0.0-prototype.1"


def _fail(message: str) -> None:
    raise ValueError(message)


def resolve_profile(brief: Mapping[str, Any]) -> dict[str, Any]:
    category = brief.get("category") or ("building" if isinstance(brief.get("building"), Mapping) else None)
    if category == "district":
        return compose_district(brief)
    if category == "outdoor":
        return compose_outdoor(brief)
    if category == "building":
        profile = resolve_building_profile(brief)
        profile["category"] = "building"
        profile["scene"] = copy.deepcopy(dict(brief["building"]))
        return profile
    _fail("profile visual input requires a district, building or outdoor brief")


def compose_profile_visual_input(brief: Mapping[str, Any]) -> dict[str, Any]:
    profile = resolve_profile(brief)
    visual_plan = resolve_visual_plan(profile)
    return {
        "schema_version": PROFILE_VISUAL_INPUT_SCHEMA,
        "input_version": PROFILE_VISUAL_INPUT_VERSION,
        "category": profile["category"],
        "scene": copy.deepcopy(dict(profile["scene"])),
        "profile": profile,
        "visual_plan": visual_plan,
        "source_brief_sha256": hashlib.sha256(canonical_bytes(dict(brief))).hexdigest(),
    }


def validate_profile_visual_input(document: Mapping[str, Any]) -> dict[str, Any]:
    if document.get("schema_version") != PROFILE_VISUAL_INPUT_SCHEMA:
        _fail("unsupported profile visual input schema")
    category = document.get("category")
    if category not in {"district", "building", "outdoor"}:
        _fail("profile visual input category is invalid")
    profile = document.get("profile")
    visual_plan = document.get("visual_plan")
    if not isinstance(profile, Mapping) or profile.get("category") != category:
        _fail("profile visual input embeds a mismatched profile")
    if not isinstance(visual_plan, Mapping) or visual_plan.get("category") != category:
        _fail("profile visual input embeds a mismatched visual plan")
    if not document.get("source_brief_sha256"):
        _fail("profile visual input is missing source brief hash")
    return {"status": "passed", "category": category, "scene_id": document.get("scene", {}).get("id", ""), "packs": len(visual_plan.get("packs", [])), "profile_hash": hashlib.sha256(canonical_bytes(dict(profile))).hexdigest(), "visual_plan_hash": hashlib.sha256(canonical_bytes(dict(visual_plan))).hexdigest()}
