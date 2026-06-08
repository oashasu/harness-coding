#!/usr/bin/env python3
"""
HARNESS Rework Handler — manages rework and escalation after review.

Handles the 3 rejection paths:
  REQ_REVIEW reject → back to REQ_DRAFT
  SPEC_REVIEW reject → back to SPEC_DRAFT
  MACHINE_CHECK fail → back to CODE_IMPL
  DUAL_REVIEW reject → back to CODE_IMPL

Escalation: after 2 failed reworks, escalate to human.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from state_integrity import load_state, save_state


DECISIONS_DIR = Path(__file__).resolve().parents[2] / ".harness" / "decisions"

REWORK_PATHS = {
    "REQ_REVIEW": "REQ_DRAFT",
    "SPEC_REVIEW": "SPEC_DRAFT",
    "MACHINE_CHECK": "CODE_IMPL",
    "DUAL_REVIEW": "CODE_IMPL",
}

MAX_REWORKS = 2

def get_rework_count(step: str) -> int:
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    rework_file = DECISIONS_DIR / "rework-counts.json"
    if not rework_file.exists():
        return 0
    try:
        counts = json.loads(rework_file.read_text())
        return counts.get(step, 0)
    except (json.JSONDecodeError, FileNotFoundError):
        return 0


def increment_rework_count(step: str) -> int:
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    rework_file = DECISIONS_DIR / "rework-counts.json"
    counts = {}
    if rework_file.exists():
        try:
            counts = json.loads(rework_file.read_text())
        except json.JSONDecodeError:
            pass
    counts[step] = counts.get(step, 0) + 1
    rework_file.write_text(json.dumps(counts, indent=2))
    return counts[step]


def handle_rework(current_step: str, reason: str) -> dict[str, Any]:
    if current_step not in REWORK_PATHS:
        return {"error": f"No rework path from {current_step}"}

    target_step = REWORK_PATHS[current_step]
    rework_count = increment_rework_count(current_step)

    result = {
        "action": "rework",
        "from_step": current_step,
        "to_step": target_step,
        "reason": reason,
        "rework_count": rework_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if rework_count > MAX_REWORKS:
        result["action"] = "escalate"
        result["message"] = f"Max reworks ({MAX_REWORKS}) exceeded for {current_step}. Escalating to human."

    # Update state
    state, state_path = load_state(verify=False, allow_unsigned=True)
    if state:
        phase_truth = state.setdefault("phase_truth", {})
        if isinstance(phase_truth, dict):
            phase_truth["current_phase"] = (
                target_step if rework_count <= MAX_REWORKS else current_step
            )

        recovery_truth = state.setdefault("recovery_truth", {})
        if not isinstance(recovery_truth, dict):
            recovery_truth = {}
            state["recovery_truth"] = recovery_truth
        resume_context = recovery_truth.setdefault("resume_context", {})
        if not isinstance(resume_context, dict):
            resume_context = {}
            recovery_truth["resume_context"] = resume_context
        resume_context["last_rework"] = result
        resume_context["rework_count"] = rework_count
        save_state(state, state_path, seal=True)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="HARNESS Rework Handler")
    parser.add_argument("--step", required=True, help="Current step that was rejected")
    parser.add_argument("--reason", required=True, help="Rejection reason")
    args = parser.parse_args()

    result = handle_rework(args.step, args.reason)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result.get("action") == "escalate":
        sys.exit(2)
    elif result.get("error"):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
