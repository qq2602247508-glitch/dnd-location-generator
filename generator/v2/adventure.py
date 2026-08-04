from __future__ import annotations

import hashlib
import json
from typing import Any

from .program import canonical_bytes


ADVENTURE_SCHEMA = "dnd-adventure-director-plan-1.0"
ADVENTURE_VERSION = "2.2.0-prototype.1"
DIFFICULTY_BANDS = {"easy": 0, "medium": 1, "hard": 2, "deadly": 3}


def validate_dm_profile(profile: dict[str, Any]) -> None:
    party = profile.get("party", {})
    encounters = profile.get("encounters", {})
    rewards = profile.get("rewards", {})
    if not 1 <= int(party.get("level", 0)) <= 20 or not 1 <= int(party.get("size", 0)) <= 12:
        raise ValueError("party level/size is invalid")
    if encounters.get("difficulty") not in DIFFICULTY_BANDS:
        raise ValueError("unsupported encounter difficulty")
    for key in ("density", "boss_ratio"):
        if not 0 <= float(encounters.get(key, -1)) <= 1:
            raise ValueError(f"encounter {key} must be between 0 and 1")
    if not 0 <= int(rewards.get("tier", -1)) <= 4:
        raise ValueError("reward tier must be 0..4")
    if not 0 <= float(rewards.get("hidden_ratio", -1)) <= 1:
        raise ValueError("hidden reward ratio must be between 0 and 1")


def _phase_beats(program: dict[str, Any]) -> list[dict[str, Any]]:
    source = program["adventure_beats"]
    entry = next(item for item in source if item["role"] == "arrival")
    choice = next(item for item in source if item["role"] == "route_choice")
    climax = next(item for item in source if item["role"] == "climax")
    discovery = next((item for item in source if item["role"] in {"discovery", "revelation", "state_change"}), choice)
    return [
        {"id": "beat_entry", "phase": "entry", "location_refs": [entry["node_id"]], "truth_status": "established"},
        {"id": "beat_exploration", "phase": "exploration", "location_refs": [choice["node_id"]], "truth_status": "dm_suggestion"},
        {"id": "beat_warning", "phase": "warning", "location_refs": [choice["node_id"]], "truth_status": "dm_suggestion"},
        {"id": "beat_escalation", "phase": "escalation", "location_refs": [discovery["node_id"]], "truth_status": "dm_suggestion"},
        {"id": "beat_climax", "phase": "climax", "location_refs": [climax["node_id"]], "truth_status": "established"},
        {"id": "beat_escape", "phase": "escape", "location_refs": [entry["node_id"]], "truth_status": "intentional_blank"},
    ]


def _route_options(program: dict[str, Any]) -> list[dict[str, Any]]:
    routes = program["routes"]
    primary = next(item for item in routes if item["role"] == "primary")
    alternatives = [item for item in routes if item["role"] in {"alternate", "loop", "service_loop", "vertical", "stateful_shortcut", "secret"}]
    result = [{
        "id": "route_option_primary", "route_refs": [primary["id"]], "tradeoff": "最清晰稳定，但更容易被守卫或敌人观察。",
        "converges_at_ref": primary["to"], "truth_status": "established",
    }]
    for index, route in enumerate(alternatives[:3], 1):
        result.append({
            "id": f"route_option_{index}", "route_refs": [route["id"]],
            "tradeoff": {"medium": "绕行并换取更好的位置。", "high": "更快或更隐蔽，但伴随环境危险。"}.get(route["risk"], "更安全但耗时。"),
            "converges_at_ref": route["to"],
            "truth_status": "dm_suggestion" if route["visibility"] == "public" else "intentional_blank",
        })
    return result


def _interactions(program: dict[str, Any]) -> list[dict[str, Any]]:
    verb_map = {
        "state_change": ["activate", "disable", "reverse"], "destructible": ["collapse", "reinforce", "climb"],
        "cover_field": ["move", "ignite", "hide"], "fall_hazard": ["shove", "secure", "jump"],
        "moving_hazard": ["wade", "redirect", "dam"], "verticality": ["climb", "jump", "fly"],
    }
    result = []
    for item in program["tactical_directives"]:
        result.append({
            "id": f"interaction_{item['id']}", "target_ref": item["zones"][0],
            "verbs": verb_map.get(item["role"], ["inspect", "use", "improvise"]),
            "effects": [item["role"], "route_or_encounter_change"], "truth_status": "dm_suggestion",
        })
    return result


def _population(program: dict[str, Any]) -> list[dict[str, Any]]:
    roles = {
        "authority": "guard_or_official", "labor": "worker_or_foreman", "covert": "informant_or_smuggler",
        "guardian": "ranger_or_guide", "predator": "territorial_creature", "former_operator": "engineer_or_survivor",
        "occupier": "cultist_or_commander", "wildlife": "vermin_sign", "explorer": "scavenger_or_sage",
    }
    return [{
        "id": f"population_{faction['id']}", "location_ref": faction["home_zone"],
        "identity_role": roles.get(faction["role"], "local_contact"), "faction_role": faction["role"],
        "activity": "patrol" if faction["role"] in {"authority", "guardian", "predator", "occupier"} else "work_or_negotiate",
        "clue_refs": [], "tags": [faction["id"], "unresolved"], "resolution_status": "slot",
    } for faction in program["factions"]]


def _encounters(program: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = program["nodes"]
    difficulty = profile["encounters"]["difficulty"]
    level = int(profile["party"]["level"])
    count = max(2, min(7, round(2 + float(profile["encounters"]["density"]) * 5)))
    candidates = [item for item in nodes if item["role"] not in {"entry", "exit", "secret"}]
    result = []
    for index in range(count):
        node = candidates[index % len(candidates)]
        is_boss = node["role"] == "boss" or (index == count - 1 and float(profile["encounters"]["boss_ratio"]) > 0)
        band = "deadly" if is_boss and difficulty in {"hard", "deadly"} else difficulty
        cr_center = max(1, round(level * int(profile["party"]["size"]) / 4))
        result.append({
            "id": f"encounter_{index:02d}_{node['id']}", "location_refs": [node["id"]],
            "role": "boss" if is_boss else ("patrol" if index % 2 else "set_piece"), "difficulty": band,
            "cr_range": [max(1, cr_center - 2), cr_center + (3 if is_boss else 1)],
            "waves": 2 if is_boss else 1, "reinforcement_refs": [],
            "creature_traits": ["environment_fit", "faction_fit"], "resolution_status": "slot",
        })
    return result


def _rewards(program: dict[str, Any], profile: dict[str, Any], encounters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tier = int(profile["rewards"]["tier"])
    hidden_ratio = float(profile["rewards"]["hidden_ratio"])
    result = []
    for index, encounter in enumerate(encounters):
        risk = DIFFICULTY_BANDS[encounter["difficulty"]]
        reward_tier = min(4, max(0, tier + (1 if risk >= 2 else 0)))
        hidden = hidden_ratio > 0 and index >= len(encounters) * (1 - hidden_ratio)
        result.append({
            "id": f"reward_{index:02d}", "location_ref": encounter["location_refs"][0], "tier": reward_tier,
            "risk_ref": encounter["id"], "visibility": "dm_only" if hidden else "public",
            "kind_tags": ["magic_or_consumable" if reward_tier >= 2 else "coin_or_supply", "unresolved"],
            "resolution_status": "slot",
        })
    return result


def _hooks(program: dict[str, Any], population: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entry = next(item for item in program["nodes"] if item["role"] == "entry")
    target = next(item for item in program["nodes"] if item["role"] in {"objective", "boss"})
    contact = population[0]["id"] if population else ""
    return [
        {"id": "hook_investigate", "objective_type": "investigate", "entry_ref": entry["id"], "target_ref": target["id"], "complication_refs": [], "clue_refs": [contact], "resolution_status": "slot"},
        {"id": "hook_control_or_rescue", "objective_type": "control_or_rescue", "entry_ref": entry["id"], "target_ref": target["id"], "complication_refs": ["beat_escalation"], "clue_refs": [], "resolution_status": "slot"},
    ]


def direct_adventure(program: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    validate_dm_profile(profile)
    population = _population(program)
    encounters = _encounters(program, profile)
    rewards = _rewards(program, profile, encounters)
    plan = {
        "schema_version": ADVENTURE_SCHEMA, "director_version": ADVENTURE_VERSION,
        "scene_id": program["scene"]["id"], "program_sha256": program["program_sha256"],
        "parameters": profile, "beats": _phase_beats(program), "route_options": _route_options(program),
        "interactions": _interactions(program),
        "content": {"population": population, "encounters": encounters, "rewards": rewards, "hooks": _hooks(program, population)},
    }
    plan["adventure_sha256"] = hashlib.sha256(canonical_bytes(plan)).hexdigest()
    return plan


def validate_adventure(program: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("schema_version") != ADVENTURE_SCHEMA or plan.get("program_sha256") != program.get("program_sha256"):
        raise AssertionError("adventure plan/program contract mismatch")
    phases = [item["phase"] for item in plan["beats"]]
    if phases != ["entry", "exploration", "warning", "escalation", "climax", "escape"]:
        raise AssertionError("adventure pacing phases are incomplete or unordered")
    node_ids = {item["id"] for item in program["nodes"]}
    zone_ids = {item["id"] for item in program["zones"]}
    route_ids = {item["id"] for item in program["routes"]}
    for option in plan["route_options"]:
        if not set(option["route_refs"]) <= route_ids or option["converges_at_ref"] not in node_ids:
            raise AssertionError("route option references invalid planning entities")
    content = plan["content"]
    if not content["population"] or len(content["encounters"]) < 2 or len(content["rewards"]) != len(content["encounters"]):
        raise AssertionError("adventure content slot counts are invalid")
    for slot in content["population"]:
        if slot["location_ref"] not in zone_ids or slot["resolution_status"] != "slot":
            raise AssertionError("population slot is invalid or prematurely resolved")
    encounters = {item["id"]: item for item in content["encounters"]}
    for reward in content["rewards"]:
        encounter = encounters.get(reward["risk_ref"])
        if not encounter or reward["location_ref"] not in node_ids:
            raise AssertionError("reward does not reference a valid risk/location")
        if abs(reward["tier"] - int(plan["parameters"]["rewards"]["tier"])) > 1:
            raise AssertionError("reward tier is not proportional to the DM profile")
    if any("statblock" in slot or "monster_id" in slot for slot in content["encounters"]):
        raise AssertionError("prototype content slots must not resolve D&D entities")
    return {
        "status": "passed", "scene_id": plan["scene_id"], "beats": len(plan["beats"]),
        "route_options": len(plan["route_options"]), "interactions": len(plan["interactions"]),
        "population_slots": len(content["population"]), "encounter_slots": len(content["encounters"]),
        "reward_slots": len(content["rewards"]), "hook_slots": len(content["hooks"]),
        "adventure_sha256": plan["adventure_sha256"],
    }
