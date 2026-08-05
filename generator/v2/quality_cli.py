"""Command line entry point for V2.4 scene quality reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .quality import certify_quality, discover_scene_directories, evaluate_cohort, evaluate_paths, load_policy


def _write(report: dict[str, Any], output: Path | None) -> None:
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


def _directories(samples: list[Path], roots: list[Path]) -> list[Path]:
    candidates = [*samples, *discover_scene_directories(roots)]
    return sorted({item.expanduser().resolve() for item in candidates})


def _evaluate_directory(directory: Path, policy: dict[str, Any]) -> dict[str, Any]:
    plan = directory / "scene.plan.json"
    runtime = directory / "scene.runtime.json"
    if not plan.is_file() or not runtime.is_file():
        raise FileNotFoundError(f"scene directory lacks plan/runtime: {directory}")
    return evaluate_paths(plan, runtime, policy=policy)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate V2 scene quality without invoking a generator or renderer")
    parser.add_argument("--policy", type=Path, help="quality policy JSON; defaults to specs/quality/v2.4-policy.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    single = subparsers.add_parser("evaluate", help="evaluate one plan/runtime/render bundle")
    single.add_argument("--plan", type=Path, required=True)
    single.add_argument("--runtime", type=Path, required=True)
    single.add_argument("--render-manifest", type=Path)
    single.add_argument("--build-seconds", type=float, default=0.0)
    single.add_argument("--out", type=Path)

    certify = subparsers.add_parser("certify", help="bind a visual certificate to a programmatic quality report")
    certify.add_argument("--quality-report", type=Path, required=True)
    certify.add_argument("--visual-certificate", type=Path, required=True)
    certify.add_argument("--out", type=Path, required=True)

    for name, help_text in (("baseline", "record a non-enforcing cohort baseline"), ("round", "evaluate an enforcing multi-seed round")):
        cohort = subparsers.add_parser(name, help=help_text)
        cohort.add_argument("--sample", type=Path, action="append", default=[], help="scene directory; repeatable")
        cohort.add_argument("--root", type=Path, action="append", default=[], help="recursively discover scene directories")
        if name == "round":
            cohort.add_argument("--name", choices=("round1", "round2", "round3"), required=True)
        cohort.add_argument("--sample-reports-dir", type=Path, help="write one quality.report.json per discovered sample")
        cohort.add_argument("--out", type=Path)

    args = parser.parse_args()
    policy = load_policy(args.policy)
    if args.command == "certify":
        quality_report = json.loads(args.quality_report.read_text(encoding="utf-8"))
        visual_certificate = json.loads(args.visual_certificate.read_text(encoding="utf-8"))
        report = certify_quality(
            quality_report,
            visual_certificate,
            certificate_directory=args.visual_certificate.resolve().parent,
        )
        _write(report, args.out)
        return
    if args.command == "evaluate":
        report = evaluate_paths(
            args.plan.resolve(), args.runtime.resolve(),
            args.render_manifest.resolve() if args.render_manifest else None,
            policy=policy, build_seconds=args.build_seconds,
        )
        _write(report, args.out)
        return

    directories = _directories(args.sample, args.root)
    if not directories:
        raise SystemExit("no scene directories found")
    reports = []
    for index, directory in enumerate(directories):
        report = _evaluate_directory(directory, policy)
        reports.append(report)
        if args.sample_reports_dir:
            target = args.sample_reports_dir / f"{index:03d}-{directory.name}" / "quality.report.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    round_name = "baseline" if args.command == "baseline" else args.name
    _write(evaluate_cohort(reports, policy=policy, round_name=round_name), args.out)


if __name__ == "__main__":
    main()
