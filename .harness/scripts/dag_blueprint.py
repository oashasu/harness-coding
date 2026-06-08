#!/usr/bin/env python3
"""DAG blueprint loader — reads gen layer/node topology from external YAML config."""
from __future__ import annotations

from pathlib import Path


def load_dag_blueprint(workdir: Path) -> tuple[dict, dict]:
    """Load GEN_LAYER_NODE_MAP and GEN_NODE_PREREQS from .harness/config/dag-blueprint.yaml.

    Returns (gen_layer_node_map, gen_node_prereqs). Falls back to empty dicts if the
    config file is not present.
    """
    import yaml  # noqa: PLC0415
    blueprint_path = workdir / ".harness" / "config" / "dag-blueprint.yaml"
    if not blueprint_path.exists():
        print(f"[Warning] dag-blueprint.yaml not found at {blueprint_path}, using empty defaults")
        return {}, {}
    with open(blueprint_path, "r", encoding="utf-8") as f:
        blueprint = yaml.safe_load(f) or {}
    layer_node_map = blueprint.get("gen_layer_node_map", {})
    node_prereqs = blueprint.get("gen_node_prereqs", {})
    return layer_node_map, node_prereqs
