#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from final_report_contract import validate_final_report
from prove_routing_compat import normalize_legacy_prove_routing_payload
from state_integrity import seal_state, verify_state_integrity, resolve_state_file

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_FILE = resolve_state_file()
DISPATCH_DIR = PROJECT_ROOT / ".harness/dispatch"
SESSION_BRIEF_FILE = PROJECT_ROOT / ".harness/state/SESSION_BRIEF.md"
PHASE_ORDER = ["prep", "spec", "prove", "gen", "final"]
STATE_SCHEMA = PROJECT_ROOT / ".harness/schemas/harness-state.schema.json"
SPEC_BUSINESS_FACTS_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/spec-business-facts.v1.schema.json"
PROVE_ISSUE_ROUTING_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/prove-issue-routing.v1.schema.json"
GEN_LAYER_NODE_MAP = {
    "pojo_config_dto": ["G01", "G02", "G03"],
    "dependency_provider": ["G04"],
    "adapter_notify": ["G05", "G06"],
    "admin_sql_i18n": ["G07", "G08", "G09"],
}
GEN_NODE_PREREQS = {
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
CHECKPOINT_ACTIONS = {
    "spec-ok": [
        "continue_prove_resolvable",
        "continue_prove_with_risk",
        "confirm_human_required",
        "revise_spec",
        "terminate_workflow",
    ],
    "prove-ok": [
        "authorize_gen",
        "revise_proof",
        "terminate_workflow",
    ],
    "final-ok": [
        "accept_final",
        "return_to_gen",
        "terminate_workflow",
    ],
}
CHECKPOINT_CHOICES = ["spec-ok", "prove-ok", "final-ok"]
ADVANCE_ACTIONS = {
    "spec": {"continue_prove_resolvable", "continue_prove_with_risk"},
    "prove": {"authorize_gen"},
    "final": {"accept_final"},
}
CHECKPOINT_PHASE_MAP = {
    "spec-ok": "spec",
    "prove-ok": "prove",
    "final-ok": "final",
}
TERMINAL_PHASE_ACTIONS = {
    "DONE": ("archive_runtime", "archive-harness-workflow.py --archive-only"),
    "TERMINATED": ("archive_runtime", "archive-harness-workflow.py --archive-only"),
}


def validate_resume_action_binding(
    current_phase: str,
    current_execution_unit: str | None,
    next_required_action: str | None,
    required_script: str | None,
) -> str | None:
    if not isinstance(next_required_action, str) or not next_required_action:
        return "resume_context.next_required_action不能为空"
    required_script = required_script or ""
    if current_phase in TERMINAL_PHASE_ACTIONS:
        expected_action, expected_script = TERMINAL_PHASE_ACTIONS[current_phase]
        if next_required_action != expected_action:
            return (
                f"{current_phase}终态next_required_action必须为{expected_action}: "
                f"{next_required_action}"
            )
        if required_script != expected_script:
            return (
                f"{current_phase}终态required_script必须为{expected_script}: "
                f"{required_script}"
            )
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


def refresh_state_integrity(state_file: Path, state: dict[str, Any]) -> dict[str, Any]:
    try:
        return seal_state(state_file, state, key_source_state_file=state_file)
    except ValueError:
        refreshed = json.loads(json.dumps(state))
        refreshed.pop("integrity", None)
        return refreshed


def workspace_root_for(state_file: Path) -> Path:
    return state_file.resolve().parents[2]


def dispatch_dir_for(state_file: Path) -> Path:
    return workspace_root_for(state_file) / ".harness/dispatch"


def session_brief_file_for(state_file: Path) -> Path:
    return workspace_root_for(state_file) / ".harness/state/SESSION_BRIEF.md"


def next_phase_for(current_phase: str) -> str:
    if current_phase not in PHASE_ORDER:
        raise ValueError(f"不支持的阶段:{current_phase}")
    index = PHASE_ORDER.index(current_phase)
    if index + 1 >= len(PHASE_ORDER):
        return "DONE"
    return PHASE_ORDER[index + 1]


def expected_artifacts(state: dict[str, Any], source_phase: str) -> list[str]:
    task_id = state.get("task", {}).get("id", "")
    artifacts = state.get("artifacts", {})
    if source_phase == "prep":
        return list(artifacts.get("phase_1", {}).get("outputs", []))
    if source_phase == "spec":
        return [f".harness/output/spec/{task_id}/spec-business-facts-{task_id}.json"]
    if source_phase == "prove":
        return [f".harness/output/prove/{task_id}/prove-issue-routing-{task_id}.json"]
    if source_phase == "gen":
        layers = artifacts.get("phase_3", {}).get("layers", {})
        output: list[str] = []
        for layer_state in layers.values():
            if isinstance(layer_state, dict):
                output.extend(layer_state.get("generated_files", []))
        return output
    return []


def proof_file_is_ready(state: dict[str, Any], workspace_root: Path) -> bool:
    proof_file = state.get("artifacts", {}).get("phase_2", {}).get("proof_file")
    return isinstance(proof_file, str) and proof_file.strip() and (workspace_root / proof_file).exists()


def audit_report_is_ready(state: dict[str, Any], workspace_root: Path) -> bool:
    report_validation = validate_final_report(workspace_root, state)
    return report_validation.ok


def final_gate_is_ready(state: dict[str, Any], workspace_root: Path) -> bool:
    phase_status = state.get("phase_status", {})
    phase_4 = state.get("artifacts", {}).get("phase_4", {})
    report_validation = validate_final_report(workspace_root, state)
    return (
        phase_status.get("gen") == "completed"
        and report_validation.ok
        and report_validation.result == "accept"
        and report_validation.critical == 0
        and report_validation.high == 0
        and phase_4.get("p0_scan_status") == "passed"
        and phase_4.get("final_compile_status") == "passed"
        and not validate_gen_node_completion(state)
    )


def validate_gen_node_completion(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    phase_3 = state.get("artifacts", {}).get("phase_3", {})
    layers = phase_3.get("layers", {})
    nodes = phase_3.get("nodes", {})
    current_node = phase_3.get("current_node")
    if not isinstance(nodes, dict):
        return ["phase_3.nodes缺失或非法"]
    if current_node not in {None, ""}:
        current_node_state = nodes.get(current_node)
        if not isinstance(current_node_state, dict):
            errors.append(f"phase_3.current_node未在nodes中注册: {current_node}")
        elif current_node_state.get("status") != "completed":
            errors.append(f"gen完成态下current_node必须已completed: {current_node}")
    for node_id, prereqs in GEN_NODE_PREREQS.items():
        node_state = nodes.get(node_id)
        if not isinstance(node_state, dict):
            errors.append(f"缺少节点状态: {node_id}")
            continue
        if node_state.get("status") != "completed":
            errors.append(f"节点未完成: {node_id}")
            continue
        unmet = [
            dep for dep in prereqs
            if not isinstance(nodes.get(dep), dict) or nodes.get(dep, {}).get("status") != "completed"
        ]
        if unmet:
            errors.append(f"{node_id}前置节点未完成: {', '.join(unmet)}")
        verification = node_state.get("verification")
        if not isinstance(verification, dict):
            errors.append(f"{node_id}缺少verification")
            continue
        if verification.get("review_status") != "approved":
            errors.append(f"{node_id}.verification.review_status必须为approved")
        if verification.get("script_status") != "passed":
            errors.append(f"{node_id}.verification.script_status必须为passed")
        if verification.get("compile_status") != "passed":
            errors.append(f"{node_id}.verification.compile_status必须为passed，当前为{verification.get('compile_status')}")
    for layer_name, required_nodes in GEN_LAYER_NODE_MAP.items():
        layer_state = layers.get(layer_name)
        if not isinstance(layer_state, dict):
            errors.append(f"缺少gen层状态: {layer_name}")
            continue
        if layer_state.get("status") != "completed":
            errors.append(f"gen层未完成: {layer_name}")
            continue
        missing_completed = [
            node_id for node_id in required_nodes
            if not isinstance(nodes.get(node_id), dict) or nodes.get(node_id, {}).get("status") != "completed"
        ]
        if missing_completed:
            errors.append(f"{layer_name}标记completed，但节点未完成: {', '.join(missing_completed)}")
    return errors


def validate_artifact_schema(artifact_path: Path, schema_path: Path) -> str | None:
    if jsonschema is None:
        return "jsonschema依赖不可用，无法校验正式产物Schema"
    try:
        payload = load_json(artifact_path)
        if schema_path == PROVE_ISSUE_ROUTING_SCHEMA:
            payload = normalize_legacy_prove_routing_payload(payload)
    except Exception as exc:
        return f"正式产物不是合法JSON:{artifact_path}: {exc}"
    try:
        schema = load_json(schema_path)
    except Exception as exc:
        return f"Schema不可解析:{schema_path}: {exc}"
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except Exception as exc:
        return f"正式产物不符合Schema:{artifact_path}: {exc}"
    return None


def validate_state_schema(state_file: Path, state: dict[str, Any]) -> str | None:
    if jsonschema is None:
        return "jsonschema依赖不可用，无法校验状态Schema"
    try:
        schema = load_json(STATE_SCHEMA)
    except Exception as exc:
        return f"状态Schema不可解析:{STATE_SCHEMA}: {exc}"
    try:
        jsonschema.validate(instance=state, schema=schema)
    except Exception as exc:
        return f"状态文件不符合Schema: {exc}"
    integrity_error = verify_state_integrity(state_file, state)
    if integrity_error:
        return integrity_error
    return None


def validate_transition_control_plane(state: dict[str, Any], source_phase: str) -> list[str]:
    errors: list[str] = []
    current_phase = state.get("current_phase")
    if current_phase != source_phase:
        errors.append(f"状态漂移: current_phase={current_phase}，但handoff来源阶段为{source_phase}")
        return errors

    resume_context = state.get("resume_context")
    if not isinstance(resume_context, dict):
        errors.append("缺少resume_context，禁止直接handoff")
        return errors

    last_review_status = resume_context.get("last_review_status")
    if last_review_status not in {"pending", "approved", "rework_required", "rejected"}:
        errors.append(f"resume_context.last_review_status非法: {last_review_status}")

    pending_checkpoint = resume_context.get("pending_checkpoint")
    next_required_action = resume_context.get("next_required_action")
    current_execution_unit = resume_context.get("current_execution_unit")
    required_script = resume_context.get("required_script")
    checkpoints = state.get("checkpoints", {})
    checkpoint_emitted_at = checkpoints.get("checkpoint_emitted_at")
    if checkpoint_emitted_at is not None and not isinstance(checkpoint_emitted_at, str):
        errors.append(f"checkpoints.checkpoint_emitted_at类型非法: {type(checkpoint_emitted_at).__name__}")
    if checkpoints.get("awaiting_user_action") is True:
        if pending_checkpoint != checkpoints.get("last_checkpoint"):
            errors.append("awaiting_user_action=true时，resume_context.pending_checkpoint必须等于last_checkpoint")
        if next_required_action != "wait_for_user_action":
            errors.append("awaiting_user_action=true时，resume_context.next_required_action必须为wait_for_user_action")
        if required_script != "phase-handoff.py --user-action <action>":
            errors.append("awaiting_user_action=true时，resume_context.required_script必须为phase-handoff.py --user-action <action>")
        if checkpoints.get("last_checkpoint") != "NONE" and not checkpoint_emitted_at:
            errors.append("awaiting_user_action=true且last_checkpoint!=NONE时，checkpoint_emitted_at不能为空")
    else:
        if pending_checkpoint != "NONE":
            errors.append("非等待态时，resume_context.pending_checkpoint必须为NONE")
        if checkpoints.get("last_checkpoint") == "NONE" and checkpoint_emitted_at not in {None, ""}:
            errors.append("last_checkpoint=NONE时，checkpoint_emitted_at必须为空")

    if source_phase == "gen":
        phase_3 = state.get("artifacts", {}).get("phase_3", {})
        current_node = phase_3.get("current_node")
        nodes = phase_3.get("nodes", {})
        if current_node not in {None, ""}:
            if not isinstance(current_node, str) or not current_node:
                errors.append("gen阶段phase_3.current_node必须为空或非空字符串")
            elif not isinstance(nodes, dict) or current_node not in nodes:
                errors.append(f"gen阶段current_node未在phase_3.nodes中注册: {current_node}")
            elif current_execution_unit != current_node:
                errors.append("gen阶段resume_context.current_execution_unit必须与phase_3.current_node一致")
            else:
                node_state = nodes.get(current_node, {})
                if isinstance(node_state, dict):
                    verification = node_state.get("verification")
                    if isinstance(verification, dict):
                        review_status = verification.get("review_status")
                        if review_status != last_review_status:
                            errors.append("gen阶段resume_context.last_review_status必须与当前节点verification.review_status一致")
                        if review_status in {"approved", "rework_required", "rejected"} and not str(node_state.get("last_review_report", "")).strip():
                            errors.append("当前gen节点已有review结论，但last_review_report为空")
                        if verification.get("compile_status") == "failed" and not str(node_state.get("compile_log_path", "")).strip():
                            errors.append("当前gen节点compile_status=failed时，compile_log_path不能为空")
        elif current_execution_unit != "gen":
            errors.append("gen阶段未绑定current_node时，resume_context.current_execution_unit必须为gen")
    elif current_execution_unit != source_phase:
        errors.append("非gen阶段resume_context.current_execution_unit必须与current_phase一致")

    action_binding_error = validate_resume_action_binding(
        source_phase,
        current_execution_unit,
        next_required_action,
        required_script,
    )
    if action_binding_error:
        errors.append(action_binding_error)

    return errors


def validate_handoff(
    state: dict[str, Any],
    source_phase: str,
    target_phase: str,
    state_file: Path,
) -> list[str]:
    """校验当前阶段所有门禁已通过，成功后才允许推进状态"""
    errors: list[str] = []
    state_schema_error = validate_state_schema(state_file, state)
    if state_schema_error:
        errors.append(state_schema_error)
        return errors
    errors.extend(validate_transition_control_plane(state, source_phase))
    phase_status = state.get("phase_status", {})
    checkpoints = state.get("checkpoints", {})
    gate_context = checkpoints.get("gate_context", {})
    questions = state.get("questions", {})
    open_questions = questions.get("open", [])
    phase_2 = state.get("artifacts", {}).get("phase_2", {})
    if phase_status.get(source_phase) != "completed":
        errors.append(f"{source_phase}未完成，不能handoff")
    expected_target = next_phase_for(source_phase)
    if target_phase != expected_target:
        errors.append(f"{source_phase}后继阶段应为{expected_target}，收到{target_phase}")
    if checkpoints.get("awaiting_user_action") is True:
        errors.append("awaiting_user_action=true，禁止handoff推进阶段")
    if any(
        isinstance(item, dict)
        and item.get("routing") == "human_required"
        and item.get("status") == "pending"
        for item in open_questions
    ):
        errors.append("存在未决human_required问题，禁止handoff推进阶段")
    artifact_root = workspace_root_for(state_file)
    if source_phase == "prep":
        phase_1 = state.get("artifacts", {}).get("phase_1", {})
        outputs = phase_1.get("outputs", [])
        if phase_1.get("spec_ready") is not True:
            errors.append("prep→spec前phase_1.spec_ready必须为true")
        if not any(isinstance(path, str) and "prep-facts-" in path for path in outputs):
            errors.append("prep→spec前必须存在prep-facts-*产物")
        if not any(isinstance(path, str) and "prep-evidence-" in path for path in outputs):
            errors.append("prep→spec前必须存在prep-evidence-*产物")
    if source_phase == "spec" and checkpoints.get("last_checkpoint") != "spec-ok":
        errors.append("spec阶段handoff前必须达到spec-ok")
    if source_phase == "prove" and checkpoints.get("last_checkpoint") != "prove-ok":
        errors.append("prove阶段handoff前必须达到prove-ok")
    if source_phase == "prove":
        if gate_context.get("req_validation_passed") is not True:
            errors.append("prove阶段handoff前req_validation_passed必须为true")
        if gate_context.get("spec_validation_passed") is not True:
            errors.append("prove阶段handoff前spec_validation_passed必须为true")
        if phase_2.get("allow_codegen") not in {"YES", "YES_WITH_WARNING"}:
            errors.append(f"prove阶段handoff前allow_codegen非法: {phase_2.get('allow_codegen')}")
        if not proof_file_is_ready(state, artifact_root):
            errors.append("prove阶段handoff前proof_file必须存在且可读")
    if source_phase == "gen":
        # 校验artifacts.phase_3.nodes所有节点verification三态
        errors.extend(validate_gen_node_completion(state))
        # 确保所有节点verification状态符合契约
        phase_3_nodes = state.get("artifacts", {}).get("phase_3", {}).get("nodes", {})
        if isinstance(phase_3_nodes, dict):
            for node_id in GEN_NODE_PREREQS.keys():
                node_state = phase_3_nodes.get(node_id)
                if isinstance(node_state, dict):
                    verification = node_state.get("verification")
                    if isinstance(verification, dict):
                        if verification.get("review_status") != "approved":
                            errors.append(f"gen阶段handoff前{node_id}.verification.review_status必须为approved")
                        if verification.get("script_status") != "passed":
                            errors.append(f"gen阶段handoff前{node_id}.verification.script_status必须为passed")
                        if verification.get("compile_status") != "passed":
                            errors.append(f"gen阶段handoff前{node_id}.verification.compile_status必须为passed")
    if source_phase == "final":
        if checkpoints.get("last_checkpoint") != "final-ok":
            errors.append("final阶段handoff前必须达到final-ok")
        if not final_gate_is_ready(state, artifact_root):
            errors.append("final阶段handoff前最终验收门禁未通过")
    for rel_path in expected_artifacts(state, source_phase):
        artifact_path = artifact_root / rel_path
        if not artifact_path.exists():
            errors.append(f"缺少正式产物:{rel_path}")
            continue
        if source_phase == "spec":
            schema_error = validate_artifact_schema(artifact_path, SPEC_BUSINESS_FACTS_SCHEMA)
            if schema_error:
                errors.append(schema_error)
        if source_phase == "prove":
            schema_error = validate_artifact_schema(artifact_path, PROVE_ISSUE_ROUTING_SCHEMA)
            if schema_error:
                errors.append(schema_error)
    return errors


def consume_user_action(state: dict[str, Any], user_action: str) -> str | None:
    checkpoints = state.get("checkpoints", {})
    resume_context = state.get("resume_context")
    if checkpoints.get("awaiting_user_action") is not True:
        return "当前状态未处于等待用户动作，不能消费用户编号动作。"
    allowed_actions = checkpoints.get("allowed_actions", [])
    if user_action not in allowed_actions:
        return f"用户动作{user_action}不在allowed_actions中: {allowed_actions}"
    checkpoints["awaiting_user_action"] = False
    checkpoints["allowed_actions"] = []
    checkpoints["checkpoint_emitted_at"] = None
    phase_status = state.setdefault("phase_status", {})
    if user_action in {"confirm_human_required", "revise_spec"}:
        checkpoints["last_checkpoint"] = "NONE"
        state["current_phase"] = "spec"
        phase_status["spec"] = "in_progress"
    elif user_action == "revise_proof":
        checkpoints["last_checkpoint"] = "NONE"
        state["current_phase"] = "prove"
        phase_status["prove"] = "in_progress"
    elif user_action == "return_to_gen":
        checkpoints["last_checkpoint"] = "NONE"
        state["current_phase"] = "gen"
        phase_status["gen"] = "in_progress"
    elif user_action == "terminate_workflow":
        state["current_phase"] = "TERMINATED"
    if isinstance(resume_context, dict):
        resume_context["pending_checkpoint"] = "NONE"
    if user_action == "terminate_workflow":
        update_resume_context(
            state,
            next_required_action="archive_runtime",
            required_script="archive-harness-workflow.py --archive-only",
            pending_checkpoint="NONE",
            source_phase="TERMINATED",
            target_phase="TERMINATED",
            last_review_status="pending",
        )
    state.setdefault("timestamps", {})["updated_at"] = datetime.now(timezone.utc).isoformat()
    return None


def default_resume_first_prompt(
    state: dict[str, Any],
    source_phase: str,
    target_phase: str,
    checkpoint: str | None,
) -> str:
    current_phase = str(state.get("current_phase", "unknown"))
    if current_phase in TERMINAL_PHASE_ACTIONS:
        return "当前工作流已结束，禁止继续阶段推进；如需收口，请归档当前运行态。"
    if checkpoint and state.get("checkpoints", {}).get("awaiting_user_action") is True:
        return (
            f"先读取SESSION_BRIEF和状态文件，确认当前等待{checkpoint}授权；"
            "未收到明确编号动作前，不得推进下一阶段。"
        )
    if source_phase == "gen":
        return "先读取SESSION_BRIEF和状态文件，确认当前gen层状态与dispatch包，再决定是否继续执行当前节点。"
    return (
        f"先读取SESSION_BRIEF和状态文件，先跑当前阶段preflight，再根据dispatch包进入{target_phase}。"
    )


def infer_execution_unit(state: dict[str, Any]) -> str:
    if state.get("current_phase") == "gen":
        phase_3 = state.get("artifacts", {}).get("phase_3", {})
        current_node = phase_3.get("current_node")
        if isinstance(current_node, str) and current_node:
            return current_node
    return str(state.get("current_phase", "unknown"))


def build_context_package(
    state_file: Path,
    state: dict[str, Any],
    source_phase: str,
    target_phase: str,
    checkpoint: str | None,
) -> dict[str, Any]:
    questions = state.get("questions", {})
    checkpoints = state.get("checkpoints", {})
    gate_context = checkpoints.get("gate_context", {})
    task_id = state.get("task", {}).get("id", "")
    now = datetime.now(timezone.utc).isoformat()
    resume_first_prompt = default_resume_first_prompt(state, source_phase, target_phase, checkpoint)
    try:
        state_file_ref = str(state_file.relative_to(PROJECT_ROOT))
    except ValueError:
        state_file_ref = str(state_file)
    return {
        "context_package": {
            "version": "1.0",
            "source_phase": source_phase,
            "target_phase": target_phase,
            "created_at": now,
            "artifacts": {
                "state_file": state_file_ref,
                "required_artifacts": expected_artifacts(state, source_phase),
            },
            "context_summary": {
                "task_id": task_id,
                "task_mode": state.get("task", {}).get("mode", ""),
                "current_phase": state.get("current_phase"),
                "last_checkpoint": checkpoints.get("last_checkpoint"),
                "awaiting_user_action": checkpoints.get("awaiting_user_action"),
                "allowed_actions": checkpoints.get("allowed_actions", []),
                "open_questions": len(questions.get("open", [])),
                "resolved_questions": len(questions.get("resolved", [])),
                "req_validation_passed": gate_context.get("req_validation_passed"),
                "spec_validation_passed": gate_context.get("spec_validation_passed"),
            },
            "resume_first_prompt": resume_first_prompt,
            "handoff_token": f"{source_phase}-{target_phase}-{task_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        }
    }


def update_checkpoint_state(
    state: dict[str, Any],
    checkpoint: str | None,
    await_user_action: bool,
    allowed_actions: list[str],
) -> None:
    checkpoints = state.setdefault("checkpoints", {})
    if checkpoint:
        checkpoints["last_checkpoint"] = checkpoint
        checkpoints["checkpoint_emitted_at"] = datetime.now(timezone.utc).isoformat()
    elif checkpoints.get("last_checkpoint") == "NONE":
        checkpoints["checkpoint_emitted_at"] = None
    checkpoints["awaiting_user_action"] = await_user_action
    checkpoints["allowed_actions"] = allowed_actions
    if not await_user_action and checkpoints.get("last_checkpoint") == "NONE":
        checkpoints["checkpoint_emitted_at"] = None
    state.setdefault("timestamps", {})["updated_at"] = datetime.now(timezone.utc).isoformat()


def update_resume_context(
    state: dict[str, Any],
    *,
    next_required_action: str,
    required_script: str,
    pending_checkpoint: str,
    source_phase: str,
    target_phase: str,
    last_review_status: str = "pending",
) -> None:
    current_phase = str(state.get("current_phase", "unknown"))
    if current_phase in TERMINAL_PHASE_ACTIONS:
        next_required_action, required_script = TERMINAL_PHASE_ACTIONS[current_phase]
    state["resume_context"] = {
        "current_execution_unit": infer_execution_unit(state),
        "next_required_action": next_required_action,
        "required_script": required_script,
        "pending_checkpoint": pending_checkpoint,
        "resume_first_prompt": default_resume_first_prompt(
            state,
            source_phase,
            target_phase,
            pending_checkpoint,
        ),
        "last_review_status": last_review_status,
    }
    state.setdefault("timestamps", {})["updated_at"] = datetime.now(timezone.utc).isoformat()


def derive_allowed_actions(state: dict[str, Any], checkpoint: str, workspace_root: Path) -> list[str]:
    checkpoints = state.get("checkpoints", {})
    gate_context = checkpoints.get("gate_context", {})
    phase_2 = state.get("artifacts", {}).get("phase_2", {})
    actions = list(CHECKPOINT_ACTIONS.get(checkpoint, []))
    if checkpoint == "spec-ok":
        if gate_context.get("human_required_open", 0) > 0 or phase_2.get("blockers"):
            actions = [a for a in actions if a not in {"continue_prove_resolvable", "continue_prove_with_risk"}]
        elif gate_context.get("prove_resolvable_open", 0) <= 0 and gate_context.get("prove_with_risk_open", 0) <= 0:
            actions = [a for a in actions if a != "continue_prove_with_risk"]
        if gate_context.get("prove_with_risk_open", 0) <= 0:
            actions = [a for a in actions if a != "continue_prove_with_risk"]
    elif checkpoint == "prove-ok":
        prove_with_risk_unlogged = gate_context.get("prove_with_risk_unlogged_count")
        prove_with_risk_open = gate_context.get("prove_with_risk_open", 0)
        prove_with_risk_blocked = (
            (isinstance(prove_with_risk_unlogged, int) and prove_with_risk_unlogged > 0)
            or (prove_with_risk_unlogged is None and prove_with_risk_open > 0)
        )
        if (
            phase_2.get("allow_codegen") not in {"YES", "YES_WITH_WARNING"}
            or phase_2.get("blockers")
            or gate_context.get("human_required_open", 0) > 0
            or not proof_file_is_ready(state, workspace_root)
            or prove_with_risk_blocked
        ):
            actions = [a for a in actions if a != "authorize_gen"]
    elif checkpoint == "final-ok":
        if not final_gate_is_ready(state, workspace_root):
            actions = [a for a in actions if a != "accept_final"]
    return actions


def write_session_brief(
    brief_file: Path,
    state_file: Path,
    state: dict[str, Any],
    source_phase: str,
    target_phase: str,
    checkpoint: str | None,
) -> None:
    checkpoints = state.get("checkpoints", {})
    gate_context = checkpoints.get("gate_context", {})
    questions = state.get("questions", {})
    task = state.get("task", {})
    resume_context = state.get("resume_context", {})
    resume_first_prompt = default_resume_first_prompt(state, source_phase, target_phase, checkpoint)
    try:
        state_file_ref = str(state_file.relative_to(PROJECT_ROOT))
    except ValueError:
        state_file_ref = str(state_file)
    lines = [
        "# SESSION_BRIEF",
        "",
        f"- task: {task.get('id', '')} / {task.get('name', '')}",
        f"- task_mode: {task.get('mode', '')}",
        f"- state_file: {state_file_ref}",
        f"- current_phase: {state.get('current_phase')}",
        f"- handoff_from: {source_phase}",
        f"- handoff_to: {target_phase}",
        f"- last_checkpoint: {checkpoints.get('last_checkpoint')}",
        f"- awaiting_user_action: {checkpoints.get('awaiting_user_action')}",
        f"- allowed_actions: {', '.join(checkpoints.get('allowed_actions', [])) or '(none)'}",
        f"- pending_checkpoint: {resume_context.get('pending_checkpoint', '')}",
        f"- current_execution_unit: {resume_context.get('current_execution_unit', '')}",
        f"- last_review_status: {resume_context.get('last_review_status', '')}",
        f"- next_required_action: {resume_context.get('next_required_action', '')}",
        f"- required_script: {resume_context.get('required_script', '')}",
        f"- open_questions: {len(questions.get('open', []))}",
        f"- resolved_questions: {len(questions.get('resolved', []))}",
        f"- req_validation_passed: {gate_context.get('req_validation_passed')}",
        f"- spec_validation_passed: {gate_context.get('spec_validation_passed')}",
        "",
        "## Resume First Prompt",
        "",
        resume_first_prompt,
        "",
        "## Guardrail",
        "",
        "- 恢复后先读状态文件和本brief，再决定动作。",
        "- 若awaiting_user_action=true，未收到明确编号动作前不得推进阶段。",
        "- 未跑当前阶段preflight和orchestrator，不得宣称阶段通过。",
    ]
    brief_file.parent.mkdir(parents=True, exist_ok=True)
    brief_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cleanup_phase_temp(source_phase: str) -> list[str]:
    cleaned: list[str] = []
    phase_dir = PROJECT_ROOT / ".harness/output" / source_phase
    if not phase_dir.exists():
        return cleaned
    for path in phase_dir.rglob("*"):
        if path.name in {".cache", ".scratch"} and path.is_dir():
            for child in sorted(path.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
            for child in sorted(path.rglob("*"), reverse=True):
                if child.is_dir():
                    child.rmdir()
            path.rmdir()
            cleaned.append(str(path.relative_to(PROJECT_ROOT)))
        elif path.is_file() and path.suffix in {".tmp", ".log"}:
            path.unlink()
            cleaned.append(str(path.relative_to(PROJECT_ROOT)))
    return cleaned


def advance_state(state_file: Path, state: dict[str, Any], target_phase: str) -> None:
    checkpoints = state.setdefault("checkpoints", {})
    if checkpoints.get("awaiting_user_action") is True:
        raise ValueError("awaiting_user_action=true时，禁止推进状态")
    state["current_phase"] = target_phase
    phase_status = state.setdefault("phase_status", {})
    if target_phase in phase_status and phase_status[target_phase] == "pending":
        phase_status[target_phase] = "in_progress"
    checkpoints["allowed_actions"] = []
    if checkpoints.get("last_checkpoint") == "NONE":
        checkpoints["checkpoint_emitted_at"] = None
    timestamps = state.setdefault("timestamps", {})
    timestamps["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_state_json(state_file, state)


def run_gate_command(command: list[str], cwd: Path) -> str | None:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return None
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    details = "\n".join(part for part in [output, error] if part).strip()
    return details or f"命令失败: {' '.join(command)}"


def infer_task_manifest_path(state_file: Path, state: dict[str, Any], source_phase: str) -> Path | None:
    workspace_root = workspace_root_for(state_file)
    resume_context = state.get("resume_context", {})
    execution_unit = resume_context.get("current_execution_unit")
    if not isinstance(execution_unit, str) or not execution_unit:
        execution_unit = infer_execution_unit(state)
    task_id = state.get("task", {}).get("id", "")
    candidate_names = [
        f"task-manifest-{source_phase}.json",
        f"{source_phase}-task-manifest.json",
        f"task-manifest-{execution_unit}.json",
        f"{execution_unit}-task-manifest.json",
    ]
    if task_id:
        candidate_names.extend(
            [
                f"task-manifest-{task_id}-{source_phase}.json",
                f"task-manifest-{task_id}-{execution_unit}.json",
                f"{task_id}-{source_phase}-task-manifest.json",
                f"{task_id}-{execution_unit}-task-manifest.json",
            ]
        )
    candidate_dirs = [
        dispatch_dir_for(state_file),
        workspace_root / ".harness/output/task-manifests",
        workspace_root / ".harness/output" / source_phase,
        state_file.parent,
    ]
    for candidate_dir in candidate_dirs:
        for name in candidate_names:
            candidate = candidate_dir / name
            if candidate.exists():
                return candidate
    return None


def validate_scripted_gates(
    state_file: Path,
    source_phase: str,
    target_phase: str,
    state_override: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    workspace_root = workspace_root_for(state_file)
    gate_state_file = state_file
    temp_state_path: Path | None = None
    if state_override is not None:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".json",
            prefix="phase-handoff-",
            dir=str(state_file.parent),
            delete=False,
        ) as tmp:
            json.dump(
                seal_state(Path(tmp.name), state_override, key_source_state_file=state_file),
                tmp,
                ensure_ascii=False,
                indent=2,
            )
            temp_state_path = Path(tmp.name)
        gate_state_file = temp_state_path
    orchestrator_stages = {"spec", "prove", "gen", "final"}
    try:
        if source_phase in orchestrator_stages:
            orchestrator_cmd = [
                sys.executable,
                str(workspace_root / ".harness/scripts/orchestrator.py"),
                "--stage",
                source_phase,
                "--state-file",
                str(gate_state_file),
                "--workdir",
                str(workspace_root),
            ]
            task_manifest = infer_task_manifest_path(gate_state_file, state_override or load_json(state_file), source_phase)
            if task_manifest:
                orchestrator_cmd.extend(["--task-manifest", str(task_manifest)])
            orchestrator_error = run_gate_command(orchestrator_cmd, workspace_root)
            if orchestrator_error:
                errors.append(f"orchestrator校验失败({source_phase}):\n{orchestrator_error}")
        if target_phase in PHASE_ORDER:
            preflight_cmd = [
                sys.executable,
                str(workspace_root / ".harness/scripts/preflight.py"),
                "--stage",
                target_phase,
                "--state-file",
                str(gate_state_file),
            ]
            preflight_error = run_gate_command(preflight_cmd, workspace_root)
            if preflight_error:
                errors.append(f"preflight校验失败({target_phase}):\n{preflight_error}")
    finally:
        if temp_state_path and temp_state_path.exists():
            temp_state_path.unlink()
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a minimal phase dispatch context package.")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    parser.add_argument("--from-phase", required=True, choices=PHASE_ORDER)
    parser.add_argument("--to-phase")
    parser.add_argument("--checkpoint", choices=CHECKPOINT_CHOICES)
    parser.add_argument("--await-user-action", action="store_true")
    parser.add_argument("--allowed-action", action="append", default=[])
    parser.add_argument("--user-action")
    parser.add_argument("--cleanup-temp", action="store_true")
    parser.add_argument("--advance-state", action="store_true")
    parser.add_argument("--write-session-brief", action="store_true")
    parser.add_argument("--session-brief-file")
    args = parser.parse_args()

    state_file = Path(args.state_file)
    workspace_root = workspace_root_for(state_file)
    dispatch_dir = dispatch_dir_for(state_file)
    session_brief_file = (
        Path(args.session_brief_file)
        if args.session_brief_file
        else session_brief_file_for(state_file)
    )
    state = load_json(state_file)
    target_phase = args.to_phase or next_phase_for(args.from_phase)
    if state.get("current_phase") != args.from_phase:
        print(
            f"[BLOCKER] 状态漂移: current_phase={state.get('current_phase')}，"
            f"但from-phase={args.from_phase}"
        )
        return 1
    transition_control_errors = validate_transition_control_plane(state, args.from_phase)
    if transition_control_errors:
        for error in transition_control_errors:
            print(f"[BLOCKER] {error}")
        return 1
    state_schema_error = validate_state_schema(state_file, state)
    if state_schema_error:
        print(f"[BLOCKER] {state_schema_error}")
        return 1
    if args.checkpoint and not args.await_user_action:
        print("[BLOCKER] 当前Checkpoint写入模式必须同时提供--await-user-action。")
        return 1
    if args.checkpoint and CHECKPOINT_PHASE_MAP.get(args.checkpoint) != args.from_phase:
        print(
            f"[BLOCKER] checkpoint {args.checkpoint} 只能用于阶段 {CHECKPOINT_PHASE_MAP.get(args.checkpoint)}，"
            f"当前from-phase={args.from_phase}"
        )
        return 1
    if args.checkpoint and state.get("phase_status", {}).get(args.from_phase) != "completed":
        print(f"[BLOCKER] 阶段{args.from_phase}未completed，禁止写入{args.checkpoint}。")
        return 1
    if args.allowed_action and not args.checkpoint:
        print("[BLOCKER] 需要写allowed_actions时，必须同时提供--checkpoint。")
        return 1
    if args.checkpoint and args.user_action:
        print("[BLOCKER] --checkpoint和--user-action不能同时使用。")
        return 1
    user_action_applied = False
    if args.user_action:
        consume_error = consume_user_action(state, args.user_action)
        if consume_error:
            print(f"[BLOCKER] {consume_error}")
            return 1
        state = refresh_state_integrity(state_file, state)
        user_action_applied = True

    if args.checkpoint:
        if args.checkpoint == "final-ok" and not final_gate_is_ready(state, workspace_root):
            print("[BLOCKER] final阶段最终验收门禁未通过，禁止写入final-ok。")
            return 1
        checkpoint_gate_errors: list[str] = []
        if args.checkpoint == "final-ok":
            checkpoint_gate_errors.extend(validate_scripted_gates(state_file, args.from_phase, target_phase))
        if checkpoint_gate_errors:
            for error in checkpoint_gate_errors:
                print(f"[BLOCKER] {error}")
            return 1
        derived_actions = derive_allowed_actions(state, args.checkpoint, workspace_root)
        if args.allowed_action:
            invalid_actions = [action for action in args.allowed_action if action not in derived_actions]
            if invalid_actions:
                print(
                    f"[BLOCKER] 传入allowed_actions试图扩权，非法动作:{invalid_actions}，"
                    f"当前checkpoint允许动作仅为:{derived_actions}"
                )
                return 1
            allowed_actions = args.allowed_action
        else:
            allowed_actions = derived_actions
        update_checkpoint_state(
            state,
            checkpoint=args.checkpoint,
            await_user_action=True,
            allowed_actions=allowed_actions,
        )
        update_resume_context(
            state,
            next_required_action="wait_for_user_action",
            required_script="phase-handoff.py --user-action <action>",
            pending_checkpoint=args.checkpoint,
            source_phase=args.from_phase,
            target_phase=target_phase,
            last_review_status="pending",
        )
        save_state_json(state_file, state)
        print(
            f"[PASS] 已同步checkpoint状态:last_checkpoint={state.get('checkpoints', {}).get('last_checkpoint')} "
            f"awaiting_user_action={state.get('checkpoints', {}).get('awaiting_user_action')}"
        )
        payload = build_context_package(state_file, state, args.from_phase, target_phase, args.checkpoint)
        dispatch_file = dispatch_dir / f"{args.from_phase}-to-{target_phase}.json"
        save_json(dispatch_file, payload)
        print(f"[PASS] 已生成dispatch包:{dispatch_file}")
        if args.write_session_brief:
            brief_file = session_brief_file
            write_session_brief(brief_file, state_file, state, args.from_phase, target_phase, args.checkpoint)
            print(f"[PASS] 已写SESSION_BRIEF:{brief_file}")
        if args.cleanup_temp:
            cleaned = cleanup_phase_temp(args.from_phase)
            print(f"[INFO] 已清理临时路径{len(cleaned)}项")
        return 0

    if args.advance_state and args.user_action:
        allowed_advancing_actions = ADVANCE_ACTIONS.get(args.from_phase, set())
        if args.user_action not in allowed_advancing_actions:
            print(f"[BLOCKER] 当前阶段{args.from_phase}不支持使用动作{args.user_action}推进阶段。")
            return 1
    if args.user_action and not args.advance_state:
        required_advancing_actions = ADVANCE_ACTIONS.get(args.from_phase, set())
        if args.user_action in required_advancing_actions:
            print(f"[BLOCKER] 动作{args.user_action}必须配合--advance-state使用。")
            return 1
    if args.user_action and not args.advance_state:
        update_resume_context(
            state,
            next_required_action=f"run_preflight:{state.get('current_phase')}",
            required_script=f"preflight.py --stage {state.get('current_phase')}",
            pending_checkpoint="NONE",
            source_phase=state.get("current_phase", args.from_phase),
            target_phase=state.get("current_phase", args.from_phase),
            last_review_status="pending",
        )
        save_state_json(state_file, state)
        print(f"[PASS] 已消费用户动作:{args.user_action}")
        if args.write_session_brief:
            brief_file = session_brief_file
            current_phase = state.get("current_phase", args.from_phase)
            write_session_brief(
                brief_file,
                state_file,
                state,
                current_phase,
                current_phase,
                state.get("checkpoints", {}).get("last_checkpoint"),
            )
            print(f"[PASS] 已写SESSION_BRIEF:{brief_file}")
        return 0

    # 校验当前阶段所有门禁已通过
    errors = validate_handoff(state, args.from_phase, target_phase, state_file)
    if not errors:
        gate_state_override = state if (args.advance_state and args.user_action) else None
        errors.extend(validate_scripted_gates(state_file, args.from_phase, target_phase, gate_state_override))
    # 失败时不得更新状态文件
    if errors:
        for error in errors:
            print(f"[BLOCKER] {error}")
        return 1

    payload = build_context_package(
        state_file,
        state,
        args.from_phase,
        target_phase,
        state.get("checkpoints", {}).get("last_checkpoint"),
    )
    dispatch_file = dispatch_dir / f"{args.from_phase}-to-{target_phase}.json"
    save_json(dispatch_file, payload)
    print(f"[PASS] 已生成dispatch包:{dispatch_file}")

    if args.cleanup_temp:
        cleaned = cleanup_phase_temp(args.from_phase)
        print(f"[INFO] 已清理临时路径{len(cleaned)}项")

    # 只有门禁校验全部通过后才更新current_phase、phase_status、resume_context
    if args.advance_state:
        try:
            advance_state(state_file, state, target_phase)
        except ValueError as exc:
            print(f"[BLOCKER] {exc}")
            return 1
        if target_phase in TERMINAL_PHASE_ACTIONS:
            terminal_action, terminal_script = TERMINAL_PHASE_ACTIONS[target_phase]
            update_resume_context(
                state,
                next_required_action=terminal_action,
                required_script=terminal_script,
                pending_checkpoint="NONE",
                source_phase=target_phase,
                target_phase=target_phase,
                last_review_status="pending",
            )
        else:
            update_resume_context(
                state,
                next_required_action=f"run_preflight:{target_phase}",
                required_script=f"preflight.py --stage {target_phase}",
                pending_checkpoint="NONE",
                source_phase=target_phase,
                target_phase=next_phase_for(target_phase) if target_phase in PHASE_ORDER else target_phase,
                last_review_status="pending",
            )
        save_state_json(state_file, state)
        print(f"[PASS] 已推进状态到:{target_phase}")
    elif user_action_applied:
        update_resume_context(
            state,
            next_required_action=f"run_preflight:{state.get('current_phase')}",
            required_script=f"preflight.py --stage {state.get('current_phase')}",
            pending_checkpoint="NONE",
            source_phase=state.get("current_phase", args.from_phase),
            target_phase=state.get("current_phase", args.from_phase),
            last_review_status="pending",
        )
        save_state_json(state_file, state)
        print(f"[PASS] 已消费用户动作:{args.user_action}")

    if args.write_session_brief:
        brief_file = session_brief_file
        brief_source_phase = args.from_phase
        brief_target_phase = target_phase
        if args.advance_state:
            brief_source_phase = state.get("current_phase", target_phase)
            brief_target_phase = next_phase_for(brief_source_phase) if brief_source_phase in PHASE_ORDER else target_phase
        write_session_brief(
            brief_file,
            state_file,
            state,
            brief_source_phase,
            brief_target_phase,
            state.get("checkpoints", {}).get("last_checkpoint"),
        )
        print(f"[PASS] 已写SESSION_BRIEF:{brief_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
