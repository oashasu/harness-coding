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
from __future__ import annotations

import json
import sys
import argparse
import subprocess
import os
from pathlib import Path
from datetime import datetime, timezone
import tempfile

from manifest_validators import validate_task_manifest_consistency, validate_preflight_entry_gate
from stage_helpers import detect_state_kind
from state_integrity import verify_state_integrity
from workflow_validators import (
    run_harness_workflow_spec_validation,
    run_harness_workflow_prove_validation,
    run_harness_workflow_gen_validation,
    run_harness_workflow_final_validation,
    run_plan_validation,
)

try:
    import jsonschema
    from jsonschema import validate, ValidationError
except ImportError:
    print("[Blocker] jsonschema 库未安装，无法执行契约校验！")
    print("[Blocker] 请运行: pip install jsonschema")
    sys.exit(1)


class StageOrchestrator:
    """HARNESS Orchestrator - 通用工作流调度器"""

    SCHEMA_PATHS = {
        "plan": ".harness/schemas/harness-plan-state.v1.schema.json",
    }
    HARNESS_WORKFLOW_SCHEMA = ".harness/schemas/harness-state.schema.json"

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
        self.sorted_steps: list[str] = []
        self.state_kind = "legacy"
        self._violations: list[str] = []

    def save_state(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def load_schema(self):
        """加载对应阶段的 JSON Schema"""
        if self.stage == "plan":
            schema_rel = self.SCHEMA_PATHS.get(self.stage)
        elif self.state_kind == "harness_workflow":
            schema_rel = self.HARNESS_WORKFLOW_SCHEMA
        else:
            schema_rel = self.SCHEMA_PATHS.get(self.stage)

        if not schema_rel:
            if self.stage in {"spec", "prove"} and self.state_kind == "legacy":
                print(f"[Blocker] Legacy {self.stage} 模式不再支持：缺少对应 schema 文件。")
                print("[Info] 请使用 harness-workflow-state 主线（移除 --legacy-mode）。")
                sys.exit(1)
            print(f"[Error] 未知阶段: {self.stage}")
            sys.exit(1)

        schema_path = self.workdir / schema_rel
        if not schema_path.exists():
            print(f"[Error] Schema 文件不存在: {schema_path}")
            sys.exit(1)

        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

        print(f"[*] 成功加载 {self.stage.upper()} 阶段 Schema: {schema_path.name}")

    def validate_schema(self):
        """执行 JSON Schema 校验"""
        print(f"\n--- 执行 {self.stage.upper()} 阶段 Schema 校验 ---")
        try:
            validate(instance=self.data, schema=self.schema)
            print("[Success] Schema 校验通过，契约结构完整。")
        except ValidationError as e:
            print("[Blocker] Schema 校验失败！契约结构不合规：")
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
        with open(self.state_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
        content = raw_content.strip()

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

        has_prefix_chatter = not content.startswith("{")
        has_suffix_chatter = not content.endswith("}")

        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            content = content[start_idx:end_idx + 1]

        if has_markdown_wrapper:
            self._violations.append("输出被 Markdown 代码块包裹（```json 或 ```）")
        if has_prefix_chatter:
            self._violations.append(f"开头有多余文本：{raw_content[:50].strip()[:30]}...")
        if has_suffix_chatter:
            self._violations.append(f"结尾有多余文本：...{raw_content[-50:].strip()[-30]}")

        if self.strict and self._violations:
            print("\n--- 执行 Strict 模式纯 JSON 校验 ---")
            for v in self._violations:
                print(f"[Warning] Agent 输出纪律违规：{v}")
            print("[Note] 已自动清洗并继续执行。演兵时应关注 Agent 是否严格遵守 Prompt 约束。")

        try:
            self.data = json.loads(content)
        except json.JSONDecodeError as e:
            print("[Blocker] JSON 解析失败！文件内容可能包含非法字符：")
            print(f"  错误位置: 行 {e.lineno}, 列 {e.colno}")
            print(f"  错误信息: {e.msg}")
            print("\n[Action] 请检查 Agent 输出是否包含多余 Markdown 标记或寒暄文本。")
            sys.exit(1)

        self.state_kind = detect_state_kind(self.data)
        integrity_error = verify_state_integrity(self.state_path, self.data)
        if integrity_error:
            print(f"[Blocker] {integrity_error}")
            sys.exit(1)

        batch_hint = (
            self.data.get("batch_id")
            or self.data.get("task_context", {}).get("target_institution")
            or self.state_path.name
        )
        print(f"[*] 成功加载状态文件: {batch_hint}")

    def validate_task_manifest_consistency(self):
        validate_task_manifest_consistency(self.task_manifest, self.stage, self.workdir, self.data)

    def validate_preflight_entry_gate(self):
        validate_preflight_entry_gate(self.stage, self.state_kind, self.data)

    def run_preflight(self):
        script_path = self.workdir / ".harness" / "scripts" / "preflight.py"
        if not script_path.exists():
            print(f"[Blocker] preflight脚本不存在: {script_path}")
            sys.exit(1)
        cmd = [sys.executable, str(script_path), "--stage", self.stage, "--state-file", str(self.state_path)]
        if self.source_doc:
            cmd.extend(["--source-doc", str(self.source_doc)])
        if self.output_dir:
            cmd.extend(["--output-dir", str(self.output_dir)])
        if self.strict:
            cmd.append("--strict")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.workdir), check=False)
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
        cmd = [sys.executable, str(script_path), "--state-file", str(self.state_path), "--output", str(output_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.workdir), check=False)
        if result.returncode != 0:
            print("[Blocker] next-action计划生成失败。")
            if result.stderr.strip():
                print(result.stderr.strip()[:200], file=sys.stderr)
            sys.exit(1)
        if not output_path.exists():
            print(f"[Blocker] plan-next-action结果文件未生成: {output_path}")
            sys.exit(1)
        try:
            json.loads(output_path.read_text(encoding="utf-8"))
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
        cmd = [sys.executable, str(script_path), "--plan-file", str(plan_file)]
        if output_path is not None:
            cmd.extend(["--output", str(output_path.expanduser().resolve())])
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.workdir), check=False)
        if result.returncode != 0:
            print("[Blocker] next-action安全派发链执行失败。")
            if result.stderr.strip():
                print(result.stderr.strip()[:200], file=sys.stderr)
            sys.exit(1)
        if output_path is not None:
            resolved_output = output_path.expanduser().resolve()
            if not resolved_output.exists():
                print(f"[Blocker] execute-next-action结果文件未生成: {resolved_output}")
                sys.exit(1)
            try:
                json.loads(resolved_output.read_text(encoding="utf-8"))
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

    def run_spec_validation(self):
        """Spec 阶段阻塞验证：检查未决事实歧义"""
        if self.state_kind == "harness_workflow":
            run_harness_workflow_spec_validation(self.data, self.workdir, self.business_facts_input)
            return
        print("\n--- 执行 Spec 阶段阻塞验证 ---")
        open_questions = self.data.get("open_questions", [])
        if open_questions:
            print(f"[Blocker] 拦截！Spec 阶段发现 {len(open_questions)} 个未决事实歧义：")
            for q in open_questions:
                severity = q.get("severity", "UNKNOWN")
                question = q.get("question", "未描述")
                source = q.get("source_ref", "未标注来源")
                print(f"  - [级别:{severity}] {question} (来源: {source})")
            print("\n[Action] 流水线已挂起。请人工确认接口规范或补充资料。")
            sys.exit(1)
        print("[Success] 事实提取完全闭环，无未决问题。允许流转至 Prove 阶段。")

    def run_prove_validation(self):
        """Prove 阶段阻塞验证：风控门禁与代码生成闸门"""
        if self.state_kind == "harness_workflow":
            run_harness_workflow_prove_validation(
                self.data,
                self.workdir,
                self.business_facts_input,
                self.config_boundary_input,
                self.coverage_input,
                self.prove_routing_input,
            )
            return
        print("\n--- 执行 Prove 阶段阻塞验证 ---")
        allow_codegen = self.data.get("allow_codegen", False)
        risk_findings = self.data.get("risk_findings", [])
        critical_risks = [r for r in risk_findings if r.get("severity") == "CRITICAL"]
        if critical_risks:
            print(f"[Blocker] 触发高压线！拦截 {len(critical_risks)} 个 CRITICAL 级风控门禁：")
            for r in critical_risks:
                rule_id = r.get("rule_id", "未标注")
                desc = r.get("description", "未描述")
                print(f"  - [{rule_id}] {desc}")
            sys.exit(1)
        if not allow_codegen:
            print("\n[Blocker] 核心闸门 allow_codegen == false。禁止进入代码生成！")
            sys.exit(1)
        print("[Success] 语义证明与风控审计通过，ALLOW_CODEGEN 闸门已开启。")

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
        self.validate_schema()

        if self.stage == "spec":
            self.run_spec_validation()
        elif self.stage == "prove":
            self.run_prove_validation()
        elif self.stage == "gen":
            if self.state_kind != "harness_workflow":
                print("[Blocker] gen阶段当前仅支持harness-workflow-state主线。")
                sys.exit(1)
            run_harness_workflow_gen_validation(self.data, self.workdir)
        elif self.stage == "plan":
            self.sorted_steps = run_plan_validation(self.data)
        elif self.stage == "final":
            if self.state_kind != "harness_workflow":
                print("[Blocker] final阶段当前仅支持harness-workflow-state主线。")
                sys.exit(1)
            run_harness_workflow_final_validation(self.data, self.workdir)
        self.maybe_drive_next_action()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HARNESS Orchestrator")
    parser.add_argument("--stage", choices=["spec", "prove", "gen", "final", "plan"], required=True,
                        help="要验证的工作流阶段")
    parser.add_argument("--state-file", required=True, help="状态 JSON 文件路径")
    parser.add_argument("--workdir", default=".", help="工作目录（用于定位 Schema 文件）")
    parser.add_argument("--strict", action="store_true",
                        help="严格模式：检测 Agent 是否输出纯 JSON（演兵时使用）")
    parser.add_argument("--legacy-mode", action="store_true",
                        help="显式启用旧spec-state/prove-state兼容链路；默认仅允许harness-workflow-state主线")
    parser.add_argument("--run-preflight", action="store_true",
                        help="先调用preflight.py执行阶段前置检查，成功后再进入阶段校验")
    parser.add_argument("--source-doc", help="当启用--run-preflight且阶段为prep时，传入原始文档目录或文件")
    parser.add_argument("--output-dir", help="当启用--run-preflight且阶段为prep时，传入prep输出目录")
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
