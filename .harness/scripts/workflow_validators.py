#!/usr/bin/env python3
"""Workflow stage validators — harness-workflow-state business logic checks."""
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path

from dag_blueprint import load_dag_blueprint
from final_report_contract import validate_final_report
from manifest_validators import validate_current_gen_node_gate
from prove_routing_compat import normalize_legacy_prove_routing_payload
from stage_helpers import validate_resume_action_binding

try:
    from jsonschema import validate as _jsonschema_validate, ValidationError
except ImportError:
    print("[Blocker] jsonschema 库未安装，无法执行契约校验！")
    sys.exit(1)

CONTROLLED_CHECKPOINTS = {"NONE", "spec-ok", "prove-ok", "layer-ok", "final-ok"}
CONTROLLED_ALLOW_CODEGEN = {"UNSET", "YES", "NO", "YES_WITH_WARNING"}
CONTROLLED_REVIEW_STATUS = {"pending", "approved", "rework_required", "rejected"}

HARNESS_REQ_FACTS_SCHEMA = ".harness/schemas/harness-req-facts.v1.schema.json"
HARNESS_ISSUE_ROUTING_SCHEMA = ".harness/schemas/harness-issue-routing.v1.schema.json"


def _run_validator(workdir: Path, script_name: str, input_path: Path) -> dict:
    script_path = workdir / ".harness" / "scripts" / script_name
    if not script_path.exists():
        print(f"[Error] 校验脚本不存在: {script_path}")
        sys.exit(1)
    if not input_path.exists():
        print(f"[Error] 校验输入不存在: {input_path}")
        sys.exit(1)
    result = subprocess.run(
        [sys.executable, str(script_path), "--input", str(input_path)],
        capture_output=True,
        text=True,
        cwd=str(workdir),
        check=False,
    )
    if result.returncode != 0:
        print(f"[Blocker] 校验脚本执行失败: {script_name}")
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip())
        sys.exit(1)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"[Blocker] 校验脚本输出不是合法JSON: {script_name}")
        print(result.stdout[:1000])
        sys.exit(1)


def _require_validator_pass(
    workdir: Path, script_name: str, input_path: Path, allowed_statuses: set[str]
) -> None:
    payload = _run_validator(workdir, script_name, input_path)
    status = payload.get("status")
    print(f"[*] {script_name} => {status}")
    if status not in allowed_statuses:
        summary = payload.get("summary", "")
        print(f"[Blocker] {script_name} 未达到允许状态 {sorted(allowed_statuses)}: {summary}")
        for finding in payload.get("findings", [])[:20]:
            code = finding.get("code", "UNKNOWN")
            message = finding.get("message", "未描述")
            severity = finding.get("severity", "unknown")
            print(f"  - [{severity}] {code}: {message}")
        sys.exit(1)


def _validate_json_with_schema(
    workdir: Path, input_path: Path, schema_rel_path: str, label: str
) -> dict:
    if not input_path.exists():
        print(f"[Blocker] {label}不存在: {input_path}")
        sys.exit(1)
    schema_path = workdir / schema_rel_path
    if not schema_path.exists():
        print(f"[Blocker] {label}对应Schema不存在: {schema_path}")
        sys.exit(1)
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        if schema_rel_path == HARNESS_ISSUE_ROUTING_SCHEMA:
            payload = normalize_legacy_prove_routing_payload(payload)
    except json.JSONDecodeError as exc:
        print(f"[Blocker] {label}不是合法JSON: {exc}")
        sys.exit(1)
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        _jsonschema_validate(instance=payload, schema=schema)
    except ValidationError as exc:
        path = ".".join(str(p) for p in exc.absolute_path)
        print(f"[Blocker] {label}不符合Schema: 路径={path} 错误={exc.message}")
        sys.exit(1)
    return payload


def validate_resume_context_consistency(data: dict, state_kind: str) -> None:
    if state_kind != "harness_workflow":
        return
    current_phase = data.get("current_phase")
    checkpoints = data.get("checkpoints", {})
    resume_context = data.get("resume_context")
    artifacts = data.get("artifacts", {})
    if current_phase in {"DONE", "TERMINATED"}:
        return
    if not isinstance(resume_context, dict):
        print("[Blocker] harness-workflow-state缺少resume_context，无法执行恢复控制面校验。")
        sys.exit(1)
    state_contract_version = data.get("state_contract_version")
    if state_contract_version is not None and (
        not isinstance(state_contract_version, str) or not state_contract_version.strip()
    ):
        print(f"[Blocker] state_contract_version非法: {state_contract_version}")
        sys.exit(1)
    last_review_status = resume_context.get("last_review_status")
    if last_review_status not in CONTROLLED_REVIEW_STATUS:
        print(f"[Blocker] resume_context.last_review_status非法: {last_review_status}")
        sys.exit(1)
    pending_checkpoint = resume_context.get("pending_checkpoint")
    current_execution_unit = resume_context.get("current_execution_unit")
    next_required_action = resume_context.get("next_required_action")
    required_script = resume_context.get("required_script")
    checkpoint_emitted_at = checkpoints.get("checkpoint_emitted_at")
    if checkpoint_emitted_at is not None and not isinstance(checkpoint_emitted_at, str):
        print(f"[Blocker] checkpoints.checkpoint_emitted_at类型非法: {type(checkpoint_emitted_at).__name__}")
        sys.exit(1)
    if checkpoints.get("awaiting_user_action") is True:
        if pending_checkpoint != checkpoints.get("last_checkpoint"):
            print("[Blocker] awaiting_user_action=true时，resume_context.pending_checkpoint必须与last_checkpoint一致。")
            sys.exit(1)
        if resume_context.get("next_required_action") != "wait_for_user_action":
            print("[Blocker] awaiting_user_action=true时，resume_context.next_required_action必须为wait_for_user_action。")
            sys.exit(1)
        if checkpoints.get("last_checkpoint") != "NONE" and not checkpoint_emitted_at:
            print("[Blocker] awaiting_user_action=true且last_checkpoint!=NONE时，checkpoint_emitted_at必须存在。")
            sys.exit(1)
    elif pending_checkpoint != "NONE":
        print("[Blocker] 非等待态时，resume_context.pending_checkpoint必须为NONE。")
        sys.exit(1)
    elif checkpoints.get("last_checkpoint") == "NONE" and checkpoint_emitted_at not in {None, ""}:
        print("[Blocker] last_checkpoint=NONE时，checkpoint_emitted_at必须为空。")
        sys.exit(1)

    if current_phase == "gen":
        phase_3 = artifacts.get("phase_3", {})
        current_node = phase_3.get("current_node")
        nodes = phase_3.get("nodes", {})
        if current_node is not None:
            if not isinstance(current_node, str) or not current_node:
                print("[Blocker] gen阶段phase_3.current_node必须为空或非空字符串。")
                sys.exit(1)
            if not isinstance(nodes, dict) or current_node not in nodes:
                print(f"[Blocker] gen阶段current_node未在phase_3.nodes中注册: {current_node}")
                sys.exit(1)
            if current_execution_unit != current_node:
                print("[Blocker] gen阶段resume_context.current_execution_unit必须与phase_3.current_node一致。")
                sys.exit(1)
            node_state = nodes.get(current_node, {})
            if isinstance(node_state, dict):
                verification = node_state.get("verification")
                if isinstance(verification, dict):
                    review_status = verification.get("review_status")
                    if review_status != last_review_status:
                        print("[Blocker] gen阶段resume_context.last_review_status必须与当前节点verification.review_status一致。")
                        sys.exit(1)
                    if review_status in {"approved", "rework_required", "rejected"} and not str(node_state.get("last_review_report", "")).strip():
                        print("[Blocker] 当前gen节点已有review结论，但last_review_report为空。")
                        sys.exit(1)
                    if verification.get("compile_status") == "failed" and not str(node_state.get("compile_log_path", "")).strip():
                        print("[Blocker] 当前gen节点compile_status=failed时，compile_log_path不能为空。")
                        sys.exit(1)
        elif current_execution_unit != "gen":
            print("[Blocker] gen阶段未绑定current_node时，resume_context.current_execution_unit必须为gen。")
            sys.exit(1)
    elif current_execution_unit != current_phase:
        print("[Blocker] 非gen阶段resume_context.current_execution_unit必须与current_phase一致。")
        sys.exit(1)

    action_binding_error = validate_resume_action_binding(
        current_phase, current_execution_unit, next_required_action, required_script
    )
    if action_binding_error:
        print(f"[Blocker] {action_binding_error}")
        sys.exit(1)


def validate_prove_routing_consistency(data: dict, prove_payload: dict) -> None:
    checkpoints = data.get("checkpoints", {})
    gate_context = checkpoints.get("gate_context", {})
    phase_2 = data.get("artifacts", {}).get("phase_2", {})
    last_checkpoint = checkpoints.get("last_checkpoint")

    state_allow_codegen = phase_2.get("allow_codegen")
    if prove_payload.get("allow_codegen") != state_allow_codegen:
        print("[Blocker] harness-issue-routing.allow_codegen与运行态artifacts.phase_2.allow_codegen不一致。")
        sys.exit(1)

    gate_update = prove_payload.get("gate_context_update", {})
    if gate_update.get("business_fact_validation_passed") != gate_context.get("business_fact_validation_passed"):
        print("[Blocker] harness-issue-routing中的business_fact_validation_passed与运行态gate_context不一致。")
        sys.exit(1)
    if gate_update.get("scene_coverage_passed") != gate_context.get("scene_coverage_passed"):
        print("[Blocker] harness-issue-routing中的scene_coverage_passed与运行态gate_context不一致。")
        sys.exit(1)

    bf_result = prove_payload.get("business_fact_validation", {})
    bf_passed = bf_result.get("passed")
    blocked_items = bf_result.get("blocked_items", [])
    if bf_passed != gate_context.get("business_fact_validation_passed"):
        print("[Blocker] harness-issue-routing中的business_fact_validation结果与运行态gate_context不一致。")
        sys.exit(1)
    if bf_passed is not True and last_checkpoint == "prove-ok":
        print("[Blocker] business_fact_validation未通过时，不得写prove-ok。")
        sys.exit(1)
    if blocked_items and state_allow_codegen == "YES":
        print("[Blocker] business_fact_validation存在blocked_items时，不得allow_codegen=YES。")
        sys.exit(1)

    routing = prove_payload.get("routing", {})
    prove_resolvable = routing.get("prove_resolvable", [])
    prove_with_risk = routing.get("prove_with_risk", [])
    human_required = routing.get("human_required", [])
    if len(prove_resolvable) != gate_context.get("prove_resolvable_open"):
        print("[Blocker] harness-issue-routing中的prove_resolvable数量与运行态gate_context不一致。")
        sys.exit(1)
    if len(prove_with_risk) != gate_context.get("prove_with_risk_open"):
        print("[Blocker] harness-issue-routing中的prove_with_risk数量与运行态gate_context不一致。")
        sys.exit(1)
    logged = gate_context.get("prove_with_risk_logged_count", 0)
    unlogged = gate_context.get("prove_with_risk_unlogged_count", 0)
    if logged + unlogged != len(prove_with_risk):
        print("[Blocker] prove_with_risk_logged_count+prove_with_risk_unlogged_count必须与prove_with_risk_open一致。")
        sys.exit(1)
    if len(human_required) != gate_context.get("human_required_open"):
        print("[Blocker] harness-issue-routing中的human_required数量与运行态gate_context不一致。")
        sys.exit(1)
    pending_hr = [
        item for item in human_required
        if isinstance(item, dict) and item.get("status") in {"pending", "awaiting_human"}
    ]
    if pending_hr and checkpoints.get("awaiting_user_action") is not True:
        print("[Blocker] 存在未关闭的human_required问题时，awaiting_user_action必须为true。")
        sys.exit(1)
    if pending_hr and state_allow_codegen == "YES":
        print("[Blocker] 存在未关闭的human_required问题时，不得allow_codegen=YES。")
        sys.exit(1)
    if pending_hr and last_checkpoint == "prove-ok":
        print("[Blocker] 存在未关闭的human_required问题时，不得写prove-ok。")
        sys.exit(1)
    if unlogged > 0 and last_checkpoint == "prove-ok":
        print("[Blocker] prove_with_risk仍有未留痕项时，不得写prove-ok。")
        sys.exit(1)


def run_harness_workflow_spec_validation(
    data: dict,
    workdir: Path,
    business_facts_input: Path | None,
) -> None:
    print("\n--- 执行 harness-workflow-state / Spec 阶段校验 ---")
    validate_resume_context_consistency(data, "harness_workflow")
    checkpoints = data.get("checkpoints", {})
    phase_status = data.get("phase_status", {})
    artifacts = data.get("artifacts", {})
    gate_context = checkpoints.get("gate_context", {})
    last_checkpoint = checkpoints.get("last_checkpoint")
    allow_codegen = artifacts.get("phase_2", {}).get("allow_codegen")

    if phase_status.get("prep") != "completed":
        print("[Blocker] prep阶段未完成，禁止进入spec断言。")
        sys.exit(1)
    if last_checkpoint not in CONTROLLED_CHECKPOINTS:
        print(f"[Blocker] 非法checkpoint值: {last_checkpoint}")
        sys.exit(1)
    if allow_codegen not in CONTROLLED_ALLOW_CODEGEN:
        print(f"[Blocker] 非法allow_codegen值: {allow_codegen}")
        sys.exit(1)
    if phase_status.get("spec") not in {"in_progress", "completed"}:
        print(f"[Blocker] 当前phase_status.spec非法: {phase_status.get('spec')}")
        sys.exit(1)
    if artifacts.get("phase_1", {}).get("spec_ready") is not True:
        print("[Blocker] phase_1.spec_ready != true，说明spec产物尚未准备完成。")
        sys.exit(1)
    if gate_context.get("business_fact_validation_passed") not in {True, False}:
        print("[Blocker] gate_context.business_fact_validation_passed必须为布尔值。")
        sys.exit(1)
    if business_facts_input:
        _validate_json_with_schema(workdir, business_facts_input, HARNESS_REQ_FACTS_SCHEMA, "harness-req-facts正式产物")
        _require_validator_pass(workdir, "check-business-facts.py", business_facts_input, {"PASS", "WARN"})

    print("[Success] harness-workflow-state 的 spec 阶段校验通过。")


def run_harness_workflow_prove_validation(
    data: dict,
    workdir: Path,
    business_facts_input: Path | None,
    config_boundary_input: Path | None,
    coverage_input: Path | None,
    prove_routing_input: Path | None,
) -> None:
    print("\n--- 执行 harness-workflow-state / Prove 阶段校验 ---")
    validate_resume_context_consistency(data, "harness_workflow")
    checkpoints = data.get("checkpoints", {})
    phase_status = data.get("phase_status", {})
    artifacts = data.get("artifacts", {})
    questions = data.get("questions", {})
    gate_context = checkpoints.get("gate_context", {})
    phase_2 = artifacts.get("phase_2", {})
    last_checkpoint = checkpoints.get("last_checkpoint")
    allow_codegen = phase_2.get("allow_codegen")

    if phase_status.get("spec") != "completed":
        print("[Blocker] spec阶段未完成，禁止进入prove断言。")
        sys.exit(1)
    if phase_status.get("prove") not in {"in_progress", "completed"}:
        print(f"[Blocker] 当前phase_status.prove非法: {phase_status.get('prove')}")
        sys.exit(1)
    if last_checkpoint not in CONTROLLED_CHECKPOINTS:
        print(f"[Blocker] 非法checkpoint值: {last_checkpoint}")
        sys.exit(1)
    if allow_codegen not in CONTROLLED_ALLOW_CODEGEN:
        print(f"[Blocker] 非法allow_codegen值: {allow_codegen}")
        sys.exit(1)
    if business_facts_input:
        _validate_json_with_schema(workdir, business_facts_input, HARNESS_REQ_FACTS_SCHEMA, "harness-req-facts正式产物")
        _require_validator_pass(workdir, "check-business-facts.py", business_facts_input, {"PASS", "WARN"})
        if gate_context.get("business_fact_validation_passed") is not True:
            print("[Blocker] business_fact_validation_passed未被写为true。")
            sys.exit(1)
    if config_boundary_input:
        _require_validator_pass(workdir, "check-config-boundary.py", config_boundary_input, {"PASS", "WARN"})
    if coverage_input:
        _require_validator_pass(workdir, "check-domain-coverage.py", coverage_input, {"PASS", "WARN"})
    if prove_routing_input:
        prove_payload = _validate_json_with_schema(
            workdir, prove_routing_input, HARNESS_ISSUE_ROUTING_SCHEMA, "harness-issue-routing正式产物"
        )
        validate_prove_routing_consistency(data, prove_payload)
    if gate_context.get("scene_coverage_passed") is not True and last_checkpoint == "prove-ok":
        print("[Blocker] prove-ok状态下，scene_coverage_passed必须为true。")
        sys.exit(1)
    if (
        any(item.get("status") == "pending" for item in questions.get("open", []) if isinstance(item, dict))
        and checkpoints.get("awaiting_user_action") is not True
    ):
        print("[Blocker] 存在未决问题，但awaiting_user_action未置为true。")
        sys.exit(1)
    if phase_status.get("prove") == "completed" and gate_context.get("business_fact_validation_passed") is not True:
        print("[Blocker] prove阶段已完成，但business_fact_validation_passed未被写为true。")
        sys.exit(1)
    if allow_codegen == "UNSET":
        print("[Blocker] prove阶段完成前allow_codegen不得保持UNSET。")
        sys.exit(1)
    if allow_codegen == "YES" and checkpoints.get("awaiting_user_action") is True:
        print("[Blocker] 仍需人工动作时，不得直接allow_codegen=YES。")
        sys.exit(1)
    if allow_codegen == "YES" and phase_2.get("blockers"):
        print("[Blocker] 存在prove阻塞项时，不得allow_codegen=YES。")
        sys.exit(1)
    if last_checkpoint == "prove-ok" and allow_codegen == "NO":
        print("[Blocker] prove-ok状态下，allow_codegen不得为NO。")
        sys.exit(1)

    print("[Success] harness-workflow-state 的 prove 阶段校验通过。")


def run_harness_workflow_gen_validation(data: dict, workdir: Path) -> None:
    print("\n--- 执行 harness-workflow-state / Gen 阶段校验 ---")
    validate_resume_context_consistency(data, "harness_workflow")
    checkpoints = data.get("checkpoints", {})
    phase_status = data.get("phase_status", {})
    artifacts = data.get("artifacts", {})
    resume_context = data.get("resume_context", {})
    phase_2 = artifacts.get("phase_2", {})
    phase_3 = artifacts.get("phase_3", {})
    layers = phase_3.get("layers", {})
    nodes = phase_3.get("nodes", {})
    current_node = phase_3.get("current_node")
    next_required_action = resume_context.get("next_required_action")

    gen_layer_node_map, gen_node_prereqs = load_dag_blueprint(workdir)

    if phase_status.get("prove") != "completed":
        print("[Blocker] prove阶段未完成，禁止进入gen断言。")
        sys.exit(1)
    if phase_status.get("gen") not in {"in_progress", "completed"}:
        print(f"[Blocker] 当前phase_status.gen非法: {phase_status.get('gen')}")
        sys.exit(1)
    if checkpoints.get("last_checkpoint") not in {"prove-ok", "layer-ok", "final-ok"}:
        print(f"[Blocker] gen阶段last_checkpoint非法: {checkpoints.get('last_checkpoint')}")
        sys.exit(1)
    if phase_2.get("allow_codegen") not in {"YES", "YES_WITH_WARNING"}:
        print(f"[Blocker] gen阶段allow_codegen非法: {phase_2.get('allow_codegen')}")
        sys.exit(1)
    if not isinstance(nodes, dict):
        print("[Blocker] gen阶段phase_3.nodes缺失或非法。")
        sys.exit(1)

    if isinstance(current_node, str) and current_node:
        node_state = nodes.get(current_node)
        if not isinstance(node_state, dict):
            print(f"[Blocker] gen阶段current_node未在phase_3.nodes中注册: {current_node}")
            sys.exit(1)
        current_gate_error = validate_current_gen_node_gate(current_node, node_state, next_required_action)
        if current_gate_error:
            print(f"[Blocker] {current_gate_error}")
            sys.exit(1)

    for node_id, prereqs in gen_node_prereqs.items():
        node_state = nodes.get(node_id)
        if not isinstance(node_state, dict):
            continue
        status = node_state.get("status")
        if status in {"in_progress", "completed"}:
            unmet = [
                dep for dep in prereqs
                if not isinstance(nodes.get(dep), dict) or nodes.get(dep, {}).get("status") != "completed"
            ]
            if unmet:
                print(f"[Blocker] {node_id}已启动，但前置节点未完成: {', '.join(unmet)}")
                sys.exit(1)
        if phase_status.get("gen") == "completed":
            verification = node_state.get("verification")
            if not isinstance(verification, dict):
                print(f"[Blocker] final前gen节点缺少verification: {node_id}")
                sys.exit(1)
            if verification.get("review_status") != "approved":
                print(f"[Blocker] final前{node_id}.verification.review_status必须为approved。")
                sys.exit(1)
            if verification.get("script_status") != "passed":
                print(f"[Blocker] final前{node_id}.verification.script_status必须为passed。")
                sys.exit(1)
            if verification.get("compile_status") == "failed":
                print(f"[Blocker] final前{node_id}.verification.compile_status不能为failed。")
                sys.exit(1)

    for layer_name, required_nodes in gen_layer_node_map.items():
        layer_state = layers.get(layer_name)
        if not isinstance(layer_state, dict):
            print(f"[Blocker] gen层状态缺失或非法: {layer_name}")
            sys.exit(1)
        if layer_state.get("status") == "completed":
            missing = [n for n in required_nodes if not isinstance(nodes.get(n), dict) or nodes.get(n, {}).get("status") != "completed"]
            if missing:
                print(f"[Blocker] {layer_name}标记completed，但节点未完成: {', '.join(missing)}")
                sys.exit(1)

    if phase_status.get("gen") == "completed":
        for layer_name, required_nodes in gen_layer_node_map.items():
            missing = [n for n in required_nodes if not isinstance(nodes.get(n), dict) or nodes.get(n, {}).get("status") != "completed"]
            if missing:
                print(f"[Blocker] gen阶段已completed，但仍有节点未完成: {layer_name} -> {', '.join(missing)}")
                sys.exit(1)

    print("[Success] harness-workflow-state 的 gen 阶段校验通过。")


def run_harness_workflow_final_validation(data: dict, workdir: Path) -> None:
    print("\n--- 执行 harness-workflow-state / Final 阶段校验 ---")
    validate_resume_context_consistency(data, "harness_workflow")
    phase_status = data.get("phase_status", {})
    artifacts = data.get("artifacts", {})
    phase_4 = artifacts.get("phase_4", {})
    phase_3 = artifacts.get("phase_3", {})
    nodes = phase_3.get("nodes", {})

    _, gen_node_prereqs = load_dag_blueprint(workdir)

    if phase_status.get("gen") != "completed":
        print("[Blocker] gen阶段未完成，禁止进入final断言。")
        sys.exit(1)
    if phase_status.get("final") not in {"in_progress", "completed"}:
        print(f"[Blocker] 当前phase_status.final非法: {phase_status.get('final')}")
        sys.exit(1)

    report_validation = validate_final_report(workdir, data)
    if not report_validation.ok:
        print(f"[Blocker] final审核报告不合法: {report_validation.reason}")
        sys.exit(1)
    if report_validation.result != "accept":
        print(f"[Blocker] final审核报告result必须为accept，当前为: {report_validation.result}")
        sys.exit(1)
    if report_validation.critical != 0:
        print(f"[Blocker] final审核报告critical必须为0，当前为: {report_validation.critical}")
        sys.exit(1)
    if report_validation.high != 0:
        print(f"[Blocker] final审核报告high必须为0，当前为: {report_validation.high}")
        sys.exit(1)
    if phase_4.get("p0_scan_status") != "passed":
        print(f"[Blocker] final阶段p0_scan_status必须为passed，当前为: {phase_4.get('p0_scan_status')}")
        sys.exit(1)
    if phase_4.get("final_compile_status") != "passed":
        print(f"[Blocker] final阶段final_compile_status必须为passed，当前为: {phase_4.get('final_compile_status')}")
        sys.exit(1)
    if not isinstance(nodes, dict):
        print("[Blocker] final阶段phase_3.nodes缺失或非法。")
        sys.exit(1)

    for node_id, prereqs in gen_node_prereqs.items():
        node_state = nodes.get(node_id)
        if not isinstance(node_state, dict):
            print(f"[Blocker] final阶段缺少节点状态: {node_id}")
            sys.exit(1)
        if node_state.get("status") != "completed":
            print(f"[Blocker] final阶段节点未完成: {node_id}")
            sys.exit(1)
        verification = node_state.get("verification")
        if not isinstance(verification, dict):
            print(f"[Blocker] final阶段节点缺少verification: {node_id}")
            sys.exit(1)
        if verification.get("review_status") != "approved":
            print(f"[Blocker] final阶段{node_id}.verification.review_status必须为approved。")
            sys.exit(1)
        if verification.get("script_status") != "passed":
            print(f"[Blocker] final阶段{node_id}.verification.script_status必须为passed。")
            sys.exit(1)
        if verification.get("compile_status") == "failed":
            print(f"[Blocker] final阶段{node_id}.verification.compile_status不能为failed。")
            sys.exit(1)
        unmet = [
            dep for dep in prereqs
            if not isinstance(nodes.get(dep), dict) or nodes.get(dep, {}).get("status") != "completed"
        ]
        if unmet:
            print(f"[Blocker] final阶段{node_id}前置节点未完成: {', '.join(unmet)}")
            sys.exit(1)

    print("[Success] harness-workflow-state 的 final 阶段校验通过。")


def run_plan_validation(data: dict) -> list[str]:
    """Plan stage: path sandbox checks + step_id uniqueness + DAG topological sort.

    Returns the topologically sorted list of step IDs.
    """
    print("\n--- 执行 Plan 阶段沙箱及 DAG 验证 ---")
    steps = data.get("steps", [])

    for step in steps:
        for path_type in ["reads", "writes"]:
            for p in step.get(path_type, []):
                if p.startswith("/") or p.startswith("~") or (len(p) >= 2 and p[1] == ":"):
                    print(f"[Blocker] 安全阻断！步骤 {step['step_id']} 的 {path_type} 包含绝对路径: {p}")
                    sys.exit(1)
                normalized = p.replace("\\", "/")
                if ".." in normalized.split("/") or normalized.startswith(".."):
                    print(f"[Blocker] 安全阻断！步骤 {step['step_id']} 的 {path_type} 包含路径穿越: {p}")
                    sys.exit(1)
    print("[*] 相对路径沙箱检查通过。")

    seen: set[str] = set()
    for step in steps:
        sid = step["step_id"]
        if sid in seen:
            print(f"[Blocker] step_id '{sid}' 重复定义！每个步骤必须唯一。")
            sys.exit(1)
        seen.add(sid)
    print("[*] step_id 唯一性校验通过。")

    graph: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = defaultdict(int)
    step_map: dict[str, dict] = {}
    for step in steps:
        sid = step["step_id"]
        step_map[sid] = step
        in_degree[sid] = 0
    for step in steps:
        sid = step["step_id"]
        for dep in step.get("depends_on", []):
            if dep not in step_map:
                print(f"[Blocker] 步骤 {sid} 依赖了未定义的节点 {dep}。")
                sys.exit(1)
            graph[dep].append(sid)
            in_degree[sid] += 1

    queue: deque[str] = deque(sid for sid in step_map if in_degree[sid] == 0)
    sorted_list: list[str] = []
    while queue:
        current = queue.popleft()
        sorted_list.append(current)
        for neighbor in graph[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(sorted_list) != len(steps):
        print("[Blocker] 发现循环依赖 (DAG Cycle)！流水线挂起。")
        sys.exit(1)

    print("[Success] DAG 拓扑排序完成，无循环依赖。")
    print("\n=== 预期执行编排 ===")
    for idx, sid in enumerate(sorted_list):
        step = step_map[sid]
        deps = f"(前置: {', '.join(step['depends_on'])})" if step.get("depends_on") else "(首发)"
        print(f"[{idx + 1}] {sid} | Owner: {step['owner']} | {deps}")
    print("====================\n")

    return sorted_list
