#!/usr/bin/env python3
"""init-workspace.py 集成测试。

覆盖：
  1. 全新工作区初始化（exit 0，文件/目录结构正确）
  2. 重复初始化被阻断（exit 1，提示已初始化）
  3. --force 覆盖行为（exit 0，提示"覆盖"）
  4. 初始化后 preflight REQ_DRAFT 可执行（exit 0，无 BLOCKER）

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


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Running init-workspace integration tests...")
    print()

    test_fresh_init()
    test_repeat_init_blocked()
    test_force_overwrite()
    test_next_step_preflight_works()

    print()
    print("=" * 60)
    print("All init-workspace tests passed! ✓")
