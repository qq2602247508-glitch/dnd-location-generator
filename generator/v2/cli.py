from __future__ import annotations

import argparse
import json
from pathlib import Path

from .compiler import generate


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a deterministic D&D Scene V2 plan/runtime bundle")
    parser.add_argument("spec", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.spec.resolve(), args.out.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

