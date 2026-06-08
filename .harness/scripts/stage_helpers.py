#!/usr/bin/env python3
"""Stage routing helpers — pure stateless functions used by orchestrator and validators."""
from __future__ import annotations

TERMINAL_PHASE_ACTIONS: dict[str, tuple[str, str]] = {
    "DONE": ("archive_runtime", "archive-harness-workflow.py --archive-only"),
    "TERMINATED": ("archive_runtime", "archive-harness-workflow.py --archive-only"),
}


def detect_state_kind(data: dict) -> str:
    if isinstance(data, dict) and "current_phase" in data and "phase_status" in data and "checkpoints" in data:
        return "harness_workflow"
    return "legacy"


def infer_stage_dispatch_role(next_required_action: str, phase: str) -> str:
    stage_worker_role = {
        "prep": "PrepWorkerAgent",
        "spec": "SpecWorkerAgent",
        "prove": "ProveWorkerAgent",
        "final": "FinalReviewAgent",
    }
    stage_review_role = {
        "prep": "PrepReviewAgent",
        "spec": "SpecReviewAgent",
        "prove": "ProveReviewAgent",
        "final": "FinalReviewAgent",
    }
    if next_required_action.startswith("dispatch_stage_review:"):
        return stage_review_role[phase]
    if next_required_action.startswith("dispatch_stage_worker:"):
        return stage_worker_role[phase]
    raise ValueError(f"当前next_required_action不是阶段派单动作: {next_required_action}")


def validate_resume_action_binding(
    current_phase: str,
    current_execution_unit: str | None,
    next_required_action: str | None,
    required_script: str | None,
) -> str | None:
    if not isinstance(next_required_action, str) or not next_required_action:
        return "resume_context.next_required_action不能为空。"
    required_script = required_script or ""
    if current_phase in TERMINAL_PHASE_ACTIONS:
        expected_action, expected_script = TERMINAL_PHASE_ACTIONS[current_phase]
        if next_required_action != expected_action:
            return f"{current_phase}终态next_required_action必须为{expected_action}: {next_required_action}"
        if required_script != expected_script:
            return f"{current_phase}终态required_script必须为{expected_script}: {required_script}"
        return None
    if next_required_action.startswith("run_preflight:"):
        action_stage = next_required_action.split(":", 1)[1]
        if action_stage != current_phase:
            return f"next_required_action要求preflight阶段与current_phase一致: {action_stage} != {current_phase}"
        expected_script = f"preflight.py --stage {action_stage}"
        if required_script != expected_script:
            return f"required_script应与next_required_action匹配: {required_script} != {expected_script}"
    if current_phase == "gen" and next_required_action.startswith("dispatch_gen_node_"):
        parts = next_required_action.split(":", 1)
        if len(parts) != 2 or not parts[1]:
            return f"gen阶段next_required_action缺少节点号: {next_required_action}"
        if current_execution_unit != parts[1]:
            return f"gen阶段next_required_action与current_execution_unit不一致: {parts[1]} != {current_execution_unit}"
    return None
