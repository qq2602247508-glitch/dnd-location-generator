#!/usr/bin/env python3
"""Render profile inputs through the already-running Blender MCP socket.

This deliberately never launches Blender: the desktop Blender instance owns
the render process and this tiny client only submits one deterministic build
job at a time.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "blender" / "build_profile_scene.py"


def recv_json(sock: socket.socket) -> dict[str, object]:
    decoder = json.JSONDecoder()
    buffer = ""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            raise RuntimeError("Blender socket closed before returning a response")
        buffer += chunk.decode("utf-8")
        try:
            value, _ = decoder.raw_decode(buffer)
            return value
        except json.JSONDecodeError:
            continue


def submit(input_path: Path, out_dir: Path) -> dict[str, object]:
    code = f'''import sys
from pathlib import Path
script_path = {str(SCRIPT)!r}
input_path = {str(input_path)!r}
out_dir = {str(out_dir)!r}
old_argv = sys.argv[:]
try:
    sys.argv = ["blender", "--", "--input", input_path, "--out-dir", out_dir]
    namespace = {{"bpy": bpy, "__name__": "__main__", "__file__": script_path}}
    exec(compile(Path(script_path).read_text(encoding="utf-8"), script_path, "exec"), namespace, namespace)
finally:
    sys.argv = old_argv
'''
    with socket.create_connection(("127.0.0.1", 9876), timeout=30) as sock:
        sock.settimeout(900)
        sock.sendall(json.dumps({"type": "execute_code", "params": {"code": code}}).encode("utf-8"))
        response = recv_json(sock)
    if response.get("status") != "success":
        raise RuntimeError(json.dumps(response, ensure_ascii=False))
    return response


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    for input_path in args.inputs:
        input_path = input_path.resolve()
        out_dir = ROOT / "output" / "profile-visual" / input_path.stem
        print(f"rendering {input_path.stem}", flush=True)
        submit(input_path, out_dir)
        print(f"rendered {input_path.stem}", flush=True)


if __name__ == "__main__":
    main()
