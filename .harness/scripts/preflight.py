#!/usr/bin/env python3
"""
HARNESS workflow preflight checker.

Generalized from state-contracts preflight.py.

阶段启动前检查：
1. Skill入口与关键规则文件存在性
2. 运行态状态文件存在性、JSON合法性、Schema合法性
3. 阶段输入完整性
4. 基础工具链与文档解析链可用性

注意：
- 默认只读检查，不修改状态文件
- 不替代orchestrator的产物门禁校验
- 不替代check-*.py的业务语义校验
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from final_report_contract import validate_final_report
from state_integrity import verify_state_integrity, legacy_view

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_SCHEMA = PROJECT_ROOT / ".harness/schemas/harness-state.schema.json"
HARNESS_REQ_FACTS_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/harness-req-facts.v1.schema.json"
HARNESS_ISSUE_ROUTING_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/harness-issue-routing.v1.schema.json"
SKILL_MD = PROJECT_ROOT / "skills/harness-router/SKILL.md"
STATE_CONTRACT = PROJECT_ROOT / ".harness/prompts/harness-contracts.md"
PHASE_DEP_RULE = PROJECT_ROOT / "docs/analysis-gates.md"
PREFLIGHT_RULE = None  # Deprecated: rule file removed, checks degraded to built-in logic
CAPABILITIES_CONFIG = PROJECT_ROOT / ".harness/config/capabilities.yaml"
ALIASES_CONFIG = PROJECT_ROOT / ".harness/config/aliases.yaml"

ALLOWED_STAGES = {"REQ_DRAFT", "REQ_REVIEW", "SPEC_DRAFT", "SPEC_REVIEW", "CODE_IMPL", "MACHINE_CHECK", "DUAL_REVIEW", "FINAL_ACCEPT", "KNOWLEDGE_ARCHIVE", "DONE"}
ALLOWED_CHECKPOINTS = {"NONE", "req-ok", "spec-ok", "code-ok", "review-ok", "final-ok", "archive-ok"}
ALLOWED_ALLOW_CODEGEN = {"UNSET", "YES", "NO", "YES_WITH_CONDITIONS"}
GEN_LAYERS = ["pojo_config_dto", "dependency_provider", "adapter_notify", "admin_sql_i18n"]
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
RESUME_REVIEW_STATUSES = {"pending", "approved", "rework_required", "rejected"}
RESUME_BLOCKING_REVIEW_STATUSES = {"rework_required", "rejected"}
PREFLIGHT_RESULT_FILE = "preflight-result.json"
TERMINAL_PHASE_ACTIONS = {
    "DONE": ("archive_runtime", "archive-harness-workflow.py --archive-only"),
    "TERMINATED": ("archive_runtime", "archive-harness-workflow.py --archive-only"),
}

DOC_EXTENSIONS = {".doc", ".docx", ".pdf"}
CERT_EXTENSIONS = {".pfx", ".jks", ".cer", ".pem", ".crt", ".zip"}


@dataclass
class CheckResult:
    category: str
    item: str
    status: str
    severity: str | None
    message: str


@dataclass
class CapabilityResolution:
    capability_id: str
    skill_name: str
    skill_path: Path
    source: str
    issue: str | None = None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def workspace_root_for(state_file: Path) -> Path:
    return state_file.resolve().parents[2]


def load_structured_data(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    raise ValueError(f"无法解析结构化配置: {path}")


def add_result(results: list[CheckResult], category: str, item: str, status: str, severity: str | None, message: str) -> None:
    results.append(CheckResult(category, item, status, severity, message))


def validate_resume_action_binding(
    current_phase: str,
    current_execution_unit: str | None,
    next_required_action: str | None,
    required_script: str | None,
) -> str | None:
    if not isinstance(next_required_action, str) or not next_required_action:
        return "resume_context.next_required_action不能为空"
    required_script = required_script or ""
    # P3新增：校验next_required_action与required_script一致性
    expected_script = infer_expected_script(next_required_action, current_phase)
    if expected_script and required_script != expected_script:
        return f"resume_context.next_required_action与required_script不一致: {next_required_action}期望{expected_script}，实际为{required_script}"
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
        target_node = parts[1]
        if current_execution_unit != target_node:
            return f"gen阶段next_required_action与current_execution_unit不一致: {target_node} != {current_execution_unit}"
    return None


def infer_expected_script(next_required_action: str, current_phase: str) -> str | None:
    """P3新增：根据next_required_action推断期望的required_script"""
    if next_required_action.startswith("run_preflight:"):
        stage = next_required_action.split(":", 1)[1]
        return f"preflight.py --stage {stage}"
    if next_required_action.startswith("dispatch_stage_worker:") or next_required_action.startswith("dispatch_stage_review:"):
        return "build-stage-task.py"
    if next_required_action.startswith("dispatch_gen_node_worker:") or next_required_action.startswith("dispatch_gen_node_review:"):
        return "build-gen-node-task.py"
    if next_required_action.startswith("run_checkpoint:"):
        checkpoint = next_required_action.split(":", 1)[1]
        phase = checkpoint.split("-", 1)[0]
        return f"phase-handoff.py --from-phase {phase} --checkpoint {checkpoint} --await-user-action"
    if next_required_action == "wait_for_user_action":
        return "phase-handoff.py --user-action <action>"
    if next_required_action == "archive_runtime":
        return "archive-harness-workflow.py --archive-only"
    if current_phase in TERMINAL_PHASE_ACTIONS:
        expected_action, expected_script = TERMINAL_PHASE_ACTIONS[current_phase]
        if next_required_action == expected_action:
            return expected_script
    return None


def has_command(name: str) -> bool:
    return shutil.which(name) is not None



def skill_roots(workspace_root: Path) -> list[Path]:
    return [
        workspace_root / ".harness/skills",
        workspace_root / ".claude/skills",
        Path.home() / ".codex/skills",
        Path.home() / ".claude/skills",
        Path.home() / ".agents/skills",
    ]


def detect_skill(skill_name: str, workspace_root: Path) -> Path | None:
    for root in skill_roots(workspace_root):
        candidate = root / skill_name / "SKILL.md"
        if candidate.exists():
            return candidate
    return None


def load_capabilities_config() -> dict[str, Any]:
    if not CAPABILITIES_CONFIG.exists():
        return {
            "version": "1.0",
            "capabilities": {
                "doc_parse": {
                    "default_skill": "doc-parser",
                    "env_var": "DOC_PARSE_SKILL",
                }
            },
        }
    return load_structured_data(CAPABILITIES_CONFIG)


def load_aliases_config() -> dict[str, Any]:
    if not ALIASES_CONFIG.exists():
        return {"version": "1.0", "aliases": {}}
    return load_structured_data(ALIASES_CONFIG)


def load_skill_metadata(skill_name: str, workspace_root: Path) -> dict[str, Any]:
    skill_path = detect_skill(skill_name, workspace_root)
    if skill_path is None:
        return {}
    metadata_path = skill_path.parent / "metadata.yaml"
    if not metadata_path.exists():
        return {}
    try:
        payload = load_structured_data(metadata_path)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def scan_capability_providers(capability_id: str, workspace_root: Path) -> list[CapabilityResolution]:
    providers: list[CapabilityResolution] = []
    for root in skill_roots(workspace_root):
        if not root.exists():
            continue
        for metadata_path in root.glob("*/metadata.yaml"):
            try:
                payload = load_structured_data(metadata_path)
            except Exception:
                continue
            provides = payload.get("provides", [])
            compatible_with = payload.get("compatible_with", [])
            skill_name = str(payload.get("name") or metadata_path.parent.name)
            if capability_id in provides:
                skill_path = metadata_path.parent / "SKILL.md"
                if skill_path.exists():
                    providers.append(
                        CapabilityResolution(
                            capability_id=capability_id,
                            skill_name=skill_name,
                            skill_path=skill_path,
                            source="metadata.provides",
                        )
                    )
                    continue
            if capability_id == "doc_parse" and "doc-parser" in compatible_with:
                skill_path = metadata_path.parent / "SKILL.md"
                if skill_path.exists():
                    providers.append(
                        CapabilityResolution(
                            capability_id=capability_id,
                            skill_name=skill_name,
                            skill_path=skill_path,
                            source="metadata.compatible_with",
                        )
                    )
                    continue
    return providers


def normalize_alias(alias_value: Any) -> str | None:
    if isinstance(alias_value, str):
        return alias_value.strip() or None
    if isinstance(alias_value, dict):
        skill_name = alias_value.get("skill")
        if isinstance(skill_name, str):
            return skill_name.strip() or None
    return None


def resolve_capability(capability_id: str, workspace_root: Path) -> CapabilityResolution | None:
    capabilities = load_capabilities_config().get("capabilities", {})
    capability_def = capabilities.get(capability_id, {})
    env_var = capability_def.get("env_var")
    if isinstance(env_var, str):
        env_skill = os.environ.get(env_var)
        if env_skill:
            skill_path = detect_skill(env_skill, workspace_root)
            if skill_path is not None:
                return CapabilityResolution(capability_id, env_skill, skill_path, f"env:{env_var}")
            return CapabilityResolution(capability_id, env_skill, Path(), f"env:{env_var}", issue=f"环境变量{env_var}指定的skill不存在:{env_skill}")

    aliases = load_aliases_config().get("aliases", {})
    alias_skill = normalize_alias(aliases.get(capability_id))
    if alias_skill:
        skill_path = detect_skill(alias_skill, workspace_root)
        if skill_path is not None:
            return CapabilityResolution(capability_id, alias_skill, skill_path, "aliases.yaml")

    providers = scan_capability_providers(capability_id, workspace_root)
    if providers:
        return providers[0]

    default_skill = capability_def.get("default_skill")
    if isinstance(default_skill, str):
        skill_path = detect_skill(default_skill, workspace_root)
        if skill_path is not None:
            return CapabilityResolution(capability_id, default_skill, skill_path, "capabilities.yaml.default_skill")

    return None


def detect_doc_parser(workspace_root: Path) -> Path | None:
    candidates = [
        workspace_root / ".harness/skills/doc-parser/SKILL.md",
        workspace_root / ".claude/skills/doc-parser/SKILL.md",
        Path.home() / ".codex/skills/doc-parser/SKILL.md",
        Path.home() / ".claude/skills/doc-parser/SKILL.md",
        Path.home() / ".agents/skills/doc-parser/SKILL.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def detect_doc_parse_capability(doc_files: list[Path]) -> tuple[bool, list[str], list[str]]:
    tools: list[str] = []
    warnings: list[str] = []
    if any(p.suffix.lower() in {".docx", ".doc"} for p in doc_files):
        if has_command("textutil"):
            tools.append("textutil")
        elif has_command("libreoffice"):
            tools.append("libreoffice")
        elif has_command("soffice"):
            tools.append("soffice")
        elif any(p.suffix.lower() == ".doc" for p in doc_files) and (has_command("antiword") or has_command("catdoc")):
            tools.append("antiword/catdoc")
        else:
            warnings.append("缺少.doc/.docx解析链")

    if any(p.suffix.lower() == ".pdf" for p in doc_files):
        if has_command("pdftotext"):
            tools.append("pdftotext")
        elif has_command("python3"):
            warnings.append("PDF仅能依赖较弱fallback")
        else:
            warnings.append("缺少.pdf解析链")

    return bool(tools) or not doc_files, sorted(set(tools)), warnings


def summarize(results: list[CheckResult]) -> dict[str, int]:
    summary = {"pass_count": 0, "blocker_count": 0, "warning_count": 0, "info_count": 0}
    for item in results:
        if item.status == "PASS":
            summary["pass_count"] += 1
        elif item.severity == "BLOCKER":
            summary["blocker_count"] += 1
        elif item.severity == "WARNING":
            summary["warning_count"] += 1
        elif item.severity == "INFO":
            summary["info_count"] += 1
    return summary


def decide(summary: dict[str, int], strict: bool) -> tuple[bool, str]:
    if summary["blocker_count"] > 0:
        return False, f"存在{summary['blocker_count']}项BLOCKER，需修复后才能继续"
    if strict and summary["warning_count"] > 0:
        return False, f"严格模式：存在{summary['warning_count']}项WARNING，需确认后才能继续"
    if summary["warning_count"] > 0:
        return True, f"通过preflight检查，存在{summary['warning_count']}项WARNING（已留痕）"
    return True, "通过preflight检查"


def compute_allowed_actions(state: dict[str, Any], stage: str) -> list[str]:
    """P3新增：根据状态计算允许的动作列表"""
    view = legacy_view(state)
    resume_context = view.resume_context or {}
    checkpoints_raw = view.checkpoints
    checkpoints = checkpoints_raw if isinstance(checkpoints_raw, dict) else {}
    next_action = resume_context.get("next_required_action", "")
    pending_checkpoint = resume_context.get("pending_checkpoint", "NONE")
    last_review_status = resume_context.get("last_review_status", "pending")
    awaiting_user = checkpoints.get("awaiting_user_action") is True

    # awaiting_user_action=true时，只允许wait_for_user_action或checkpoint相关动作
    if awaiting_user:
        if pending_checkpoint != "NONE":
            return [f"run_checkpoint:{pending_checkpoint}", "wait_for_user_action"]
        return ["wait_for_user_action"]

    # last_review_status为rework_required/rejected时，只允许返工动作
    if last_review_status in RESUME_BLOCKING_REVIEW_STATUSES:
        artifacts = view.artifacts
        current_node = artifacts.get("phase_3", {}).get("current_node") if isinstance(artifacts, dict) else None
        if stage == "gen" and current_node:
            return [f"dispatch_gen_node_worker:{current_node}", f"dispatch_gen_node_review:{current_node}"]
        return []  # 阻止推进

    # pending_checkpoint不为NONE时，只允许checkpoint动作
    if pending_checkpoint != "NONE":
        return [f"run_checkpoint:{pending_checkpoint}", "wait_for_user_action"]

    # 正常流程：只允许resume_context声明的唯一动作
    if next_action:
        return [next_action]
    return []


def write_preflight_result(workspace_root: Path, state: dict[str, Any], stage: str, can_proceed: bool, allowed_actions: list[str]) -> None:
    """P3新增：输出preflight-result.json"""
    from datetime import datetime, timezone
    output_dir = workspace_root / ".harness" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    result_file = output_dir / PREFLIGHT_RESULT_FILE
    result = {
        "stage": stage,
        "can_proceed": can_proceed,
        "allowed_actions": allowed_actions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_common_files(results: list[CheckResult]) -> None:
    for path, item, message in [
        (SKILL_MD, "skill_md_exists", "SKILL.md入口存在"),
        (STATE_CONTRACT, "state_contract_exists", "状态契约说明存在"),
        (PHASE_DEP_RULE, "phase_dependency_rule_exists", "阶段能力依赖清单存在"),
    ]:
        if path.exists():
            add_result(results, "skill_entry", item, "PASS", None, message)
        else:
            add_result(results, "skill_entry", item, "FAIL", "BLOCKER", f"缺少关键文件：{path}")
    # PREFLIGHT_RULE 已移除，降级为 warning
    add_result(results, "skill_entry", "preflight_rule_deprecated", "WARN", "WARNING", "preflight检查规则文件已废弃，检查规则降级为内置逻辑")


def validate_runtime_state(stage: str, state_file: Path, results: list[CheckResult]) -> dict[str, Any] | None:
    if not state_file.exists():
        add_result(results, "runtime_state", "state_file_exists", "FAIL", "BLOCKER", "状态文件不存在且未先初始化")
        return None
    add_result(results, "runtime_state", "state_file_exists", "PASS", None, "状态文件存在")

    try:
        data = load_json(state_file)
        add_result(results, "runtime_state", "state_file_json", "PASS", None, "状态文件为合法JSON")
    except Exception as exc:  # pragma: no cover
        add_result(results, "runtime_state", "state_file_json", "FAIL", "BLOCKER", f"状态文件不是合法JSON: {exc}")
        return None

    integrity_error = verify_state_integrity(state_file, data)
    if integrity_error:
        add_result(results, "runtime_state", "state_integrity_valid", "FAIL", "BLOCKER", integrity_error)
    else:
        add_result(results, "runtime_state", "state_integrity_valid", "PASS", None, "状态完整性校验通过")

    if jsonschema is None:
        add_result(results, "runtime_state", "jsonschema_available", "FAIL", "BLOCKER", "jsonschema依赖不可用")
        return data

    if not STATE_SCHEMA.exists():
        add_result(results, "runtime_state", "state_schema_exists", "FAIL", "BLOCKER", f"状态Schema不存在: {STATE_SCHEMA}")
        return data

    try:
        schema = load_json(STATE_SCHEMA)
        jsonschema.validate(instance=data, schema=schema)
        add_result(results, "runtime_state", "state_schema_valid", "PASS", None, "状态文件符合当前Schema")
    except Exception as exc:
        add_result(results, "runtime_state", "state_schema_valid", "FAIL", "BLOCKER", f"状态文件不符合当前Schema: {exc}")

    view = legacy_view(data)
    current_phase = view.current_phase
    phase_status_raw = view.phase_status
    phase_status = phase_status_raw if isinstance(phase_status_raw, dict) else {}
    checkpoints_raw = view.checkpoints
    checkpoints = checkpoints_raw if isinstance(checkpoints_raw, dict) else {}
    resume_context = view.resume_context
    artifacts = view.artifacts
    if current_phase is not None and current_phase not in {*ALLOWED_STAGES, "DONE", "TERMINATED"}:
        add_result(results, "runtime_state", "current_phase_valid", "FAIL", "BLOCKER", f"current_phase非法: {current_phase}")
    if stage in phase_status and phase_status.get(stage) not in {"pending", "in_progress", "completed", "blocked"}:
        add_result(results, "runtime_state", "phase_status_valid", "FAIL", "BLOCKER", f"phase_status.{stage}非法: {phase_status.get(stage)}")
    elif phase_status.get(stage) not in {"in_progress", "completed"}:
        add_result(results, "runtime_state", "phase_status_alignment", "WARN", "WARNING", f"当前检查阶段为{stage}，但phase_status.{stage}={phase_status.get(stage)}")

    last_checkpoint_val = checkpoints.get("last_checkpoint")
    if last_checkpoint_val is not None and last_checkpoint_val not in ALLOWED_CHECKPOINTS:
        add_result(results, "runtime_state", "last_checkpoint_valid", "FAIL", "BLOCKER", f"last_checkpoint非法: {last_checkpoint_val}")
    elif last_checkpoint_val is None:
        add_result(results, "runtime_state", "last_checkpoint_valid", "WARN", "WARNING", "last_checkpoint未设置")
    state_contract_version = data.get("state_contract_version")
    if state_contract_version is None:
        add_result(results, "runtime_state", "state_contract_version_exists", "WARN", "WARNING", "state_contract_version缺失，当前按兼容模式继续")
    elif not isinstance(state_contract_version, str) or not state_contract_version.strip():
        add_result(results, "runtime_state", "state_contract_version_valid", "FAIL", "BLOCKER", f"state_contract_version非法: {state_contract_version}")
    else:
        add_result(results, "runtime_state", "state_contract_version_valid", "PASS", None, f"state_contract_version={state_contract_version}")
    if artifacts.get("phase_2", {}).get("allow_codegen") not in ALLOWED_ALLOW_CODEGEN:
        add_result(results, "runtime_state", "allow_codegen_valid", "FAIL", "BLOCKER", f"allow_codegen非法: {artifacts.get('phase_2', {}).get('allow_codegen')}")
    if checkpoints.get("awaiting_user_action") is True:
        add_result(results, "runtime_state", "awaiting_user_action", "FAIL", "BLOCKER", "awaiting_user_action=true，当前不应自动推进")
        # 等待态恢复动作绑定检查
        if isinstance(resume_context, dict):
            pending_checkpoint = resume_context.get("pending_checkpoint", "NONE")
            if pending_checkpoint not in ALLOWED_CHECKPOINTS:
                add_result(results, "runtime_state", "awaiting_pending_checkpoint", "FAIL", "BLOCKER", f"等待态pending_checkpoint无效: {pending_checkpoint}，期望: {', '.join(sorted(ALLOWED_CHECKPOINTS))}")
            next_required_action = resume_context.get("next_required_action", "")
            if next_required_action != "wait_for_user_action":
                add_result(results, "runtime_state", "awaiting_next_action", "FAIL", "BLOCKER", f"等待态next_required_action错配: {next_required_action}，必须为wait_for_user_action")
            required_script = resume_context.get("required_script", "")
            if "phase-handoff.py --user-action" not in required_script:
                add_result(results, "runtime_state", "awaiting_required_script", "FAIL", "BLOCKER", f"等待态required_script必须包含phase-handoff.py --user-action: {required_script}")
    checkpoint_emitted_at = checkpoints.get("checkpoint_emitted_at")
    if checkpoint_emitted_at is not None and not isinstance(checkpoint_emitted_at, str):
        add_result(results, "runtime_state", "checkpoint_emitted_at_type", "FAIL", "BLOCKER", f"checkpoint_emitted_at类型非法: {type(checkpoint_emitted_at).__name__}")
    elif checkpoints.get("last_checkpoint") == "NONE" and checkpoint_emitted_at not in {None, ""}:
        add_result(results, "runtime_state", "checkpoint_emitted_at_cleared", "FAIL", "BLOCKER", "last_checkpoint=NONE时，checkpoint_emitted_at必须为空")
    elif checkpoints.get("last_checkpoint") != "NONE" and checkpoints.get("awaiting_user_action") is True and not checkpoint_emitted_at:
        add_result(results, "runtime_state", "checkpoint_emitted_at_waiting", "FAIL", "BLOCKER", "等待用户动作且last_checkpoint!=NONE时，checkpoint_emitted_at不能为空")
    else:
        add_result(results, "runtime_state", "checkpoint_emitted_at_shape", "PASS", None, "checkpoint_emitted_at结构合法")

    if current_phase in {*ALLOWED_STAGES, *TERMINAL_PHASE_ACTIONS.keys()}:
        if not isinstance(resume_context, dict):
            add_result(results, "runtime_state", "resume_context_exists", "FAIL", "BLOCKER", "resume_context缺失，无法作为恢复控制面继续执行")
            return data
        required_resume_keys = {
            "current_execution_unit",
            "next_required_action",
            "required_script",
            "pending_checkpoint",
            "resume_first_prompt",
            "last_review_status",
        }
        missing_resume_keys = sorted(key for key in required_resume_keys if key not in resume_context)
        if missing_resume_keys:
            add_result(results, "runtime_state", "resume_context_keys", "FAIL", "BLOCKER", f"resume_context缺少字段: {', '.join(missing_resume_keys)}")
        elif resume_context.get("last_review_status") not in RESUME_REVIEW_STATUSES:
            add_result(results, "runtime_state", "resume_review_status", "FAIL", "BLOCKER", f"resume_context.last_review_status非法: {resume_context.get('last_review_status')}")
        else:
            add_result(results, "runtime_state", "resume_context_shape", "PASS", None, "resume_context控制面结构完整")

        current_execution_unit = resume_context.get("current_execution_unit")
        pending_checkpoint = resume_context.get("pending_checkpoint")
        next_required_action = resume_context.get("next_required_action")
        required_script = resume_context.get("required_script")

        if current_phase == "gen":
            phase_3 = artifacts.get("phase_3", {})
            current_node = phase_3.get("current_node")
            nodes = phase_3.get("nodes", {})
            if current_node is not None and not isinstance(current_node, str):
                add_result(results, "runtime_state", "gen_current_node_type", "FAIL", "BLOCKER", f"phase_3.current_node类型非法: {type(current_node).__name__}")
            if not isinstance(nodes, dict):
                add_result(results, "runtime_state", "gen_nodes_type", "FAIL", "BLOCKER", "phase_3.nodes必须为对象")
            else:
                if isinstance(current_node, str) and current_node and current_node not in nodes:
                    add_result(results, "runtime_state", "gen_current_node_exists", "FAIL", "BLOCKER", f"phase_3.current_node未在phase_3.nodes中注册: {current_node}")
                elif isinstance(current_node, str) and current_node and current_execution_unit != current_node:
                    add_result(results, "runtime_state", "gen_execution_unit_alignment", "FAIL", "BLOCKER", f"resume_context.current_execution_unit应与phase_3.current_node一致: {current_execution_unit} != {current_node}")
                elif current_node is None and current_execution_unit != "gen":
                    add_result(results, "runtime_state", "gen_execution_unit_alignment", "FAIL", "BLOCKER", f"gen阶段未绑定current_node时，resume_context.current_execution_unit必须为gen，当前为: {current_execution_unit}")
                else:
                    add_result(results, "runtime_state", "gen_execution_unit_alignment", "PASS", None, "gen阶段执行单元与current_node一致")
                if isinstance(current_node, str) and current_node and current_node in nodes:
                    node_state = nodes.get(current_node, {})
                    if isinstance(node_state, dict):
                        verification = node_state.get("verification")
                        if isinstance(verification, dict):
                            review_status = verification.get("review_status")
                            # P3新增：校验last_review_status为rework_required/rejected时必须返工或少量修补
                            last_review_status = resume_context.get("last_review_status")
                            if last_review_status in RESUME_BLOCKING_REVIEW_STATUSES:
                                if next_required_action.startswith("dispatch_gen_node_worker:") and not next_required_action.endswith(f":{current_node}"):
                                    add_result(results, "runtime_state", "rework_node_alignment", "FAIL", "BLOCKER",
                                               f"last_review_status={last_review_status}时必须返工当前节点{current_node}，禁止派发其他节点: {next_required_action}")
                                if next_required_action.startswith("run_preflight:") or next_required_action.startswith("run_checkpoint:"):
                                    add_result(results, "runtime_state", "rework_action_blocked", "FAIL", "BLOCKER",
                                               f"last_review_status={last_review_status}时禁止推进阶段或checkpoint，必须先返工: {next_required_action}")
                            if review_status != resume_context.get("last_review_status"):
                                add_result(results, "runtime_state", "gen_review_status_alignment", "FAIL", "BLOCKER", f"resume_context.last_review_status应与当前节点review_status一致: {resume_context.get('last_review_status')} != {review_status}")
                            if review_status in {"approved", "rework_required", "rejected"} and not str(node_state.get("last_review_report", "")).strip():
                                add_result(results, "runtime_state", "gen_review_report_presence", "FAIL", "BLOCKER", f"{current_node}已产生review结论，但last_review_report为空")
                            if verification.get("compile_status") == "failed" and not str(node_state.get("compile_log_path", "")).strip():
                                add_result(results, "runtime_state", "gen_compile_log_presence", "FAIL", "BLOCKER", f"{current_node}.compile_status=failed时，compile_log_path不能为空")
        elif current_execution_unit != current_phase:
            # P3新增：校验current_execution_unit与current_phase一致性
            add_result(results, "runtime_state", "execution_unit_phase_mismatch", "FAIL", "BLOCKER",
                       f"resume_context.current_execution_unit={current_execution_unit}与current_phase={current_phase}不一致")

        action_binding_error = validate_resume_action_binding(
            current_phase,
            current_execution_unit,
            next_required_action,
            required_script,
        )
        if action_binding_error:
            add_result(results, "runtime_state", "resume_action_binding", "FAIL", "BLOCKER", action_binding_error)

        # P3新增：pending_checkpoint不为NONE时必须先处理checkpoint
        pending_checkpoint = resume_context.get("pending_checkpoint")
        if pending_checkpoint != "NONE":
            if not next_required_action.startswith("run_checkpoint:") and next_required_action != "wait_for_user_action":
                add_result(results, "runtime_state", "pending_checkpoint_action", "FAIL", "BLOCKER",
                           f"pending_checkpoint={pending_checkpoint}时必须先处理checkpoint，当前next_required_action={next_required_action}")
            if checkpoints.get("awaiting_user_action") is not True:
                add_result(results, "runtime_state", "pending_checkpoint_awaiting", "FAIL", "BLOCKER",
                           f"pending_checkpoint={pending_checkpoint}时awaiting_user_action必须为true")

        if checkpoints.get("awaiting_user_action") is True:
            if pending_checkpoint != checkpoints.get("last_checkpoint"):
                add_result(results, "runtime_state", "pending_checkpoint_alignment", "FAIL", "BLOCKER", "等待用户动作时，resume_context.pending_checkpoint必须等于last_checkpoint")
            if next_required_action != "wait_for_user_action":
                add_result(results, "runtime_state", "resume_next_action_wait", "FAIL", "BLOCKER", f"等待用户动作时next_required_action非法: {next_required_action}")
            if "phase-handoff.py --user-action" not in required_script:
                add_result(results, "runtime_state", "resume_required_script_wait", "FAIL", "BLOCKER", f"等待用户动作时required_script非法: {required_script}")
        else:
            if pending_checkpoint != "NONE":
                add_result(results, "runtime_state", "pending_checkpoint_cleared", "FAIL", "BLOCKER", f"非等待态时pending_checkpoint必须为NONE，当前为: {pending_checkpoint}")
            if not required_script:
                add_result(results, "runtime_state", "resume_required_script_set", "FAIL", "BLOCKER", "非等待态时required_script不能为空")

    return data


def expected_artifact_path(data: dict[str, Any], stage: str, base_root: Path | None = None) -> Path:
    code = data.get("institution", {}).get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("institution.code缺失，无法限定阶段产物范围")
    code = code.strip()
    root = base_root or PROJECT_ROOT
    if stage == "spec":
        return root / ".harness" / "output" / "req" / code / f"harness-req-facts-{code}.json"
    if stage == "prove":
        return root / ".harness" / "output" / "spec" / code / f"harness-issue-routing-{code}.json"
    raise ValueError(f"不支持的阶段产物: {stage}")


def validate_json_artifacts(files: list[Path], schema_path: Path, results: list[CheckResult], item_prefix: str) -> None:
    if not files:
        add_result(results, "stage_input", f"{item_prefix}_exists", "FAIL", "BLOCKER", "正式JSON产物不存在")
        return
    if not schema_path.exists():
        add_result(results, "stage_input", f"{item_prefix}_schema_exists", "FAIL", "BLOCKER", f"缺少Schema: {schema_path}")
        return
    try:
        schema = load_json(schema_path)
    except Exception as exc:
        add_result(results, "stage_input", f"{item_prefix}_schema_parse", "FAIL", "BLOCKER", f"Schema不可解析: {exc}")
        return

    for artifact in files:
        try:
            payload = load_json(artifact)
            if schema_path == HARNESS_ISSUE_ROUTING_SCHEMA:
                # prove_routing_compat removed in generalization — payload passed through as-is
                pass
        except Exception as exc:
            add_result(results, "stage_input", f"{item_prefix}_json_parse", "FAIL", "BLOCKER", f"JSON不可解析: {artifact}: {exc}")
            continue
        try:
            jsonschema.validate(instance=payload, schema=schema)
        except Exception as exc:
            add_result(results, "stage_input", f"{item_prefix}_schema_valid", "FAIL", "BLOCKER", f"JSON不符合Schema: {artifact}: {exc}")
            continue
    if not any(r.item.startswith(item_prefix) and r.status == "FAIL" for r in results):
        add_result(results, "stage_input", f"{item_prefix}_validated", "PASS", None, "正式JSON产物存在、可解析且符合Schema")


def validate_stage_inputs(
    stage: str,
    state_file: Path,
    data: dict[str, Any] | None,
    source_doc: Path | None,
    output_dir: Path | None,
    results: list[CheckResult],
) -> None:
    workspace_root = workspace_root_for(state_file)
    if stage == "prep":
        if source_doc is None:
            add_result(results, "stage_input", "source_doc_arg", "FAIL", "BLOCKER", "prep阶段缺少--source-doc")
        elif not source_doc.exists():
            add_result(results, "stage_input", "source_doc_exists", "FAIL", "BLOCKER", f"文档输入不存在: {source_doc}")
        else:
            files = [p for p in source_doc.rglob("*") if p.is_file()] if source_doc.is_dir() else [source_doc]
            if not files:
                add_result(results, "stage_input", "source_doc_non_empty", "FAIL", "BLOCKER", "文档输入目录为空")
            else:
                add_result(results, "stage_input", "source_doc_non_empty", "PASS", None, "文档输入目录非空")
                doc_files = [p for p in files if p.suffix.lower() in DOC_EXTENSIONS]
                cert_files = [p for p in files if p.suffix.lower() in CERT_EXTENSIONS]
                parser_resolution = resolve_capability("doc_parse", workspace_root)
                parser_skill_path = parser_resolution.skill_path if parser_resolution else detect_doc_parser(workspace_root)
                if parser_resolution:
                    if parser_resolution.issue:
                        add_result(
                            results,
                            "doc_parse",
                            "doc_parse_capability_override_missing",
                            "FAIL",
                            "BLOCKER",
                            parser_resolution.issue,
                        )
                        return
                    add_result(
                        results,
                        "doc_parse",
                        "doc_parse_capability_resolved",
                        "PASS",
                        None,
                        f"doc_parse能力已解析为skill:{parser_resolution.skill_name}（来源:{parser_resolution.source}）",
                    )
                if parser_skill_path:
                    add_result(results, "doc_parse", "doc_parser_skill", "PASS", None, f"文档解析skill可用: {parser_skill_path}")
                elif doc_files:
                    ok, tools, warnings = detect_doc_parse_capability(doc_files)
                    if ok:
                        add_result(results, "doc_parse", "fallback_chain_available", "WARN", "WARNING", f"doc_parse能力未解析，将fallback到平台工具链: {', '.join(tools) or '弱fallback'}")
                    else:
                        add_result(results, "doc_parse", "fallback_chain_available", "FAIL", "BLOCKER", "存在.doc/.docx/.pdf输入，但完全没有可用解析链")
                    for warning in warnings:
                        add_result(results, "doc_parse", "fallback_chain_warning", "WARN", "WARNING", warning)
                if cert_files:
                    add_result(results, "doc_parse", "attachments_detected", "INFO", "INFO", f"检测到附件文件{len(cert_files)}个，当前阶段只做识别")

        if output_dir is None:
            add_result(results, "stage_input", "output_dir_arg", "FAIL", "BLOCKER", "prep阶段缺少--output-dir")
        elif not output_dir.exists():
            add_result(results, "stage_input", "output_dir_exists", "FAIL", "BLOCKER", f"prep输出目录不存在: {output_dir}")
        elif not output_dir.is_dir() or not os_writable(output_dir):
            add_result(results, "stage_input", "output_dir_writable", "FAIL", "BLOCKER", f"prep输出目录不可写: {output_dir}")
        else:
            add_result(results, "stage_input", "output_dir_writable", "PASS", None, "prep输出目录可写")
        return

    if data is None:
        return

    view = legacy_view(data) if data is not None else None
    phase_status_raw = view.phase_status if view else {}
    phase_status = phase_status_raw if isinstance(phase_status_raw, dict) else {}
    checkpoints_raw = view.checkpoints if view else []
    checkpoints = checkpoints_raw if isinstance(checkpoints_raw, dict) else {}
    gate_context = checkpoints.get("gate_context", {})
    artifacts = view.artifacts if view else {}
    questions = data.get("questions", {}) if data is not None else {}
    phase1_outputs = artifacts.get("phase_1", {}).get("outputs", [])

    def generated_file_path(raw_path: str) -> Path:
        path = Path(raw_path)
        return path if path.is_absolute() else workspace_root / path

    if stage == "spec":
        if phase_status.get("prep") != "completed":
            add_result(results, "stage_input", "prep_completed", "FAIL", "BLOCKER", "prep未完成")
        facts_exists = any("prep-facts-" in p for p in phase1_outputs)
        evidence_exists = any("prep-evidence-" in p for p in phase1_outputs)
        if not facts_exists:
            add_result(results, "stage_input", "prep_facts_exists", "FAIL", "BLOCKER", "prep-facts-*.md不存在")
        if not evidence_exists:
            add_result(results, "stage_input", "prep_evidence_exists", "FAIL", "BLOCKER", "prep-evidence-*.md不存在")
        return

    if stage == "prove":
        if phase_status.get("spec") != "completed":
            add_result(results, "stage_input", "spec_completed", "FAIL", "BLOCKER", "spec未完成")
        if checkpoints.get("last_checkpoint") != "spec-ok":
            add_result(results, "stage_input", "spec_ok_reached", "FAIL", "BLOCKER", "spec-ok未达到")
        try:
            spec_artifact = expected_artifact_path(data, "spec", workspace_root_for(state_file))
        except ValueError as exc:
            add_result(results, "stage_input", "spec_json_scope", "FAIL", "BLOCKER", str(exc))
            return
        validate_json_artifacts(
            [spec_artifact] if spec_artifact.exists() else [],
            HARNESS_REQ_FACTS_SCHEMA,
            results,
            "spec_json",
        )
        if checkpoints.get("last_checkpoint") == "prove-ok" and gate_context.get("business_fact_validation_passed") is not True:
            add_result(results, "stage_input", "business_fact_gate", "FAIL", "BLOCKER", "已达到prove-ok，但business_fact_validation_passed未写为true")
        return

    if stage == "gen":
        if phase_status.get("prove") != "completed":
            add_result(results, "stage_input", "prove_completed", "FAIL", "BLOCKER", "prove未完成")
        if checkpoints.get("last_checkpoint") != "prove-ok":
            add_result(results, "stage_input", "prove_ok_reached", "FAIL", "BLOCKER", "prove-ok未达到")
        try:
            prove_artifact = expected_artifact_path(data, "prove", workspace_root_for(state_file))
        except ValueError as exc:
            add_result(results, "stage_input", "prove_json_scope", "FAIL", "BLOCKER", str(exc))
            return
        validate_json_artifacts(
            [prove_artifact] if prove_artifact.exists() else [],
            HARNESS_ISSUE_ROUTING_SCHEMA,
            results,
            "prove_json",
        )
        if artifacts.get("phase_2", {}).get("allow_codegen") == "NO":
            add_result(results, "stage_input", "allow_codegen_no", "FAIL", "BLOCKER", "allow_codegen == NO")
        if any(item.get("routing") == "human_required" and item.get("status") == "pending" for item in questions.get("open", []) if isinstance(item, dict)):
            add_result(results, "stage_input", "human_required_pending", "FAIL", "BLOCKER", "关键问题仍处于human_required待确认")
        phase_3 = artifacts.get("phase_3", {})
        layers = phase_3.get("layers", {})
        nodes = phase_3.get("nodes", {})
        if not isinstance(nodes, dict):
            add_result(results, "stage_input", "gen_nodes_present", "FAIL", "BLOCKER", "gen阶段phase_3.nodes缺失或非法")
            return
        for layer_name, required_nodes in GEN_LAYER_NODE_MAP.items():
            layer_state = layers.get(layer_name, {})
            if not isinstance(layer_state, dict):
                continue
            if layer_state.get("status") == "completed":
                missing_completed = [
                    node_id for node_id in required_nodes
                    if not isinstance(nodes.get(node_id), dict) or nodes.get(node_id, {}).get("status") != "completed"
                ]
                if missing_completed:
                    add_result(results, "stage_input", f"{layer_name}_node_completion", "FAIL", "BLOCKER", f"{layer_name}标记completed，但节点未完成: {', '.join(missing_completed)}")
        for node_id, prereqs in GEN_NODE_PREREQS.items():
            node_state = nodes.get(node_id)
            if not isinstance(node_state, dict):
                continue
            if node_state.get("status") in {"in_progress", "completed"}:
                unmet = [
                    dep for dep in prereqs
                    if not isinstance(nodes.get(dep), dict) or nodes.get(dep, {}).get("status") != "completed"
                ]
                if unmet:
                    add_result(results, "stage_input", f"{node_id}_prereqs", "FAIL", "BLOCKER", f"{node_id}已启动，但前置节点未完成: {', '.join(unmet)}")
            generated_files = node_state.get("generated_files", [])
            if node_state.get("status") == "completed" and isinstance(generated_files, list):
                missing_generated = [
                    raw_path for raw_path in generated_files
                    if isinstance(raw_path, str) and raw_path.strip() and not generated_file_path(raw_path).exists()
                ]
                if missing_generated:
                    add_result(
                        results,
                        "stage_input",
                        f"{node_id}_generated_files_exist",
                        "FAIL",
                        "BLOCKER",
                        f"{node_id}已完成，但声明产物不存在: {', '.join(missing_generated)}",
                    )
        current_node = phase_3.get("current_node")
        if isinstance(current_node, str):
            current_state = nodes.get(current_node)
            if not isinstance(current_state, dict):
                add_result(results, "stage_input", "current_node_registered", "FAIL", "BLOCKER", f"current_node未在nodes中注册: {current_node}")
            elif current_state.get("status") not in {"pending", "in_progress", "completed"}:
                add_result(results, "stage_input", "current_node_status", "FAIL", "BLOCKER", f"current_node状态非法: {current_node}={current_state.get('status')}")
        return

    if stage == "final":
        if phase_status.get("gen") != "completed":
            add_result(results, "stage_input", "gen_completed", "FAIL", "BLOCKER", "gen未完成")
        phase_4 = artifacts.get("phase_4", {})
        audit_report = phase_4.get("audit_report")
        if isinstance(audit_report, str) and audit_report.strip():
            report_validation = validate_final_report(workspace_root, data)
            if not report_validation.ok:
                add_result(results, "stage_input", "audit_report_contract_final", "FAIL", "BLOCKER", f"final阶段audit_report不合法: {report_validation.reason}")
            else:
                add_result(results, "stage_input", "audit_report_contract_final", "PASS", None, "final阶段audit_report契约合法")
        else:
            add_result(results, "stage_input", "audit_report_contract_final", "WARN", "WARNING", "final阶段尚未生成audit_report，允许进入final阶段产出报告")
        phase_3 = artifacts.get("phase_3", {})
        layers = phase_3.get("layers", {})
        nodes = phase_3.get("nodes", {})
        missing_layers = [layer_name for layer_name in GEN_LAYERS if layer_name not in layers]
        if missing_layers:
            add_result(results, "stage_input", "required_layers_present", "FAIL", "BLOCKER", f"缺少必需gen层: {', '.join(missing_layers)}")
        if not isinstance(nodes, dict):
            add_result(results, "stage_input", "gen_nodes_present_final", "FAIL", "BLOCKER", "final阶段缺少phase_3.nodes")
            return
        for node_id, prereqs in GEN_NODE_PREREQS.items():
            node_state = nodes.get(node_id)
            if not isinstance(node_state, dict):
                add_result(results, "stage_input", f"{node_id}_present_final", "FAIL", "BLOCKER", f"final阶段缺少节点状态: {node_id}")
                continue
            if node_state.get("status") != "completed":
                add_result(results, "stage_input", f"{node_id}_completed_final", "FAIL", "BLOCKER", f"final阶段节点未完成: {node_id}")
                continue
            verification = node_state.get("verification")
            if not isinstance(verification, dict):
                add_result(results, "stage_input", f"{node_id}_verification_final", "FAIL", "BLOCKER", f"final阶段节点缺少verification: {node_id}")
            else:
                if verification.get("review_status") != "approved":
                    add_result(results, "stage_input", f"{node_id}_review_final", "FAIL", "BLOCKER", f"final阶段{node_id}.review_status必须为approved")
                if verification.get("script_status") != "passed":
                    add_result(results, "stage_input", f"{node_id}_script_final", "FAIL", "BLOCKER", f"final阶段{node_id}.script_status必须为passed")
                if verification.get("compile_status") == "failed":
                    add_result(results, "stage_input", f"{node_id}_compile_final", "FAIL", "BLOCKER", f"final阶段{node_id}.compile_status不能为failed")
            unmet = [
                dep for dep in prereqs
                if not isinstance(nodes.get(dep), dict) or nodes.get(dep, {}).get("status") != "completed"
            ]
            if unmet:
                add_result(results, "stage_input", f"{node_id}_prereqs_final", "FAIL", "BLOCKER", f"final阶段{node_id}前置节点未完成: {', '.join(unmet)}")
        for layer_name in GEN_LAYERS:
            layer_state = layers.get(layer_name)
            if not isinstance(layer_state, dict):
                add_result(results, "stage_input", "layer_state_valid", "FAIL", "BLOCKER", f"{layer_name}状态缺失或非法")
                continue
            if layer_state.get("status") != "completed":
                add_result(results, "stage_input", "layer_completed", "FAIL", "BLOCKER", f"{layer_name}未完成")
            required_nodes = GEN_LAYER_NODE_MAP.get(layer_name, [])
            missing_completed = [
                node_id for node_id in required_nodes
                if not isinstance(nodes.get(node_id), dict) or nodes.get(node_id, {}).get("status") != "completed"
            ]
            if missing_completed:
                add_result(results, "stage_input", f"{layer_name}_node_completion_final", "FAIL", "BLOCKER", f"{layer_name}标记completed，但节点未完成: {', '.join(missing_completed)}")
            if layer_name == "admin_sql_i18n" and layer_state.get("compile_status") in {"failed", "not_run"}:
                add_result(results, "stage_input", "admin_compile_status", "FAIL", "BLOCKER", f"{layer_name}编译状态非法: {layer_state.get('compile_status')}")


def os_writable(path: Path) -> bool:
    try:
        return path.is_dir() and os.access(path, os.W_OK)
    except Exception:
        return False


def audit_report_path_valid(data: dict[str, Any], workspace_root: Path) -> bool:
    return validate_final_report(workspace_root, data).ok


def render_text(stage: str, results: list[CheckResult], summary: dict[str, int], decision: tuple[bool, str]) -> str:
    lines = [f"=== Preflight Check: {stage} ==="]
    for item in results:
        level = item.severity or item.status
        lines.append(f"[{level}] {item.message}")
    lines.append("=============================")
    lines.append("")
    lines.append(f"[Result] BLOCKER: {summary['blocker_count']}项，WARNING: {summary['warning_count']}项")
    lines.append(f"[Action] {decision[1]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="HARNESS workflow preflight checker")
    parser.add_argument("--stage", required=True, choices=sorted(ALLOWED_STAGES))
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--source-doc")
    parser.add_argument("--output-dir")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json-output", action="store_true")
    args = parser.parse_args()
    state_file = Path(args.state_file)
    workspace_root = workspace_root_for(state_file)

    results: list[CheckResult] = []
    validate_common_files(results)
    if has_command("python3"):
        add_result(results, "toolchain", "python3_available", "PASS", None, "python3可用")
    else:  # pragma: no cover
        add_result(results, "toolchain", "python3_available", "FAIL", "BLOCKER", "python3不可用")
    if jsonschema is None:
        add_result(results, "toolchain", "jsonschema_available", "FAIL", "BLOCKER", "jsonschema依赖不可用")
    else:
        add_result(results, "toolchain", "jsonschema_available", "PASS", None, "jsonschema依赖可用")
    has_gradle_wrapper = (workspace_root / "gradlew").exists() or (workspace_root / "gradlew.bat").exists()
    if not has_command("mvn") and not has_command("gradle") and not has_gradle_wrapper:
        add_result(results, "toolchain", "build_tool_available", "WARN", "WARNING", "未检测到mvn或gradle，后续本地编译验证能力可能下降")

    state_data = validate_runtime_state(args.stage, state_file, results)
    validate_stage_inputs(
        args.stage,
        state_file,
        state_data,
        Path(args.source_doc) if args.source_doc else None,
        Path(args.output_dir) if args.output_dir else None,
        results,
    )

    summary = summarize(results)
    can_proceed, reason = decide(summary, args.strict)

    # P3新增：计算允许动作并输出preflight-result.json
    allowed_actions = []
    if state_data:
        allowed_actions = compute_allowed_actions(state_data, args.stage)
        write_preflight_result(workspace_root, state_data, args.stage, can_proceed, allowed_actions)

    if args.json_output:
        output = {
            "stage": args.stage,
            "checks": [asdict(item) for item in results],
            "summary": summary,
            "decision": {"can_proceed": can_proceed, "reason": reason},
            "allowed_actions": allowed_actions,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(render_text(args.stage, results, summary, (can_proceed, reason)))

    return 0 if can_proceed else 1


if __name__ == "__main__":
    raise SystemExit(main())
