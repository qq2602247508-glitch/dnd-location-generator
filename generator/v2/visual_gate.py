"""Profile-level visual gate with separate structure and visual evidence.

This is a cheap pre-Blender gate, not a claim of human visual approval.  It
checks that a profile contains enough signals for four camera views, scores
independent dimensions, and can compare multiple seeds for meaningful
variation.  Rendered screenshots can later replace the proxy observations
without changing the certificate shape.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Iterable, Mapping

from .scene_contract import canonical_bytes
from .visual_packs import validate_visual_plan


VISUAL_CERTIFICATE_SCHEMA = "dnd-visual-certificate-1.0"
VISUAL_GATE_VERSION = "3.0.0-prototype.1"
DIMENSIONS = ("composition", "silhouette", "material_coherence", "vertical_readability", "tactical_legibility")


def _fail(message: str) -> None:
    raise ValueError(message)


def _clamp(value: float) -> float:
    return max(1.0, min(5.0, round(float(value), 2)))


def _category(profile: Mapping[str, Any]) -> str:
    category = str(profile.get("category", ""))
    if category not in {"district", "building", "outdoor"}:
        _fail("visual gate requires a district, building or outdoor profile")
    return category


def _score(profile: Mapping[str, Any], visual_plan: Mapping[str, Any]) -> dict[str, float]:
    category = _category(profile)
    validate_visual_plan(visual_plan)
    packs = len(visual_plan.get("packs", []))
    materials = len(visual_plan.get("materials", []))
    if category == "district":
        buildings = profile.get("buildings", [])
        roads = profile.get("roads", [])
        landmarks = profile.get("landmarks", [])
        orientations = len({int(item.get("orientation_deg", 0)) % 360 for item in buildings})
        composition = 2.5 + min(1.5, len(roads) / 5) + min(1.0, len(buildings) / 12)
        silhouette = 2.2 + min(1.6, len(landmarks) / 2) + (0.7 if any(item.get("height_band") == "high" for item in landmarks) else 0)
        vertical = 2.2 + min(1.1, orientations / 4) + (0.9 if "high_landmark" in profile.get("skyline", {}).get("tiers", []) else 0)
        tactical = 2.0 + min(1.3, len(profile.get("entries", [])) / 2) + (0.8 if any(route.get("role") == "service" for route in roads) else 0)
    elif category == "building":
        rooms = len(profile.get("room_grammar", []))
        floor_policy = profile.get("floor_policy", {})
        max_floors = int(floor_policy.get("maximum", floor_policy.get("value", 1)))
        composition = 2.7 + min(1.4, rooms / 8)
        silhouette = 2.4 + min(1.5, max_floors / 4)
        vertical = 2.0 + min(2.0, max_floors / 3) + (0.5 if profile.get("vertical_grammar") else 0)
        tactical = 2.2 + min(1.3, rooms / 8) + (0.7 if "vertical_connections" in profile.get("packs", []) else 0)
    else:
        terrain = profile.get("terrain", {})
        bands = len(terrain.get("elevation_bands", []))
        routes = profile.get("routes", [])
        platforms = len(profile.get("tactical_platforms", []))
        composition = 2.5 + min(1.5, bands / 5) + min(0.8, len(routes) / 8)
        silhouette = 2.5 + min(1.8, bands / 5) + (0.5 if terrain.get("cliffs") else 0)
        vertical = 2.3 + min(2.2, (int(terrain.get("elevation_range_ft", [0, 0])[1]) / 60))
        tactical = 2.0 + min(1.8, platforms / 3) + (0.7 if any(route.get("role") == "alternate" for route in routes) else 0)
    material_coherence = 2.3 + min(1.5, materials / 16) + min(0.8, packs / 8)
    return {dimension: _clamp(value) for dimension, value in {
        "composition": composition,
        "silhouette": silhouette,
        "material_coherence": material_coherence,
        "vertical_readability": vertical,
        "tactical_legibility": tactical,
    }.items()}


def certify_visual_plan(profile: Mapping[str, Any], visual_plan: Mapping[str, Any], *, minimum_score: float | None = None) -> dict[str, Any]:
    scores = _score(profile, visual_plan)
    threshold = float(minimum_score if minimum_score is not None else visual_plan.get("evidence", {}).get("minimum_score", 3.0))
    if threshold < 1 or threshold > 5:
        _fail("visual gate threshold must be between 1 and 5")
    overall = round(sum(scores.values()) / len(scores), 2)
    return {
        "schema_version": VISUAL_CERTIFICATE_SCHEMA,
        "gate_version": VISUAL_GATE_VERSION,
        "scene": dict(profile.get("scene", {})),
        "category": _category(profile),
        "status": "passed" if min(scores.values()) >= threshold else "needs_review",
        "threshold": threshold,
        "scores": scores,
        "overall_score": overall,
        "evidence": {"views": ["far", "mid", "near", "tactical"], "source": "profile_proxy_before_render"},
        "profile_sha256": hashlib.sha256(canonical_bytes(dict(profile))).hexdigest(),
    }


def compare_seed_variants(certificates: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(certificates)
    if len(items) < 2:
        _fail("seed variation check requires at least two certificates")
    signatures = []
    for certificate in items:
        signature = hashlib.sha256(canonical_bytes({"category": certificate.get("category"), "scores": certificate.get("scores"), "scene": certificate.get("scene")})).hexdigest()
        signatures.append(signature)
    unique = len(set(signatures))
    score_values = [float(item.get("overall_score", 0)) for item in items]
    return {"status": "passed" if unique >= 2 else "needs_review", "samples": len(items), "unique_signatures": unique, "score_range": round(max(score_values) - min(score_values), 2)}


def validate_certificate(certificate: Mapping[str, Any]) -> dict[str, Any]:
    if certificate.get("schema_version") != VISUAL_CERTIFICATE_SCHEMA:
        _fail("unsupported visual certificate schema")
    if set(certificate.get("scores", {})) != set(DIMENSIONS):
        _fail("visual certificate must contain exactly five score dimensions")
    for dimension in DIMENSIONS:
        score = float(certificate["scores"][dimension])
        if score < 1 or score > 5:
            _fail(f"visual score out of range: {dimension}")
    if certificate.get("status") not in {"passed", "needs_review"}:
        _fail("visual certificate status is invalid")
    return {"status": "passed", "category": certificate.get("category"), "overall_score": certificate.get("overall_score"), "threshold": certificate.get("threshold"), "score_dimensions": len(certificate["scores"])}

