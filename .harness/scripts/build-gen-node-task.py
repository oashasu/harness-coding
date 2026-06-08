#!/usr/bin/env python3
"""
Build gen_node task manifest
Generate gen node task manifest from harness-workflow-state.json, output fields strictly aligned with task-manifest.v1.schema.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from task_identity import derive_task_id
from state_integrity import legacy_view

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_SCHEMA = PROJECT_ROOT / ".harness/schemas/harness-state.schema.json"
MANIFEST_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/task-manifest.v1.schema.json"
VALIDATE_SCRIPT = PROJECT_ROOT / ".harness/scripts/validate-task-manifest.py"

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
GEN_PHASE_HANDOFF = ("prove", "gen")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def detect_workspace_root(state_file: Path) -> Path:
    for candidate in [state_file.resolve(), *state_file.resolve().parents]:
        skill_root = candidate / ".harness"
        if skill_root.exists() and (skill_root / "scripts").exists():
            return candidate
    return PROJECT_ROOT


def validate_state(state: dict[str, Any]) -> str | None:
    if jsonschema is None:
        return None
    try:
        schema = load_json(STATE_SCHEMA)
        jsonschema.validate(instance=state, schema=schema)
    except Exception as exc:
        return str(exc)
    return None


def handoff_file_for_gen(workspace_root: Path) -> str:
    source_phase, target_phase = GEN_PHASE_HANDOFF
    return str(workspace_root / ".harness" / "handoff" / f"{source_phase}-to-{target_phase}.json")


def build_gen_node_manifest(state: dict[str, Any], state_file: Path) -> dict[str, Any]:
    view = legacy_view(state)
    if view.current_phase != "gen":
        raise ValueError(f"Current phase is not gen: {view.current_phase}")

    checkpoints = view.checkpoints
    if isinstance(checkpoints, dict) and checkpoints.get("awaiting_user_action") is True:
        raise ValueError("awaiting_user_action=true, cannot build gen node task now")

    resume_context = view.resume_context
    if not isinstance(resume_context, dict):
        raise ValueError("Missing resume_context")

    phase_3 = view.artifacts_phase_3
    current_node = phase_3.get("current_node")
    nodes = phase_3.get("nodes", {})
    if not isinstance(current_node, str) or not current_node:
        raise ValueError("Gen phase missing phase_3.current_node")
    if not isinstance(nodes, dict) or current_node not in nodes:
        raise ValueError(f"current_node not registered in phase_3.nodes: {current_node}")

    current_execution_unit = resume_context.get("current_execution_unit")
    if current_execution_unit != current_node:
        raise ValueError(f"resume_context.current_execution_unit does not match current_node: {current_execution_unit} != {current_node}")

    next_required_action = resume_context.get("next_required_action")
    required_script = resume_context.get("required_script")
    if not isinstance(next_required_action, str) or not next_required_action:
        raise ValueError("resume_context.next_required_action cannot be empty")
    if not isinstance(required_script, str) or not required_script:
        raise ValueError("resume_context.required_script cannot be empty")
    action_parts = next_required_action.split(":", 1)
    if len(action_parts) != 2 or action_parts[1] != current_node:
        raise ValueError(f"next_required_action does not match current_node: {next_required_action} != {current_node}")
    valid_prefixes = ("dispatch_gen_node_worker:", "dispatch_gen_node_review:")
    if not any(next_required_action.startswith(prefix) for prefix in valid_prefixes):
        raise ValueError(f"Illegal dispatch action prefix: {action_parts[0]}, only gen node worker dispatch actions allowed")

    node_state = nodes[current_node]
    if not isinstance(node_state, dict):
        raise ValueError(f"Node state invalid: {current_node}")

    workspace_root = detect_workspace_root(state_file)
    project = state.get("project", {})

    expected_outputs = list(node_state.get("generated_files", []))
    if not expected_outputs:
        code = project.get("code", "unknown")
        expected_outputs = [f".harness/output/gen/{code}/gen-{current_node}-{code}.json"]

    manifest = {
        "manifest_version": "1.0",
        "task_scope": "gen_node",
        "phase": "gen",
        "execution_unit": current_node,
        "node_id": current_node,
        "project": {
            "code": project.get("code", ""),
            "name": project.get("name", ""),
        },
        "task_id": derive_task_id(
            state,
            task_scope="gen_node",
            phase="gen",
            execution_unit=current_node,
        ),
        "dispatch_role": "Worker",
        "review_role": "ReviewAgent",
        "inputs": {
            "state_file": str(state_file),
            "session_brief": str(workspace_root / ".harness/state/SESSION_BRIEF.md"),
            "handoff_dir": str(workspace_root / ".harness/handoff"),
            "handoff_file": handoff_file_for_gen(workspace_root),
        },
        "expected_outputs": expected_outputs,
        "prerequisites": list(NODE_PREREQS.get(current_node, [])),
    }

    return manifest


def run_manifest_validator(manifest_path: Path) -> bool:
    result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), "--manifest-file", str(manifest_path)],
        capture_output=False,
    )
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build gen node task manifest for OrchestratorAgent.")
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    state_file = Path(args.state_file)
    state = load_json(state_file)
    schema_error = validate_state(state)
    if schema_error:
        print(f"[BLOCKER] State file does not match schema: {schema_error}")
        return 1

    try:
        manifest = build_gen_node_manifest(state, state_file)
    except ValueError as exc:
        print(f"[BLOCKER] {exc}")
        return 1

    if args.output:
        output_file = Path(args.output)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[INFO] Generated gen node task manifest: {output_file}")
        if not run_manifest_validator(output_file):
            return 1
        print(f"[PASS] Manifest validation passed: {output_file}")
        return 0

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        tmp.write(json.dumps(manifest, ensure_ascii=False, indent=2))
        tmp_path = Path(tmp.name)
    try:
        if not run_manifest_validator(tmp_path):
            return 1
    finally:
        tmp_path.unlink(missing_ok=True)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
