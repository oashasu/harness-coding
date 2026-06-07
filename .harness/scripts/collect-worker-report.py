#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

from task_identity import derive_task_id
from state_integrity import seal_state, verify_state_integrity


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_SCHEMA = PROJECT_ROOT / ".harness/skills/harness-workflow-skill/references/task/harness-workflow-state.schema.json"
WORKER_REPORT_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/worker-final-report.v2.schema.json"
WORKER_STATUSES = {"completed", "failed", "blocked"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_state_json(path: Path, payload: dict[str, Any], *, key_source_state_file: Path | None = None) -> None:
    try:
        save_json(path, seal_state(path, payload, key_source_state_file=key_source_state_file))
    except ValueError:
        save_json(path, payload)


def validate_state_schema(state: dict[str, Any]) -> str | None:
    if jsonschema is None:
        return None
    try:
        schema = load_json(STATE_SCHEMA)
        jsonschema.validate(instance=state, schema=schema)
    except Exception as exc:
        return str(exc)
    return None


def validate_worker_report(payload: dict[str, Any]) -> str | None:
    if jsonschema is None:
        return None
    try:
        schema = load_json(WORKER_REPORT_SCHEMA)
        jsonschema.validate(instance=payload, schema=schema)
    except Exception as exc:
        return str(exc)
    return None


def validate_manifest(manifest: dict[str, Any]) -> str | None:
    for field in ["task_scope", "phase", "execution_unit", "task_id", "inputs"]:
        if field not in manifest:
            return f"task manifest missing field: {field}"
    if manifest.get("task_scope") not in {"stage", "gen_node"}:
        return f"task manifest.task_scope illegal: {manifest.get('task_scope')}"
    return None


def validate_dispatch_payload(dispatch: dict[str, Any], manifest: dict[str, Any], state_file: Path) -> str | None:
    for field in ["task_id", "task_scope", "phase", "execution_unit", "task_manifest", "context_contract"]:
        if field not in dispatch:
            return f"dispatch payload missing field: {field}"
    for field in ["task_id", "task_scope", "phase", "execution_unit"]:
        if dispatch.get(field) != manifest.get(field):
            return f"dispatch payload.{field} does not match task manifest: {dispatch.get(field)} != {manifest.get(field)}"
    context_contract = dispatch.get("context_contract")
    if not isinstance(context_contract, dict):
        return "dispatch payload.context_contract must be an object"
    if context_contract.get("worker_report_collector") != "collect-worker-report.py":
        return "dispatch payload.context_contract.worker_report_collector must be collect-worker-report.py"
    if context_contract.get("review_result_collector") != "collect-review.py":
        return "dispatch payload.context_contract.review_result_collector must be collect-review.py"
    forbidden_state_writes = context_contract.get("forbidden_state_writes")
    if not isinstance(forbidden_state_writes, list) or not all(isinstance(item, str) for item in forbidden_state_writes):
        return "dispatch payload.context_contract.forbidden_state_writes must be a string array"
    normalized_forbidden_paths = {str(Path(item).expanduser().resolve()) for item in forbidden_state_writes if item.strip()}
    if str(state_file.resolve()) not in normalized_forbidden_paths:
        return "dispatch payload.context_contract.forbidden_state_writes must include state_file"
    schema_path = context_contract.get("worker_final_report_schema")
    if not isinstance(schema_path, str) or not schema_path.strip():
        return "dispatch payload.context_contract.worker_final_report_schema cannot be empty"
    return None


def validate_report_semantics(report: dict[str, Any], manifest: dict[str, Any]) -> str | None:
    worker_status = report.get("worker_status")
    if worker_status not in WORKER_STATUSES:
        return f"worker_status illegal: {worker_status}"
    manifest_task_id = manifest.get("task_id")
    if manifest_task_id and report.get("task_id") != manifest_task_id:
        return f"task_id does not match manifest: {report.get('task_id')} != {manifest_task_id}"
    summary = report.get("summary", "")
    if len(summary) > 500:
        return f"summary exceeds 500 char limit: {len(summary)}"
    changed_files = report.get("changed_files", [])
    if len(changed_files) > 50:
        return f"changed_files exceeds limit 50: {len(changed_files)}"
    generated_files = report.get("generated_files", [])
    if len(generated_files) > 50:
        return f"generated_files exceeds limit 50: {len(generated_files)}"
    commands = report.get("commands", [])
    if len(commands) > 20:
        return f"commands exceeds limit 20: {len(commands)}"
    review_hints = report.get("review_hints", [])
    if len(review_hints) > 10:
        return f"review_hints exceeds limit 10: {len(review_hints)}"
    script_status = report.get("script_status")
    compile_status = report.get("compile_status")
    compile_log_path = str(report.get("compile_log_path", "") or "").strip()
    if worker_status == "completed":
        if script_status != "passed":
            return f"worker_status=completed requires script_status=passed: {script_status}"
        if compile_status == "failed":
            return "worker_status=completed requires compile_status not be failed"
    if compile_status == "failed" and not compile_log_path:
        return "compile_status=failed requires compile_log_path"
    return None


def validate_alignment(state: dict[str, Any], manifest: dict[str, Any], report: dict[str, Any]) -> str | None:
    task_scope = manifest.get("task_scope")
    phase = manifest.get("phase")
    execution_unit = manifest.get("execution_unit")
    expected_task_id = derive_task_id(state, task_scope=task_scope, phase=phase, execution_unit=execution_unit)
    if report.get("task_id") != expected_task_id:
        return f"task_id does not match current state: {report.get('task_id')} != {expected_task_id}"
    if task_scope not in {"stage", "gen_node"}:
        return f"task_scope illegal: {task_scope}"
    if task_scope != report.get("task_scope"):
        return f"task_scope mismatch: {task_scope} != {report.get('task_scope')}"
    if phase != report.get("phase"):
        return f"phase mismatch: {phase} != {report.get('phase')}"
    if execution_unit != report.get("execution_unit"):
        return f"execution_unit mismatch: {execution_unit} != {report.get('execution_unit')}"
    if task_scope == "gen_node":
        node_id = report.get("node_id")
        if node_id:
            valid_node_ids = {"G01", "G02", "G03", "G04", "G05", "G06", "G07", "G08", "G09"}
            if node_id not in valid_node_ids:
                return f"node_id illegal: {node_id}"
            if node_id != execution_unit:
                return f"node_id and execution_unit mismatch: {node_id} != {execution_unit}"
    return None


def validate_required_reports(report: dict[str, Any], dispatch: dict[str, Any]) -> str | None:
    """Validate worker report delivers files declared in required_reports"""
    if report.get("worker_status") != "completed":
        return None

    required_reports = dispatch.get("required_reports", [])
    if not required_reports:
        return None

    generated_files = report.get("generated_files", [])
    if not isinstance(generated_files, list):
        generated_files = []

    missing = []
    for req in required_reports:
        req_name = Path(req).name if isinstance(req, str) else str(req)
        found = any(req_name in (Path(f).name if isinstance(f, str) else str(f)) for f in generated_files)
        if not found:
            missing.append(req_name)

    if missing:
        return f"Worker report missing files declared in required_reports: {', '.join(missing)}"
    return None

def rewrite_stage_resume_context(state: dict[str, Any], report: dict[str, Any]) -> None:
    phase = report["phase"]
    status = report["worker_status"]
    next_required_action = "dispatch_review" if status == "completed" else f"dispatch_worker:{phase}"
    prompt = (
        "Read SESSION_BRIEF, handoff package and Worker final report, then execute current phase Review."
        if status == "completed"
        else "Read SESSION_BRIEF, handoff package and previous Worker final report, then continue current phase rework."
    )
    state["resume_context"] = {
        "current_execution_unit": phase,
        "next_required_action": next_required_action,
        "required_script": "build-stage-task.py",
        "pending_checkpoint": "NONE",
        "resume_first_prompt": prompt,
        "last_review_status": "pending",
    }


def rewrite_gen_resume_context(state: dict[str, Any], report: dict[str, Any]) -> None:
    phase_3 = state.get("artifacts", {}).get("phase_3", {})
    current_node = phase_3.get("current_node")
    node_state = phase_3.get("nodes", {}).get(current_node, {})
    status = report["worker_status"]
    next_required_action = (
        f"dispatch_gen_node_review:{current_node}"
        if status == "completed"
        else f"dispatch_gen_node_worker:{current_node}"
    )
    prompt = (
        "Read SESSION_BRIEF, handoff package and Worker final report, then execute current gen node Review."
        if status == "completed"
        else "Read SESSION_BRIEF, handoff package and previous Worker final report, then continue current gen node rework."
    )
    node_state["generated_files"] = list(report.get("generated_files", []))
    node_state["compile_command"] = report.get("compile_command", "")
    node_state["compile_log_path"] = report.get("compile_log_path", "")
    node_state["last_error"] = "" if status == "completed" else report.get("summary", "")
    node_state["artifacts"] = [report.get("report_path", "")] if report.get("report_path") else []
    node_state["status"] = "completed" if status == "completed" else "in_progress"
    verification = node_state.setdefault("verification", {})
    verification["script_status"] = report.get("script_status", "not_run")
    verification["compile_status"] = report.get("compile_status", "not_run")
    verification["review_status"] = "pending"
    if status != "completed":
        node_state["failed_attempts"] = int(node_state.get("failed_attempts", 0) or 0) + 1
    state["resume_context"] = {
        "current_execution_unit": current_node,
        "next_required_action": next_required_action,
        "required_script": "build-gen-node-task.py",
        "pending_checkpoint": "NONE",
        "resume_first_prompt": prompt,
        "last_review_status": "pending",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Worker final report and advance to Review or rework")
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--task-manifest", required=True)
    parser.add_argument("--dispatch-payload")
    parser.add_argument("--worker-report-file", help="Worker final report file path (recommended)")
    parser.add_argument("--worker-report", help="Worker final report file path (compat alias)")
    parser.add_argument("--output")
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args()

    if args.output and args.in_place:
        print("[BLOCKER] --output and --in-place cannot be used together")
        return 1

    worker_report_arg = args.worker_report_file or args.worker_report
    if not worker_report_arg:
        print("[BLOCKER] Must specify --worker-report-file or --worker-report")
        return 1

    state_file = Path(args.state_file).expanduser().resolve()
    output_file = Path(args.output).expanduser().resolve() if args.output else state_file if args.in_place else None
    state = load_json(state_file)
    integrity_error = verify_state_integrity(state_file, state)
    if integrity_error:
        print(f"[BLOCKER] {integrity_error}")
        return 1
    manifest = load_json(Path(args.task_manifest).expanduser().resolve())
    dispatch = load_json(Path(args.dispatch_payload).expanduser().resolve()) if args.dispatch_payload else None
    report_path = Path(worker_report_arg).expanduser().resolve()
    report = load_json(report_path)

    state_error = validate_state_schema(state)
    if state_error:
        print(f"[BLOCKER] Input state file does not match schema: {state_error}")
        return 1
    manifest_error = validate_manifest(manifest)
    if manifest_error:
        print(f"[BLOCKER] {manifest_error}")
        return 1
    if dispatch is not None:
        dispatch_error = validate_dispatch_payload(dispatch, manifest, state_file)
        if dispatch_error:
            print(f"[BLOCKER] {dispatch_error}")
            return 1
    required_reports_error = validate_required_reports(report, dispatch) if dispatch else None
    if required_reports_error:
        print(f"[BLOCKER] {required_reports_error}")
        return 1

    report_error = validate_worker_report(report)
    if report_error:
        print(f"[BLOCKER] Worker final report illegal: {report_error}")
        return 1
    report_semantic_error = validate_report_semantics(report, manifest)
    if report_semantic_error:
        print(f"[BLOCKER] Worker final report semantic error: {report_semantic_error}")
        return 1
    report["report_path"] = str(report_path)
    alignment_error = validate_alignment(state, manifest, report)
    if alignment_error:
        print(f"[BLOCKER] {alignment_error}")
        return 1

    if manifest["task_scope"] == "stage":
        rewrite_stage_resume_context(state, report)
    else:
        rewrite_gen_resume_context(state, report)

    state.setdefault("timestamps", {})["updated_at"] = datetime.now(timezone.utc).isoformat()
    final_error = validate_state_schema(state)
    if final_error:
        print(f"[BLOCKER] State file does not match schema after writeback: {final_error}")
        return 1

    if output_file is not None:
        save_state_json(output_file, state, key_source_state_file=state_file)
        print(f"[PASS] Collected Worker final report: {output_file}")
        return 0
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
