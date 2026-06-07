#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from task_identity import derive_task_id
from state_integrity import seal_state, verify_state_integrity

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_SCHEMA = PROJECT_ROOT / ".harness/skills/harness-workflow-skill/references/task/harness-workflow-state.schema.json"
REVIEW_RESULT_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/review-result.v1.schema.json"
REVIEW_STATUSES = {"pending", "approved", "rework_required", "rejected"}
GEN_NODE_IDS = {"G01", "G02", "G03", "G04", "G05", "G06", "G07", "G08", "G09"}


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


def validate_review_payload(payload: dict[str, Any], manifest: dict[str, Any]) -> str | None:
    if jsonschema is not None:
        try:
            schema = load_json(REVIEW_RESULT_SCHEMA)
            jsonschema.validate(instance=payload, schema=schema)
        except Exception as exc:
            return str(exc)
    else:
        required_fields = [
            "manifest_version",
            "task_id",
            "task_scope",
            "phase",
            "execution_unit",
            "review_status",
            "summary",
            "report_path",
        ]
        missing = [field for field in required_fields if field not in payload]
        if missing:
            return f"Review result missing fields: {', '.join(missing)}"
    review_status = payload.get("review_status")
    if review_status not in REVIEW_STATUSES:
        return f"review_status illegal: {review_status}"
    manifest_task_id = manifest.get("task_id")
    if manifest_task_id and payload.get("task_id") != manifest_task_id:
        return f"task_id does not match manifest: {payload.get('task_id')} != {manifest_task_id}"
    summary = payload.get("summary", "")
    if len(summary) > 500:
        return f"summary exceeds 500 char limit: {len(summary)}"
    rework_items = payload.get("rework_items", [])
    if len(rework_items) > 10:
        return f"rework_items exceeds limit 10: {len(rework_items)}"
    if review_status == "rework_required":
        if not rework_items or len(rework_items) < 1:
            return "review_status=rework_required requires at least 1 rework_item"
    scope = payload.get("task_scope")
    if scope == "stage":
        if payload.get("node_id") not in (None, ""):
            return f"stage review must not contain node_id: {payload.get('node_id')}"
    elif scope == "gen_node":
        node_id = payload.get("node_id")
        if node_id not in GEN_NODE_IDS:
            return f"node_id illegal: {node_id}"
        if payload.get("execution_unit") != node_id:
            return f"execution_unit and node_id mismatch: {payload.get('execution_unit')} != {node_id}"
    return None


def validate_dispatch_payload(dispatch: dict[str, Any], review_payload: dict[str, Any], state_file: Path) -> str | None:
    for field in ["task_id", "task_scope", "phase", "execution_unit", "task_manifest", "context_contract"]:
        if field not in dispatch:
            return f"dispatch payload missing field: {field}"
    for field in ["task_id", "task_scope", "phase", "execution_unit"]:
        if dispatch.get(field) != review_payload.get(field):
            return f"dispatch payload.{field} does not match review result: {dispatch.get(field)} != {review_payload.get(field)}"
    context_contract = dispatch.get("context_contract")
    if not isinstance(context_contract, dict):
        return "dispatch payload.context_contract must be an object"
    if context_contract.get("review_result_collector") != "collect-review.py":
        return "dispatch payload.context_contract.review_result_collector must be collect-review.py"
    if context_contract.get("worker_report_collector") != "collect-worker-report.py":
        return "dispatch payload.context_contract.worker_report_collector must be collect-worker-report.py"
    forbidden_state_writes = context_contract.get("forbidden_state_writes")
    if not isinstance(forbidden_state_writes, list) or not all(isinstance(item, str) for item in forbidden_state_writes):
        return "dispatch payload.context_contract.forbidden_state_writes must be a string array"
    normalized_forbidden_paths = {str(Path(item).expanduser().resolve()) for item in forbidden_state_writes if item.strip()}
    if str(state_file.resolve()) not in normalized_forbidden_paths:
        return "dispatch payload.context_contract.forbidden_state_writes must include state_file"
    return None


def rewrite_resume_context_for_gate(state: dict[str, Any], review_status: str, node_id: str | None = None) -> None:
    """Rewrite resume_context based on review result to ensure state contract validity."""
    phase = state.get("current_phase", "unknown")
    checkpoints = state.setdefault("checkpoints", {})

    if review_status == "approved":
        if node_id:
            state["resume_context"] = {
                "current_execution_unit": node_id,
                "next_required_action": "run_preflight:gen",
                "required_script": "preflight.py --stage gen",
                "pending_checkpoint": "NONE",
                "resume_first_prompt": "Gen node passed Review, continue gen phase flow.",
                "last_review_status": review_status,
            }
        else:
            state["resume_context"] = {
                "current_execution_unit": phase,
                "next_required_action": f"run_preflight:{phase}",
                "required_script": f"preflight.py --stage {phase}",
                "pending_checkpoint": "NONE",
                "resume_first_prompt": "Phase passed Review, prepare to advance to next phase.",
                "last_review_status": review_status,
            }
    elif review_status == "rejected":
        if node_id:
            state["resume_context"] = {
                "current_execution_unit": node_id,
                "next_required_action": "run_preflight:gen",
                "required_script": "preflight.py --stage gen",
                "pending_checkpoint": "NONE",
                "resume_first_prompt": "Gen node rejected, need to re-execute.",
                "last_review_status": review_status,
            }
        else:
            state["resume_context"] = {
                "current_execution_unit": phase,
                "next_required_action": f"run_preflight:{phase}",
                "required_script": f"preflight.py --stage {phase}",
                "pending_checkpoint": "NONE",
                "resume_first_prompt": "Phase rejected, need to re-execute.",
                "last_review_status": review_status,
            }
    else:  # rework_required
        state["resume_context"] = {
            "current_execution_unit": phase,
            "next_required_action": f"run_preflight:{phase}",
            "required_script": f"preflight.py --stage {phase}",
            "pending_checkpoint": "NONE",
            "resume_first_prompt": "Read SESSION_BRIEF, handoff package and Review report, then continue current phase rework.",
            "last_review_status": review_status,
        }
    checkpoints["awaiting_user_action"] = False
    if checkpoints.get("last_checkpoint") == "NONE":
        checkpoints["checkpoint_emitted_at"] = None


def apply_stage_review(state: dict[str, Any], payload: dict[str, Any]) -> None:
    phase = payload["phase"]
    if state.get("current_phase") != phase:
        raise ValueError(f"State phase does not match review phase: {state.get('current_phase')} != {phase}")
    expected_task_id = derive_task_id(
        state,
        task_scope="stage",
        phase=phase,
        execution_unit=phase,
    )
    if payload.get("task_id") != expected_task_id:
        raise ValueError(f"Review task_id does not match current stage task: {payload.get('task_id')} != {expected_task_id}")
    rewrite_resume_context_for_gate(state, payload["review_status"])


def apply_gen_node_review(state: dict[str, Any], payload: dict[str, Any]) -> None:
    if state.get("current_phase") != "gen":
        raise ValueError(f"Current phase is not gen: {state.get('current_phase')}")
    phase_3 = state.get("artifacts", {}).get("phase_3", {})
    current_node = phase_3.get("current_node")
    node_id = payload["node_id"]
    if current_node != node_id:
        raise ValueError(f"Current node does not match review node: {current_node} != {node_id}")
    expected_task_id = derive_task_id(
        state,
        task_scope="gen_node",
        phase="gen",
        execution_unit=node_id,
    )
    if payload.get("task_id") != expected_task_id:
        raise ValueError(f"Review task_id does not match current gen node task: {payload.get('task_id')} != {expected_task_id}")
    nodes = phase_3.get("nodes", {})
    node_state = nodes.get(node_id)
    if not isinstance(node_state, dict):
        raise ValueError(f"Missing node state: {node_id}")
    verification = node_state.get("verification")
    if not isinstance(verification, dict):
        raise ValueError(f"Node verification illegal: {node_id}")

    review_status = payload["review_status"]
    verification["review_status"] = review_status
    report_path = payload.get("report_path")
    if isinstance(report_path, str) and report_path.strip():
        node_state["last_review_report"] = report_path.strip()

    summary = str(payload.get("summary", "") or "").strip()
    if review_status in {"rework_required", "rejected"}:
        if summary:
            node_state["last_error"] = summary
    elif review_status == "approved":
        node_state["last_error"] = ""

    rewrite_resume_context_for_gate(state, review_status, node_id=node_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect review result into harness-workflow-state.")
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--dispatch-payload")
    parser.add_argument("--review-file", required=True)
    parser.add_argument("--output")
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args()

    if args.output and args.in_place:
        print("[BLOCKER] --output and --in-place cannot be used together")
        return 1

    state_file = Path(args.state_file).expanduser().resolve()
    review_file = Path(args.review_file).expanduser().resolve()
    output_file = Path(args.output).expanduser().resolve() if args.output else state_file if args.in_place else None

    state = load_json(state_file)
    integrity_error = verify_state_integrity(state_file, state)
    if integrity_error:
        print(f"[BLOCKER] {integrity_error}")
        return 1
    state_schema_error = validate_state_schema(state)
    if state_schema_error:
        print(f"[BLOCKER] Input state file does not match schema: {state_schema_error}")
        return 1

    review_payload = load_json(review_file)
    manifest = None
    dispatch_payload = None
    if args.dispatch_payload:
        dispatch_payload = load_json(Path(args.dispatch_payload).expanduser().resolve())
        dispatch_error = validate_dispatch_payload(dispatch_payload, review_payload, state_file)
        if dispatch_error:
            print(f"[BLOCKER] {dispatch_error}")
            return 1
        # Support dispatch_payload["task_manifest"] as string path or dict
        manifest_val = dispatch_payload.get("task_manifest")
        if isinstance(manifest_val, str):
            manifest_path = Path(manifest_val).expanduser().resolve()
            if not manifest_path.exists():
                print(f"[BLOCKER] task_manifest file does not exist: {manifest_path}")
                return 1
            try:
                manifest = load_json(manifest_path)
            except Exception as exc:
                print(f"[BLOCKER] task_manifest load failed: {exc}")
                return 1
        elif isinstance(manifest_val, dict):
            manifest = manifest_val
        elif manifest_val is not None:
            print(f"[BLOCKER] task_manifest type illegal: {type(manifest_val).__name__}")
            return 1

    review_error = validate_review_payload(review_payload, manifest or {})
    if review_error:
        print(f"[BLOCKER] Review result illegal: {review_error}")
        return 1

    try:
        if review_payload["task_scope"] == "stage":
            apply_stage_review(state, review_payload)
        else:
            apply_gen_node_review(state, review_payload)
    except ValueError as exc:
        print(f"[BLOCKER] {exc}")
        return 1

    state.setdefault("timestamps", {})["updated_at"] = datetime.now(timezone.utc).isoformat()
    state_schema_error = validate_state_schema(state)
    if state_schema_error:
        print(f"[BLOCKER] State file does not match schema after writeback: {state_schema_error}")
        return 1

    if output_file is not None:
        save_state_json(output_file, state, key_source_state_file=state_file)
        print(f"[PASS] Collected review result: {output_file}")
        return 0
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
