#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "harbor-v2"


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
        raise AssertionError("invalid GLB header")
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != 0x4E4F534A:
        raise AssertionError("GLB first chunk is not JSON")
    return json.loads(data[20 : 20 + chunk_length].decode("utf-8")), version


def json_list(value: Any) -> list[Any]:
    if not isinstance(value, str):
        raise AssertionError("expected a JSON-encoded list in GLB extras")
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise AssertionError("GLB extras value is not a list")
    return parsed


def main() -> None:
    plan_path, runtime_path = OUT / "scene.plan.json", OUT / "scene.runtime.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    manifest = json.loads((OUT / "scene-render-manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "generated" or manifest["plan_sha256"] != sha256(plan_path) or manifest["runtime_sha256"] != sha256(runtime_path):
        raise AssertionError("render manifest input hashes are stale")
    if manifest["levels"] != len(plan["levels"]) or manifest["connectors"] != len(plan["connectors"]):
        raise AssertionError("render manifest counts do not match plan")
    if manifest["prototype_objects"] >= len(runtime["cells"]) // 4:
        raise AssertionError("scene was not batched; object count is too close to cell count")
    if manifest["prototype_objects"] >= 250 or manifest.get("estimated_draw_calls", 9999) >= 250:
        raise AssertionError("V2.1 visual layer exceeded the 250 object/draw-call budget")

    images: dict[str, dict[str, Any]] = {}
    for name in ("scene-isometric.png", "scene-topdown.png"):
        path = OUT / name
        if png_size(path) != (1400, 1000):
            raise AssertionError(f"unexpected PNG dimensions: {name}")
        images[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    if images["scene-isometric.png"]["sha256"] == images["scene-topdown.png"]["sha256"]:
        raise AssertionError("camera renders are identical")

    glb_path = OUT / "scene.glb"
    gltf, glb_version = glb_json(glb_path)
    material_colors = {
        item["name"]: item.get("pbrMetallicRoughness", {}).get("baseColorFactor")
        for item in gltf.get("materials", [])
    }
    required_materials = {
        "ground", "road", "water", "interior", "roof", "connector_vertical", "door_frame", "stair_wood",
        "hatch_metal", "secret_portal", "window_glow", "beacon", "dock_wood", "sewer_bridge",
    }
    if not required_materials <= material_colors.keys():
        raise AssertionError("required visual materials are missing")
    distinct_colors = {tuple(round(float(channel), 4) for channel in color[:3]) for color in material_colors.values() if color}
    if len(distinct_colors) < 8:
        raise AssertionError("materials collapsed to too few colors (likely default Principled gray)")
    water = material_colors["water"]
    road = material_colors["road"]
    roof = material_colors["roof"]
    if not (water[2] > water[0] * 2 and roof[0] > roof[2] * 2 and max(road[:3]) < max(water[:3])):
        raise AssertionError("water/road/roof color roles are not visually distinct")
    extras = [node.get("extras", {}) for node in gltf.get("nodes", []) if node.get("extras")]
    connector_nodes = [item for item in extras if item.get("prototype_kind") == "connector"]
    connector_ids = {item.get("connector_id") for item in connector_nodes}
    if connector_ids != {item["id"] for item in plan["connectors"]}:
        raise AssertionError("connector pick nodes do not map one-to-one to plan connectors")
    required_connector_extras = {"connector_id", "connector_type", "pick_role", "level_ids", "endpoints"}
    if any(not required_connector_extras <= item.keys() or item.get("pick_role") != "connector" for item in connector_nodes):
        raise AssertionError("connector extras are incomplete")
    connector_visuals = [item for item in extras if item.get("prototype_kind") == "connector_visual"]
    planned_connector_types = {item["type"] for item in plan["connectors"]}
    if not planned_connector_types <= {item.get("visual_role") for item in connector_visuals}:
        raise AssertionError("door/stair/hatch/secret-door visible geometry is incomplete")
    if any(item.get("pick_role") != "none" for item in connector_visuals):
        raise AssertionError("connector visuals must stay separate from connector pick meshes")
    if any("volume_ids" not in item for item in connector_nodes + connector_visuals):
        raise AssertionError("connector meshes must identify every participating volume")
    connectors_by_id = {item["id"]: item for item in plan["connectors"]}
    for item in connector_nodes:
        connector = connectors_by_id[item["connector_id"]]
        expected_levels = sorted({endpoint["level_id"] for endpoint in connector["endpoints"]})
        expected_volumes = sorted({endpoint.get("volume_id", "") for endpoint in connector["endpoints"]})
        if json_list(item["level_ids"]) != expected_levels or json_list(item["volume_ids"]) != expected_volumes:
            raise AssertionError("connector pick scope metadata does not match its endpoints")
    for item in connector_visuals:
        connector_ids_in_batch = json_list(item["connector_ids"])
        expected_signatures = {
            (
                tuple(sorted({endpoint["level_id"] for endpoint in connectors_by_id[connector_id]["endpoints"]})),
                tuple(sorted({endpoint.get("volume_id", "") for endpoint in connectors_by_id[connector_id]["endpoints"]})),
            )
            for connector_id in connector_ids_in_batch
        }
        if len(expected_signatures) != 1:
            raise AssertionError("connector visual batch mixes incompatible level/volume scopes")
        expected_levels, expected_volumes = next(iter(expected_signatures))
        if json_list(item["level_ids"]) != list(expected_levels) or json_list(item["volume_ids"]) != list(expected_volumes):
            raise AssertionError("connector visual scope metadata does not match its connectors")
        if "surface" in expected_levels and any(
            "surface" not in {endpoint["level_id"] for endpoint in connectors_by_id[connector_id]["endpoints"]}
            for connector_id in connector_ids_in_batch
        ):
            raise AssertionError("surface connector visual batch leaked a purely interior connector")
    rendered_levels = {item.get("level_id") for item in extras if item.get("level_id")}
    if not {item["id"] for item in plan["levels"]} <= rendered_levels:
        raise AssertionError("some string level IDs were not emitted into GLB extras")
    surface_kinds = {item.get("surface_kind") for item in extras if item.get("prototype_kind") == "surface"}
    if not {"ground", "road", "water", "sewage"} <= surface_kinds:
        raise AssertionError("surface material classes are incomplete")
    if not any(item.get("prototype_kind") == "roof" and item.get("pick_role") == "hideable" for item in extras):
        raise AssertionError("hideable roof metadata is missing")
    detail_groups = {
        item.get("detail_group") for item in extras
        if item.get("prototype_kind") in {"archetype_detail", "harbor_detail"}
    }
    if not {"signal_tower", "harbor_inn", "sewer", "harbor"} <= detail_groups:
        raise AssertionError("V2.1 tower/inn/sewer/harbor visual groups are incomplete")
    rendered_feature_kinds = {item.get("feature_kind") for item in extras if item.get("prototype_kind") == "feature"}
    if not {item["kind"] for item in plan["features"]} <= rendered_feature_kinds:
        raise AssertionError("one or more plan feature kinds were not interpreted")
    feature_nodes = [item for item in extras if item.get("prototype_kind") == "feature"]
    interior_feature_nodes = [item for item in feature_nodes if item.get("level_id") != "surface"]
    if any(not item.get("volume_id") or "room_ids" not in item for item in interior_feature_nodes):
        raise AssertionError("interior feature batches must retain volume and room ownership")
    features_by_id = {item["id"]: item for item in plan["features"]}
    for item in feature_nodes:
        features = [features_by_id[feature_id] for feature_id in json_list(item["feature_ids"])]
        if {feature.get("volume_id", "") for feature in features} != {item.get("volume_id", "")}:
            raise AssertionError("feature batch mixes multiple volume owners")
    mesh_count = len(gltf.get("meshes", []))
    primitive_count = sum(len(mesh.get("primitives", [])) for mesh in gltf.get("meshes", []))
    if mesh_count >= 250 or primitive_count >= 250:
        raise AssertionError("GLB draw-call/mesh budget exceeded")

    blend = OUT / "scene-prototype.blend"
    if blend.stat().st_size < 1_000_000:
        raise AssertionError("BLEND output is unexpectedly small")
    if glb_path.stat().st_size >= 25_000_000:
        raise AssertionError("GLB exceeds the 25 MB V2.1 budget")
    report = {
        "status": "passed", "scene_id": plan["scene"]["id"], "blender_version": manifest["blender_version"],
        "levels": manifest["levels"], "runtime_cells": len(runtime["cells"]), "prototype_objects": manifest["prototype_objects"],
        "batched_boxes": manifest["batched_boxes"], "mesh_vertices": manifest["mesh_vertices"], "connector_pick_nodes": len(connector_nodes),
        "distinct_material_colors": len(distinct_colors),
        "connector_visual_batches": len(connector_visuals), "mesh_count": mesh_count, "estimated_draw_calls": primitive_count,
        "images": images, "glb": {"version": glb_version, "bytes": glb_path.stat().st_size, "sha256": sha256(glb_path)},
        "blend_bytes": blend.stat().st_size,
    }
    (OUT / "scene-render-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
