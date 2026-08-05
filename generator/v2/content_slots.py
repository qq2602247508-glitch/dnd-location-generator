"""Category-neutral NPC, encounter and reward attachment slots.

The generator owns placement intent and difficulty envelopes.  A future DND
adapter may resolve these slots to the user's NPC/monster/item tables; this
module intentionally never emits statblocks or writes an external project.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Mapping

from .adventure import DIFFICULTY_BANDS, validate_dm_profile
from .scene_contract import canonical_bytes


CONTENT_SLOTS_SCHEMA = "dnd-location-content-slots-1.0"
CONTENT_SLOTS_VERSION = "3.0.0-prototype.1"


def _fail(message: str) -> None:
    raise ValueError(message)


def _category(profile: Mapping[str, Any]) -> str:
    category = str(profile.get("category", ""))
    if category not in {"district", "building", "outdoor"}:
        _fail("content slots require a district, building or outdoor profile")
    return category


def _anchors(profile: Mapping[str, Any], category: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if category == "district":
        for landmark in profile.get("landmarks", []):
            result.append({"id": str(landmark["id"]), "kind": "landmark", "role": str(landmark.get("role", "orientation")), "visibility": "public"})
        for building in profile.get("buildings", []):
            result.append({"id": str(building["id"]), "kind": "building", "role": "landmark" if building.get("is_landmark") else "building", "visibility": "public"})
        for entry in profile.get("entries", []):
            result.append({"id": str(entry["id"]), "kind": "entry", "role": "entry", "visibility": "public"})
    elif category == "building":
        building = profile.get("building", {})
        result.append({"id": str(building.get("id", "building")), "kind": "building", "role": "objective", "visibility": "public"})
        for index, room in enumerate(profile.get("room_grammar", [])):
            result.append({"id": f"room_{index:02d}_{room}", "kind": "room", "role": "room", "visibility": "dm_only" if room in {"secret", "secret_vault", "buried_shrine", "hidden_cache"} else "public"})
    else:
        for landmark in profile.get("landmarks", []):
            result.append({"id": str(landmark["id"]), "kind": "landmark", "role": str(landmark.get("role", "orientation")), "visibility": "public"})
        for feature in profile.get("terrain", {}).get("features", []):
            result.append({"id": str(feature["id"]), "kind": str(feature.get("kind", "feature")), "role": str(feature.get("tactical_role", "cover")), "visibility": "public"})
        for entry in profile.get("entries", []):
            result.append({"id": str(entry["id"]), "kind": "entry", "role": "entry", "visibility": "public"})
    deduped = []
    seen = set()
    for anchor in result:
        if anchor["id"] not in seen:
            seen.add(anchor["id"])
            deduped.append(anchor)
    if len(deduped) < 2:
        _fail("profile does not expose enough anchors for content placement")
    return deduped


def _difficulty_envelope(level: int, size: int, difficulty: str, boss: bool) -> list[int]:
    center = max(1, round(level * size / 4))
    offset = DIFFICULTY_BANDS[difficulty]
    return [max(1, center - 2 + offset), center + (3 if boss else 1) + offset]


def compose_content_slots(profile: Mapping[str, Any], dm_profile: Mapping[str, Any]) -> dict[str, Any]:
    category = _category(profile)
    validate_dm_profile(dict(dm_profile))
    anchors = _anchors(profile, category)
    party = dm_profile["party"]
    encounter_profile = dm_profile["encounters"]
    reward_profile = dm_profile["rewards"]
    seed = int(profile.get("scene", {}).get("seed", profile.get("building", {}).get("seed", 0)))
    count = max(2, min(8, round(2 + float(encounter_profile["density"]) * 6)))
    public_anchors = [item for item in anchors if item["visibility"] == "public"] or anchors
    population = []
    for index, anchor in enumerate(public_anchors[: max(2, min(5, len(public_anchors))) ]):
        population.append({
            "id": f"npc_slot_{index:02d}_{anchor['id']}",
            "anchor_ref": anchor["id"],
            "role": ["local_contact", "authority", "worker", "guide", "witness"][index % 5],
            "faction_hint": "derive_from_scene_context",
            "visibility": anchor["visibility"],
            "resolution_status": "slot",
        })
    encounters = []
    for index in range(count):
        anchor = public_anchors[index % len(public_anchors)]
        boss = index == count - 1 and float(encounter_profile["boss_ratio"]) > 0
        difficulty = "deadly" if boss and encounter_profile["difficulty"] in {"hard", "deadly"} else str(encounter_profile["difficulty"])
        encounters.append({
            "id": f"encounter_slot_{index:02d}_{anchor['id']}",
            "anchor_ref": anchor["id"],
            "role": "boss" if boss else ("patrol" if index % 2 else "set_piece"),
            "difficulty": difficulty,
            "cr_range": _difficulty_envelope(int(party["level"]), int(party["size"]), difficulty, boss),
            "waves": 2 if boss else 1,
            "monster_tags": ["environment_fit", "faction_fit", "resolve_via_dnd_adapter"],
            "resolution_status": "slot",
        })
    rewards = []
    hidden_cutoff = len(encounters) * (1 - float(reward_profile["hidden_ratio"]))
    for index, encounter in enumerate(encounters):
        risk = DIFFICULTY_BANDS[encounter["difficulty"]]
        tier = min(4, max(0, int(reward_profile["tier"]) + (1 if risk >= 2 else 0)))
        rewards.append({
            "id": f"reward_slot_{index:02d}",
            "anchor_ref": encounter["anchor_ref"],
            "risk_ref": encounter["id"],
            "tier": tier,
            "visibility": "dm_only" if index >= hidden_cutoff else "public",
            "item_tags": ["resolve_via_dnd_adapter", "magic_or_consumable" if tier >= 2 else "coin_or_supply"],
            "resolution_status": "slot",
        })
    objective = next((anchor for anchor in anchors if anchor["role"] in {"objective", "boss"}), anchors[0])
    hooks = [
        {"id": "hook_slot_investigate", "objective": "investigate", "target_ref": objective["id"], "resolution_status": "slot"},
        {"id": "hook_slot_control_or_rescue", "objective": "control_or_rescue", "target_ref": objective["id"], "resolution_status": "slot"},
    ]
    result = {
        "schema_version": CONTENT_SLOTS_SCHEMA,
        "content_slots_version": CONTENT_SLOTS_VERSION,
        "scene": copy.deepcopy(dict(profile.get("scene", {}))),
        "category": category,
        "parameters": copy.deepcopy(dict(dm_profile)),
        "anchors": anchors,
        "content": {"population": population, "encounters": encounters, "rewards": rewards, "hooks": hooks},
        "external_resolution": {"status": "unresolved", "adapter": "future_dnd_content_adapter", "writes_external_project": False},
        "source_profile_sha256": hashlib.sha256(canonical_bytes(dict(profile))).hexdigest(),
        "source_seed": seed,
    }
    validate_content_slots(result)
    return result


def validate_content_slots(slots: Mapping[str, Any]) -> dict[str, Any]:
    if slots.get("schema_version") != CONTENT_SLOTS_SCHEMA:
        _fail("unsupported content slots schema")
    _category(slots)
    validate_dm_profile(dict(slots.get("parameters", {})))
    anchors = {str(item["id"]) for item in slots.get("anchors", [])}
    content = slots.get("content", {})
    for group in ("population", "encounters", "rewards", "hooks"):
        if not isinstance(content.get(group), list) or not content[group]:
            _fail(f"content slot group is empty: {group}")
        for item in content[group]:
            if item.get("resolution_status") != "slot":
                _fail(f"content item was resolved too early: {group}/{item.get('id')}")
            ref = item.get("anchor_ref", item.get("target_ref"))
            if ref and ref not in anchors:
                _fail(f"content item references unknown anchor: {item.get('id')} -> {ref}")
            if any(key in item for key in ("statblock", "monster_id", "item_id", "npc_id")):
                _fail(f"resolved DND entity leaked into slot: {item.get('id')}")
    encounter_ids = {item["id"] for item in content["encounters"]}
    for reward in content["rewards"]:
        if reward.get("risk_ref") not in encounter_ids:
            _fail(f"reward references unknown encounter: {reward.get('id')}")
        if abs(int(reward["tier"]) - int(slots["parameters"]["rewards"]["tier"])) > 1:
            _fail(f"reward tier is not proportional to DM profile: {reward.get('id')}")
    return {"status": "passed", "category": slots["category"], "population_slots": len(content["population"]), "encounter_slots": len(content["encounters"]), "reward_slots": len(content["rewards"]), "hook_slots": len(content["hooks"]), "external_resolution": slots["external_resolution"]}

