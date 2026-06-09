#!/usr/bin/env python3
"""init-workspace.py 集成测试。

覆盖：
  1. 全新工作区初始化（exit 0，文件/目录结构正确）
  2. 重复初始化被阻断（exit 1，提示已初始化）
  3. --force 覆盖行为（exit 0，提示"覆盖"）
  4. 初始化后 preflight REQ_DRAFT 可执行（exit 0，无 BLOCKER）
  5. 完整链路：init → preflight REQ_DRAFT → orchestrator --stage spec 读取同一个初始化状态文件
     （期望 exit 1，被 legacy spec 规则业务拦截，证明状态文件被加载并进入主校验链）

Run with: python3 .harness/tests/test_init_workspace.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = HARNESS_ROOT / ".harness" / "scripts"
INIT_SCRIPT = SCRIPTS_DIR / "init-workspace.py"
PREFLIGHT_SCRIPT = SCRIPTS_DIR / "preflight.py"
ORCHESTRATOR_SCRIPT = SCRIPTS_DIR / "orchestrator.py"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable] + args,
        cwd=str(cwd or HARNESS_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _init(workspace: str, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    return _run([str(INIT_SCRIPT), "--workspace", workspace] + (extra or []))


# ---------------------------------------------------------------------------

def test_fresh_init():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _init(tmpdir)
        assert result.returncode == 0, (
            f"全新初始化期望 exit 0，实际 exit {result.returncode}\n{result.stdout}\n{result.stderr}"
        )
        harness = Path(tmpdir) / ".harness"

        # 文件存在性
        assert (harness / "state" / "harness-state.json").exists(), "state/harness-state.json 未创建"
        assert (harness / "state" / "SESSION_BRIEF.md").exists(), "state/SESSION_BRIEF.md 未创建"
        assert (harness / "knowledge" / "experience.md").exists(), "knowledge/experience.md 未创建"
        assert (harness / "knowledge" / "failure_memory.jsonl").exists(), "knowledge/failure_memory.jsonl 未创建"
        assert (harness / "output" / "preflight-result.json").exists(), "output/preflight-result.json 未创建"

        # .gitkeep 目录存在
        for rel in ["output", "archive", "handoff", "logs", "knowledge/wal"]:
            assert (harness / rel / ".gitkeep").exists(), f"{rel}/.gitkeep 未创建"

        # 输出包含"创建"
        assert "创建" in result.stdout, "输出缺少'创建'标志"

        print("✓ test_fresh_init: exit 0，文件结构完整")


def test_repeat_init_blocked():
    with tempfile.TemporaryDirectory() as tmpdir:
        r1 = _init(tmpdir)
        assert r1.returncode == 0, f"首次初始化失败: {r1.stdout}"

        r2 = _init(tmpdir)
        assert r2.returncode == 1, (
            f"重复初始化期望 exit 1，实际 exit {r2.returncode}\n{r2.stdout}"
        )
        assert "已初始化" in r2.stdout, f"输出缺少'已初始化'提示\n{r2.stdout}"
        assert "--force" in r2.stdout, f"输出缺少 --force 提示\n{r2.stdout}"

        print("✓ test_repeat_init_blocked: exit 1，阻断信息正确")


def test_force_overwrite():
    with tempfile.TemporaryDirectory() as tmpdir:
        r1 = _init(tmpdir)
        assert r1.returncode == 0, f"首次初始化失败: {r1.stdout}"

        r2 = _init(tmpdir, ["--force"])
        assert r2.returncode == 0, (
            f"--force 期望 exit 0，实际 exit {r2.returncode}\n{r2.stdout}"
        )
        assert "覆盖" in r2.stdout, f"--force 输出缺少'覆盖'标志\n{r2.stdout}"

        print("✓ test_force_overwrite: exit 0，覆盖行为正确")


def test_next_step_preflight_works():
    """验证初始化后 init-workspace.py 提示的 preflight 命令真能 exit 0。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        r_init = _init(tmpdir)
        assert r_init.returncode == 0, f"初始化失败: {r_init.stdout}"

        # 确认 guidance 里出现了正确的阶段名 REQ_DRAFT（不是 prep）
        assert "REQ_DRAFT" in r_init.stdout, (
            f"guidance 缺少 REQ_DRAFT\n{r_init.stdout}"
        )
        assert "prep" not in r_init.stdout, (
            f"guidance 不应出现已废弃的 'prep' 阶段\n{r_init.stdout}"
        )

        state_file = str(Path(tmpdir) / ".harness" / "state" / "harness-state.json")
        r_preflight = _run([
            str(PREFLIGHT_SCRIPT),
            "--stage", "REQ_DRAFT",
            "--state-file", state_file,
        ])
        assert r_preflight.returncode == 0, (
            f"preflight REQ_DRAFT 期望 exit 0，实际 exit {r_preflight.returncode}\n"
            f"stdout: {r_preflight.stdout}\nstderr: {r_preflight.stderr}"
        )
        assert "BLOCKER: 0" in r_preflight.stdout, (
            f"preflight 存在 BLOCKER\n{r_preflight.stdout}"
        )

        print("✓ test_next_step_preflight_works: init → preflight REQ_DRAFT 全链路 exit 0，0 BLOCKER")


def test_full_chain_init_preflight_orchestrator():
    """完整链路：init → preflight REQ_DRAFT → orchestrator 读取初始化状态文件。

    orchestrator --stage spec 会：
      1. 加载 init 生成的 harness-state.json（schema 校验、integrity 校验）
      2. 因初始状态为 legacy 类型（无扁平 current_phase/checkpoints），
         被"spec 阶段默认不接受 legacy 状态"规则拦截 → exit 1

    exit 1 是预期结果——它证明状态文件被成功加载并进入主校验链，
    而不是在 argparse 或文件读取阶段就失败。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Step 1: init
        r_init = _init(tmpdir)
        assert r_init.returncode == 0, f"初始化失败: {r_init.stdout}"

        state_file = str(Path(tmpdir) / ".harness" / "state" / "harness-state.json")

        # Step 2: preflight REQ_DRAFT（确认初始状态文件通过 preflight）
        r_pre = _run([str(PREFLIGHT_SCRIPT), "--stage", "REQ_DRAFT", "--state-file", state_file])
        assert r_pre.returncode == 0, (
            f"preflight REQ_DRAFT 失败 exit {r_pre.returncode}\n{r_pre.stdout}"
        )
        assert "BLOCKER: 0" in r_pre.stdout, f"preflight 存在 BLOCKER\n{r_pre.stdout}"

        # Step 3: orchestrator 使用同一个初始化状态文件
        # --stage spec：初始状态是 legacy 类型（无扁平 current_phase/checkpoints），
        # 会被 "默认不接受 legacy spec" 规则拦截 → exit 1
        # 这验证了：状态文件被加载 + schema 校验通过 + 进入阶段判断层
        r_orch = _run([
            str(ORCHESTRATOR_SCRIPT),
            "--stage", "spec",
            "--state-file", state_file,
            "--workdir", str(HARNESS_ROOT),
        ])
        # exit 1 且错误来自业务逻辑（不是文件找不到或 argparse 错误）
        assert r_orch.returncode == 1, (
            f"orchestrator spec 期望 exit 1（legacy 模式拦截），实际 exit {r_orch.returncode}\n{r_orch.stdout}"
        )
        combined = r_orch.stdout + r_orch.stderr
        # 进到业务逻辑层的标志：schema 校验通过后才会走到这里
        assert "成功加载" in combined or "Schema 校验" in combined or "Blocker" in combined or "默认只接受" in combined, (
            f"输出不含预期业务拦截信息，说明未进入主校验链\n{combined}"
        )

        print("✓ test_full_chain_init_preflight_orchestrator: init → preflight → orchestrator 全链路，状态文件被加载并进入业务校验层")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Running init-workspace integration tests...")
    print()

    test_fresh_init()
    test_repeat_init_blocked()
    test_force_overwrite()
    test_next_step_preflight_works()
    test_full_chain_init_preflight_orchestrator()

    print()
    print("=" * 60)
    print("All init-workspace tests passed! ✓")
