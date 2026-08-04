from __future__ import annotations

from typing import Any, Protocol


class DndContentAdapter(Protocol):
    adapter_id: str
    adapter_version: str

    def resolve(self, program: dict[str, Any], adventure: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]: ...


class NullDndContentAdapter:
    """Safe prototype boundary: preserves slots without touching another project."""

    adapter_id = "null-dnd-content-adapter"
    adapter_version = "1.0.0"

    def resolve(self, program: dict[str, Any], adventure: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "dnd-content-resolution-1.0",
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "scene_id": program["scene"]["id"],
            "program_sha256": program["program_sha256"],
            "adventure_sha256": adventure["adventure_sha256"],
            "status": "unresolved",
            "context": {"campaign_id": context.get("campaign_id", ""), "ruleset": context.get("ruleset", "dnd5e")},
            "slots": adventure["content"],
            "capabilities": {
                "writes_external_project": False,
                "generates_statblocks": False,
                "preserves_dm_visibility": True,
                "reroll_without_geometry": True,
            },
        }
