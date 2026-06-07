#!/usr/bin/env python3
"""
HARNESS Gate Runner — orchestrates all 14 gates.

L4 Enforce gates (deterministic):
  G-REQ-01: requirement.md schema validation
  G-SPEC-01: task_brief schema validation
  G-SPEC-02: R-ID uniqueness check
  G-CODE-01: compile check
  G-CODE-02: test execution
  G-CODE-03: coverage >= 80%
  G-CODE-04: static analysis
  G-TEST-02: security scan

L3 Policy gates (model judgment):
  G-REQ-02: acceptance criteria testability
  G-SPEC-03: spec review
  G-TEST-01: R-ID verification
  G-ARCH-01: architecture principles
  G-ARCH-02: error code specification
  G-ARCH-03: cross-package calls
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATES_DIR = PROJECT_ROOT / ".harness" / "gates"
GATE_RESULTS_DIR = PROJECT_ROOT / ".harness" / "gates" / "gate-results"
GATE_RESULT_SCHEMA = PROJECT_ROOT / ".harness" / "schemas" / "harness-gate-result.v1.schema.json"

L4_GATES = {
    "G-REQ-01": "g-req-01.sh",
    "G-SPEC-01": "g-spec-01.sh",
    "G-SPEC-02": "g-spec-02.sh",
    "G-CODE-01": "g-compile.sh",
    "G-CODE-02": "g-test.sh",
    "G-CODE-03": "g-coverage.sh",
    "G-CODE-04": "g-static.sh",
    "G-TEST-02": "g-security.sh",
}

L3_GATES = {
    "G-REQ-02": "acceptance_criteria_testability",
    "G-SPEC-03": "spec_review",
    "G-TEST-01": "rid_verification",
    "G-ARCH-01": "architecture_principles",
    "G-ARCH-02": "error_code_specification",
    "G-ARCH-03": "cross_package_calls",
}

STEP_TO_GATES = {
    "REQ_DRAFT": ["G-REQ-01"],
    "REQ_REVIEW": ["G-REQ-02"],
    "SPEC_DRAFT": ["G-SPEC-01", "G-SPEC-02"],
    "SPEC_REVIEW": ["G-SPEC-03"],
    "CODE_IMPL": ["G-CODE-01", "G-CODE-02", "G-CODE-03", "G-CODE-04"],
    "MACHINE_CHECK": ["G-TEST-01", "G-TEST-02"],
    "DUAL_REVIEW": ["G-ARCH-01", "G-ARCH-02", "G-ARCH-03"],
    "FINAL_ACCEPT": [],
    "KNOWLEDGE_ARCHIVE": [],
}


class GateResult:
    def __init__(self, gate_id: str, gate_level: str, status: str, message: str, details: dict | None = None):
        self.gate_id = gate_id
        self.gate_level = gate_level
        self.status = status
        self.message = message
        self.details = details or {}
        self.executed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "gate_level": self.gate_level,
            "status": self.status,
            "message": self.message,
            "executed_at": self.executed_at,
            "details": self.details,
        }


def run_l4_gate(gate_id: str, workspace: Path, **kwargs) -> GateResult:
    script_name = L4_GATES[gate_id]
    script_path = GATES_DIR / script_name

    if not script_path.exists():
        return GateResult(gate_id, "L4_Enforce", "SKIP", f"Gate script not found: {script_name}")

    try:
        result = subprocess.run(
            [str(script_path), str(workspace)],
            capture_output=True, text=True, timeout=300,
        )
        # Try to parse JSON output
        output = result.stdout.strip()
        if output:
            last_line = output.splitlines()[-1]
            try:
                parsed = json.loads(last_line)
                return GateResult(
                    parsed.get("gate_id", gate_id),
                    parsed.get("gate_level", "L4_Enforce"),
                    parsed.get("status", "PASS" if result.returncode == 0 else "FAIL"),
                    parsed.get("message", ""),
                    {"raw_output": output},
                )
            except json.JSONDecodeError:
                pass

        status = "PASS" if result.returncode == 0 else "FAIL"
        return GateResult(gate_id, "L4_Enforce", status, output or f"Exit code: {result.returncode}")
    except subprocess.TimeoutExpired:
        return GateResult(gate_id, "L4_Enforce", "FAIL", "Gate execution timed out (300s)")
    except Exception as e:
        return GateResult(gate_id, "L4_Enforce", "ERROR", str(e))


def run_l3_gate_placeholder(gate_id: str) -> GateResult:
    """L3 gates require model judgment — return placeholder for orchestrator to handle."""
    description = L3_GATES.get(gate_id, "unknown")
    return GateResult(
        gate_id, "L3_Policy", "PENDING",
        f"L3 gate requires model judgment: {description}",
        {"requires_agent": True, "gate_type": description},
    )


def run_gates_for_step(step: str, workspace: Path, only_l4: bool = False) -> list[GateResult]:
    gate_ids = STEP_TO_GATES.get(step, [])
    results = []
    for gate_id in gate_ids:
        if gate_id in L4_GATES:
            results.append(run_l4_gate(gate_id, workspace))
        elif not only_l4:
            results.append(run_l3_gate_placeholder(gate_id))
    return results


def save_gate_results(results: list[GateResult], output_dir: Path | None = None) -> Path:
    output_dir = output_dir or GATE_RESULTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"gate-results-{ts}.json"
    data = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "results": [r.to_dict() for r in results],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.status == "PASS"),
            "failed": sum(1 for r in results if r.status == "FAIL"),
            "pending": sum(1 for r in results if r.status == "PENDING"),
            "skipped": sum(1 for r in results if r.status == "SKIP"),
        },
    }
    output_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return output_file


def main() -> None:
    parser = argparse.ArgumentParser(description="HARNESS Gate Runner")
    parser.add_argument("--step", required=True, help="Pipeline step to run gates for")
    parser.add_argument("--workspace", default=".", help="Workspace root directory")
    parser.add_argument("--only-l4", action="store_true", help="Only run L4 deterministic gates")
    parser.add_argument("--gate", help="Run a single gate by ID")
    parser.add_argument("--output-dir", help="Output directory for gate results")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    output_dir = Path(args.output_dir) if args.output_dir else None

    if args.gate:
        if args.gate in L4_GATES:
            result = run_l4_gate(args.gate, workspace)
        elif args.gate in L3_GATES:
            result = run_l3_gate_placeholder(args.gate)
        else:
            print(f"Unknown gate: {args.gate}", file=sys.stderr)
            sys.exit(1)
        results = [result]
    else:
        results = run_gates_for_step(args.step, workspace, only_l4=args.only_l4)

    output_file = save_gate_results(results, output_dir)

    all_passed = all(r.status in ("PASS", "SKIP", "PENDING") for r in results)
    print(json.dumps({
        "all_passed": all_passed,
        "output_file": str(output_file),
        "results": [r.to_dict() for r in results],
    }, indent=2, ensure_ascii=False))

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
