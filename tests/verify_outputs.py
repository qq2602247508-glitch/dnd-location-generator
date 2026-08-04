#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
SPEC = ROOT / "specs" / "church.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"invalid PNG signature: {path.name}")
    return struct.unpack(">II", header[16:24])


def glb_info(path: Path) -> dict[str, int]:
    header = path.read_bytes()[:12]
    magic, version, declared_length = struct.unpack("<4sII", header)
    if magic != b"glTF" or version != 2:
        raise AssertionError(f"invalid GLB header: {path.name}")
    actual_length = path.stat().st_size
    if declared_length != actual_length:
        raise AssertionError(f"GLB length mismatch: {path.name}")
    return {"version": version, "bytes": actual_length}


def main() -> None:
    manifest = json.loads((OUTPUT / "manifest.json").read_text(encoding="utf-8"))
    spec_hash = sha256(SPEC)
    if manifest["source_sha256"] != spec_hash:
        raise AssertionError("manifest does not match church.json")
    if manifest["levels"] != 3 or manifest["rooms"] != 14 or manifest["secret_rooms"] != 3:
        raise AssertionError("manifest structure totals are wrong")

    pngs = [
        "church-dm-exploded.png",
        "church-dm-floor1.png",
        "church-dm-floor2.png",
        "church-dm-floor3.png",
        "church-player-floor1.png",
    ]
    images = {}
    for name in pngs:
        path = OUTPUT / name
        dimensions = png_dimensions(path)
        if dimensions != (1200, 850):
            raise AssertionError(f"unexpected image size for {name}: {dimensions}")
        images[name] = {"width": dimensions[0], "height": dimensions[1], "sha256": sha256(path)}

    if images["church-dm-floor1.png"]["sha256"] == images["church-player-floor1.png"]["sha256"]:
        raise AssertionError("DM and player floor renders are identical; secret visibility failed")

    dm_glb = glb_info(OUTPUT / "church-dm.glb")
    player_glb = glb_info(OUTPUT / "church-player.glb")
    if player_glb["bytes"] >= dm_glb["bytes"]:
        raise AssertionError("player GLB is not smaller than DM GLB")
    blend_bytes = (OUTPUT / "church-prototype.blend").stat().st_size
    if blend_bytes < 1_000_000:
        raise AssertionError("BLEND file is unexpectedly small")

    report = {
        "status": "passed",
        "source_sha256": spec_hash,
        "structure": {
            "levels": manifest["levels"],
            "rooms": manifest["rooms"],
            "secret_rooms": manifest["secret_rooms"],
            "prototype_objects": manifest["prototype_objects"],
            "secret_door_objects": manifest["secret_door_objects"],
        },
        "images": images,
        "glb": {"dm": dm_glb, "player": player_glb},
        "blend_bytes": blend_bytes,
        "visibility_evidence": {
            "dm_player_renders_differ": True,
            "player_glb_smaller_by_bytes": dm_glb["bytes"] - player_glb["bytes"],
        },
    }
    (OUTPUT / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
