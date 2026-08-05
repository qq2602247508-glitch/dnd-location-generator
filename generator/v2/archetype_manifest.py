"""Declarative archetype/theme manifest loading and validation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


MANIFEST_SCHEMA = "dnd-archetype-manifest-1.0"
MANIFEST_VERSION = "2.5.0-prototype.1"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


def _fail(message: str) -> None:
    raise ValueError(message)


def validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        _fail("unsupported archetype manifest schema")
    for field in ("id", "name", "family"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            _fail(f"manifest requires non-empty {field}")
    floors = manifest.get("floors")
    if not isinstance(floors, list) or not floors:
        _fail("manifest requires at least one floor")
    floor_ids: set[str] = set()
    room_ids: set[str] = set()
    room_roles: set[str] = set()
    for floor in floors:
        floor_id = str(floor.get("id", ""))
        if not floor_id or floor_id in floor_ids:
            _fail(f"duplicate or missing floor id: {floor_id or '<missing>'}")
        floor_ids.add(floor_id)
        rooms = floor.get("rooms")
        if not isinstance(rooms, list) or not rooms:
            _fail(f"floor requires rooms: {floor_id}")
        for room in rooms:
            room_id = str(room.get("id", ""))
            if not room_id or room_id in room_ids:
                _fail(f"duplicate or missing room id: {room_id or '<missing>'}")
            room_ids.add(room_id)
            role = str(room.get("role", ""))
            if not role:
                _fail(f"room requires role: {room_id}")
            room_roles.add(role)
            minimum, maximum = int(room.get("min_area", 0)), int(room.get("max_area", 0))
            if minimum <= 0 or maximum < minimum:
                _fail(f"invalid room area bounds: {room_id}")
            if int(room.get("min_span", 0)) < 1:
                _fail(f"room requires positive min_span: {room_id}")
    constraints = manifest.get("constraints", {})
    if not isinstance(constraints, Mapping):
        _fail("manifest constraints must be an object")
    if constraints.get("require_entry", True) and "entry" not in room_roles:
        _fail("manifest requires an entry room")
    if constraints.get("require_objective", True) and not {"objective", "boss"} & room_roles:
        _fail("manifest requires an objective or boss room")
    if constraints.get("require_secret", False) and "secret" not in room_roles:
        _fail("manifest requires a secret room")
    if constraints.get("require_vertical_connector", False) and len(floors) < 2:
        _fail("vertical connector requires at least two floors")
    themes = manifest.get("themes", {})
    if not isinstance(themes, Mapping) or not themes:
        _fail("manifest requires at least one theme")
    if "default" not in themes:
        _fail("manifest themes must include default")
    return {
        "status": "passed",
        "manifest_id": str(manifest["id"]),
        "family": str(manifest["family"]),
        "floors": len(floors),
        "rooms": len(room_ids),
        "room_roles": sorted(room_roles),
        "themes": sorted(str(theme_id) for theme_id in themes),
        "manifest_sha256": manifest_sha256(manifest),
    }


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    return manifest


def resolve_theme(manifest: Mapping[str, Any], theme_id: str = "default") -> dict[str, Any]:
    """Return a copy with a resolved visual theme, without mutating source data."""

    validate_manifest(manifest)
    themes = manifest["themes"]
    if theme_id not in themes:
        raise ValueError(f"unknown theme for {manifest['id']}: {theme_id}")
    resolved = copy.deepcopy(dict(manifest))
    resolved["resolved_theme_id"] = str(theme_id)
    resolved["resolved_theme"] = copy.deepcopy(themes[theme_id])
    resolved["manifest_sha256"] = manifest_sha256(manifest)
    return resolved
