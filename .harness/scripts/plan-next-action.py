#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from task_identity import derive_task_id
from state_integrity import verify_state_integrity

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_FILE = PROJECT_ROOT / ".harness/state/harness-workflow-state.json"
STATE_SCHEMA = PROJECT_ROOT / ".harness/skills/harness-workflow-skill/references/task/harness-workflow-state.schema.json"
NEXT_ACTION_PLAN_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/next-action-plan.v1.schema.json"
STAGE_PHASES = {"prep", "spec", "prove", "final"}
GEN_NODES = {"G01", "G02", "G03", "G04", "G05", "G06", "G07", "G08", "G09"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def load_preflight_result(workspace_root: Path) -> dict[str, Any] | None:
    """Load preflight-result.json"""
    preflight_file = workspace_root / ".harness" / "output" / "preflight-result.json"
    if not preflight_file.exists():
        return None
    try:
        return load_json(preflight_file)
    except Exception:
        return None


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_state_schema(state: dict[str, Any]) -> str | None:
    if jsonschema is None:
        return None
    try:
        schema = load_json(STATE_SCHEMA)
        jsonschema.validate(instance=state, schema=schema)
    except Exception as exc:
        return str(exc)
    return None


def validate_plan_schema(plan: dict[str, Any]) -> str | None:
    if jsonschema is None:
        return None
    try:
        schema = load_json(NEXT_ACTION_PLAN_SCHEMA)
        jsonschema.validate(instance=plan, schema=schema)
    except Exception as exc:
        return str(exc)
    return None


def detect_workspace_root(state_file: Path) -> Path:
    for candidate in [state_file.resolve(), *state_file.resolve().parents]:
        skill_root = candidate / ".harness"
        if skill_root.exists() and (skill_root / "scripts").exists():
            return candidate
    return PROJECT_ROOT


def output_path(workspace_root: Path, *parts: str) -> str:
    return str(workspace_root.joinpath(".harness", "output", *parts))


def command(workspace_root: Path, script: str, args: list[str], output: str | None = None) -> dict[str, Any]:
    script_path = workspace_root / ".harness" / "scripts" / script
    if not script_path.exists():
        raise ValueError(f"Plan command script not found: {script_path}")
    payload: dict[str, Any] = {
        "script": script,
        "script_path": str(script_path),
        "args": args,
    }
    if output is not None:
        payload["output"] = output
    return payload


def validate_resume_context(state: dict[str, Any]) -> dict[str, Any]:
    resume_context = state.get("resume_context")
    if not isinstance(resume_context, dict):
        raise ValueError("Missing resume_context")
    for field in [
        "current_execution_unit",
        "next_required_action",
        "required_script",
        "pending_checkpoint",
        "last_review_status",
    ]:
        if not isinstance(resume_context.get(field), str):
            raise ValueError(f"resume_context.{field} must be a string")
    return resume_context


def expected_required_script(action: str) -> str:
    if action.startswith("dispatch_stage_worker:") or action.startswith("dispatch_stage_review:"):
        return "build-stage-task.py"
    if action.startswith("dispatch_gen_node_worker:") or action.startswith("dispatch_gen_node_review:"):
        return "build-gen-node-task.py"
    if action.startswith("run_preflight:"):
        return f"preflight.py --stage {action.split(':', 1)[1]}"
    if action.startswith("run_checkpoint:"):
        checkpoint = action.split(":", 1)[1]
        phase = checkpoint.split("-", 1)[0]
        return f"phase-handoff.py --from-phase {phase} --checkpoint {checkpoint} --await-user-action"
    if action == "wait_for_user_action":
        return "phase-handoff.py --user-action <action>"
    if action == "archive_runtime":
        return "archive-harness-workflow.py --archive-only"
    return ""


def validate_action_binding(resume_context: dict[str, Any]) -> None:
    """Validate resume_context action-script binding consistency"""
    action = resume_context["next_required_action"]
    expected_script = expected_required_script(action)
    if not expected_script:
        raise ValueError(f"Unsupported next_required_action: {action}")
    actual_script = resume_context["required_script"]
    if actual_script != expected_script:
        raise ValueError(f"required_script does not match next_required_action: {actual_script} != {expected_script}")


def dispatch_plan(
    state: dict[str, Any],
    state_file: Path,
    workspace_root: Path,
    *,
    task_scope: str,
    phase: str,
    execution_unit: str,
    action_kind: str,
    manifest_script: str,
) -> dict[str, Any]:
    task_id = derive_task_id(state, task_scope=task_scope, phase=phase, execution_unit=execution_unit)
    manifest_path = output_path(workspace_root, "task-manifest", phase, f"{execution_unit}-manifest.json")
    dispatch_path = output_path(workspace_root, "dispatch", phase, f"{execution_unit}-dispatch.json")
    report_path = output_path(workspace_root, "worker-report", phase, f"{execution_unit}-worker-report.json")
    review_path = output_path(workspace_root, "review", phase, f"{execution_unit}-review.json")
    return {
        "plan_version": "1.0",
        "current_phase": state.get("current_phase"),
        "current_execution_unit": execution_unit,
        "next_required_action": state["resume_context"]["next_required_action"],
        "required_script": state["resume_context"]["required_script"],
        "action_kind": action_kind,
        "task_scope": task_scope,
        "phase": phase,
        "execution_unit": execution_unit,
        "task_id": task_id,
        "task_manifest": manifest_path,
        "dispatch_payload": dispatch_path,
        "commands": [
            command(workspace_root, manifest_script, ["--state-file", str(state_file), "--output", manifest_path], manifest_path),
            command(workspace_root, "dispatch-worker.py", ["--task-manifest", manifest_path, "--output", dispatch_path], dispatch_path),
        ],
        "collectors": {
            "worker_report": "collect-worker-report.py",
            "review_result": "collect-review.py",
        },
        "expected_report": {
            "task_id": task_id,
            "path": report_path,
        },
        "expected_review": {
            "task_id": task_id,
            "path": review_path,
        },
    }


def plan_dispatch_action(state: dict[str, Any], state_file: Path, workspace_root: Path, action: str) -> dict[str, Any]:
    if action.startswith("dispatch_stage_worker:") or action.startswith("dispatch_stage_review:"):
        prefix, phase = action.split(":", 1)
        if phase not in STAGE_PHASES:
            raise ValueError(f"Illegal stage dispatch target: {phase}")
        if state.get("current_phase") != phase:
            raise ValueError(f"Stage dispatch target does not match current_phase: {phase} != {state.get('current_phase')}")
        if state["resume_context"].get("current_execution_unit") != phase:
            raise ValueError("Stage dispatch current_execution_unit must equal phase")
        return dispatch_plan(
            state,
            state_file,
            workspace_root,
            task_scope="stage",
            phase=phase,
            execution_unit=phase,
            action_kind="dispatch_review" if prefix == "dispatch_stage_review" else "dispatch_worker",
            manifest_script="build-stage-task.py",
        )

    if action.startswith("dispatch_gen_node_worker:") or action.startswith("dispatch_gen_node_review:"):
        prefix, node_id = action.split(":", 1)
        if node_id not in GEN_NODES:
            raise ValueError(f"Illegal gen node dispatch target: {node_id}")
        phase_3 = state.get("artifacts", {}).get("phase_3", {})
        if state.get("current_phase") != "gen":
            raise ValueError(f"Gen node dispatch requires current_phase=gen: {state.get('current_phase')}")
        if phase_3.get("current_node") != node_id:
            raise ValueError(f"Gen node dispatch target does not match current_node: {node_id} != {phase_3.get('current_node')}")
        if state["resume_context"].get("current_execution_unit") != node_id:
            raise ValueError("Gen node dispatch current_execution_unit must equal current_node")
        plan = dispatch_plan(
            state,
            state_file,
            workspace_root,
            task_scope="gen_node",
            phase="gen",
            execution_unit=node_id,
            action_kind="dispatch_review" if prefix == "dispatch_gen_node_review" else "dispatch_worker",
            manifest_script="build-gen-node-task.py",
        )
        plan["expected_review"]["node_id"] = node_id
        return plan

    raise ValueError(f"Unsupported dispatch action: {action}")


def plan_script_action(state: dict[str, Any], state_file: Path, workspace_root: Path, action: str) -> dict[str, Any]:
    current_phase = state.get("current_phase")
    if action.startswith("run_preflight:"):
        phase = action.split(":", 1)[1]
        if phase != current_phase:
            raise ValueError(f"Preflight phase does not match current_phase: {phase} != {current_phase}")
        followup = "phase-handoff.py"
        post_gate_commands: list[dict[str, Any]] = []
        if phase == "gen" and state.get("phase_status", {}).get("gen") != "completed":
            followup = "advance-gen-node.py"
            post_gate_commands = [
                command(workspace_root, "advance-gen-node.py", ["--state-file", str(state_file), "--in-place"]),
            ]
        elif phase == "gen":
            post_gate_commands = [
                command(
                    workspace_root,
                    "phase-handoff.py",
                    ["--state-file", str(state_file), "--from-phase", "gen", "--to-phase", "final", "--advance-state"],
                ),
            ]
        elif phase == "final":
            followup = "register-final-artifacts.py"
            post_gate_commands = [
                command(
                    workspace_root,
                    "register-final-artifacts.py",
                    ["--state-file", str(state_file)],
                ),
            ]
        return {
            "plan_version": "1.0",
            "current_phase": current_phase,
            "current_execution_unit": state["resume_context"]["current_execution_unit"],
            "next_required_action": action,
            "required_script": state["resume_context"]["required_script"],
            "action_kind": "run_gate",
            "task_scope": "stage" if phase != "gen" else "gen_phase",
            "phase": phase,
            "execution_unit": state["resume_context"]["current_execution_unit"],
            "commands": [
                command(workspace_root, "preflight.py", ["--stage", phase, "--state-file", str(state_file)]),
            ],
            "followup": followup,
            **({"post_gate_commands": post_gate_commands} if post_gate_commands else {}),
        }
    if action.startswith("run_checkpoint:"):
        checkpoint = action.split(":", 1)[1]
        source_phase = checkpoint.split("-", 1)[0]
        if source_phase != current_phase:
            raise ValueError(f"Checkpoint phase does not match current_phase: {source_phase} != {current_phase}")
        return {
            "plan_version": "1.0",
            "current_phase": current_phase,
            "current_execution_unit": state["resume_context"]["current_execution_unit"],
            "next_required_action": action,
            "required_script": state["resume_context"]["required_script"],
            "action_kind": "run_checkpoint",
            "task_scope": "checkpoint",
            "phase": current_phase,
            "execution_unit": state["resume_context"]["current_execution_unit"],
            "pending_checkpoint": state["resume_context"]["pending_checkpoint"],
            "commands": [
                command(
                    workspace_root,
                    "phase-handoff.py",
                    ["--state-file", str(state_file), "--from-phase", source_phase, "--checkpoint", checkpoint, "--await-user-action"],
                ),
            ],
        }
    if action == "wait_for_user_action":
        return {
            "plan_version": "1.0",
            "current_phase": current_phase,
            "current_execution_unit": state["resume_context"]["current_execution_unit"],
            "next_required_action": action,
            "required_script": state["resume_context"]["required_script"],
            "action_kind": "wait_for_user",
            "task_scope": "checkpoint",
            "phase": current_phase,
            "execution_unit": state["resume_context"]["current_execution_unit"],
            "pending_checkpoint": state["resume_context"]["pending_checkpoint"],
            "allowed_actions": state.get("checkpoints", {}).get("allowed_actions", []),
            "commands": [
                command(workspace_root, "phase-handoff.py", ["--state-file", str(state_file), "--user-action", "<action>", "--advance-state"]),
            ],
        }
    if action == "archive_runtime":
        return {
            "plan_version": "1.0",
            "current_phase": current_phase,
            "current_execution_unit": state["resume_context"]["current_execution_unit"],
            "next_required_action": action,
            "required_script": state["resume_context"]["required_script"],
            "action_kind": "archive",
            "task_scope": "terminal",
            "phase": current_phase,
            "execution_unit": state["resume_context"]["current_execution_unit"],
            "commands": [
                command(workspace_root, "archive-harness-workflow.py", ["--state-file", str(state_file), "--archive-only"]),
            ],
        }
    raise ValueError(f"Unsupported script action: {action}")


def build_plan(state: dict[str, Any], state_file: Path) -> dict[str, Any]:
    """Build next action plan from resume_context and preflight results"""
    resume_context = validate_resume_context(state)
    validate_action_binding(resume_context)
    workspace_root = detect_workspace_root(state_file)

    # Load preflight-result.json to validate allowed actions
    preflight_result = load_preflight_result(workspace_root)
    if preflight_result is not None:
        allowed_actions = preflight_result.get("allowed_actions", [])
        next_action = resume_context.get("next_required_action", "")
        if next_action and next_action not in allowed_actions:
            raise ValueError(f"resume_context.next_required_action={next_action} not in preflight allowed list: {allowed_actions}")

    # Determine action based on last_review_status
    last_review_status = resume_context.get("last_review_status", "pending")
    if last_review_status in {"rework_required", "rejected"}:
        current_node = state.get("artifacts", {}).get("phase_3", {}).get("current_node")
        if state.get("current_phase") == "gen" and current_node:
            if not resume_context.get("next_required_action", "").endswith(f":{current_node}"):
                raise ValueError(f"last_review_status={last_review_status} must plan rework for current node {current_node}")
    action = resume_context["next_required_action"]
    if not action:
        raise ValueError("resume_context.next_required_action is empty, cannot plan")

    plan = None
    if action.startswith("dispatch_"):
        plan = plan_dispatch_action(state, state_file, workspace_root, action)
    else:
        plan = plan_script_action(state, state_file, workspace_root, action)

    if plan:
        plan_action = plan.get("next_required_action", "")
        if plan_action != action:
            raise ValueError(f"Planned action {plan_action} does not match resume_context.next_required_action={action}, must be unique")

    return plan


def main() -> int:
    """Generate machine-consumable next-action orchestration plan from harness-workflow-state"""
    parser = argparse.ArgumentParser(description="Generate next-action orchestration plan from harness-workflow-state")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    parser.add_argument("--output")
    args = parser.parse_args()

    state_file = Path(args.state_file).expanduser().resolve()
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
        plan = build_plan(state, state_file)
    except ValueError as exc:
        print(f"[BLOCKER] {exc}")
        return 1
    plan_error = validate_plan_schema(plan)
    if plan_error:
        print(f"[BLOCKER] Orchestration plan does not match schema: {plan_error}")
        return 1

    if args.output:
        save_json(Path(args.output), plan)
        print(f"[PASS] Generated next-action orchestration plan: {args.output}")
        return 0
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
