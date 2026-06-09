#!/usr/bin/env python3
"""状态文件路径解析测试 — 验证统一主状态文件与旧名兼容回退。

主状态文件：harness-state.json（CANONICAL_STATE_FILENAME）
兼容旧名：harness-workflow-state.json（LEGACY_STATE_FILENAMES）

覆盖：
  1. 默认解析到正式主路径（state/harness-state.json）
  2. 正式名与旧名同时存在时，优先正式名
  3. 仅旧名存在时，兼容回退仍可读取
  4. 显式 state_file 参数始终最高优先级
  5. 旧根目录位置（.harness/harness-state.json）兼容回退

Run with: python3 .harness/tests/test_state_path_resolution.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from state_integrity import (  # noqa: E402
    CANONICAL_STATE_FILENAME,
    LEGACY_STATE_FILENAMES,
    resolve_state_file,
)


def _make_harness(tmp: Path) -> Path:
    harness = tmp / ".harness"
    (harness / "state").mkdir(parents=True)
    return harness


def test_constants_sane():
    assert CANONICAL_STATE_FILENAME == "harness-state.json"
    assert "harness-workflow-state.json" in LEGACY_STATE_FILENAMES
    print("✓ test_constants_sane: 主名/旧名常量符合预期")


def test_default_resolves_to_canonical_when_none_exist():
    with tempfile.TemporaryDirectory() as t:
        harness = _make_harness(Path(t))
        result = resolve_state_file(harness_root=harness)
        assert result == harness / "state" / CANONICAL_STATE_FILENAME, (
            f"空目录应默认正式主路径，实际 {result}"
        )
    print("✓ test_default_resolves_to_canonical_when_none_exist: 默认 → state/harness-state.json")


def test_canonical_wins_over_legacy():
    with tempfile.TemporaryDirectory() as t:
        harness = _make_harness(Path(t))
        canonical = harness / "state" / CANONICAL_STATE_FILENAME
        legacy = harness / "state" / LEGACY_STATE_FILENAMES[0]
        canonical.write_text("{}", encoding="utf-8")
        legacy.write_text("{}", encoding="utf-8")
        result = resolve_state_file(harness_root=harness)
        assert result == canonical, f"正式名应优先于旧名，实际 {result}"
    print("✓ test_canonical_wins_over_legacy: 两者并存 → 正式名优先")


def test_legacy_fallback_when_only_legacy_exists():
    with tempfile.TemporaryDirectory() as t:
        harness = _make_harness(Path(t))
        legacy = harness / "state" / LEGACY_STATE_FILENAMES[0]
        legacy.write_text("{}", encoding="utf-8")
        result = resolve_state_file(harness_root=harness)
        assert result == legacy, f"仅旧名存在应回退到旧名，实际 {result}"
    print("✓ test_legacy_fallback_when_only_legacy_exists: 仅旧名 → 兼容回退读取")


def test_explicit_arg_always_wins():
    with tempfile.TemporaryDirectory() as t:
        harness = _make_harness(Path(t))
        canonical = harness / "state" / CANONICAL_STATE_FILENAME
        canonical.write_text("{}", encoding="utf-8")
        explicit = Path(t) / "somewhere" / "custom-state.json"
        result = resolve_state_file(explicit, harness_root=harness)
        assert result == explicit, f"显式参数应最高优先，实际 {result}"
    print("✓ test_explicit_arg_always_wins: 显式 state_file → 直接采用")


def test_legacy_root_location_fallback():
    """旧根目录位置 .harness/harness-state.json 兼容回退。"""
    with tempfile.TemporaryDirectory() as t:
        harness = _make_harness(Path(t))
        # state/ 下都没有，但 .harness/ 根下有旧位置文件
        root_legacy = harness / CANONICAL_STATE_FILENAME
        root_legacy.write_text("{}", encoding="utf-8")
        result = resolve_state_file(harness_root=harness)
        assert result == root_legacy, f"应回退到旧根位置，实际 {result}"
    print("✓ test_legacy_root_location_fallback: state/ 为空 → 回退 .harness/harness-state.json")


if __name__ == "__main__":
    print("Running state path resolution tests...")
    print()

    test_constants_sane()
    test_default_resolves_to_canonical_when_none_exist()
    test_canonical_wins_over_legacy()
    test_legacy_fallback_when_only_legacy_exists()
    test_explicit_arg_always_wins()
    test_legacy_root_location_fallback()

    print()
    print("=" * 60)
    print("All state path resolution tests passed! ✓")
