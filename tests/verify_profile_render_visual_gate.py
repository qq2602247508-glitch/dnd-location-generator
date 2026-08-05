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


PROFILE_ROOT = ROOT / "output" / "profile-visual"
FIXTURES = tuple(sorted(path.name for path in PROFILE_ROOT.glob("visual_*") if path.is_dir()))


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
    base_path = PROFILE_ROOT / "darkflow_pump_house" / "scene-isometric.png"
    baseline, _ = score(base_path)
    reports = []
    for fixture in FIXTURES:
        iso = PROFILE_ROOT / fixture / "scene-isometric.png"
        top = PROFILE_ROOT / fixture / "scene-topdown.png"
        assert iso.is_file() and top.is_file(), fixture
        value, metrics = score(iso)
        top_value, top_metrics = score(top)
        assert metrics["coverage"] > 0.20, f"{fixture}: empty isometric frame"
        edge_floor = 0.04 if fixture in {"visual_cavern", "visual_ruin"} else 0.06
        assert metrics["edge_density"] > edge_floor, f"{fixture}: isometric structure collapsed"
        assert metrics["material_buckets"] >= 20, f"{fixture}: material separation collapsed"
        top_coverage_floor = 0.15 if fixture == "visual_lighthouse" else 0.20
        assert top_metrics["coverage"] > top_coverage_floor, f"{fixture}: empty topdown frame"
        if fixture != "darkflow_pump_house":
            # The pump house is a useful regression floor, never a golden
            # standard.  Natural/ruined scenes intentionally use negative
            # space, and civic interiors vary in density, so the shared gate
            # uses a coarse 74% floor plus the absolute readability checks
            # above instead of overfitting one reference composition.
            assert value >= max(3.0, baseline * 0.74), f"{fixture}: below shared visual floor"
        reports.append({"fixture": fixture, "isometric": metrics, "topdown": top_metrics, "reference_ratio": round(value / baseline, 3)})
    print(json.dumps({"status": "passed", "baseline": baseline, "reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
