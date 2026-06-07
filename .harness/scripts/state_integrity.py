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
