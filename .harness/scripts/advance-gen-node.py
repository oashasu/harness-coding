#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

from state_integrity import seal_state, verify_state_integrity, resolve_state_file, legacy_view


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_FILE = resolve_state_file()
STATE_SCHEMA = PROJECT_ROOT / ".harness/schemas/harness-state.schema.json"
NODE_ORDER = ["G01", "G02", "G03", "G04", "G05", "G06", "G07", "G08", "G09"]
NODE_PREREQS = {
    "G01": [],
    "G02": ["G01"],
    "G03": ["G02"],
    "G04": ["G03"],
    "G05": ["G04"],
    "G06": ["G02", "G03"],
    "G07": ["G01"],
    "G08": ["G01"],
    "G09": ["G02", "G07", "G08"],
}
GEN_LAYER_NODE_MAP = {
    "layer_1": ["G01", "G02", "G03"],
    "layer_2": ["G04"],
    "layer_3": ["G05", "G06"],
    "layer_4": ["G07", "G08", "G09"],
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def save_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(payload, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def save_state_json_atomic(path: Path, payload: dict[str, Any], *, key_source_state_file: Path | None = None) -> None:
    try:
        save_json_atomic(path, seal_state(path, payload, key_source_state_file=key_source_state_file))
    except ValueError:
        save_json_atomic(path, payload)


def validate_state_schema(state: dict[str, Any]) -> str | None:
    if jsonschema is None:
        return None
    try:
        schema = load_json(STATE_SCHEMA)
        jsonschema.validate(instance=state, schema=schema)
    except Exception as exc:
        return str(exc)
    return None


def node_complete(node_id: str, nodes: dict[str, Any]) -> tuple[bool, str]:
    node_state = nodes.get(node_id)
    if not isinstance(node_state, dict):
        return False, f"{node_id} not registered in phase_3.nodes"
    verification = node_state.get("verification")
    if not isinstance(verification, dict):
        return False, f"{node_id} missing verification"
    if node_state.get("status") != "completed":
        return False, f"{node_id}.status must be completed: {node_state.get('status')}"
    if verification.get("review_status") != "approved":
        return False, f"{node_id}.verification.review_status must be approved: {verification.get('review_status')}"
    if verification.get("script_status") != "passed":
        return False, f"{node_id}.verification.script_status must be passed: {verification.get('script_status')}"
    if verification.get("compile_status") == "failed":
        return False, f"{node_id}.verification.compile_status must not be failed"
    if not str(node_state.get("last_review_report", "")).strip():
        return False, f"{node_id}.last_review_report cannot be empty"
    return True, ""


def validate_entry_gate(state: dict[str, Any]) -> None:
    view = legacy_view(state)
    phase_status_dict = state.get("phase_status", {})  # Keep raw for write compatibility
    phase_2 = view.artifacts_phase_2
    phase_3 = view.artifacts_phase_3
    checkpoints = view.checkpoints
    resume_context = view.resume_context or {}

    if view.current_phase != "gen":
        raise ValueError(f"Current phase is not gen: {view.current_phase}")
    prove_status = view.get_phase_status_for("prove")
    if prove_status != "completed":
        raise ValueError(f"prove phase not completed, cannot advance gen nodes: {prove_status}")
    gen_status = view.get_phase_status_for("gen")
    if gen_status != "in_progress":
        raise ValueError(f"phase_status.gen must be in_progress: {gen_status}")
    if isinstance(checkpoints, dict) and checkpoints.get("awaiting_user_action") is True:
        raise ValueError("awaiting_user_action=true, cannot advance gen nodes")
    last_checkpoint = checkpoints.get("last_checkpoint") if isinstance(checkpoints, dict) else None
    if last_checkpoint not in {"prove-ok", "layer-ok"}:
        raise ValueError(f"last_checkpoint must be prove-ok or layer-ok: {last_checkpoint}")
    if phase_2.get("allow_codegen") not in {"YES", "YES_WITH_WARNING"}:
        raise ValueError(f"allow_codegen did not permit code generation: {phase_2.get('allow_codegen')}")
    if resume_context.get("next_required_action") != "run_preflight:gen":
        raise ValueError(f"next_required_action must be run_preflight:gen: {resume_context.get('next_required_action')}")
    if resume_context.get("required_script") != "preflight.py --stage gen":
        raise ValueError(f"required_script must be preflight.py --stage gen: {resume_context.get('required_script')}")
    if resume_context.get("pending_checkpoint") != "NONE":
        raise ValueError(f"pending_checkpoint must be NONE: {resume_context.get('pending_checkpoint')}")
    if resume_context.get("last_review_status") != "approved":
        raise ValueError(f"last_review_status must be approved: {resume_context.get('last_review_status')}")

    current_node = phase_3.get("current_node")
    if not isinstance(current_node, str) or current_node not in NODE_ORDER:
        raise ValueError(f"phase_3.current_node illegal: {current_node}")
    if resume_context.get("current_execution_unit") != current_node:
        raise ValueError(
            "resume_context.current_execution_unit does not match current_node: "
            f"{resume_context.get('current_execution_unit')} != {current_node}"
        )


def ensure_started_nodes_have_completed_prereqs(nodes: dict[str, Any]) -> None:
    for node_id in NODE_ORDER:
        node_state = nodes.get(node_id)
        if not isinstance(node_state, dict):
            raise ValueError(f"Missing gen node state: {node_id}")
        if node_state.get("status") not in {"in_progress", "completed"}:
            continue
        unmet = [dep for dep in NODE_PREREQS[node_id] if not node_complete(dep, nodes)[0]]
        if unmet:
            raise ValueError(f"{node_id} already started, but prerequisite nodes not completed: {', '.join(unmet)}")


def sync_layer_statuses(phase_3: dict[str, Any]) -> None:
    nodes = phase_3.get("nodes", {})
    layers = phase_3.get("layers", {})
    if not isinstance(nodes, dict) or not isinstance(layers, dict):
        return
    for layer_name, required_nodes in GEN_LAYER_NODE_MAP.items():
        layer_state = layers.get(layer_name)
        if not isinstance(layer_state, dict):
            continue
        if all(node_complete(node_id, nodes)[0] for node_id in required_nodes):
            layer_state["status"] = "completed"


def next_ready_node(nodes: dict[str, Any]) -> str | None:
    for node_id in NODE_ORDER:
        node_state = nodes.get(node_id)
        if not isinstance(node_state, dict):
            raise ValueError(f"Missing gen node state: {node_id}")
        if node_state.get("status") != "pending":
            continue
        unmet = [dep for dep in NODE_PREREQS[node_id] if not node_complete(dep, nodes)[0]]
        if not unmet:
            return node_id
    return None


def all_nodes_completed(nodes: dict[str, Any]) -> tuple[bool, list[str]]:
    blockers = []
    for node_id in NODE_ORDER:
        complete, reason = node_complete(node_id, nodes)
        if not complete:
            blockers.append(reason)
    return not blockers, blockers


def rewrite_resume_for_node(state: dict[str, Any], node_id: str) -> None:
    state["resume_context"] = {
        "current_execution_unit": node_id,
        "next_required_action": f"dispatch_gen_node_worker:{node_id}",
        "required_script": "build-gen-node-task.py",
        "pending_checkpoint": "NONE",
        "resume_first_prompt": f"Read SESSION_BRIEF and state file, confirm current gen node {node_id} and its prerequisites are satisfied, then build task manifest to dispatch Worker.",
        "last_review_status": "pending",
    }


def rewrite_resume_for_gen_preflight(state: dict[str, Any]) -> None:
    state["resume_context"] = {
        "current_execution_unit": "gen",
        "next_required_action": "run_preflight:gen",
        "required_script": "preflight.py --stage gen",
        "pending_checkpoint": "NONE",
        "resume_first_prompt": "All gen nodes completed, run gen phase preflight, then advance to final via phase-handoff.",
        "last_review_status": "approved",
    }


def advance_gen_node(state: dict[str, Any]) -> dict[str, Any]:
    validate_entry_gate(state)
    updated = json.loads(json.dumps(state))
    phase_3 = updated.setdefault("artifacts", {}).setdefault("phase_3", {})
    nodes = phase_3.get("nodes", {})
    if not isinstance(nodes, dict):
        raise ValueError("phase_3.nodes missing or invalid")

    current_node = phase_3["current_node"]
    current_complete, current_reason = node_complete(current_node, nodes)
    if not current_complete:
        raise ValueError(f"Current node does not meet advancement criteria: {current_reason}")

    ensure_started_nodes_have_completed_prereqs(nodes)
    sync_layer_statuses(phase_3)

    ready_node = next_ready_node(nodes)
    if ready_node:
        nodes[ready_node]["status"] = "in_progress"
        phase_3["current_node"] = ready_node
        rewrite_resume_for_node(updated, ready_node)
    else:
        completed, blockers = all_nodes_completed(nodes)
        if not completed:
            raise ValueError("No pending nodes available but gen not complete; DAG or state inconsistency: " + "; ".join(blockers))
        updated["phase_status"]["gen"] = "completed"
        phase_3["current_node"] = None
        rewrite_resume_for_gen_preflight(updated)

    updated.setdefault("timestamps", {})["updated_at"] = iso_utc_now()
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Advance gen DAG node after review and preflight gate are satisfied.")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    parser.add_argument("--output")
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args()

    if args.output and args.in_place:
        print("[BLOCKER] --output and --in-place cannot be used together")
        return 1

    state_file = Path(args.state_file)
    output_file = Path(args.output) if args.output else state_file if args.in_place else None
    state = load_json(state_file)
    integrity_error = verify_state_integrity(state_file, state)
    if integrity_error:
        print(f"[BLOCKER] {integrity_error}")
        return 1
    schema_error = validate_state_schema(state)
    if schema_error:
        print(f"[BLOCKER] Input state file does not match schema: {schema_error}")
        return 1

    try:
        updated_state = advance_gen_node(state)
    except ValueError as exc:
        print(f"[BLOCKER] {exc}")
        return 1

    schema_error = validate_state_schema(updated_state)
    if schema_error:
        print(f"[BLOCKER] State file does not match schema after advancement: {schema_error}")
        return 1

    if output_file is not None:
        save_state_json_atomic(output_file, updated_state, key_source_state_file=state_file)
        print(f"[PASS] Advanced gen node state: {output_file}")
        return 0
    print(json.dumps(updated_state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
