#!/usr/bin/env python3
"""
HARNESS Knowledge Curator — curates experience from WAL entries.

Reads failure_memory.jsonl, deduplicates, applies decay, and updates experience.md.
Called after KNOWLEDGE_ARCHIVE step.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / ".harness" / "knowledge"
FAILURE_MEMORY = KNOWLEDGE_DIR / "failure_memory.jsonl"
EXPERIENCE_MD = KNOWLEDGE_DIR / "experience.md"
WAL_DIR = KNOWLEDGE_DIR / "wal"

# Decay: entries older than this lose relevance
DECAY_HALF_LIFE_DAYS = 30
MAX_EXPERIENCE_ENTRIES = 100


def load_entries() -> list[dict[str, Any]]:
    if not FAILURE_MEMORY.exists():
        return []
    entries = []
    for line in FAILURE_MEMORY.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def compute_decay_weight(recorded_at: str) -> float:
    try:
        dt = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        return max(0.1, 2 ** (-age_days / DECAY_HALF_LIFE_DAYS))
    except (ValueError, TypeError):
        return 0.5


def deduplicate(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = f"{entry.get('type', '')}:{entry.get('gate_id', '')}:{entry.get('pattern', '')}"
        if key in seen:
            # Keep the more recent one, increment count
            existing = seen[key]
            existing["count"] = existing.get("count", 1) + 1
            if entry.get("recorded_at", "") > existing.get("recorded_at", ""):
                entry["count"] = existing["count"]
                seen[key] = entry
        else:
            entry["count"] = 1
            seen[key] = entry
    return list(seen.values())


def apply_decay(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for entry in entries:
        weight = compute_decay_weight(entry.get("recorded_at", ""))
        entry["decay_weight"] = round(weight, 3)
    return entries


def filter_and_rank(entries: list[dict[str, Any]], max_entries: int = MAX_EXPERIENCE_ENTRIES) -> list[dict[str, Any]]:
    # Sort by weight * count
    entries.sort(key=lambda e: e.get("decay_weight", 0) * e.get("count", 1), reverse=True)
    return entries[:max_entries]


def generate_experience_md(entries: list[dict[str, Any]]) -> str:
    lines = ["# HARNESS Experience Log\n"]
    lines.append(f"_Last curated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_\n")

    # Group by type
    gate_failures = [e for e in entries if e.get("type") == "gate_failure"]
    drift_patterns = [e for e in entries if e.get("type") == "drift_pattern"]
    positive = [e for e in entries if e.get("type") == "positive"]

    if gate_failures:
        lines.append("\n## Gate Failure Patterns\n")
        for entry in gate_failures[:20]:
            count = entry.get("count", 1)
            weight = entry.get("decay_weight", 1)
            gate_id = entry.get("gate_id", "unknown")
            message = entry.get("message", "")
            step = entry.get("step", "")
            lines.append(f"- **[{gate_id}]** ({step}) {message} [seen {count}x, weight {weight}]")

    if drift_patterns:
        lines.append("\n## Drift Patterns\n")
        for entry in drift_patterns[:20]:
            count = entry.get("count", 1)
            weight = entry.get("decay_weight", 1)
            pattern = entry.get("pattern", "")
            step = entry.get("step", "")
            lines.append(f"- **{pattern}** ({step}) [seen {count}x, weight {weight}]")

    if positive:
        lines.append("\n## Positive Experiences\n")
        for entry in positive[:20]:
            title = entry.get("title", "")
            desc = entry.get("description", "")
            phases = ", ".join(entry.get("applicable_phases", []))
            lines.append(f"- **{title}**: {desc} [{phases}]")

    return "\n".join(lines) + "\n"


def curate(dry_run: bool = False) -> dict[str, Any]:
    entries = load_entries()
    entries = deduplicate(entries)
    entries = apply_decay(entries)
    entries = filter_and_rank(entries)

    result = {
        "total_raw": len(load_entries()),
        "after_dedup": len(entries),
        "curated_at": datetime.now(timezone.utc).isoformat(),
    }

    if not dry_run:
        content = generate_experience_md(entries)
        EXPERIENCE_MD.write_text(content)
        result["experience_md_updated"] = True

    return result


def prune_stale(max_age_days: int = 90) -> int:
    """Remove entries older than max_age_days from failure_memory.jsonl."""
    if not FAILURE_MEMORY.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    kept = []
    removed = 0
    for line in FAILURE_MEMORY.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            recorded = entry.get("recorded_at", "")
            if recorded:
                dt = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
                if dt < cutoff:
                    removed += 1
                    continue
        except (json.JSONDecodeError, ValueError):
            pass
        kept.append(line)

    FAILURE_MEMORY.write_text("\n".join(kept) + "\n" if kept else "")
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="HARNESS Knowledge Curator")
    sub = parser.add_subparsers(dest="command")

    curate_parser = sub.add_parser("curate", help="Curate experience from WAL")
    curate_parser.add_argument("--dry-run", action="store_true")

    prune_parser = sub.add_parser("prune", help="Prune stale entries")
    prune_parser.add_argument("--max-age-days", type=int, default=90)

    sub.add_parser("flush-wal", help="Flush WAL entries to failure_memory")

    args = parser.parse_args()

    if args.command == "curate":
        result = curate(dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
    elif args.command == "prune":
        removed = prune_stale(args.max_age_days)
        print(json.dumps({"removed": removed}))
    elif args.command == "flush-wal":
        from experience_wal import flush_wal
        count = flush_wal()
        print(json.dumps({"flushed": count}))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
