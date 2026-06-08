#!/usr/bin/env python3
"""
HARNESS Experience Injector — reads experience.md and failure_memory.jsonl,
filters by applicable phase, and injects relevant experience into task context.

Called by orchestrator before dispatching to workers.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any



def _get_knowledge_dir() -> Path:
    """Resolve knowledge directory from HARNESS_WORKSPACE or fallback to repo root."""
    workspace = os.getenv("HARNESS_WORKSPACE")
    if workspace:
        return Path(workspace) / ".harness" / "knowledge"
    return Path(__file__).resolve().parents[2] / ".harness" / "knowledge"

KNOWLEDGE_DIR = _get_knowledge_dir()
FAILURE_MEMORY = KNOWLEDGE_DIR / "failure_memory.jsonl"
EXPERIENCE_MD = KNOWLEDGE_DIR / "experience.md"


def load_failure_entries(step: str | None = None, days: int = 30) -> list[dict[str, Any]]:
    if not FAILURE_MEMORY.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = []
    for line in FAILURE_MEMORY.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        recorded = entry.get("recorded_at", "")
        if recorded:
            try:
                dt = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
                if dt < cutoff:
                    continue
            except ValueError:
                continue
        if step and entry.get("step") != step:
            continue
        entries.append(entry)
    return entries


def load_experience_sections(step: str | None = None) -> list[str]:
    if not EXPERIENCE_MD.exists():
        return []
    content = EXPERIENCE_MD.read_text()
    sections = []
    current_section = None
    current_lines = []

    for line in content.splitlines():
        if line.startswith("## "):
            if current_section and current_lines:
                sections.append((current_section, "\n".join(current_lines)))
            current_section = line[3:].strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section and current_lines:
        sections.append((current_section, "\n".join(current_lines)))

    if not step:
        return [body for _, body in sections]

    # Filter by step relevance
    step_keywords = {
        "REQ_DRAFT": ["需求", "requirement", "遗漏", "缺失"],
        "REQ_REVIEW": ["需求", "requirement", "审查", "review"],
        "SPEC_DRAFT": ["spec", "设计", "接口", "契约"],
        "SPEC_REVIEW": ["spec", "审查", "review", "架构"],
        "CODE_IMPL": ["代码", "code", "实现", "bug", "编译", "test"],
        "MACHINE_CHECK": ["测试", "test", "编译", "compile", "覆盖"],
        "DUAL_REVIEW": ["架构", "arch", "审查", "review", "规范"],
        "FINAL_ACCEPT": ["验收", "accept", "最终"],
    }

    keywords = step_keywords.get(step, [])
    filtered = []
    for title, body in sections:
        title_lower = title.lower()
        body_lower = body.lower()
        if any(kw in title_lower or kw in body_lower for kw in keywords):
            filtered.append(body)

    return filtered if filtered else [body for _, body in sections[-3:]]


def build_injection(step: str, max_items: int = 5) -> dict[str, Any]:
    failures = load_failure_entries(step)
    experiences = load_experience_sections(step)

    injection = {
        "step": step,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "failure_warnings": [],
        "experience_hints": [],
    }

    for entry in failures[:max_items]:
        injection["failure_warnings"].append({
            "gate_id": entry.get("gate_id", "unknown"),
            "message": entry.get("message", ""),
            "recorded_at": entry.get("recorded_at", ""),
        })

    for section in experiences[:max_items]:
        lines = [l.strip() for l in section.splitlines() if l.strip()]
        injection["experience_hints"].extend(lines[:3])

    injection["experience_hints"] = injection["experience_hints"][:max_items]
    return injection


def main() -> None:
    parser = argparse.ArgumentParser(description="HARNESS Experience Injector")
    parser.add_argument("--step", required=True, help="Current pipeline step")
    parser.add_argument("--max-items", type=int, default=5, help="Max items per category")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    args = parser.parse_args()

    injection = build_injection(args.step, args.max_items)

    if args.format == "json":
        print(json.dumps(injection, indent=2, ensure_ascii=False))
    else:
        print(f"=== Experience Injection for {args.step} ===")
        if injection["failure_warnings"]:
            print("\n--- Past Failures ---")
            for w in injection["failure_warnings"]:
                print(f"  [{w['gate_id']}] {w['message']}")
        if injection["experience_hints"]:
            print("\n--- Experience Hints ---")
            for h in injection["experience_hints"]:
                print(f"  - {h}")
        if not injection["failure_warnings"] and not injection["experience_hints"]:
            print("  No relevant experience found.")


if __name__ == "__main__":
    main()
