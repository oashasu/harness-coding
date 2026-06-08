#!/usr/bin/env python3
"""
Build stage task manifest
Generate stage task manifest from harness-workflow-state.json, output fields strictly aligned with task-manifest.v1.schema.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from task_identity import derive_task_id

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_SCHEMA = PROJECT_ROOT / ".harness/schemas/harness-state.schema.json"
MANIFEST_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/task-manifest.v1.schema.json"
VALIDATE_SCRIPT = PROJECT_ROOT / ".harness/scripts/validate-task-manifest.py"

ALLOWED_STAGES = {"prep", "spec", "prove", "final"}
PHASE_INPUT_HANDOFF = {
    "spec": ("prep", "spec"),
    "prove": ("spec", "prove"),
    "final": ("gen", "final"),
}


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


def handoff_file_for_phase(workspace_root: Path, current_phase: str) -> str:
    mapping = PHASE_INPUT_HANDOFF.get(current_phase)
    if mapping is None:
        return ""
    source_phase, target_phase = mapping
    return str(workspace_root / ".harness" / "handoff" / f"{source_phase}-to-{target_phase}.json")


def build_stage_manifest(state: dict[str, Any], state_file: Path) -> dict[str, Any]:
    current_phase = state.get("current_phase")
    if current_phase not in ALLOWED_STAGES:
        raise ValueError(f"Current phase not applicable for build-stage-task.py: {current_phase}")

    checkpoints = state.get("checkpoints", {})
    if checkpoints.get("awaiting_user_action") is True:
        raise ValueError("awaiting_user_action=true, cannot build stage execution task now")

    resume_context = state.get("resume_context")
    if not isinstance(resume_context, dict):
        raise ValueError("Missing resume_context")

    current_execution_unit = resume_context.get("current_execution_unit")
    if current_execution_unit != current_phase:
        raise ValueError(f"resume_context.current_execution_unit does not match current phase: {current_execution_unit} != {current_phase}")

    next_required_action = resume_context.get("next_required_action")
    required_script = resume_context.get("required_script")
    if not isinstance(next_required_action, str) or not next_required_action:
        raise ValueError("resume_context.next_required_action cannot be empty")
    if not isinstance(required_script, str) or not required_script:
        raise ValueError("resume_context.required_script cannot be empty")
    action_parts = next_required_action.split(":", 1)
    if len(action_parts) != 2 or action_parts[1] != current_phase:
        raise ValueError(f"next_required_action does not match current phase: {next_required_action} != {current_phase}")

    workspace_root = detect_workspace_root(state_file)
    project = state.get("project", {})

    outputs: list[str] = []
    code = project.get("code", "")

    if current_phase == "prep":
        outputs = list(state.get("artifacts", {}).get("phase_1", {}).get("outputs", []))
    elif current_phase == "spec":
        if code:
            outputs = [f".harness/output/spec/{code}/spec-business-facts-{code}.json"]
    elif current_phase == "prove":
        if code:
            outputs = [f".harness/output/prove/{code}/prove-business-facts-{code}.json"]
    elif current_phase == "final":
        outputs = [".harness/output/final/audit-report.md"]

    # Ensure expected_outputs is non-empty (schema requires minItems: 1)
    if not outputs:
        code_safe = code if code else "unknown"
        if current_phase == "prep":
            outputs = [f".harness/output/prep/prep-output-{code_safe}.json"]
        elif current_phase == "spec":
            outputs = [f".harness/output/spec/{code_safe}/spec-business-facts-{code_safe}.json"]
        elif current_phase == "prove":
            outputs = [f".harness/output/prove/{code_safe}/prove-business-facts-{code_safe}.json"]
        elif current_phase == "final":
            outputs = [".harness/output/final/audit-report.md"]

    inputs_obj: dict[str, str] = {
        "state_file": str(state_file),
        "session_brief": str(workspace_root / ".harness/state/SESSION_BRIEF.md"),
        "handoff_dir": str(workspace_root / ".harness/handoff"),
    }
    handoff_file = handoff_file_for_phase(workspace_root, current_phase)
    if handoff_file:
        inputs_obj["handoff_file"] = handoff_file

    return {
        "manifest_version": "1.0",
        "task_scope": "stage",
        "phase": current_phase,
        "execution_unit": current_phase,
        "project": {
            "code": project.get("code", ""),
            "name": project.get("name", ""),
        },
        "task_id": derive_task_id(
            state,
            task_scope="stage",
            phase=current_phase,
            execution_unit=current_phase,
        ),
        "dispatch_role": "Worker",
        "review_role": "ReviewAgent",
        "inputs": inputs_obj,
        "expected_outputs": outputs,
    }


def run_manifest_validator(manifest_path: Path) -> bool:
    result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), "--manifest-file", str(manifest_path)],
        capture_output=False,
    )
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build stage task manifest for OrchestratorAgent.")
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
        manifest = build_stage_manifest(state, state_file)
    except ValueError as exc:
        print(f"[BLOCKER] {exc}")
        return 1

    if args.output:
        output_file = Path(args.output)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[INFO] Generated stage task manifest: {output_file}")
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
