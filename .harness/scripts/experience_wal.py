#!/usr/bin/env python3
"""
HARNESS Experience WAL — Write-Ahead Log for knowledge recording.

Provides atomic append to failure_memory.jsonl and experience.md.
Used by gate_runner and knowledge-curator.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / ".harness" / "knowledge"
WAL_DIR = KNOWLEDGE_DIR / "wal"
FAILURE_MEMORY = KNOWLEDGE_DIR / "failure_memory.jsonl"
EXPERIENCE_MD = KNOWLEDGE_DIR / "experience.md"


def ensure_dirs() -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    WAL_DIR.mkdir(parents=True, exist_ok=True)


def wal_append(entry: dict[str, Any]) -> Path:
    """Append entry to WAL, then flush to failure_memory.jsonl."""
    ensure_dirs()
    ts = datetime.now(timezone.utc)
    wal_file = WAL_DIR / f"wal-{ts.strftime('%Y%m%d_%H%M%S_%f')}.json"

    entry["wal_timestamp"] = ts.isoformat()
    wal_file.write_text(json.dumps(entry, ensure_ascii=False))

    # Flush to failure_memory
    with FAILURE_MEMORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return wal_file


def record_gate_failure(gate_id: str, message: str, step: str, details: dict | None = None) -> dict[str, Any]:
    entry = {
        "type": "gate_failure",
        "gate_id": gate_id,
        "step": step,
        "message": message,
        "details": details or {},
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    wal_append(entry)
    return entry


def record_drift_pattern(pattern: str, step: str, evidence: str) -> dict[str, Any]:
    entry = {
        "type": "drift_pattern",
        "pattern": pattern,
        "step": step,
        "evidence": evidence,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    wal_append(entry)
    return entry


def record_positive_experience(title: str, description: str, applicable_phases: list[str]) -> dict[str, Any]:
    entry = {
        "type": "positive",
        "title": title,
        "description": description,
        "applicable_phases": applicable_phases,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    wal_append(entry)
    return entry


def append_experience_md(section: str, content: str) -> None:
    """Append content to experience.md under a section."""
    ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not EXPERIENCE_MD.exists():
        EXPERIENCE_MD.write_text("# HARNESS Experience Log\n\n")

    with EXPERIENCE_MD.open("a", encoding="utf-8") as f:
        f.write(f"\n## {section} ({ts})\n\n{content}\n")


def flush_wal() -> int:
    """Flush all WAL entries to failure_memory.jsonl. Returns count of flushed entries."""
    ensure_dirs()
    count = 0
    for wal_file in sorted(WAL_DIR.glob("wal-*.json")):
        try:
            entry = json.loads(wal_file.read_text())
            with FAILURE_MEMORY.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            wal_file.unlink()
            count += 1
        except (json.JSONDecodeError, OSError):
            continue
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="HARNESS Experience WAL")
    sub = parser.add_subparsers(dest="command")

    gate_parser = sub.add_parser("gate-failure", help="Record gate failure")
    gate_parser.add_argument("--gate-id", required=True)
    gate_parser.add_argument("--message", required=True)
    gate_parser.add_argument("--step", required=True)

    drift_parser = sub.add_parser("drift", help="Record drift pattern")
    drift_parser.add_argument("--pattern", required=True)
    drift_parser.add_argument("--step", required=True)
    drift_parser.add_argument("--evidence", required=True)

    positive_parser = sub.add_parser("positive", help="Record positive experience")
    positive_parser.add_argument("--title", required=True)
    positive_parser.add_argument("--description", required=True)
    positive_parser.add_argument("--phases", nargs="+", required=True)

    sub.add_parser("flush", help="Flush WAL entries")

    args = parser.parse_args()

    if args.command == "gate-failure":
        entry = record_gate_failure(args.gate_id, args.message, args.step)
        print(json.dumps(entry, indent=2))
    elif args.command == "drift":
        entry = record_drift_pattern(args.pattern, args.step, args.evidence)
        print(json.dumps(entry, indent=2))
    elif args.command == "positive":
        entry = record_positive_experience(args.title, args.description, args.phases)
        print(json.dumps(entry, indent=2))
    elif args.command == "flush":
        count = flush_wal()
        print(f"Flushed {count} WAL entries")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
