#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.compiler import generate  # noqa: E402


def main() -> None:
    spec = ROOT / "specs" / "scenes" / "harbor_vertical_underground.json"
    with tempfile.TemporaryDirectory() as left_dir, tempfile.TemporaryDirectory() as right_dir:
        left = generate(spec, Path(left_dir))
        right = generate(spec, Path(right_dir))
        if left["plan_sha256"] != right["plan_sha256"] or left["runtime_sha256"] != right["runtime_sha256"]:
            raise AssertionError("same spec/seed did not produce byte-identical plan/runtime")
        report = left["validation"]
        if report["non_rectangular_buildings"] < 4 or report["sewer_hatches"] < 2:
            raise AssertionError("pressure-scene geometry contract is incomplete")
        if report["levels"] < 5 or report["connectors"] < 10:
            raise AssertionError("vertical/connector contract is incomplete")
        if report["blocking_features"] < 12 or report["semantic_rooms"] != report["rooms"]:
            raise AssertionError("semantic dressing contract is incomplete")
        plan = json.loads((Path(left_dir) / "scene.plan.json").read_text(encoding="utf-8"))
        runtime = json.loads((Path(left_dir) / "scene.runtime.json").read_text(encoding="utf-8"))

        volumes = {item["id"]: item for item in plan["volumes"]}
        for hero_id in ("signal_tower", "harbor_inn", "undertide_sewer"):
            hero = volumes[hero_id]
            if not all(isinstance(hero.get(key), dict) and hero[key] for key in ("style", "roof", "facade")):
                raise AssertionError(f"hero presentation metadata missing: {hero_id}")

        rooms = {item["id"]: item for item in plan["rooms"]}
        roles_by_level = {
            level_id: {room["role"] for room in rooms.values() if room["level_id"] == level_id}
            for level_id in {room["level_id"] for room in rooms.values()}
        }
        expected_roles = {
            "signal_tower_l1": {"guard_post", "equipment_store"},
            "signal_tower_l2": {"sleeping_quarters", "living_landing"},
            "signal_tower_l3": {"machinery", "signal_room"},
            "signal_tower_l4": {"beacon_chamber", "observation_gallery"},
            "harbor_inn_l1": {"tavern", "kitchen_store"},
            "harbor_inn_l2": {"guest_room", "guest_corridor"},
            "sewer_main": {"sewer_main", "sewage_channel", "secret_cistern"},
        }
        for level_id, expected in expected_roles.items():
            if roles_by_level.get(level_id) != expected:
                raise AssertionError(f"unexpected room program for {level_id}: {roles_by_level.get(level_id)}")
        if any(not room.get("name") or not room.get("tags") for room in rooms.values()):
            raise AssertionError("room name/tags must be populated")

        runtime_rooms = {item["id"]: item for item in runtime.get("rooms", [])}
        if runtime_rooms.keys() != rooms.keys():
            raise AssertionError("runtime room projection is incomplete")
        for room_id, room in rooms.items():
            projected = runtime_rooms[room_id]
            for key in ("name", "role", "level_id", "volume_id", "visibility"):
                if projected[key] != room[key]:
                    raise AssertionError(f"runtime room metadata mismatch: {room_id}/{key}")

        feature_fields = {"volume_id", "room_id", "rotation_deg", "dimensions_ft", "variant", "blocks_movement"}
        if any(not feature_fields <= feature.keys() for feature in plan["features"]):
            raise AssertionError("feature placement metadata is incomplete")
        required_kinds = {
            "guard_desk", "bunk_bed", "signal_winch", "harbor_beacon", "bar_counter", "guest_bed",
            "sewer_pipe", "maintenance_bridge", "fungus_patch", "rat_tracks", "sealed_cache",
        }
        feature_kinds = {feature["kind"] for feature in plan["features"]}
        if not required_kinds <= feature_kinds:
            raise AssertionError(f"hero dressing kinds are missing: {sorted(required_kinds - feature_kinds)}")
        connector_cells = {
            f"{ep['level_id']}:{ep['row']}:{ep['col']}"
            for connector in plan["connectors"] for ep in connector["endpoints"]
        }
        anchor_cells = {f"{item['level_id']}:{item['row']}:{item['col']}" for item in plan["anchors"]}
        runtime_cells = {cell["id"]: cell for cell in runtime["cells"]}
        for feature in (item for item in plan["features"] if item["blocks_movement"]):
            target = f"{feature['level_id']}:{feature['row']}:{feature['col']}"
            if target in connector_cells or target in anchor_cells or runtime_cells[target]["walkable"]:
                raise AssertionError(f"blocking feature violated navigation clearance: {feature['id']}")
    output = ROOT / "output" / "harbor-v2"
    manifest = generate(spec, output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
