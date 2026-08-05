#!/usr/bin/env python3
"""Objective smoke gate for rendered profile scenes.

This is intentionally a regression floor, not a golden-image test.  It uses
coverage, edge density and material-bucket diversity from the existing PNG
analyser so a new seed or renderer can vary while still rejecting empty,
black, or dramatically less legible buildings.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from visual_quality_images import analyze_png  # noqa: E402


FIXTURES = ("darkflow_pump_house", "visual_tower", "visual_manor", "visual_sewer")


def score(path: Path) -> tuple[float, dict[str, object]]:
    metrics = analyze_png(path)
    coverage = float(metrics["coverage"]["non_background_fraction"])
    edges = float(metrics["edges"]["density"])
    buckets = int(metrics["colors"]["non_background_bucket_count"])
    # The weights favour readable structure and material separation, while
    # remaining deliberately coarse enough not to overfit one seed.
    value = 2.0 * coverage + 12.0 * edges + buckets / 40.0
    return round(value, 3), {
        "coverage": round(coverage, 6),
        "edge_density": round(edges, 6),
        "material_buckets": buckets,
        "score": round(value, 3),
    }


def main() -> None:
    base_path = ROOT / "output" / "profile-visual" / "darkflow_pump_house" / "scene-isometric.png"
    baseline, _ = score(base_path)
    reports = []
    for fixture in FIXTURES:
        iso = ROOT / "output" / "profile-visual" / fixture / "scene-isometric.png"
        top = ROOT / "output" / "profile-visual" / fixture / "scene-topdown.png"
        assert iso.is_file() and top.is_file(), fixture
        value, metrics = score(iso)
        top_value, top_metrics = score(top)
        assert metrics["coverage"] > 0.20, f"{fixture}: empty isometric frame"
        assert metrics["edge_density"] > 0.06, f"{fixture}: isometric structure collapsed"
        assert metrics["material_buckets"] >= 20, f"{fixture}: material separation collapsed"
        assert top_metrics["coverage"] > 0.20, f"{fixture}: empty topdown frame"
        if fixture != "darkflow_pump_house":
            # The pump house is a useful regression floor, never a golden
            # standard: a generic recipe may differ, but not fall below 82% of
            # the reference's coarse visual signal.
            assert value >= baseline * 0.82, f"{fixture}: below shared visual floor"
        reports.append({"fixture": fixture, "isometric": metrics, "topdown": top_metrics, "reference_ratio": round(value / baseline, 3)})
    print(json.dumps({"status": "passed", "baseline": baseline, "reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
