#!/usr/bin/env python3
"""
HARNESS state integrity — HMAC-SHA256 seal/verify for pipeline.json.

Generalized from state-contracts state_integrity.py.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INTEGRITY_KEY_FILENAME = ".harness-state.integrity.key"
INTEGRITY_VERSION = "1.0"
INTEGRITY_ALGORITHM = "HMAC-SHA256"


def workspace_root_for_state_file(state_file: Path) -> Path:
    resolved = state_file.expanduser().resolve()
    for candidate in [resolved.parent, *resolved.parents]:
        harness_root = candidate / ".harness"
        if harness_root.exists() and (harness_root / "scripts").exists():
            return candidate
    raise ValueError(f"无法根据state_file推断工作区根目录: {state_file}")


def integrity_key_path(state_file: Path) -> Path:
    workspace_root = workspace_root_for_state_file(state_file)
    return workspace_root / ".harness/state" / INTEGRITY_KEY_FILENAME


def integrity_key_exists(state_file: Path) -> bool:
    try:
        return integrity_key_path(state_file).exists()
    except ValueError:
        return False


def ensure_integrity_key(state_file: Path) -> bytes:
    key_path = integrity_key_path(state_file)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_text(secrets.token_hex(32), encoding="utf-8")
    return key_path.read_text(encoding="utf-8").strip().encode("utf-8")


def read_integrity_key(state_file: Path) -> bytes:
    key_path = integrity_key_path(state_file)
    if not key_path.exists():
        raise ValueError(f"状态完整性密钥不存在: {key_path}")
    return key_path.read_text(encoding="utf-8").strip().encode("utf-8")


def key_fingerprint(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def canonicalize_state(state: dict[str, Any]) -> str:
    payload = json.loads(json.dumps(state))
    payload.pop("integrity", None)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_state_hmac(state: dict[str, Any], key: bytes) -> str:
    canonical = canonicalize_state(state).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def seal_state(state_file: Path, state: dict[str, Any], *, key_source_state_file: Path | None = None) -> dict[str, Any]:
    key_material_state_file = key_source_state_file or state_file
    key = ensure_integrity_key(key_material_state_file)
    sealed = json.loads(json.dumps(state))
    sealed["integrity"] = {
        "version": INTEGRITY_VERSION,
        "algorithm": INTEGRITY_ALGORITHM,
        "key_fingerprint": key_fingerprint(key),
        "signed_at": datetime.now(timezone.utc).isoformat(),
        "state_hmac": compute_state_hmac(sealed, key),
    }
    return sealed


def verify_state_integrity(state_file: Path, state: dict[str, Any], *, allow_unsigned: bool = False) -> str | None:
    integrity = state.get("integrity")
    if integrity is None:
        if allow_unsigned or not integrity_key_exists(state_file):
            return None
        return "状态文件缺少integrity签名。"
    if not isinstance(integrity, dict):
        return "状态文件integrity必须为对象。"
    for field in ["version", "algorithm", "key_fingerprint", "signed_at", "state_hmac"]:
        if not isinstance(integrity.get(field), str) or not integrity[field]:
            return f"状态文件integrity.{field}不能为空。"
    if integrity.get("version") != INTEGRITY_VERSION:
        return f"状态文件integrity.version非法: {integrity.get('version')}"
    if integrity.get("algorithm") != INTEGRITY_ALGORITHM:
        return f"状态文件integrity.algorithm非法: {integrity.get('algorithm')}"
    try:
        key = read_integrity_key(state_file)
    except ValueError as exc:
        return str(exc)
    expected_fingerprint = key_fingerprint(key)
    if integrity.get("key_fingerprint") != expected_fingerprint:
        return (
            "状态文件integrity.key_fingerprint与当前工作区密钥不一致: "
            f"{integrity.get('key_fingerprint')} != {expected_fingerprint}"
        )
    expected_hmac = compute_state_hmac(state, key)
    if integrity.get("state_hmac") != expected_hmac:
        return "状态文件完整性校验失败: state_hmac不匹配。"
    return None


def resolve_state_file(
    state_file: Path | None = None,
    *,
    prefer_state_dir: bool = True,
) -> Path:
    """
    解析状态文件路径，按优先级返回实际路径。
    
    优先级（prefer_state_dir=True，默认）：
    1. 显式 state_file 参数
    2. .harness/state/harness-state.json
    3. .harness/harness-state.json
    
    优先级（prefer_state_dir=False）：
    1. 显式 state_file 参数
    2. .harness/harness-state.json
    
    注意：不再默认鼓励 pipeline.json / harness-workflow-state.json。
    """
    if state_file is not None:
        return state_file
    
    workspace_root = Path.cwd()
    harness_root = workspace_root / ".harness"
    
    if prefer_state_dir:
        state_dir_file = harness_root / "state" / "harness-state.json"
        if state_dir_file.exists():
            return state_dir_file
    
    legacy_file = harness_root / "harness-state.json"
    if legacy_file.exists():
        return legacy_file
    
    # 默认返回 state_dir 路径（即使不存在，让调用方决定是否创建）
    if prefer_state_dir:
        return harness_root / "state" / "harness-state.json"
    return legacy_file


def load_state(
    state_file: Path | None = None,
    *,
    verify: bool = True,
    allow_unsigned: bool = False,
    prefer_state_dir: bool = True,
) -> tuple[dict[str, Any], Path]:
    """
    加载状态文件并可选验证完整性。
    
    Args:
        state_file: 显式指定的状态文件路径，None 则自动解析
        verify: 是否验证 HMAC 完整性
        allow_unsigned: 是否允许未签名状态
        prefer_state_dir: 是否优先使用 .harness/state/harness-state.json
    
    Returns:
        (state_dict, actual_path): 状态字典和实际使用的文件路径
    
    Raises:
        FileNotFoundError: 状态文件不存在
        ValueError: 完整性验证失败（当 verify=True 时）
    """
    actual_path = resolve_state_file(state_file, prefer_state_dir=prefer_state_dir)
    
    if not actual_path.exists():
        raise FileNotFoundError(f"状态文件不存在: {actual_path}")
    
    state = json.loads(actual_path.read_text(encoding="utf-8"))
    
    if verify:
        error = verify_state_integrity(actual_path, state, allow_unsigned=allow_unsigned)
        if error:
            raise ValueError(f"状态完整性验证失败: {error}")
    
    return state, actual_path


def save_state(
    state: dict[str, Any],
    state_file: Path | None = None,
    *,
    seal: bool = True,
    prefer_state_dir: bool = True,
) -> Path:
    """
    保存状态文件并可选签名。
    
    Args:
        state: 状态字典
        state_file: 显式指定的状态文件路径，None 则自动解析
        seal: 是否进行 HMAC 签名
        prefer_state_dir: 是否优先使用 .harness/state/harness-state.json
    
    Returns:
        实际保存的文件路径
    """
    actual_path = resolve_state_file(state_file, prefer_state_dir=prefer_state_dir)
    actual_path.parent.mkdir(parents=True, exist_ok=True)
    
    if seal:
        state = seal_state(actual_path, state)
    
    actual_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    return actual_path


# =============================================================================
# Legacy State View Adapter (WP7)
# =============================================================================
"""
Legacy state view adapter for v2 harness state structure.

Provides read-only projections from v2 state (phase_truth/recovery_truth) 
to legacy field names (current_phase/phase_status/resume_context/checkpoints/artifacts).

Usage:
    from state_integrity import legacy_view, LegacyStateView
    
    state, _ = load_state()
    view = legacy_view(state)
    
    # Access projected fields
    phase = view.current_phase
    ps = view.phase_status
    resume_ctx = view.resume_context
    checkpoints = view.checkpoints
    artifacts = view.artifacts
    
    # Convenience accessors
    phase_2 = view.artifacts_phase_2
    phase_3 = view.artifacts_phase_3
    
    # For scripts expecting flat dict
    legacy_dict = view.to_legacy_dict()
"""
from typing import Any as _Any


class LegacyStateView:
    """
    Read-only adapter that projects v2 state structure to legacy field names.
    
    v2 structure:
        - phase_truth.current_phase -> current_phase
        - phase_truth.phase_status -> phase_status (computed from phase_truth.phase_status + previous_phases)
        - recovery_truth.resume_context -> resume_context
        - recovery_truth.checkpoints -> checkpoints
        - artifacts (runtime, not in v2 schema) -> artifacts
    
    Legacy scripts can use:
        view.current_phase
        view.phase_status
        view.resume_context
        view.checkpoints
        view.artifacts
        
    Or access nested fields directly:
        view.artifacts_phase_2
        view.artifacts_phase_3
    """
    
    def __init__(self, state: dict[str, _Any]):
        self._state = state
    
    # Direct mappings from v2 structure
    
    @property
    def current_phase(self) -> str | None:
        """
        Map: phase_truth.current_phase (v2) -> current_phase (legacy)
        
        Falls back to root-level current_phase if v2 structure not present.
        """
        phase_truth = self._state.get("phase_truth", {})
        if isinstance(phase_truth, dict) and "current_phase" in phase_truth:
            return phase_truth.get("current_phase")
        # Backward compatibility: direct root-level field
        return self._state.get("current_phase")
    
    @property
    def phase_status(self) -> dict[str, _Any]:
        """
        Map: phase_truth.phase_status (v2) -> phase_status (legacy)
        
        Falls back to root-level phase_status if v2 structure not present.
        """
        phase_truth = self._state.get("phase_truth", {})
        if isinstance(phase_truth, dict) and "phase_status" in phase_truth:
            # v2 stores phase_status as a string (single status for current phase)
            # Legacy expects a dict of {phase_name: status}
            # For now, return as-is; caller handles both formats
            return phase_truth.get("phase_status")
        # Backward compatibility: direct root-level field
        return self._state.get("phase_status", {})
    
    @property
    def resume_context(self) -> dict[str, _Any] | None:
        """
        Map: recovery_truth.resume_context (v2) -> resume_context (legacy)
        
        Falls back to root-level resume_context if v2 structure not present.
        """
        recovery_truth = self._state.get("recovery_truth", {})
        if isinstance(recovery_truth, dict) and "resume_context" in recovery_truth:
            return recovery_truth.get("resume_context")
        # Backward compatibility: direct root-level field
        return self._state.get("resume_context")
    
    @property
    def checkpoints(self) -> list[_Any]:
        """
        Map: recovery_truth.checkpoints (v2) -> checkpoints (legacy)
        
        Falls back to root-level checkpoints if v2 structure not present.
        """
        recovery_truth = self._state.get("recovery_truth", {})
        if isinstance(recovery_truth, dict) and "checkpoints" in recovery_truth:
            return recovery_truth.get("checkpoints", [])
        # Backward compatibility: direct root-level field
        return self._state.get("checkpoints", [])
    
    # Runtime fields (not in v2 schema, but present during execution)
    
    @property
    def artifacts(self) -> dict[str, _Any]:
        """
        Map: artifacts (runtime, root-level) -> artifacts (legacy)
        
        Note: artifacts is NOT part of v2 schema but is created at runtime
        by scripts like init-gen-nodes.py, phase-handoff.py, etc.
        """
        return self._state.get("artifacts", {})
    
    @property
    def artifacts_phase_2(self) -> dict[str, _Any]:
        """Convenience accessor: artifacts.phase_2"""
        return self.artifacts.get("phase_2", {})
    
    @property
    def artifacts_phase_3(self) -> dict[str, _Any]:
        """Convenience accessor: artifacts.phase_3"""
        return self.artifacts.get("phase_3", {})
    
    # Utility methods for legacy code patterns
    
    def get_phase_status_for(self, phase_name: str) -> str | None:
        """
        Get status for a specific phase.
        
        Handles both:
        - Legacy dict format: {"prep": "completed", "spec": "in_progress"}
        - v2 single-status format: returns the status string directly
        """
        ps = self.phase_status
        if isinstance(ps, dict):
            return ps.get(phase_name)
        # If phase_status is a string (v2), it represents current phase status
        # Caller should use current_phase to determine which phase this applies to
        return None
    
    def get_checkpoint(self, key: str, default: _Any = None) -> _Any:
        """Convenience method to get a specific checkpoint value."""
        # checkpoints in v2 is a list, in legacy it may be a dict
        cps = self.checkpoints
        if isinstance(cps, dict):
            return cps.get(key, default)
        # If it's a list, return default (caller should handle list format)
        return default
    
    def to_legacy_dict(self) -> dict[str, _Any]:
        """
        Export a legacy-compatible dictionary with projected fields at root level.
        
        Useful for scripts that expect flat access like state["current_phase"].
        Returns a NEW dict; does NOT modify the original state.
        """
        return {
            **self._state,
            "current_phase": self.current_phase,
            "phase_status": self.phase_status,
            "resume_context": self.resume_context,
            "checkpoints": self.checkpoints,
            "artifacts": self.artifacts,
        }


def legacy_view(state: dict[str, _Any]) -> LegacyStateView:
    """
    Factory function to create a LegacyStateView.
    
    Usage:
        view = legacy_view(state)
        phase = view.current_phase
        phase_2 = view.artifacts_phase_2
    """
    return LegacyStateView(state)


# Export mapping rules for documentation
MAPPING_RULES: dict[str, dict[str, str]] = {
    "current_phase": {
        "v2_path": "phase_truth.current_phase",
        "legacy_path": "current_phase",
        "mapping_type": "direct_with_fallback",
        "notes": "Direct mapping; falls back to root-level if v2 structure absent"
    },
    "phase_status": {
        "v2_path": "phase_truth.phase_status",
        "legacy_path": "phase_status",
        "mapping_type": "derived",
        "notes": "v2 stores as single status string; legacy expects dict {phase: status}"
    },
    "resume_context": {
        "v2_path": "recovery_truth.resume_context",
        "legacy_path": "resume_context",
        "mapping_type": "direct_with_fallback",
        "notes": "Direct mapping; falls back to root-level if v2 structure absent"
    },
    "checkpoints": {
        "v2_path": "recovery_truth.checkpoints",
        "legacy_path": "checkpoints",
        "mapping_type": "direct_with_fallback",
        "notes": "Direct mapping; falls back to root-level if v2 structure absent"
    },
    "artifacts.phase_2": {
        "v2_path": "artifacts.phase_2",
        "legacy_path": "artifacts.phase_2",
        "mapping_type": "runtime_only",
        "notes": "Not in v2 schema; created at runtime by scripts"
    },
    "artifacts.phase_3": {
        "v2_path": "artifacts.phase_3",
        "legacy_path": "artifacts.phase_3",
        "mapping_type": "runtime_only",
        "notes": "Not in v2 schema; created at runtime by init-gen-nodes.py, etc."
    },
}
