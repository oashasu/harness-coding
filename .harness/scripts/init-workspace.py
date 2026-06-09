#!/usr/bin/env python3
"""初始化 HARNESS 工作区运行目录。

在用户项目目录下生成运行态骨架：
  - state/harness-state.json      (从模板复制)
  - state/SESSION_BRIEF.md        (从模板复制)
  - knowledge/experience.md       (从模板复制)
  - knowledge/failure_memory.jsonl (空文件)
  - output/ archive/ handoff/ logs/ knowledge/wal/  (.gitkeep)

规则：
  - 默认拒绝覆盖已存在的运行态文件
  - --force 只覆盖模板生成物，不清空 archive/ 和 knowledge/
  - 幂等：重复运行不会破坏已有状态

用法：
  python3 .harness/scripts/init-workspace.py
  python3 .harness/scripts/init-workspace.py --workspace /path/to/project
  python3 .harness/scripts/init-workspace.py --force
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"

# (模板文件名, 目标路径相对于 .harness/)
TEMPLATE_FILES: list[tuple[str, str]] = [
    ("harness-workflow-state.template.json", "state/harness-state.json"),
    ("SESSION_BRIEF.template.md", "state/SESSION_BRIEF.md"),
    ("experience.template.md", "knowledge/experience.md"),
    ("preflight-result.template.json", "output/preflight-result.json"),
]

# 仅创建目录 + .gitkeep，不从模板复制
EMPTY_DIRS: list[str] = [
    "output",
    "archive",
    "handoff",
    "logs",
    "knowledge/wal",
]

# 这些路径的存在意味着工作区已初始化（--force 前检查）
INIT_SENTINEL = "state/harness-state.json"


def _already_initialized(harness_dir: Path) -> bool:
    return (harness_dir / INIT_SENTINEL).exists()


def _ensure_gitkeep(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    gitkeep = directory / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()


def _copy_template(template_name: str, target: Path, force: bool) -> str:
    src = TEMPLATES_DIR / template_name
    if not src.exists():
        return f"  [跳过] 模板不存在: {src}"
    if target.exists() and not force:
        return f"  [保留] {target.relative_to(target.parent.parent.parent)} (已存在，用 --force 覆盖)"
    action = "覆盖" if target.exists() else "创建"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return f"  [{action}] {target.relative_to(target.parent.parent.parent)}"


def _create_empty_file(path: Path, force: bool) -> str:
    if path.exists() and not force:
        return f"  [保留] {path.name} (已存在)"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return f"  [创建] {path.name}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="初始化 HARNESS 工作区运行目录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--workspace",
        default=".",
        help="工作区根目录（默认：当前目录）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制覆盖模板生成物（不清空 archive/ 和 knowledge/）",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    harness_dir = workspace / ".harness"

    print(f"HARNESS 工作区初始化")
    print(f"  workspace : {workspace}")
    print(f"  skill_root: {SKILL_ROOT}")
    print()

    if not TEMPLATES_DIR.exists():
        print(f"[错误] 模板目录不存在: {TEMPLATES_DIR}")
        print("  请确认 init-workspace.py 与 templates/ 在同一个 .harness/ 目录下。")
        return 1

    if _already_initialized(harness_dir) and not args.force:
        print("[中止] 工作区已初始化（state/harness-state.json 已存在）。")
        print("  若要重新初始化，请使用 --force 参数。")
        print("  注意：--force 不会清空 archive/ 和 knowledge/。")
        return 1

    print("--- 创建运行目录 ---")
    for rel_dir in EMPTY_DIRS:
        target_dir = harness_dir / rel_dir
        _ensure_gitkeep(target_dir)
        print(f"  [就绪] {rel_dir}/")

    print()
    print("--- 从模板生成初始文件 ---")
    for template_name, rel_target in TEMPLATE_FILES:
        target = harness_dir / rel_target
        msg = _copy_template(template_name, target, args.force)
        print(msg)

    jsonl_path = harness_dir / "knowledge" / "failure_memory.jsonl"
    print(_create_empty_file(jsonl_path, args.force))

    print()
    print("--- 完成 ---")
    print(f"工作区已初始化：{harness_dir}")
    print()
    print("下一步：")
    print(f"  1. 编辑 {harness_dir}/state/harness-state.json，填写 contract_hash 和 prompt_version")
    print(f"  2. 运行 preflight 前置检查（使用首个工作流阶段）：")
    print(f"       python3 {SKILL_ROOT}/scripts/preflight.py \\")
    print(f"         --stage REQ_DRAFT \\")
    print(f"         --state-file {harness_dir}/state/harness-state.json")
    print(f"  3. 查阅 {SKILL_ROOT.parent}/docs/harness-skill-market-packaging.md 了解运行态分层规则")
    return 0


if __name__ == "__main__":
    sys.exit(main())
