#!/usr/bin/env python3
# Generalized from state-contracts payment-workflow-state-contracts branch
"""
HARNESS Orchestrator
====================
统一的工作流调度器。负责：
1. 按阶段 (spec/prove/plan) 加载状态契约文件。
2. 执行 JSON Schema 校验（契约完整性验证）。
3. 在 harness-workflow-state 主线下执行受控门禁校验。
4. 按需串联结构化校验器，形成正式测试断言入口。
5. 在 plan 阶段执行 DAG 拓扑排序与沙箱路径检查。
"""
import json
import sys
import argparse
import subprocess
import os
from pathlib import Path
from collections import defaultdict, deque
from datetime import datetime, timezone
import tempfile

from .final_report_contract import validate_final_report
from .prove_routing_compat import normalize_legacy_prove_routing_payload
from .state_integrity import verify_state_integrity
from .task_identity import derive_task_id

try:
    import jsonschema
    from jsonschema import validate, ValidationError, Draft7Validator
except ImportError:
    print("[Blocker] jsonschema 库未安装，无法执行契约校验！")
    print("[Blocker] 请运行: pip install jsonschema")
    sys.exit(1)


class StageOrchestrator:
    """HARNESS Orchestrator - 通用工作流调度器"""

    # Schema 文件路径映射
    SCHEMA_PATHS = {
        "spec": ".harness/schemas/harness-spec-state.v1.schema.json",
        "prove": ".harness/schemas/harness-prove-state.v1.schema.json",
        "plan": ".harness/schemas/harness-plan-state.v1.schema.json",
    }
    HARNESS_WORKFLOW_SCHEMA = (
        ".harness/schemas/harness-workflow-state.schema.json"
    )
    HARNESS_REQ_FACTS_SCHEMA = ".harness/schemas/harness-req-facts.v1.schema.json"
    HARNESS_ISSUE_ROUTING_SCHEMA = ".harness/schemas/harness-issue-routing.v1.schema.json"
    CONTROLLED_CHECKPOINTS = {"NONE", "spec-ok", "prove-ok", "layer-ok", "final-ok"}
    CONTROLLED_ALLOW_CODEGEN = {"UNSET", "YES", "NO", "YES_WITH_WARNING"}
    CONTROLLED_REVIEW_STATUS = {"pending", "approved", "rework_required", "rejected"}
    STAGE_MANIFEST_REQUIRED_FIELDS = {
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
    }
    GEN_NODE_MANIFEST_REQUIRED_FIELDS = {
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
    }
    # Externalized to .harness/config/dag-blueprint.yaml
    # GEN_LAYER_NODE_MAP = {
    #     "pojo_config_dto": ["G01", "G02", "G03"],
    #     "dependency_provider": ["G04"],
    #     "adapter_notify": ["G05", "G06"],
    #     "admin_sql_i18n": ["G07", "G08", "G09"],
    # }
    # GEN_NODE_PREREQS = {
    #     "G01": [],
    #     "G02": ["G01"],
    #     "G03": ["G02"],
    #     "G04": ["G03"],
    #     "G05": ["G04"],
    #     "G06": ["G02", "G03"],
    #     "G07": ["G01"],
    #     "G08": ["G01"],
    #     "G09": ["G02", "G07", "G08"],
    # }
    TERMINAL_PHASE_ACTIONS = {
        "DONE": ("archive_runtime", "archive-harness-workflow.py --archive-only"),
        "TERMINATED": ("archive_runtime", "archive-harness-workflow.py --archive-only"),
    }

    @staticmethod
    def _load_dag_blueprint(workdir: Path) -> tuple[dict, dict]:
        """Load GEN_LAYER_NODE_MAP and GEN_NODE_PREREQS from external dag-blueprint.yaml.

        Returns (gen_layer_node_map, gen_node_prereqs) tuples.
        Falls back to empty dicts if the config file is not present.
        """
        # TODO: Implement YAML loading from .harness/config/dag-blueprint.yaml
        # For now, return empty defaults - the blueprint must be provided externally
        import yaml  # noqa: F811
        blueprint_path = workdir / ".harness" / "config" / "dag-blueprint.yaml"
        if not blueprint_path.exists():
            print(f"[Warning] dag-blueprint.yaml not found at {blueprint_path}, using empty defaults")
            return {}, {}
        with open(blueprint_path, 'r', encoding='utf-8') as f:
            blueprint = yaml.safe_load(f) or {}
        layer_node_map = blueprint.get("gen_layer_node_map", {})
        node_prereqs = blueprint.get("gen_node_prereqs", {})
        return layer_node_map, node_prereqs

    @staticmethod
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

    @staticmethod
    def validate_resume_action_binding(
        current_phase: str,
        current_execution_unit: str | None,
        next_required_action: str | None,
        required_script: str | None,
    ) -> str | None:
        if not isinstance(next_required_action, str) or not next_required_action:
            return "resume_context.next_required_action不能为空。"
        required_script = required_script or ""
        if current_phase in StageOrchestrator.TERMINAL_PHASE_ACTIONS:
            expected_action, expected_script = StageOrchestrator.TERMINAL_PHASE_ACTIONS[current_phase]
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

    def __init__(
        self,
        state_file: str,
        stage: str,
        workdir: str = ".",
        strict: bool = False,
        legacy_mode: bool = False,
        run_preflight: bool = False,
        source_doc: str | None = None,
        output_dir: str | None = None,
        business_facts_input: str | None = None,
        config_boundary_input: str | None = None,
        coverage_input: str | None = None,
        prove_routing_input: str | None = None,
        task_manifest: str | None = None,
        next_action_plan_output: str | None = None,
        execute_next_action: bool = False,
        next_action_execution_output: str | None = None,
    ):
        self.state_path = Path(state_file)
        self.stage = stage
        self.workdir = Path(workdir)
        self.strict = strict
        self.legacy_mode = legacy_mode
        self.run_preflight_first = run_preflight
        self.source_doc = Path(source_doc) if source_doc else None
        self.output_dir = Path(output_dir) if output_dir else None
        self.business_facts_input = Path(business_facts_input) if business_facts_input else None
        self.config_boundary_input = Path(config_boundary_input) if config_boundary_input else None
        self.coverage_input = Path(coverage_input) if coverage_input else None
        self.prove_routing_input = Path(prove_routing_input) if prove_routing_input else None
        self.task_manifest = Path(task_manifest) if task_manifest else None
        self.next_action_plan_output = Path(next_action_plan_output) if next_action_plan_output else None
        self.execute_next_action_enabled = execute_next_action
        self.next_action_execution_output = (
            Path(next_action_execution_output) if next_action_execution_output else None
        )
        self.data = None
        self.schema = None
        self.sorted_steps = []
        self.state_kind = "legacy"
        self._violations = []  # 记录检测到的违规

    def save_state(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def fail_gen_gate(self, message: str, node_id: str | None = None):
        print(f"[Blocker] {message}")
        sys.exit(1)

    def validate_current_gen_node_gate(
        self,
        node_id: str,
        node_state: dict,
        next_required_action: str | None,
    ) -> str | None:
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

    def load_schema(self):
        """加载对应阶段的 JSON Schema"""
        if self.stage == "plan":
            schema_rel = self.SCHEMA_PATHS.get(self.stage)
        elif self.state_kind == "harness_workflow":
            schema_rel = self.HARNESS_WORKFLOW_SCHEMA
        else:
            schema_rel = self.SCHEMA_PATHS.get(self.stage)

        if not schema_rel:
            print(f"[Error] 未知阶段: {self.stage}")
            sys.exit(1)

        schema_path = self.workdir / schema_rel
        if not schema_path.exists():
            print(f"[Error] Schema 文件不存在: {schema_path}")
            sys.exit(1)

        with open(schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)

        print(f"[*] 成功加载 {self.stage.upper()} 阶段 Schema: {schema_path.name}")

    def validate_schema(self):
        """执行 JSON Schema 校验"""
        print(f"\n--- 执行 {self.stage.upper()} 阶段 Schema 校验 ---")
        try:
            validate(instance=self.data, schema=self.schema)
            print(f"[Success] Schema 校验通过，契约结构完整。")
        except ValidationError as e:
            print(f"[Blocker] Schema 校验失败！契约结构不合规：")
            print(f"  路径: {'.'.join(str(p) for p in e.absolute_path)}")
            print(f"  错误: {e.message}")
            schema_title = self.schema.get("title") or "当前阶段Schema"
            print(f"\n[Action] 请修正状态文件，使其符合 {schema_title} 定义。")
            sys.exit(1)

    def load_state(self):
        """加载状态文件（含 Markdown 标记检测与清洗防抖）"""
        if not self.state_path.exists():
            print(f"[Error] 状态文件不存在: {self.state_path}")
            sys.exit(1)
        with open(self.state_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()
        content = raw_content.strip()

        # 检测违规：Markdown 包裹
        has_markdown_wrapper = False
        if content.startswith("```json"):
            has_markdown_wrapper = True
            content = content[7:]
        if content.startswith("```"):
            has_markdown_wrapper = True
            content = content[3:]
        if content.endswith("```"):
            has_markdown_wrapper = True
            content = content[:-3]
        content = content.strip()

        # 检测违规：前后废话（不以 { 开头或不以 } 结尾）
        has_prefix_chatter = not content.startswith("{")
        has_suffix_chatter = not content.endswith("}")

        # 截取第一个 { 和最后一个 } 之间的内容
        start_idx = content.find('{')
        end_idx = content.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            content = content[start_idx:end_idx + 1]

        # 收集违规信息
        if has_markdown_wrapper:
            self._violations.append("输出被 Markdown 代码块包裹（```json 或 ```）")
        if has_prefix_chatter:
            self._violations.append(f"开头有多余文本：{raw_content[:50].strip()[:30]}...")
        if has_suffix_chatter:
            self._violations.append(f"结尾有多余文本：...{raw_content[-50:].strip()[-30]}")

        # strict 模式：检测到违规时报 Warning 或 Blocker
        if self.strict and self._violations:
            print("\n--- 执行 Strict 模式纯 JSON 校验 ---")
            for v in self._violations:
                print(f"[Warning] Agent 输出纪律违规：{v}")
            print("[Note] 已自动清洗并继续执行。演兵时应关注 Agent 是否严格遵守 Prompt 约束。")

        try:
            self.data = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"[Blocker] JSON 解析失败！文件内容可能包含非法字符：")
            print(f"  错误位置: 行 {e.lineno}, 列 {e.colno}")
            print(f"  错误信息: {e.msg}")
            print(f"\n[Action] 请检查 Agent 输出是否包含多余 Markdown 标记或寒暄文本。")
            sys.exit(1)

        self.state_kind = self.detect_state_kind(self.data)
        integrity_error = verify_state_integrity(self.state_path, self.data)
        if integrity_error:
            print(f"[Blocker] {integrity_error}")
            sys.exit(1)

        batch_hint = self.data.get('batch_id') or self.data.get('task_context', {}).get('target_institution') or self.state_path.name
        print(f"[*] 成功加载状态文件: {batch_hint}")

    def validate_task_manifest_consistency(self):
        if self.task_manifest is None:
            return
        if not self.task_manifest.exists():
            print(f"[Blocker] task manifest不存在: {self.task_manifest}")
            sys.exit(1)
        try:
            manifest = json.loads(self.task_manifest.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[Blocker] task manifest不可解析: {exc}")
            sys.exit(1)

        task_scope = manifest.get("task_scope")
        phase = manifest.get("phase")
        execution_unit = manifest.get("execution_unit")
        resume_context = self.data.get("resume_context", {})
        required_fields = (
            self.STAGE_MANIFEST_REQUIRED_FIELDS
            if task_scope == "stage"
            else self.GEN_NODE_MANIFEST_REQUIRED_FIELDS
            if task_scope == "gen_node"
            else set()
        )
        missing = sorted(field for field in required_fields if field not in manifest)
        if missing:
            print(f"[Blocker] task manifest缺少必填字段: {', '.join(missing)}")
            sys.exit(1)
        if phase != self.stage:
            print(f"[Blocker] task manifest.phase与当前stage不一致: {phase} != {self.stage}")
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
            self.data,
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
        expected_session_brief = str(self.workdir / ".harness/state/SESSION_BRIEF.md")
        expected_handoff_dir = str(self.workdir / ".harness/handoff")
        if inputs.get("session_brief") != expected_session_brief:
            print("[Blocker] task manifest.inputs.session_brief与当前workdir不一致。")
            sys.exit(1)
        if inputs.get("handoff_dir") != expected_handoff_dir:
            print("[Blocker] task manifest.inputs.handoff_dir与当前workdir不一致。")
            sys.exit(1)
        if task_scope == "stage":
            if self.stage == "gen":
                print("[Blocker] gen阶段不得使用stage task manifest。")
                sys.exit(1)
            if execution_unit != self.stage:
                print("[Blocker] 阶段任务单execution_unit必须等于当前阶段。")
                sys.exit(1)
            try:
                expected_dispatch_role = self.infer_stage_dispatch_role(str(manifest.get("next_required_action") or ""), self.stage)
            except ValueError as exc:
                print(f"[Blocker] {exc}")
                sys.exit(1)
            if manifest.get("dispatch_role") != expected_dispatch_role:
                print("[Blocker] task manifest.dispatch_role与当前阶段派单动作不一致。")
                sys.exit(1)
            phase_status = self.data.get("phase_status", {})
            if manifest.get("phase_status") != phase_status.get(self.stage):
                print("[Blocker] task manifest.phase_status与运行态不一致。")
                sys.exit(1)
            if not isinstance(manifest.get("expected_outputs"), list):
                print("[Blocker] stage task manifest.expected_outputs必须为数组。")
                sys.exit(1)
            expected_handoff_map = {
                "spec": self.workdir / ".harness/handoff/prep-to-spec.json",
                "prove": self.workdir / ".harness/handoff/spec-to-prove.json",
                "final": self.workdir / ".harness/handoff/gen-to-final.json",
            }
            expected_handoff_file = expected_handoff_map.get(self.stage)
            if expected_handoff_file is not None:
                if inputs.get("handoff_file") != str(expected_handoff_file):
                    print("[Blocker] task manifest.inputs.handoff_file与当前阶段上下文不一致。")
                    sys.exit(1)
        elif task_scope == "gen_node":
            if self.stage != "gen":
                print("[Blocker] 非gen阶段不得使用gen_node task manifest。")
                sys.exit(1)
            phase_3 = self.data.get("artifacts", {}).get("phase_3", {})
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
                if manifest_node_state.get(field) != node_state.get(field, [] if field == "generated_files" else "" if field in {"compile_command", "compile_log_path", "last_error", "last_review_report"} else None):
                    print(f"[Blocker] task manifest.node_state.{field}与运行态不一致。")
                    sys.exit(1)
            if manifest.get("expected_outputs") != node_state.get("generated_files", []):
                print("[Blocker] gen_node task manifest.expected_outputs与节点generated_files不一致。")
                sys.exit(1)
            expected_handoff_file = self.workdir / ".harness/handoff/prove-to-gen.json"
            if inputs.get("handoff_file") != str(expected_handoff_file):
                print("[Blocker] gen_node task manifest.inputs.handoff_file与当前阶段上下文不一致。")
                sys.exit(1)
        else:
            print(f"[Blocker] task manifest.task_scope非法: {task_scope}")
            sys.exit(1)

    def validate_preflight_entry_gate(self):
        if self.stage != "gen" or self.state_kind != "harness_workflow":
            return
        resume_context = self.data.get("resume_context", {})
        if resume_context.get("next_required_action") != "run_preflight:gen":
            return
        phase_3 = self.data.get("artifacts", {}).get("phase_3", {})
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
            self.fail_gen_gate(
                f"{current_node}当前review_status={review_status}，不得执行run_preflight:gen；"
                "主编排必须按返工/solo规则处理。",
                current_node,
            )
        if review_status == "approved" and not str(node_state.get("last_review_report", "")).strip():
            self.fail_gen_gate(
                f"{current_node}当前review_status=approved，但last_review_report为空，禁止run_preflight:gen",
                current_node,
            )

    @staticmethod
    def detect_state_kind(data: dict) -> str:
        if isinstance(data, dict) and "current_phase" in data and "phase_status" in data and "checkpoints" in data:
            return "harness_workflow"
        return "legacy"

    def run_spec_validation(self):
        """Spec 阶段阻塞验证：检查未决事实歧义"""
        if self.state_kind == "harness_workflow":
            self.run_harness_workflow_spec_validation()
            return
        print("\n--- 执行 Spec 阶段阻塞验证 ---")
        open_questions = self.data.get("open_questions", [])
        if open_questions:
            print(f"[Blocker] 拦截！Spec 阶段发现 {len(open_questions)} 个未决事实歧义：")
            for q in open_questions:
                severity = q.get('severity', 'UNKNOWN')
                question = q.get('question', '未描述')
                source = q.get('source_ref', '未标注来源')
                print(f"  - [级别:{severity}] {question} (来源: {source})")
            print("\n[Action] 流水线已挂起。请人工确认接口规范或补充资料。")
            sys.exit(1)
        print("[Success] 事实提取完全闭环，无未决问题。允许流转至 Prove 阶段。")

    def run_prove_validation(self):
        """Prove 阶段阻塞验证：风控门禁与代码生成闸门"""
        if self.state_kind == "harness_workflow":
            self.run_harness_workflow_prove_validation()
            return
        print("\n--- 执行 Prove 阶段阻塞验证 ---")
        allow_codegen = self.data.get("allow_codegen", False)
        risk_findings = self.data.get("risk_findings", [])

        critical_risks = [r for r in risk_findings if r.get("severity") == "CRITICAL"]
        if critical_risks:
            print(f"[Blocker] 触发高压线！拦截 {len(critical_risks)} 个 CRITICAL 级风控门禁：")
            for r in critical_risks:
                rule_id = r.get('rule_id', '未标注')
                desc = r.get('description', '未描述')
                print(f"  - [{rule_id}] {desc}")
            sys.exit(1)

        if not allow_codegen:
            print("\n[Blocker] 核心闸门 allow_codegen == false。禁止进入代码生成！")
            sys.exit(1)

        print("[Success] 语义证明与风控审计通过，ALLOW_CODEGEN 闸门已开启。")

    def run_validator(self, script_name: str, input_path: Path) -> dict:
        script_path = self.workdir / ".harness" / "scripts" / script_name
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
            cwd=str(self.workdir),
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

    def run_preflight(self):
        script_path = self.workdir / ".harness" / "scripts" / "preflight.py"
        if not script_path.exists():
            print(f"[Blocker] preflight脚本不存在: {script_path}")
            sys.exit(1)

        cmd = [
            sys.executable,
            str(script_path),
            "--stage",
            self.stage,
            "--state-file",
            str(self.state_path),
        ]
        if self.source_doc:
            cmd.extend(["--source-doc", str(self.source_doc)])
        if self.output_dir:
            cmd.extend(["--output-dir", str(self.output_dir)])
        if self.strict:
            cmd.append("--strict")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.workdir),
            check=False,
        )
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        if result.returncode != 0:
            print("[Blocker] preflight检查未通过，当前阶段不得继续。")
            sys.exit(1)

    def emit_next_action_plan(self, output_path: Path) -> Path:
        script_path = self.workdir / ".harness" / "scripts" / "plan-next-action.py"
        if not script_path.exists():
            print(f"[Blocker] next-action计划脚本不存在: {script_path}")
            sys.exit(1)
        output_path = output_path.expanduser().resolve()
        cmd = [
            sys.executable,
            str(script_path),
            "--state-file",
            str(self.state_path),
            "--output",
            str(output_path),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.workdir),
            check=False,
        )
        if result.returncode != 0:
            print("[Blocker] next-action计划生成失败。")
            if result.stderr.strip():
                print(result.stderr.strip()[:200], file=sys.stderr)
            sys.exit(1)
        # 验证结果文件而非依赖stdout
        if not output_path.exists():
            print(f"[Blocker] plan-next-action结果文件未生成: {output_path}")
            sys.exit(1)
        try:
            plan_payload = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[Blocker] plan-next-action结果文件不是合法JSON: {output_path}")
            sys.exit(1)
        print(f"[Success] next-action编排计划已生成: {output_path}")
        return output_path

    def execute_next_action_chain(self, plan_file: Path, output_path: Path | None) -> None:
        script_path = self.workdir / ".harness" / "scripts" / "execute-next-action.py"
        if not script_path.exists():
            print(f"[Blocker] next-action执行脚本不存在: {script_path}")
            sys.exit(1)
        cmd = [
            sys.executable,
            str(script_path),
            "--plan-file",
            str(plan_file),
        ]
        if output_path is not None:
            cmd.extend(["--output", str(output_path.expanduser().resolve())])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.workdir),
            check=False,
        )
        if result.returncode != 0:
            print("[Blocker] next-action安全派发链执行失败。")
            if result.stderr.strip():
                print(result.stderr.strip()[:200], file=sys.stderr)
            sys.exit(1)
        if output_path is not None:
            # 验证结果文件而非依赖stdout
            resolved_output = output_path.expanduser().resolve()
            if not resolved_output.exists():
                print(f"[Blocker] execute-next-action结果文件未生成: {resolved_output}")
                sys.exit(1)
            try:
                exec_payload = json.loads(resolved_output.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                print(f"[Blocker] execute-next-action结果文件不是合法JSON: {resolved_output}")
                sys.exit(1)
            print(f"[Success] next-action执行结果已生成: {resolved_output}")

    def maybe_drive_next_action(self) -> None:
        if not self.next_action_plan_output and not self.execute_next_action_enabled:
            return
        if self.state_kind != "harness_workflow":
            print("[Blocker] 只有harness-workflow-state主线支持next-action编排输出。")
            sys.exit(1)
        plan_output = self.next_action_plan_output
        temp_plan = None
        if plan_output is None:
            fd, temp_path = tempfile.mkstemp(prefix="next-action-", suffix=".json")
            temp_plan = Path(temp_path)
            os.close(fd)
            plan_output = temp_plan
        assert plan_output is not None
        plan_file = self.emit_next_action_plan(plan_output)
        if self.execute_next_action_enabled:
            self.execute_next_action_chain(plan_file, self.next_action_execution_output)
        if temp_plan is not None and temp_plan.exists():
            temp_plan.unlink()

    def require_validator_pass(self, script_name: str, input_path: Path, allowed_statuses: set[str]):
        payload = self.run_validator(script_name, input_path)
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

    def validate_json_with_schema(self, input_path: Path, schema_rel_path: str, label: str) -> dict:
        if not input_path.exists():
            print(f"[Blocker] {label}不存在: {input_path}")
            sys.exit(1)
        schema_path = self.workdir / schema_rel_path
        if not schema_path.exists():
            print(f"[Blocker] {label}对应Schema不存在: {schema_path}")
            sys.exit(1)
        try:
            payload = json.loads(input_path.read_text(encoding="utf-8"))
            if schema_rel_path == self.HARNESS_ISSUE_ROUTING_SCHEMA:
                payload = normalize_legacy_prove_routing_payload(payload)
        except json.JSONDecodeError as exc:
            print(f"[Blocker] {label}不是合法JSON: {exc}")
            sys.exit(1)
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            validate(instance=payload, schema=schema)
        except ValidationError as exc:
            path = ".".join(str(p) for p in exc.absolute_path)
            print(f"[Blocker] {label}不符合Schema: 路径={path} 错误={exc.message}")
            sys.exit(1)
        return payload

    def validate_prove_routing_consistency(self, prove_payload: dict) -> None:
        checkpoints = self.data.get("checkpoints", {})
        gate_context = checkpoints.get("gate_context", {})
        phase_2 = self.data.get("artifacts", {}).get("phase_2", {})
        last_checkpoint = checkpoints.get("last_checkpoint")

        state_allow_codegen = phase_2.get("allow_codegen")
        routing_allow_codegen = prove_payload.get("allow_codegen")
        if routing_allow_codegen != state_allow_codegen:
            print(
                "[Blocker] harness-issue-routing.allow_codegen与运行态artifacts.phase_2.allow_codegen不一致。"
            )
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
        prove_with_risk_logged_count = gate_context.get("prove_with_risk_logged_count", 0)
        prove_with_risk_unlogged_count = gate_context.get("prove_with_risk_unlogged_count", 0)
        if prove_with_risk_logged_count + prove_with_risk_unlogged_count != len(prove_with_risk):
            print("[Blocker] prove_with_risk_logged_count+prove_with_risk_unlogged_count必须与prove_with_risk_open一致。")
            sys.exit(1)
        if len(human_required) != gate_context.get("human_required_open"):
            print("[Blocker] harness-issue-routing中的human_required数量与运行态gate_context不一致。")
            sys.exit(1)
        pending_human_required = [
            item for item in human_required
            if isinstance(item, dict) and item.get("status") in {"pending", "awaiting_human"}
        ]
        if pending_human_required and checkpoints.get("awaiting_user_action") is not True:
            print("[Blocker] 存在未关闭的human_required问题时，awaiting_user_action必须为true。")
            sys.exit(1)
        if pending_human_required and state_allow_codegen == "YES":
            print("[Blocker] 存在未关闭的human_required问题时，不得allow_codegen=YES。")
            sys.exit(1)
        if pending_human_required and last_checkpoint == "prove-ok":
            print("[Blocker] 存在未关闭的human_required问题时，不得写prove-ok。")
            sys.exit(1)
        if prove_with_risk_unlogged_count > 0 and last_checkpoint == "prove-ok":
            print("[Blocker] prove_with_risk仍有未留痕项时，不得写prove-ok。")
            sys.exit(1)

    def validate_resume_context_consistency(self) -> None:
        if self.state_kind != "harness_workflow":
            return
        current_phase = self.data.get("current_phase")
        checkpoints = self.data.get("checkpoints", {})
        resume_context = self.data.get("resume_context")
        artifacts = self.data.get("artifacts", {})
        if current_phase in {"DONE", "TERMINATED"}:
            return
        if not isinstance(resume_context, dict):
            print("[Blocker] harness-workflow-state缺少resume_context，无法执行恢复控制面校验。")
            sys.exit(1)
        state_contract_version = self.data.get("state_contract_version")
        if state_contract_version is not None and (not isinstance(state_contract_version, str) or not state_contract_version.strip()):
            print(f"[Blocker] state_contract_version非法: {state_contract_version}")
            sys.exit(1)
        last_review_status = resume_context.get("last_review_status")
        if last_review_status not in self.CONTROLLED_REVIEW_STATUS:
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

        action_binding_error = self.validate_resume_action_binding(
            current_phase,
            current_execution_unit,
            next_required_action,
            required_script,
        )
        if action_binding_error:
            print(f"[Blocker] {action_binding_error}")
            sys.exit(1)

    def run_harness_workflow_spec_validation(self):
        """TODO: Adapt spec validation logic to domain-specific requirements."""
        print("\n--- 执行 harness-workflow-state / Spec 阶段校验 ---")
        self.validate_resume_context_consistency()
        checkpoints = self.data.get("checkpoints", {})
        phase_status = self.data.get("phase_status", {})
        artifacts = self.data.get("artifacts", {})
        gate_context = checkpoints.get("gate_context", {})
        last_checkpoint = checkpoints.get("last_checkpoint")
        allow_codegen = artifacts.get("phase_2", {}).get("allow_codegen")

        if phase_status.get("prep") != "completed":
            print("[Blocker] prep阶段未完成，禁止进入spec断言。")
            sys.exit(1)

        if last_checkpoint not in self.CONTROLLED_CHECKPOINTS:
            print(f"[Blocker] 非法checkpoint值: {last_checkpoint}")
            sys.exit(1)

        if allow_codegen not in self.CONTROLLED_ALLOW_CODEGEN:
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

        if self.business_facts_input:
            self.validate_json_with_schema(
                self.business_facts_input,
                self.HARNESS_REQ_FACTS_SCHEMA,
                "harness-req-facts正式产物",
            )
            self.require_validator_pass(
                "check-business-facts.py",
                self.business_facts_input,
                {"PASS", "WARN"},
            )

        print("[Success] harness-workflow-state 的 spec 阶段校验通过。")

    def run_harness_workflow_prove_validation(self):
        """TODO: Adapt prove validation logic to domain-specific requirements."""
        print("\n--- 执行 harness-workflow-state / Prove 阶段校验 ---")
        self.validate_resume_context_consistency()
        checkpoints = self.data.get("checkpoints", {})
        phase_status = self.data.get("phase_status", {})
        artifacts = self.data.get("artifacts", {})
        questions = self.data.get("questions", {})
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

        if last_checkpoint not in self.CONTROLLED_CHECKPOINTS:
            print(f"[Blocker] 非法checkpoint值: {last_checkpoint}")
            sys.exit(1)

        if allow_codegen not in self.CONTROLLED_ALLOW_CODEGEN:
            print(f"[Blocker] 非法allow_codegen值: {allow_codegen}")
            sys.exit(1)

        if self.business_facts_input:
            self.validate_json_with_schema(
                self.business_facts_input,
                self.HARNESS_REQ_FACTS_SCHEMA,
                "harness-req-facts正式产物",
            )
            self.require_validator_pass(
                "check-business-facts.py",
                self.business_facts_input,
                {"PASS", "WARN"},
            )
            gate_context_value = gate_context.get("business_fact_validation_passed")
            if gate_context_value is not True:
                print("[Blocker] business_fact_validation_passed未被写为true。")
                sys.exit(1)

        if self.config_boundary_input:
            self.require_validator_pass(
                "check-config-boundary.py",
                self.config_boundary_input,
                {"PASS", "WARN"},
            )

        if self.coverage_input:
            self.require_validator_pass(
                "check-domain-coverage.py",
                self.coverage_input,
                {"PASS", "WARN"},
            )
        if self.prove_routing_input:
            prove_payload = self.validate_json_with_schema(
                self.prove_routing_input,
                self.HARNESS_ISSUE_ROUTING_SCHEMA,
                "harness-issue-routing正式产物",
            )
            self.validate_prove_routing_consistency(prove_payload)
        if gate_context.get("scene_coverage_passed") is not True and last_checkpoint == "prove-ok":
            print("[Blocker] prove-ok状态下，scene_coverage_passed必须为true。")
            sys.exit(1)

        if any(item.get("status") == "pending" for item in questions.get("open", []) if isinstance(item, dict)) and checkpoints.get("awaiting_user_action") is not True:
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

    def run_harness_workflow_gen_validation(self):
        """TODO: Adapt gen validation logic to domain-specific requirements.

        Loads DAG blueprint from .harness/config/dag-blueprint.yaml instead of
        using hardcoded GEN_LAYER_NODE_MAP and GEN_NODE_PREREQS.
        """
        print("\n--- 执行 harness-workflow-state / Gen 阶段校验 ---")
        self.validate_resume_context_consistency()
        checkpoints = self.data.get("checkpoints", {})
        phase_status = self.data.get("phase_status", {})
        artifacts = self.data.get("artifacts", {})
        resume_context = self.data.get("resume_context", {})
        phase_2 = artifacts.get("phase_2", {})
        phase_3 = artifacts.get("phase_3", {})
        layers = phase_3.get("layers", {})
        nodes = phase_3.get("nodes", {})
        current_node = phase_3.get("current_node")
        next_required_action = resume_context.get("next_required_action")

        # Load DAG blueprint from external config
        gen_layer_node_map, gen_node_prereqs = self._load_dag_blueprint(self.workdir)

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
                self.fail_gen_gate(f"gen阶段current_node未在phase_3.nodes中注册: {current_node}", current_node)
            current_gate_error = self.validate_current_gen_node_gate(current_node, node_state, next_required_action)
            if current_gate_error:
                self.fail_gen_gate(current_gate_error, current_node)

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
                missing_completed = [
                    node_id for node_id in required_nodes
                    if not isinstance(nodes.get(node_id), dict) or nodes.get(node_id, {}).get("status") != "completed"
                ]
                if missing_completed:
                    print(f"[Blocker] {layer_name}标记completed，但节点未完成: {', '.join(missing_completed)}")
                    sys.exit(1)

        if phase_status.get("gen") == "completed":
            for layer_name, required_nodes in gen_layer_node_map.items():
                missing_completed = [
                    node_id for node_id in required_nodes
                    if not isinstance(nodes.get(node_id), dict) or nodes.get(node_id, {}).get("status") != "completed"
                ]
                if missing_completed:
                    print(f"[Blocker] gen阶段已completed，但仍有节点未完成: {layer_name} -> {', '.join(missing_completed)}")
                    sys.exit(1)

        print("[Success] harness-workflow-state 的 gen 阶段校验通过。")

    def run_harness_workflow_final_validation(self):
        """TODO: Adapt final validation logic to domain-specific requirements."""
        print("\n--- 执行 harness-workflow-state / Final 阶段校验 ---")
        self.validate_resume_context_consistency()
        phase_status = self.data.get("phase_status", {})
        artifacts = self.data.get("artifacts", {})
        phase_4 = artifacts.get("phase_4", {})
        phase_3 = artifacts.get("phase_3", {})
        nodes = phase_3.get("nodes", {})

        # Load DAG blueprint for prerequisite checking
        _, gen_node_prereqs = self._load_dag_blueprint(self.workdir)

        if phase_status.get("gen") != "completed":
            print("[Blocker] gen阶段未完成，禁止进入final断言。")
            sys.exit(1)
        if phase_status.get("final") not in {"in_progress", "completed"}:
            print(f"[Blocker] 当前phase_status.final非法: {phase_status.get('final')}")
            sys.exit(1)

        report_validation = validate_final_report(self.workdir, self.data)
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

    def run_plan_validation(self):
        """Plan 阶段：路径沙箱校验 + step_id唯一性 + DAG拓扑排序"""
        print("\n--- 执行 Plan 阶段沙箱及 DAG 验证 ---")
        steps = self.data.get("steps", [])

        # 1. Path Sandbox Validation (含反斜杠路径穿越)
        for step in steps:
            for path_type in ["reads", "writes"]:
                for p in step.get(path_type, []):
                    # 检查绝对路径: /开头, ~开头, Windows盘符
                    if p.startswith("/") or p.startswith("~") or (len(p) >= 2 and p[1] == ":"):
                        print(f"[Blocker] 安全阻断！步骤 {step['step_id']} 的 {path_type} 包含绝对路径: {p}")
                        sys.exit(1)
                    # 检查路径穿越: 统一分隔符后检查 ..
                    normalized = p.replace("\\", "/")
                    if ".." in normalized.split("/") or normalized.startswith(".."):
                        print(f"[Blocker] 安全阻断！步骤 {step['step_id']} 的 {path_type} 包含路径穿越: {p}")
                        sys.exit(1)
        print("[*] 相对路径沙箱检查通过。")

        # 2. step_id 唯一性校验
        seen = set()
        for step in steps:
            sid = step["step_id"]
            if sid in seen:
                print(f"[Blocker] step_id '{sid}' 重复定义！每个步骤必须唯一。")
                sys.exit(1)
            seen.add(sid)
        print("[*] step_id 唯一性校验通过。")

        # 3. DAG Topological Sort
        graph = defaultdict(list)
        in_degree = defaultdict(int)
        step_map = {}

        for step in steps:
            sid = step["step_id"]
            step_map[sid] = step
            in_degree[sid] = 0

        for step in steps:
            sid = step["step_id"]
            deps = step.get("depends_on", [])
            for dep in deps:
                if dep not in step_map:
                    print(f"[Blocker] 步骤 {sid} 依赖了未定义的节点 {dep}。")
                    sys.exit(1)
                graph[dep].append(sid)
                in_degree[sid] += 1

        queue = deque([sid for sid in step_map if in_degree[sid] == 0])
        sorted_list = []

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

        self.sorted_steps = sorted_list
        print("[Success] DAG 拓扑排序完成，无循环依赖。")

        print("\n=== 预期执行编排 ===")
        for idx, sid in enumerate(self.sorted_steps):
            step = step_map[sid]
            deps = f"(前置: {', '.join(step['depends_on'])})" if step.get('depends_on') else "(首发)"
            print(f"[{idx + 1}] {sid} | Owner: {step['owner']} | {deps}")
        print("====================\n")

    def execute(self):
        """按阶段执行对应验证"""
        self.load_state()
        self.validate_task_manifest_consistency()
        self.validate_preflight_entry_gate()
        if self.run_preflight_first:
            self.run_preflight()
        if self.stage in {"spec", "prove"} and self.state_kind == "legacy" and not self.legacy_mode:
            print("[Blocker] spec/prove默认只接受harness-workflow-state主线。旧spec-state/prove-state仅能在--legacy-mode下运行。")
            sys.exit(1)
        self.load_schema()
        self.validate_schema()  # Schema 校验优先于业务逻辑校验

        if self.stage == "spec":
            self.run_spec_validation()
        elif self.stage == "prove":
            self.run_prove_validation()
        elif self.stage == "gen":
            if self.state_kind != "harness_workflow":
                print("[Blocker] gen阶段当前仅支持harness-workflow-state主线。")
                sys.exit(1)
            self.run_harness_workflow_gen_validation()
        elif self.stage == "plan":
            self.run_plan_validation()
        elif self.stage == "final":
            if self.state_kind != "harness_workflow":
                print("[Blocker] final阶段当前仅支持harness-workflow-state主线。")
                sys.exit(1)
            self.run_harness_workflow_final_validation()
        self.maybe_drive_next_action()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HARNESS Orchestrator")
    parser.add_argument("--stage", choices=["spec", "prove", "gen", "final", "plan"], required=True,
                        help="要验证的工作流阶段")
    parser.add_argument("--state-file", required=True,
                        help="状态 JSON 文件路径")
    parser.add_argument("--workdir", default=".",
                        help="工作目录（用于定位 Schema 文件）")
    parser.add_argument("--strict", action="store_true",
                        help="严格模式：检测 Agent 是否输出纯 JSON（演兵时使用）")
    parser.add_argument("--legacy-mode", action="store_true",
                        help="显式启用旧spec-state/prove-state兼容链路；默认仅允许harness-workflow-state主线")
    parser.add_argument("--run-preflight", action="store_true",
                        help="先调用preflight.py执行阶段前置检查，成功后再进入阶段校验")
    parser.add_argument("--source-doc",
                        help="当启用--run-preflight且阶段为prep时，传入原始文档目录或文件")
    parser.add_argument("--output-dir",
                        help="当启用--run-preflight且阶段为prep时，传入prep输出目录")
    parser.add_argument("--business-facts-input",
                        help="harness-workflow-state主线下，spec/prove使用的业务事实校验输入JSON")
    parser.add_argument("--config-boundary-input",
                        help="harness-workflow-state主线下，prove使用的配置边界校验输入JSON")
    parser.add_argument("--coverage-input",
                        help="harness-workflow-state主线下，prove使用的域覆盖校验输入JSON")
    parser.add_argument("--prove-routing-input",
                        help="harness-workflow-state主线下，prove阶段正式产物harness-issue-routing-*.json")
    parser.add_argument("--task-manifest",
                        help="由build-stage-task.py或build-gen-node-task.py生成的任务单，若提供则必须与当前状态严格一致")
    parser.add_argument("--next-action-plan-output",
                        help="阶段校验通过后，输出由plan-next-action.py生成的下一步编排计划JSON")
    parser.add_argument("--execute-next-action", action="store_true",
                        help="在输出next-action计划后，继续执行安全派发链")
    parser.add_argument("--next-action-execution-output",
                        help="当启用--execute-next-action时，输出execute-next-action.py生成的执行结果JSON")
    args = parser.parse_args()

    orchestrator = StageOrchestrator(
        args.state_file,
        args.stage,
        args.workdir,
        args.strict,
        args.legacy_mode,
        args.run_preflight,
        args.source_doc,
        args.output_dir,
        args.business_facts_input,
        args.config_boundary_input,
        args.coverage_input,
        args.prove_routing_input,
        args.task_manifest,
        args.next_action_plan_output,
        args.execute_next_action,
        args.next_action_execution_output,
    )
    orchestrator.execute()
