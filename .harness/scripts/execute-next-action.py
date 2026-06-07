#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

from state_integrity import verify_state_integrity


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NEXT_ACTION_PLAN_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/next-action-plan.v1.schema.json"
NEXT_ACTION_EXECUTION_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/next-action-execution.v1.schema.json"
SAFE_EXECUTABLE_SCRIPTS = {
    "build-stage-task.py",
    "build-gen-node-task.py",
    "dispatch-worker.py",
    "preflight.py",
    "advance-gen-node.py",
    "phase-handoff.py",
    "register-final-artifacts.py",
    "archive-harness-workflow.py",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_plan_schema(plan: dict[str, Any]) -> str | None:
    if jsonschema is None:
        return None
    try:
        schema = load_json(NEXT_ACTION_PLAN_SCHEMA)
        jsonschema.validate(instance=plan, schema=schema)
    except Exception as exc:
        return str(exc)
    return None


def validate_execution_schema(result: dict[str, Any]) -> str | None:
    if jsonschema is None:
        return None
    try:
        schema = load_json(NEXT_ACTION_EXECUTION_SCHEMA)
        jsonschema.validate(instance=result, schema=schema)
    except Exception as exc:
        return str(exc)
    return None


def validate_command(command: dict[str, Any]) -> str | None:
    """Validate command script safety"""
    script = command.get("script")
    script_path = command.get("script_path")
    args = command.get("args")
    if script not in SAFE_EXECUTABLE_SCRIPTS:
        return f"execute-next-action only allows safe dispatch chain scripts: {script}"
    if not isinstance(script_path, str) or not script_path:
        return "Plan command missing script_path"
    path = Path(script_path)
    if not path.exists():
        return f"Plan command script_path does not exist: {script_path}"
    if path.name != script:
        return f"Plan command script and script_path mismatch: {script} != {path.name}"
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        return "Plan command args must be a string array"
    return None

def load_preflight_result(workspace_root: Path) -> dict[str, Any] | None:
    """Load preflight-result.json"""
    preflight_file = workspace_root / ".harness" / "output" / "preflight-result.json"
    if not preflight_file.exists():
        return None
    try:
        return load_json(preflight_file)
    except Exception:
        return None

def validate_preflight_allowed(plan: dict[str, Any], workspace_root: Path) -> str | None:
    """Validate plan action is in preflight allowed list"""
    preflight_result = load_preflight_result(workspace_root)
    if preflight_result is None:
        # Skip validation if preflight-result doesn't exist (backward compat)
        return None
    allowed_actions = preflight_result.get("allowed_actions", [])
    if not isinstance(allowed_actions, list):
        return "preflight-result.json allowed_actions must be an array"
    next_action = plan.get("next_required_action", "")
    if next_action and next_action not in allowed_actions:
        return f"Action {next_action} not in preflight allowed list: {allowed_actions}, execution blocked"
    return None


def state_file_from_args(args: list[str]) -> Path | None:
    for index, arg in enumerate(args):
        if arg == "--state-file" and index + 1 < len(args):
            return Path(args[index + 1]).expanduser().resolve()
    return None


def infer_state_file(plan: dict[str, Any]) -> Path | None:
    commands = list(plan.get("commands", [])) + list(plan.get("post_gate_commands", []))
    for command in commands:
        args = command.get("args")
        if isinstance(args, list) and all(isinstance(item, str) for item in args):
            state_file = state_file_from_args(args)
            if state_file is not None:
                return state_file
    return None


def validate_plan_binding(plan: dict[str, Any]) -> str | None:
    """Validate plan must execute the script declared in resume_context.required_script"""
    state_file = infer_state_file(plan)
    if state_file is None:
        return "next-action plan does not declare state_file, execution blocked"
    if not state_file.exists():
        return f"next-action plan references non-existent state_file: {state_file}"
    state = load_json(state_file)
    integrity_error = verify_state_integrity(state_file, state)
    if integrity_error:
        return integrity_error
    if state.get("current_phase") != plan.get("current_phase"):
        return f"next-action plan current_phase does not match runtime: {plan.get('current_phase')} != {state.get('current_phase')}"
    resume_context = state.get("resume_context")
    if not isinstance(resume_context, dict):
        return "Runtime missing resume_context, next-action plan execution blocked"
    for field in ["next_required_action", "required_script", "current_execution_unit"]:
        if resume_context.get(field) != plan.get(field if field != "current_execution_unit" else "current_execution_unit"):
            plan_field = field if field != "current_execution_unit" else "current_execution_unit"
            return f"next-action plan {plan_field} does not match runtime: {plan.get(plan_field)} != {resume_context.get(field)}"
    checkpoints = state.get("checkpoints", {})
    if checkpoints.get("awaiting_user_action") is True:
        return "Runtime still awaiting user action, next-action plan execution blocked"
    # Validate preflight result contains this action
    workspace_root = detect_workspace_root_from_state(state_file)
    preflight_error = validate_preflight_allowed(plan, workspace_root)
    if preflight_error:
        return preflight_error
    return None

def detect_workspace_root_from_state(state_file: Path) -> Path:
    """Infer workspace root from state_file"""
    resolved = state_file.resolve()
    for candidate in [resolved.parent, *resolved.parents]:
        skill_root = candidate / ".harness"
        if skill_root.exists() and (skill_root / "scripts").exists():
            return candidate
    return PROJECT_ROOT


def execute_command(command: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    """Execute script and collect output"""
    script_path = str(command["script_path"])
    args = list(command["args"])
    result = subprocess.run(
        ["python3", script_path, *args],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result


def execute_commands(commands: list[dict[str, Any]], dry_run: bool) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for command in commands:
        command_error = validate_command(command)
        if command_error:
            raise ValueError(command_error)
        if dry_run:
            results.append({"script": command["script"], "status": "DRY_RUN", "output": command.get("output", "")})
            continue
        completed = execute_command(command)
        if completed.returncode != 0:
            raise RuntimeError(
                f"{command['script']} execution failed: {completed.stdout}{completed.stderr}"
            )
        results.append({"script": command["script"], "status": "PASS", "output": command.get("output", "")})
    return results


def execute_plan(plan: dict[str, Any], dry_run: bool) -> list[dict[str, Any]]:
    action_kind = plan.get("action_kind")
    if action_kind == "wait_for_user":
        raise ValueError("execute-next-action does not execute wait_for_user plans")
    if action_kind not in {"dispatch_worker", "dispatch_review", "run_gate", "run_checkpoint", "archive"}:
        raise ValueError(f"execute-next-action does not support this plan type: {action_kind}")
    results = execute_commands(list(plan.get("commands", [])), dry_run=dry_run)
    if action_kind == "run_gate":
        post_gate_commands = plan.get("post_gate_commands", [])
        if post_gate_commands:
            results.extend(execute_commands(list(post_gate_commands), dry_run=dry_run))
    return results


def build_execution_result(plan: dict[str, Any], plan_file: Path, command_results: list[dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "execution_version": "1.0",
        "status": "PASS",
        "plan_file": str(plan_file),
        "action_kind": plan["action_kind"],
        "task_scope": plan["task_scope"],
        "phase": plan["phase"],
        "execution_unit": plan["execution_unit"],
        "dry_run": dry_run,
        "commands": command_results,
    }
    if "task_id" in plan:
        result["task_id"] = plan["task_id"]
    return result


def main() -> int:
    """Execute safe dispatch command chain from next-action orchestration plan"""
    parser = argparse.ArgumentParser(description="Execute safe dispatch command chain from next-action orchestration plan")
    parser.add_argument("--plan-file", required=True)
    parser.add_argument("--output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    plan_file = Path(args.plan_file).expanduser().resolve()
    plan = load_json(plan_file)
    schema_error = validate_plan_schema(plan)
    if schema_error:
        print(f"[BLOCKER] next-action plan does not match schema: {schema_error}")
        return 1
    binding_error = validate_plan_binding(plan)
    if binding_error:
        print(f"[BLOCKER] {binding_error}")
        return 1
    try:
        results = execute_plan(plan, dry_run=args.dry_run)
    except (ValueError, RuntimeError) as exc:
        print(f"[BLOCKER] {exc}")
        return 1
    execution_result = build_execution_result(plan, plan_file, results, args.dry_run)
    execution_error = validate_execution_schema(execution_result)
    if execution_error:
        print(f"[BLOCKER] next-action execution result does not match schema: {execution_error}")
        return 1
    if args.output:
        save_json(Path(args.output), execution_result)
        print(f"[PASS] Generated next-action execution result: {args.output}")
        return 0
    print(json.dumps(execution_result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
