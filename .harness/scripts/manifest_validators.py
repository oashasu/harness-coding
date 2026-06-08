#!/usr/bin/env python3
"""Task manifest and preflight entry gate validators."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from stage_helpers import infer_stage_dispatch_role
from task_identity import derive_task_id

STAGE_MANIFEST_REQUIRED_FIELDS: frozenset[str] = frozenset({
    "manifest_version",
    "task_scope",
    "phase",
    "execution_unit",
    "institution",
    "phase_status",
    "next_required_action",
    "required_script",
    "dispatch_role",
    "review_role",
    "task_id",
    "pending_checkpoint",
    "last_review_status",
    "resume_first_prompt",
    "inputs",
    "expected_outputs",
})

GEN_NODE_MANIFEST_REQUIRED_FIELDS: frozenset[str] = frozenset({
    "manifest_version",
    "task_scope",
    "phase",
    "execution_unit",
    "node_id",
    "institution",
    "dispatch_role",
    "review_role",
    "task_id",
    "next_required_action",
    "required_script",
    "pending_checkpoint",
    "last_review_status",
    "resume_first_prompt",
    "prerequisites",
    "node_state",
    "inputs",
    "expected_outputs",
})


def validate_current_gen_node_gate(
    node_id: str,
    node_state: dict,
    next_required_action: str | None,
) -> str | None:
    """Pure validator for a gen node's gate state. Returns error message or None."""
    verification = node_state.get("verification")
    if not isinstance(verification, dict):
        return f"{node_id}缺少verification"

    review_status = verification.get("review_status")
    script_status = verification.get("script_status")
    compile_status = verification.get("compile_status")
    expected_worker_action = f"dispatch_gen_node_worker:{node_id}"
    expected_review_action = f"dispatch_gen_node_review:{node_id}"

    if next_required_action == expected_worker_action:
        if node_state.get("status") == "completed" and review_status == "approved":
            return f"{node_id}已通过review，不应再次派发worker"
    elif next_required_action == expected_review_action:
        if node_state.get("status") not in {"in_progress", "completed"}:
            return f"{node_id}处于review派发前，状态必须为in_progress或completed，当前为: {node_state.get('status')}"
        if review_status == "approved":
            return f"{node_id}已通过review，不应再次派发review"
    elif next_required_action == "run_preflight:gen":
        if review_status in {"rework_required", "rejected"}:
            return (
                f"{node_id}当前review_status={review_status}，不得执行run_preflight:gen；"
                "主编排必须按返工/solo规则处理。"
            )
        if review_status == "approved" and not str(node_state.get("last_review_report", "")).strip():
            return f"{node_id}当前review_status=approved，但last_review_report为空，禁止run_preflight:gen"
        if node_state.get("status") == "completed":
            if review_status != "approved":
                return f"{node_id}已completed，但review_status不是approved: {review_status}"
            if script_status != "passed":
                return f"{node_id}已completed，但script_status不是passed: {script_status}"
            if compile_status == "failed":
                return f"{node_id}已completed，但compile_status仍为failed"
    if compile_status == "failed" and not str(node_state.get("compile_log_path", "")).strip():
        return f"{node_id}.compile_status=failed时，compile_log_path不能为空"
    if review_status in {"approved", "rework_required", "rejected"} and not str(node_state.get("last_review_report", "")).strip():
        return f"{node_id}已有review结论，但last_review_report为空"
    return None


def validate_task_manifest_consistency(
    manifest_path: Path | None,
    stage: str,
    workdir: Path,
    data: dict,
) -> None:
    """Validate that the task manifest matches the current runtime state.

    Exits with code 1 on any inconsistency.
    """
    if manifest_path is None:
        return
    if not manifest_path.exists():
        print(f"[Blocker] task manifest不存在: {manifest_path}")
        sys.exit(1)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[Blocker] task manifest不可解析: {exc}")
        sys.exit(1)

    task_scope = manifest.get("task_scope")
    phase = manifest.get("phase")
    execution_unit = manifest.get("execution_unit")
    resume_context = data.get("resume_context", {})
    required_fields = (
        STAGE_MANIFEST_REQUIRED_FIELDS
        if task_scope == "stage"
        else GEN_NODE_MANIFEST_REQUIRED_FIELDS
        if task_scope == "gen_node"
        else set()
    )
    missing = sorted(field for field in required_fields if field not in manifest)
    if missing:
        print(f"[Blocker] task manifest缺少必填字段: {', '.join(missing)}")
        sys.exit(1)
    if phase != stage:
        print(f"[Blocker] task manifest.phase与当前stage不一致: {phase} != {stage}")
        sys.exit(1)
    if execution_unit != resume_context.get("current_execution_unit"):
        print("[Blocker] task manifest.execution_unit与resume_context.current_execution_unit不一致。")
        sys.exit(1)
    if manifest.get("next_required_action") != resume_context.get("next_required_action"):
        print("[Blocker] task manifest.next_required_action与运行态不一致。")
        sys.exit(1)
    if manifest.get("required_script") != resume_context.get("required_script"):
        print("[Blocker] task manifest.required_script与运行态不一致。")
        sys.exit(1)
    if manifest.get("last_review_status") != resume_context.get("last_review_status"):
        print("[Blocker] task manifest.last_review_status与运行态不一致。")
        sys.exit(1)
    expected_task_id = derive_task_id(
        data,
        task_scope=task_scope,
        phase=phase,
        execution_unit=execution_unit,
    )
    if manifest.get("task_id") != expected_task_id:
        print("[Blocker] task manifest.task_id与运行态不一致。")
        sys.exit(1)
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        print("[Blocker] task manifest.inputs必须为对象。")
        sys.exit(1)
    expected_session_brief = str(workdir / ".harness/state/SESSION_BRIEF.md")
    expected_handoff_dir = str(workdir / ".harness/handoff")
    if inputs.get("session_brief") != expected_session_brief:
        print("[Blocker] task manifest.inputs.session_brief与当前workdir不一致。")
        sys.exit(1)
    if inputs.get("handoff_dir") != expected_handoff_dir:
        print("[Blocker] task manifest.inputs.handoff_dir与当前workdir不一致。")
        sys.exit(1)
    if task_scope == "stage":
        if stage == "gen":
            print("[Blocker] gen阶段不得使用stage task manifest。")
            sys.exit(1)
        if execution_unit != stage:
            print("[Blocker] 阶段任务单execution_unit必须等于当前阶段。")
            sys.exit(1)
        try:
            expected_dispatch_role = infer_stage_dispatch_role(
                str(manifest.get("next_required_action") or ""), stage
            )
        except ValueError as exc:
            print(f"[Blocker] {exc}")
            sys.exit(1)
        if manifest.get("dispatch_role") != expected_dispatch_role:
            print("[Blocker] task manifest.dispatch_role与当前阶段派单动作不一致。")
            sys.exit(1)
        phase_status = data.get("phase_status", {})
        if manifest.get("phase_status") != phase_status.get(stage):
            print("[Blocker] task manifest.phase_status与运行态不一致。")
            sys.exit(1)
        if not isinstance(manifest.get("expected_outputs"), list):
            print("[Blocker] stage task manifest.expected_outputs必须为数组。")
            sys.exit(1)
        expected_handoff_map = {
            "spec": workdir / ".harness/handoff/prep-to-spec.json",
            "prove": workdir / ".harness/handoff/spec-to-prove.json",
            "final": workdir / ".harness/handoff/gen-to-final.json",
        }
        expected_handoff_file = expected_handoff_map.get(stage)
        if expected_handoff_file is not None:
            if inputs.get("handoff_file") != str(expected_handoff_file):
                print("[Blocker] task manifest.inputs.handoff_file与当前阶段上下文不一致。")
                sys.exit(1)
    elif task_scope == "gen_node":
        if stage != "gen":
            print("[Blocker] 非gen阶段不得使用gen_node task manifest。")
            sys.exit(1)
        phase_3 = data.get("artifacts", {}).get("phase_3", {})
        current_node = phase_3.get("current_node")
        nodes = phase_3.get("nodes", {})
        if manifest.get("node_id") != current_node:
            print("[Blocker] task manifest.node_id与phase_3.current_node不一致。")
            sys.exit(1)
        if execution_unit != current_node:
            print("[Blocker] task manifest.execution_unit与phase_3.current_node不一致。")
            sys.exit(1)
        node_state = nodes.get(current_node) if isinstance(nodes, dict) else None
        if not isinstance(node_state, dict):
            print("[Blocker] 运行态当前gen节点状态缺失，无法校验task manifest。")
            sys.exit(1)
        manifest_node_state = manifest.get("node_state")
        if not isinstance(manifest_node_state, dict):
            print("[Blocker] task manifest.node_state必须为对象。")
            sys.exit(1)
        for field in [
            "status",
            "verification",
            "generated_files",
            "compile_command",
            "compile_log_path",
            "failed_attempts",
            "last_error",
            "last_review_report",
        ]:
            default = [] if field == "generated_files" else "" if field in {
                "compile_command", "compile_log_path", "last_error", "last_review_report"
            } else None
            if manifest_node_state.get(field) != node_state.get(field, default):
                print(f"[Blocker] task manifest.node_state.{field}与运行态不一致。")
                sys.exit(1)
        if manifest.get("expected_outputs") != node_state.get("generated_files", []):
            print("[Blocker] gen_node task manifest.expected_outputs与节点generated_files不一致。")
            sys.exit(1)
        expected_handoff_file = workdir / ".harness/handoff/prove-to-gen.json"
        if inputs.get("handoff_file") != str(expected_handoff_file):
            print("[Blocker] gen_node task manifest.inputs.handoff_file与当前阶段上下文不一致。")
            sys.exit(1)
    else:
        print(f"[Blocker] task manifest.task_scope非法: {task_scope}")
        sys.exit(1)


def validate_preflight_entry_gate(stage: str, state_kind: str, data: dict) -> None:
    """Block run_preflight:gen if the current gen node is in a non-continuable review state."""
    if stage != "gen" or state_kind != "harness_workflow":
        return
    resume_context = data.get("resume_context", {})
    if resume_context.get("next_required_action") != "run_preflight:gen":
        return
    phase_3 = data.get("artifacts", {}).get("phase_3", {})
    current_node = phase_3.get("current_node")
    nodes = phase_3.get("nodes", {})
    if not isinstance(current_node, str) or not current_node:
        return
    node_state = nodes.get(current_node) if isinstance(nodes, dict) else None
    if not isinstance(node_state, dict):
        return
    verification = node_state.get("verification")
    if not isinstance(verification, dict):
        return
    review_status = verification.get("review_status")
    if review_status in {"rework_required", "rejected"}:
        print(
            f"[Blocker] {current_node}当前review_status={review_status}，不得执行run_preflight:gen；"
            "主编排必须按返工/solo规则处理。"
        )
        sys.exit(1)
    if review_status == "approved" and not str(node_state.get("last_review_report", "")).strip():
        print(
            f"[Blocker] {current_node}当前review_status=approved，但last_review_report为空，禁止run_preflight:gen"
        )
        sys.exit(1)
