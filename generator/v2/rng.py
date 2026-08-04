from __future__ import annotations

import hashlib
import random


def named_seed(root_seed: int, stream: str) -> int:
    payload = f"dnd-scene-v2:{root_seed}:{stream}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def named_rng(root_seed: int, stream: str) -> random.Random:
    """Return an isolated stream so later dressing changes cannot move roads."""
    return random.Random(named_seed(root_seed, stream))

