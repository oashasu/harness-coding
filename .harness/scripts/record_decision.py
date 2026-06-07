#!/usr/bin/env python3
"""
HARNESS Decision Recorder — records human approval/rejection decisions.

Writes decision records to .harness/decisions/ for the 3 human approval points:
  1. REQ_REVIEW: requirement approval
  2. SPEC_REVIEW: spec approval  
  3. FINAL_ACCEPT: final acceptance
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DECISIONS_DIR = Path(__file__).resolve().parents[2] / ".harness" / "decisions"

VALID_STEPS = ["REQ_REVIEW", "SPEC_REVIEW", "FINAL_ACCEPT"]
VALID_ACTIONS = ["approve", "reject", "reject_with_reason"]


def record_decision(
    step: str,
    action: str,
    reason: str | None = None,
    artifacts: list[str] | None = None,
) -> dict[str, Any]:
    if step not in VALID_STEPS:
        raise ValueError(f"Invalid step: {step}. Must be one of {VALID_STEPS}")
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action: {action}. Must be one of {VALID_ACTIONS}")
    if action == "reject_with_reason" and not reason:
        raise ValueError("reject_with_reason requires a reason")

    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc)
    decision = {
        "decision_id": f"D-{ts.strftime('%Y%m%d%H%M%S')}",
        "step": step,
        "action": action,
        "reason": reason,
        "artifacts_reviewed": artifacts or [],
        "recorded_at": ts.isoformat(),
    }

    # Write to step-specific file
    output_file = DECISIONS_DIR / f"decision-{step.lower()}.json"
    existing = []
    if output_file.exists():
        try:
            existing = json.loads(output_file.read_text())
            if not isinstance(existing, list):
                existing = [existing]
        except json.JSONDecodeError:
            existing = []

    existing.append(decision)
    output_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

    # Also write latest decision for quick access
    latest_file = DECISIONS_DIR / "latest-decision.json"
    latest_file.write_text(json.dumps(decision, indent=2, ensure_ascii=False))

    return decision


def get_latest_decision(step: str | None = None) -> dict[str, Any] | None:
    if step:
        output_file = DECISIONS_DIR / f"decision-{step.lower()}.json"
        if output_file.exists():
            try:
                decisions = json.loads(output_file.read_text())
                if isinstance(decisions, list) and decisions:
                    return decisions[-1]
                elif isinstance(decisions, dict):
                    return decisions
            except json.JSONDecodeError:
                pass
        return None

    latest_file = DECISIONS_DIR / "latest-decision.json"
    if latest_file.exists():
        try:
            return json.loads(latest_file.read_text())
        except json.JSONDecodeError:
            pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="HARNESS Decision Recorder")
    sub = parser.add_subparsers(dest="command")

    record_parser = sub.add_parser("record", help="Record a decision")
    record_parser.add_argument("--step", required=True, choices=VALID_STEPS)
    record_parser.add_argument("--action", required=True, choices=VALID_ACTIONS)
    record_parser.add_argument("--reason", help="Reason for rejection")
    record_parser.add_argument("--artifacts", nargs="*", help="Reviewed artifact paths")

    query_parser = sub.add_parser("query", help="Query latest decision")
    query_parser.add_argument("--step", choices=VALID_STEPS)

    args = parser.parse_args()

    if args.command == "record":
        decision = record_decision(args.step, args.action, args.reason, args.artifacts)
        print(json.dumps(decision, indent=2, ensure_ascii=False))
    elif args.command == "query":
        decision = get_latest_decision(args.step)
        if decision:
            print(json.dumps(decision, indent=2, ensure_ascii=False))
        else:
            print("No decision found")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
