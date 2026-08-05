#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "old-clock-v23"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"invalid PNG: {path.name}")
    return struct.unpack(">II", header[16:24])


def glb_json(path: Path) -> tuple[dict[str, Any], int]:
    data = path.read_bytes()
    magic, version, declared = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2 or declared != len(data):
        raise AssertionError("invalid old-clock GLB header")
    length, kind = struct.unpack_from("<II", data, 12)
    if kind != 0x4E4F534A:
        raise AssertionError("old-clock GLB first chunk is not JSON")
    return json.loads(data[20:20 + length].decode("utf-8")), version


def json_list(value: Any) -> list[Any]:
    if not isinstance(value, str):
        raise AssertionError("expected a JSON-encoded GLB extras list")
    result = json.loads(value)
    if not isinstance(result, list):
        raise AssertionError("GLB extras list is malformed")
    return result


def main() -> None:
    plan_path, runtime_path = OUT / "scene.plan.json", OUT / "scene.runtime.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    manifest = json.loads((OUT / "scene-render-manifest.json").read_text(encoding="utf-8"))
    if manifest["scene_id"] != "old_clock_quarter_v23" or manifest["visual_layer_version"] != "2.3":
        raise AssertionError("old-clock render manifest identity/version is stale")
    if manifest["plan_sha256"] != sha256(plan_path) or manifest["runtime_sha256"] != sha256(runtime_path):
        raise AssertionError("old-clock render manifest input hashes are stale")
    if manifest["prototype_objects"] >= 225 or manifest["estimated_draw_calls"] >= 225:
        raise AssertionError("old-clock object/draw-call budget exceeded")
    if manifest["mesh_vertices"] > 180_000:
        raise AssertionError("old-clock vertex budget exceeded")

    images: dict[str, dict[str, Any]] = {}
    for name in ("scene-isometric.png", "scene-topdown.png"):
        path = OUT / name
        if png_size(path) != (1400, 1000):
            raise AssertionError(f"unexpected old-clock render dimensions: {name}")
        images[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    if images["scene-isometric.png"]["sha256"] == images["scene-topdown.png"]["sha256"]:
        raise AssertionError("old-clock camera renders are identical")

    glb_path = OUT / "scene.glb"
    gltf, version = glb_json(glb_path)
    extras = [node.get("extras", {}) for node in gltf.get("nodes", []) if node.get("extras")]
    connector_nodes = [item for item in extras if item.get("prototype_kind") == "connector"]
    if {item.get("connector_id") for item in connector_nodes} != {item["id"] for item in plan["connectors"]}:
        raise AssertionError("old-clock connector pick nodes are incomplete")
    if any(item.get("pick_role") != "connector" or "level_ids" not in item or "volume_ids" not in item for item in connector_nodes):
        raise AssertionError("old-clock connector metadata is incomplete")
    planned = {item["id"]: item for item in plan["connectors"]}
    for item in connector_nodes:
        source = planned[item["connector_id"]]
        if json_list(item["level_ids"]) != sorted({ep["level_id"] for ep in source["endpoints"]}):
            raise AssertionError("old-clock connector level scope is stale")
    visual_roles = {item.get("visual_role") for item in extras if item.get("prototype_kind") == "connector_visual"}
    if not {"door", "stairs", "ladder", "bridge", "hatch", "secret_door"} <= visual_roles:
        raise AssertionError("old-clock visible transition geometry is incomplete")

    rendered_levels = {item.get("level_id") for item in extras if item.get("level_id")}
    if not {item["id"] for item in plan["levels"]} <= rendered_levels:
        raise AssertionError("old-clock GLB omitted one or more runtime levels")
    roof_surfaces = [item for item in extras if item.get("level_id") == "old_clock_roof_route" and item.get("prototype_kind") == "surface"]
    if not roof_surfaces or any(item.get("pick_role") != "tactical_floor" for item in roof_surfaces):
        raise AssertionError("old-clock roof route is decorative instead of tactical")
    if any(item.get("level_id") == "old_clock_roof_route" and item.get("pick_role") == "hideable" for item in extras):
        raise AssertionError("old-clock tactical roof route was emitted as a hideable cosmetic roof")
    if not any(item.get("prototype_visibility") == "dm_only" for item in extras):
        raise AssertionError("old-clock GLB lacks a DM-only visual batch")

    detail_roles = {item.get("detail_role") for item in extras if item.get("prototype_kind") in {"archetype_detail", "life_trace"}}
    if not {"clock_faces", "great_bell", "stepped_gable", "channel_curbs", "roof_route_parapets", "irregular_street_edges"} <= detail_roles:
        raise AssertionError("old-clock hero/life-trace visual groups are incomplete")
    feature_kinds = {item.get("feature_kind") for item in extras if item.get("prototype_kind") == "feature"}
    if not {item["kind"] for item in plan["features"]} <= feature_kinds:
        raise AssertionError("old-clock plan feature was not realized")
    materials = {item.get("name") for item in gltf.get("materials", [])}
    if not {"clock_gold", "clock_face", "market_canvas", "puddle", "secret_floor"} <= materials:
        raise AssertionError("old-clock semantic material palette is incomplete")

    mesh_count = len(gltf.get("meshes", []))
    primitive_count = sum(len(mesh.get("primitives", [])) for mesh in gltf.get("meshes", []))
    if mesh_count >= 225 or primitive_count >= 225:
        raise AssertionError("old-clock GLB mesh/primitive budget exceeded")
    blend_path = OUT / "scene-prototype.blend"
    if blend_path.stat().st_size < 1_000_000 or glb_path.stat().st_size >= 16_000_000:
        raise AssertionError("old-clock BLEND/GLB size budget failed")
    report = {
        "status": "passed", "scene_id": plan["scene"]["id"], "blender_version": manifest["blender_version"],
        "runtime_cells": len(runtime["cells"]), "prototype_objects": manifest["prototype_objects"],
        "mesh_vertices": manifest["mesh_vertices"], "connector_pick_nodes": len(connector_nodes),
        "mesh_count": mesh_count, "draw_calls": primitive_count,
        "images": images, "glb": {"version": version, "bytes": glb_path.stat().st_size, "sha256": sha256(glb_path)},
        "blend_bytes": blend_path.stat().st_size,
    }
    (OUT / "scene-render-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
