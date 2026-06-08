#!/usr/bin/env python3
"""端到端集成测试：通过 subprocess 真实调用 orchestrator.py CLI。

覆盖：
  - plan 阶段通过（最小合法 state）
  - plan 阶段失败（有环 → exit 1）
  - final 阶段失败（gen 未完成 → exit 1）
  - 三个调用方脚本 --help smoke

Run with: python3 .harness/tests/test_orchestrator_e2e.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = HARNESS_ROOT / ".harness" / "scripts"
ORCHESTRATOR = SCRIPTS_DIR / "orchestrator.py"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable] + args,
        cwd=str(cwd or HARNESS_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# plan 阶段
# ---------------------------------------------------------------------------

def _minimal_plan_state(steps: list[dict]) -> dict:
    return {"batch_id": "test-batch", "steps": steps}


def _valid_step(step_id: str, depends_on: list[str] | None = None) -> dict:
    return {
        "step_id": step_id,
        "owner": "coding-worker",
        "depends_on": depends_on or [],
        "reads": [],
        "writes": [],
        "checks": ["python3 -m pytest"],
    }


def test_plan_stage_pass():
    steps = [
        _valid_step("s1"),
        _valid_step("s2", ["s1"]),
        _valid_step("s3", ["s2"]),
    ]
    state = _minimal_plan_state(steps)
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump(state, f, ensure_ascii=False)
        state_file = f.name

    result = _run([str(ORCHESTRATOR), "--stage", "plan", "--state-file", state_file, "--workdir", str(HARNESS_ROOT)])
    assert result.returncode == 0, f"期望 exit 0，实际 exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "DAG 拓扑排序完成" in result.stdout, f"输出缺少成功标志\n{result.stdout}"
    print("✓ test_plan_stage_pass: exit 0, DAG 排序完成")


def test_plan_stage_fail_cycle():
    steps = [
        _valid_step("s1", ["s2"]),
        _valid_step("s2", ["s1"]),
    ]
    state = _minimal_plan_state(steps)
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump(state, f, ensure_ascii=False)
        state_file = f.name

    result = _run([str(ORCHESTRATOR), "--stage", "plan", "--state-file", state_file, "--workdir", str(HARNESS_ROOT)])
    assert result.returncode == 1, f"期望 exit 1（环），实际 exit {result.returncode}"
    combined = result.stdout + result.stderr
    assert "循环" in combined, f"输出缺少循环错误信息\n{combined}"
    print("✓ test_plan_stage_fail_cycle: exit 1, 循环检测正常")


# ---------------------------------------------------------------------------
# final 阶段：验证 gen 未完成时 exit 1
# ---------------------------------------------------------------------------

def _minimal_harness_workflow_state(*, gen_completed: bool = False) -> dict:
    """构造同时满足：
    1. harness-state.schema.json 必填字段（schema 校验）
    2. detect_state_kind → 'harness_workflow'（顶层有 current_phase/phase_status/checkpoints）
    3. validate_resume_context_consistency 通过（final 阶段的合法 resume_context）
    """
    flat_phase_status: dict = {}
    if gen_completed:
        flat_phase_status["gen"] = "completed"

    return {
        # schema 必填字段（嵌套结构）
        "version": "2.0",
        "contract": {
            "contract_hash": "test-hash",
            "prompt_version": "1.0",
            "constraints": [],
            "allowed_write_paths": [],
            "blocked_paths": [],
            "acceptance_refs": [],
        },
        "phase_truth": {
            "current_phase": "final",
            "phase_status": "in_progress",
            "previous_phases": [],
        },
        "node_truth": {"subtasks": []},
        "recovery_truth": {"resume_context": None, "checkpoints": []},
        "route_decision": {
            "workflow": "harness",
            "confidence": 1.0,
            "scores": {
                "loc_estimate": 0,
                "file_count": 0,
                "db_changes": 0,
                "cross_module": 0,
                "risk_level": 0,
            },
            "total_score": 0,
            "reasoning": "e2e test fixture",
            "overrides": {"force_super_dev": False, "force_light": False},
            "split_required": False,
            "subtasks": [],
        },
        "quality_results": {"last_run": None, "tier_results": {}, "overall_passed": None},
        "history": [],
        # 顶层扁平字段（供 detect_state_kind 和 workflow_validators 读取）
        "current_phase": "final",
        "phase_status": flat_phase_status,
        "checkpoints": {"last_checkpoint": "NONE", "awaiting_user_action": False},
        "resume_context": {
            "last_review_status": "pending",
            "pending_checkpoint": "NONE",
            "current_execution_unit": "final",
            "next_required_action": "run_preflight:final",
            "required_script": "preflight.py --stage final",
        },
        "artifacts": {},
    }


def test_final_stage_fail_gen_not_done():
    state = _minimal_harness_workflow_state(gen_completed=False)
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump(state, f, ensure_ascii=False)
        state_file = f.name

    result = _run([str(ORCHESTRATOR), "--stage", "final", "--state-file", state_file, "--workdir", str(HARNESS_ROOT)])
    assert result.returncode == 1, f"期望 exit 1（gen 未完成），实际 exit {result.returncode}\nstdout: {result.stdout}"
    combined = result.stdout + result.stderr
    assert "gen阶段未完成" in combined, f"输出缺少 gen 未完成错误\n{combined}"
    print("✓ test_final_stage_fail_gen_not_done: exit 1, gen 未完成被正确拦截")


# ---------------------------------------------------------------------------
# 调用方脚本 --help smoke
# ---------------------------------------------------------------------------

def _caller_script(name: str) -> str:
    return str(SCRIPTS_DIR / name)


def test_caller_scripts_help_smoke():
    callers = [
        "register-spec-artifacts.py",
        "register-final-artifacts.py",
        "phase-handoff.py",
    ]
    for script in callers:
        result = _run([_caller_script(script), "--help"])
        assert result.returncode == 0, (
            f"{script} --help 返回 exit {result.returncode}\nstderr: {result.stderr}"
        )
        assert "usage:" in result.stdout.lower() or "usage:" in result.stderr.lower(), (
            f"{script} --help 输出缺少 usage\n{result.stdout}"
        )
    print(f"✓ test_caller_scripts_help_smoke: {len(callers)} 个调用方脚本 --help 正常")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Running orchestrator e2e integration tests...")
    print()

    test_plan_stage_pass()
    test_plan_stage_fail_cycle()
    test_final_stage_fail_gen_not_done()
    test_caller_scripts_help_smoke()

    print()
    print("=" * 60)
    print("All e2e tests passed! ✓")
