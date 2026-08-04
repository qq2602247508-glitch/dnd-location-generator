from __future__ import annotations

import argparse
import json
from pathlib import Path

from .program import generate_program


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a deterministic D&D SceneProgram")
    parser.add_argument("spec", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate_program(args.spec, args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
