#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FINAL_REPORT_FILENAME = "audit-report.md"
PROJECT_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
RESULT_PATTERN = re.compile(r"^result:\s*(accept|rework)\s*$", re.MULTILINE)
REVIEW_ID_PATTERN = re.compile(r"^review_id:\s*(.+?)\s*$", re.MULTILINE)
COUNT_PATTERNS = {
    "critical": re.compile(r"^critical:\s*(\d+)\s*$", re.MULTILINE),
    "high": re.compile(r"^high:\s*(\d+)\s*$", re.MULTILINE),
    "medium": re.compile(r"^medium:\s*(\d+)\s*$", re.MULTILINE),
    "low": re.compile(r"^low:\s*(\d+)\s*$", re.MULTILINE),
}


@dataclass(frozen=True)
class FinalReportValidation:
    ok: bool
    reason: str
    resolved_path: Path | None = None
    result: str | None = None
    critical: int | None = None
    high: int | None = None
    medium: int | None = None
    low: int | None = None


def expected_final_report_relpath(project_code: str) -> str:
    return f".harness/output/final/{project_code}/" + FINAL_REPORT_FILENAME


def is_safe_project_code(project_code: str) -> bool:
    return bool(PROJECT_CODE_PATTERN.fullmatch(project_code))


def validate_final_report(project_root: Path, state: dict[str, Any]) -> FinalReportValidation:
    project_code = str(state.get("project", {}).get("code", "")).strip()
    if not project_code:
        return FinalReportValidation(False, "project.code missing")
    if not is_safe_project_code(project_code):
        return FinalReportValidation(False, "project.code contains illegal path characters")

    audit_report = state.get("artifacts", {}).get("phase_4", {}).get("audit_report")
    if not isinstance(audit_report, str) or not audit_report.strip():
        return FinalReportValidation(False, "phase_4.audit_report missing")

    expected_relpath = expected_final_report_relpath(project_code)
    normalized_relpath = audit_report.strip().replace("\\", "/")
    if normalized_relpath != expected_relpath:
        return FinalReportValidation(False, f"audit_report must exactly equal {expected_relpath}")

    expected_dir = (project_root / f".harness/output/final/{project_code}").resolve()
    resolved_path = (project_root / normalized_relpath).resolve()
    try:
        resolved_path.relative_to(expected_dir)
    except ValueError:
        return FinalReportValidation(False, "audit_report resolves outside target final directory")

    if resolved_path.name != FINAL_REPORT_FILENAME:
        return FinalReportValidation(False, f"audit_report filename must be {FINAL_REPORT_FILENAME}")
    if resolved_path.suffix.lower() != ".md":
        return FinalReportValidation(False, "audit_report must be a Markdown file")
    if not resolved_path.exists() or not resolved_path.is_file():
        return FinalReportValidation(False, "audit_report file does not exist")

    try:
        content = resolved_path.read_text(encoding="utf-8")
    except Exception as exc:
        return FinalReportValidation(False, f"audit_report cannot be read: {exc}")

    if "# Audit Report" not in content and "# audit-report" not in content.lower():
        return FinalReportValidation(False, "audit_report missing standard title")
    if not REVIEW_ID_PATTERN.search(content):
        return FinalReportValidation(False, "audit_report missing review_id")

    result_match = RESULT_PATTERN.search(content)
    if not result_match:
        return FinalReportValidation(False, "audit_report missing valid result: accept|rework")
    result = result_match.group(1)

    counts: dict[str, int] = {}
    for name, pattern in COUNT_PATTERNS.items():
        match = pattern.search(content)
        if not match:
            return FinalReportValidation(False, f"audit_report missing {name} count")
        counts[name] = int(match.group(1))

    return FinalReportValidation(
        ok=True,
        reason="PASS",
        resolved_path=resolved_path,
        result=result,
        critical=counts["critical"],
        high=counts["high"],
        medium=counts["medium"],
        low=counts["low"],
    )
