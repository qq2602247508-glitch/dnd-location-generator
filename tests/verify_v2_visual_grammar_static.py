#!/usr/bin/env python3
"""Static contract checks for the generic V2 building visual grammar.

This deliberately parses the Blender script instead of importing it, so the
check can run in ordinary Python without a Blender/bpy runtime or any outputs.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "blender" / "build_scene_v2.py"
REQUIRED_ARCHETYPES = {
    "guildhall", "shrine", "shop", "tenement", "watchhouse", "inn", "clock_tower",
}


def _assignment(tree: ast.Module, name: str) -> ast.AST:
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                return node.value
    raise AssertionError(f"missing top-level assignment: {name}")


def _function_source(tree: ast.Module, source: str, name: str) -> str:
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name), None)
    if not function:
        raise AssertionError(f"missing function: {name}")
    value = ast.get_source_segment(source, function)
    if not value:
        raise AssertionError(f"unable to recover function source: {name}")
    return value


def main() -> None:
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SOURCE_PATH))
    styles = ast.literal_eval(_assignment(tree, "ARCHETYPE_VISUAL_STYLES"))
    if not REQUIRED_ARCHETYPES <= styles.keys():
        raise AssertionError(f"visual grammar omits archetypes: {sorted(REQUIRED_ARCHETYPES - styles.keys())}")
    for archetype in REQUIRED_ARCHETYPES:
        style = styles[archetype]
        if not {"roof_profile", "roof_material", "wall_material", "trim_material"} <= style.keys():
            raise AssertionError(f"visual grammar is incomplete: {archetype}")
    if len({styles[item]["roof_profile"] for item in REQUIRED_ARCHETYPES}) < 5:
        raise AssertionError("roof profiles collapsed across required archetypes")
    if len({styles[item]["wall_material"] for item in REQUIRED_ARCHETYPES}) < 6:
        raise AssertionError("facade palettes collapsed across required archetypes")

    roofs = _function_source(tree, source, "build_roofs")
    details = _function_source(tree, source, "build_archetype_details")
    terrain = _function_source(tree, source, "build_terrain")
    floors = _function_source(tree, source, "build_level_floors_and_grids")
    camera = _function_source(tree, source, "content_camera_frame")
    connectors = _function_source(tree, source, "build_connectors")
    if "roof_profile_boxes" not in roofs or "InnGableRoof" in source:
        raise AssertionError("inn roof is still duplicated instead of using the shared roof profile")
    if not {"facade_band_and_eave_boxes", "facade_window_boxes", "grammar_roles"} <= set(
        token for token in ("facade_band_and_eave_boxes", "facade_window_boxes", "grammar_roles") if token in details
    ):
        raise AssertionError("generic facade grammar lacks windows, eaves or facade bands")
    if "PLAN[\"scene\"]" in roofs + details + camera:
        raise AssertionError("new visual grammar/camera must not branch on scene id")
    if "cell_run_boxes" not in terrain or "cell_run_boxes" not in floors:
        raise AssertionError("floor/terrain batching regressed to per-cell boxes")
    if "weathered_ground_material" not in source:
        raise AssertionError("weathered city ground material is missing")
    if connectors.count('"connector_vertical"') < 4:
        raise AssertionError("stairs, ladders and hatches lack a shared vertical-transition language")
    print("v2 visual grammar static contract passed")


if __name__ == "__main__":
    main()
