#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.v2.quality import (  # noqa: E402
    CERTIFIED_REPORT_SCHEMA,
    COHORT_SCHEMA,
    QUALITY_SCHEMA,
    VISUAL_CERTIFICATE_SCHEMA,
    certify_quality,
    evaluate_cohort,
    evaluate_paths,
    evaluate_scene,
    layout_fingerprint,
    load_policy,
)


def rle(row: int, start: int, length: int) -> dict:
    return {"encoding": "rle-v1", "runs": [[row, start, length]]}


def fixture(seed: int = 101, *, width: int = 8) -> tuple[dict, dict, dict]:
    scene_id = f"quality_fixture_{seed}"
    plan = {
        "schema_version": "dnd-scene-plan-2.0",
        "generator_version": "test",
        "scene": {"id": scene_id, "name": "Generic quality fixture", "seed": seed, "archetype": "test_site"},
        "grid": {"width": width, "height": 4, "cell_size_ft": 5},
        "terrain": [
            {"id": "ground", "kind": "ground", "level_id": "surface", "cell_mask": rle(1, 1, width - 2)},
        ],
        "parcels": [{"id": "parcel", "cell_mask": rle(1, 1, width - 2)}],
        "volumes": [{"id": "site", "kind": "district", "archetype": "mixed_site", "level_ids": ["surface"]}],
        "levels": [{"id": "surface", "volume_id": "site", "z_base_ft": 0, "height_ft": 0, "cell_mask": rle(1, 1, width - 2)}],
        "rooms": [
            {"id": "public_room", "role": "public_hall", "level_id": "surface", "volume_id": "site", "visibility": "public", "cell_mask": rle(1, 1, width - 3)},
            {"id": "secret_room", "role": "secret", "level_id": "surface", "volume_id": "site", "visibility": "dm_only", "cell_mask": rle(1, width - 2, 1)},
        ],
        "connectors": [{
            "id": "hidden_link", "type": "secret_door", "visibility": "dm_only", "bidirectional": True,
            "endpoints": [
                {"level_id": "surface", "row": 1, "col": width - 3, "volume_id": "site", "room_id": "public_room"},
                {"level_id": "surface", "row": 1, "col": width - 2, "volume_id": "site", "room_id": "secret_room"},
            ],
        }],
        "features": [
            {
                "id": f"feature_{index}", "kind": ("cover", "light", "trace")[index % 3],
                "level_id": "surface", "row": 1, "col": 1 + index % max(1, width - 3),
                "room_id": "public_room", "volume_id": "site", "variant": ("used", "worn")[index % 2],
                "tags": ["life_trace"] if index % 2 else ["work"], "blocks_movement": False,
            }
            for index in range(12)
        ],
        "anchors": [
            {"id": "start", "kind": "party_start", "level_id": "surface", "row": 1, "col": 1, "visibility": "public"},
            {"id": "goal", "kind": "objective", "level_id": "surface", "row": 1, "col": width - 3, "visibility": "public"},
            {"id": "hidden", "kind": "secret", "level_id": "surface", "row": 1, "col": width - 2, "visibility": "dm_only"},
        ],
    }
    cells = []
    for col in range(1, width - 1):
        cells.append({
            "id": f"surface:1:{col}", "level_id": "surface", "row": 1, "col": col,
            "walkable": True, "surface": "ground", "z_base_ft": 0,
            "visibility": "dm_only" if col == width - 2 else "public",
        })
    edges = [
        {"a": f"surface:1:{col}", "b": f"surface:1:{col + 1}", "kind": "walk", "cost": 1}
        for col in range(1, width - 3)
    ]
    edges.append({
        "a": f"surface:1:{width - 3}", "b": f"surface:1:{width - 2}",
        "kind": "secret_door", "connector_id": "hidden_link", "visibility": "dm_only", "cost": 1,
    })
    runtime = {
        "schema_version": "dnd-scene-runtime-2.0", "generator_version": "test",
        "scene": {"id": scene_id, "name": "Generic quality fixture", "seed": seed},
        "cells": cells, "nav": {"mode": "explicit", "edges": edges},
        "connectors": [{**plan["connectors"][0], "cell_ids": [f"surface:1:{width - 3}", f"surface:1:{width - 2}"]}],
        "features": plan["features"], "anchors": plan["anchors"], "rooms": plan["rooms"], "volumes": plan["volumes"],
    }
    render = {
        "schema_version": "dnd-scene-render-manifest-2.0", "scene_id": scene_id,
        "levels": 1, "rooms": 2, "connectors": 1, "features": 12,
        "estimated_draw_calls": 24, "mesh_vertices": 1200, "glb_bytes": 50000, "build_seconds": 2.0,
        "outputs": ["scene.glb", "scene-isometric.png"],
    }
    return plan, runtime, render


def main() -> None:
    policy = load_policy(ROOT / "specs" / "quality" / "v2.4-policy.json")
    plan, runtime, render = fixture()
    report = evaluate_scene(plan, runtime, render, policy=policy)
    if report["schema_version"] != QUALITY_SCHEMA or not report["hard_gates"]["passed"]:
        raise AssertionError("valid generic fixture failed V2.4 hard gates")
    if set(report["dimensions"]) != set(policy["weights"]) or sum(item["weight"] for item in report["dimensions"].values()) != 100:
        raise AssertionError("soft quality dimensions do not form a 100-point contract")
    if not report["layout"]["fingerprint"] or not report["layout"]["tokens"]:
        raise AssertionError("layout fingerprint contract is incomplete")

    # IDs, names and seed are intentionally excluded from semantic layout
    # identity; geometry changes must still change it.
    renamed_plan, renamed_runtime = copy.deepcopy(plan), copy.deepcopy(runtime)
    renamed_plan["scene"].update({"id": "renamed", "name": "Renamed", "seed": 999})
    renamed_runtime["scene"].update({"id": "renamed", "name": "Renamed", "seed": 999})
    if layout_fingerprint(plan, runtime)[0] != layout_fingerprint(renamed_plan, renamed_runtime)[0]:
        raise AssertionError("layout fingerprint was contaminated by identity/provenance")
    changed_plan, changed_runtime, _ = fixture(102, width=9)
    if layout_fingerprint(plan, runtime)[0] == layout_fingerprint(changed_plan, changed_runtime)[0]:
        raise AssertionError("layout fingerprint ignored a real spatial change")

    leaked = copy.deepcopy(runtime)
    leaked["nav"]["edges"][-1].pop("visibility")
    rejected = evaluate_scene(plan, leaked, render, policy=policy)
    if rejected["status"] != "rejected_hard_gate" or rejected["soft_score"] is not None:
        raise AssertionError("permission hard failure was incorrectly compensated by a soft score")
    if "permissions.no_dm_cell_publicly_reachable" not in rejected["hard_gates"]["failure_ids"]:
        raise AssertionError("secret visibility leak was not identified")

    # A baseline records evidence without enforcing diversity.  An enforcing
    # round must reject eight seeds that all share one semantic layout.
    repeated = []
    for seed in range(8):
        sample_plan, sample_runtime = copy.deepcopy(plan), copy.deepcopy(runtime)
        sample_plan["scene"]["seed"] = seed
        sample_runtime["scene"]["seed"] = seed
        repeated.append(evaluate_scene(sample_plan, sample_runtime, render, policy=policy))
    baseline = evaluate_cohort(repeated, policy=policy, round_name="baseline")
    if baseline["schema_version"] != COHORT_SCHEMA or baseline["status"] != "baseline_recorded":
        raise AssertionError("baseline cohort report did not record successfully")
    round_report = evaluate_cohort(repeated, policy=policy, round_name="round1")
    if round_report["status"] != "rejected" or round_report["metrics"]["unique_layout_rate"] != 0.125:
        raise AssertionError("cross-seed clone cohort escaped the diversity gate")
    if "unique_layout_rate" not in round_report["failure_ids"] or "clone_rate" not in round_report["failure_ids"]:
        raise AssertionError("cohort diversity failure evidence is incomplete")

    # Exercise the file/receipt path, including GLB primitive/accessor metrics.
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        plan_path, runtime_path = directory / "scene.plan.json", directory / "scene.runtime.json"
        plan_path.write_text(json.dumps(plan, separators=(",", ":")), encoding="utf-8")
        runtime_path.write_text(json.dumps(runtime, separators=(",", ":")), encoding="utf-8")
        document = {"asset": {"version": "2.0"}, "accessors": [{"count": 3}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]}
        json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
        json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
        glb = struct.pack("<4sII", b"glTF", 2, 20 + len(json_chunk)) + struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
        (directory / "scene.glb").write_bytes(glb)
        (directory / "scene-isometric.png").write_bytes(b"test-image-receipt")
        file_manifest = {
            **render,
            "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "runtime_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
        }
        manifest_path = directory / "scene-render-manifest.json"
        manifest_path.write_text(json.dumps(file_manifest), encoding="utf-8")
        path_report = evaluate_paths(plan_path, runtime_path, manifest_path, policy=policy)
        if not path_report["hard_gates"]["passed"] or path_report["inputs"]["glb"]["sha256"] != hashlib.sha256(glb).hexdigest():
            raise AssertionError("file-based V2 plan/runtime/render evaluation failed")
        performance = path_report["dimensions"]["performance"]["raw"]
        if performance["draw_calls"] != 1 or performance["vertices"] != 3:
            raise AssertionError("quality evaluator trusted estimates instead of actual GLB metrics")

        image_path = directory / "scene-isometric.png"
        certificate = {
            "schema_version": VISUAL_CERTIFICATE_SCHEMA,
            "scene_id": path_report["scene"]["id"],
            "programmatic_report_sha256": path_report["report_sha256"],
            "images": [{"path": image_path.name, "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest()}],
            "ratings": {
                "silhouette_naturalness": 5,
                "landmark_hierarchy": 5,
                "route_level_readability": 5,
                "lived_in_plausibility": 5,
                "tactical_clarity": 5,
            },
            "critical_defects": [],
        }
        source_before = json.dumps(path_report, sort_keys=True)
        certified = certify_quality(path_report, certificate, certificate_directory=directory)
        expected_final = round(float(path_report["soft_score"]) * 0.70 + 100 * 0.30, 2)
        if certified["schema_version"] != CERTIFIED_REPORT_SCHEMA or certified["status"] != "certified":
            raise AssertionError("valid visual certificate did not complete certification")
        if certified["final_score"] != expected_final or certified["programmatic"]["score"] != path_report["soft_score"] or certified["visual"]["score"] != 100:
            raise AssertionError("certified report did not preserve and combine the two scores at 70/30")
        if certified["semantic_scene_hash_modified"] or json.dumps(path_report, sort_keys=True) != source_before:
            raise AssertionError("visual certification mutated semantic/programmatic input")

        defect_certificate = copy.deepcopy(certificate)
        defect_certificate["critical_defects"] = ["major route is hidden by foreground geometry"]
        defect_report = certify_quality(path_report, defect_certificate, certificate_directory=directory)
        if defect_report["status"] != "visual_rejected" or "critical_defects_present" not in defect_report["rejection_reasons"]:
            raise AssertionError("critical visual defect did not block certification")

        low_item_certificate = copy.deepcopy(certificate)
        low_item_certificate["ratings"]["tactical_clarity"] = 2.5
        low_item_report = certify_quality(path_report, low_item_certificate, certificate_directory=directory)
        if low_item_report["status"] != "visual_rejected" or "visual_item_below_threshold" not in low_item_report["rejection_reasons"]:
            raise AssertionError("a visual item below 3 incorrectly passed certification")

        low_mean_certificate = copy.deepcopy(certificate)
        low_mean_certificate["ratings"] = {key: 3 for key in low_mean_certificate["ratings"]}
        low_mean_report = certify_quality(path_report, low_mean_certificate, certificate_directory=directory)
        if low_mean_report["status"] != "visual_rejected" or "visual_mean_below_threshold" not in low_mean_report["rejection_reasons"]:
            raise AssertionError("visual mean below 3.5 incorrectly passed certification")

        hard_failure_certificate = copy.deepcopy(certificate)
        hard_failure_certificate["scene_id"] = rejected["scene"]["id"]
        hard_failure_certificate["programmatic_report_sha256"] = rejected["report_sha256"]
        hard_failure_report = certify_quality(rejected, hard_failure_certificate, certificate_directory=directory)
        if hard_failure_report["status"] != "visual_rejected" or "programmatic_hard_gates_failed" not in hard_failure_report["rejection_reasons"]:
            raise AssertionError("visual scores certified a programmatic hard-gate failure")

        stale_certificate = copy.deepcopy(certificate)
        stale_certificate["images"][0]["sha256"] = "0" * 64
        try:
            certify_quality(path_report, stale_certificate, certificate_directory=directory)
        except ValueError as error:
            if "image hash is stale" not in str(error):
                raise
        else:
            raise AssertionError("stale visual image hash was accepted")

        malformed_certificate = copy.deepcopy(certificate)
        malformed_certificate["ratings"].pop("landmark_hierarchy")
        try:
            certify_quality(path_report, malformed_certificate, certificate_directory=directory)
        except ValueError as error:
            if "exactly the five" not in str(error):
                raise
        else:
            raise AssertionError("incomplete five-item visual rubric was accepted")

        wrong_schema_certificate = copy.deepcopy(certificate)
        wrong_schema_certificate["schema_version"] = "unsupported"
        try:
            certify_quality(path_report, wrong_schema_certificate, certificate_directory=directory)
        except ValueError as error:
            if "certificate schema" not in str(error):
                raise
        else:
            raise AssertionError("unsupported visual certificate schema was accepted")

        quality_path, certificate_path, certified_path = (
            directory / "quality.report.json", directory / "quality.visual-certificate.json", directory / "quality.certified.json"
        )
        quality_path.write_text(json.dumps(path_report), encoding="utf-8")
        certificate_path.write_text(json.dumps(certificate), encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable, "-m", "generator.v2.quality_cli", "certify",
                "--quality-report", str(quality_path), "--visual-certificate", str(certificate_path),
                "--out", str(certified_path),
            ],
            cwd=ROOT, check=False, capture_output=True, text=True,
        )
        cli_report = json.loads(certified_path.read_text(encoding="utf-8")) if certified_path.is_file() else {}
        if completed.returncode or cli_report.get("status") != "certified":
            raise AssertionError(f"quality_cli certify failed: {completed.stderr}")

    print(json.dumps({
        "status": "passed", "scene_score": report["soft_score"],
        "hard_gate_count": len(report["hard_gates"]["checks"]),
        "layout_fingerprint": report["layout"]["fingerprint"],
        "clone_round_failures": round_report["failure_ids"], "certified_final_score": certified["final_score"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
