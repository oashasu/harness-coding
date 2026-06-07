#!/usr/bin/env python3
"""
Dispatch Worker
Generate Worker dispatch package from task manifest, strictly validating manifest format,
consuming only declared inputs and expected_outputs.
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
MANIFEST_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/task-manifest.v1.schema.json"
VALIDATE_SCRIPT = PROJECT_ROOT / ".harness/scripts/validate-task-manifest.py"
WORKER_PROMPT = PROJECT_ROOT / ".harness/prompts/worker-node-prompt.md"
REVIEW_PROMPT = PROJECT_ROOT / ".harness/prompts/review-node-prompt.md"
WORKER_REPORT_SCHEMA = PROJECT_ROOT / ".harness/spec/schema/worker-final-report.v2.schema.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def detect_workspace_root(state_file: Path) -> Path:
    """Walk up from state_file to find directory containing .harness/scripts"""
    for candidate in [state_file.resolve(), *state_file.resolve().parents]:
        skill_root = candidate / ".harness"
        if skill_root.exists() and (skill_root / "scripts").exists():
            return candidate
    return PROJECT_ROOT


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_manifest_validator(manifest_path: Path) -> bool:
    """Call validate-task-manifest.py to validate manifest"""
    result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), "--manifest-file", str(manifest_path)],
        capture_output=False,
    )
    return result.returncode == 0


def default_output_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    inputs = manifest["inputs"]
    state_file = Path(inputs["state_file"])
    workspace_root = detect_workspace_root(state_file)
    phase = manifest["phase"]
    execution_unit = manifest["execution_unit"]
    return workspace_root / ".harness/output/dispatch" / phase / f"{execution_unit}-dispatch.json"


def workspace_root_for_manifest(manifest: dict[str, Any]) -> Path:
    state_file = Path(manifest["inputs"]["state_file"])
    return detect_workspace_root(state_file)


def prompt_path(workspace_root: Path, prompt_name: str, fallback: Path) -> str:
    candidate = workspace_root / ".harness/prompts" / prompt_name
    return str(candidate if candidate.exists() else fallback)


def worker_instruction(manifest: dict[str, Any]) -> str:
    task_scope = manifest["task_scope"]
    phase = manifest["phase"]
    execution_unit = manifest["execution_unit"]
    expected_outputs = manifest.get("expected_outputs", [])
    expected_output_text = ", ".join(expected_outputs) if expected_outputs else "manifest has no fixed artifacts declared, deliver minimum scope for current execution unit"
    if task_scope == "gen_node":
        node_id = manifest.get("node_id", execution_unit)
        return (
            f"Read task_manifest, then only execute gen node {node_id}. "
            f"Do not process other Gxx nodes; artifact scope={expected_output_text}. "
            "After completion, output a Worker final report conforming to worker-final-report.v2.schema.json."
        )
    return (
        f"Read task_manifest, then only execute {phase} phase. "
        f"Do not advance checkpoint or switch phases; artifact scope={expected_output_text}. "
        "After completion, output a Worker final report conforming to worker-final-report.v2.schema.json."
    )


def review_instruction(manifest: dict[str, Any]) -> str:
    task_scope = manifest["task_scope"]
    phase = manifest["phase"]
    execution_unit = manifest["execution_unit"]
    if task_scope == "gen_node":
        return (
            f"Read-only review of gen node {execution_unit} task manifest, Worker final report and declared artifacts. "
            "Only output a gen_node review result JSON consumable by collect-review.py."
        )
    return (
        f"Read-only review of {phase} phase task manifest, Worker final report and declared artifacts. "
        "Only output a stage review result JSON consumable by collect-review.py."
    )


def build_dispatch_payload(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Build dispatch package from manifest, consuming only declared inputs and expected_outputs"""
    inputs = manifest["inputs"]
    workspace_root = workspace_root_for_manifest(manifest)

    dispatch_inputs = {
        "state_file": inputs["state_file"],
        "session_brief": inputs["session_brief"],
        "handoff_dir": inputs["handoff_dir"],
    }
    if "handoff_file" in inputs:
        dispatch_inputs["handoff_file"] = inputs["handoff_file"]
    if "forbidden_primary_inputs" in inputs:
        dispatch_inputs["forbidden_primary_inputs"] = inputs["forbidden_primary_inputs"]

    payload = {
        "dispatch_version": "1.0",
        "task_id": manifest["task_id"],
        "task_scope": manifest["task_scope"],
        "phase": manifest["phase"],
        "execution_unit": manifest["execution_unit"],
        "dispatch_role": manifest["dispatch_role"],
        "review_role": manifest["review_role"],
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "task_manifest": str(manifest_path),
        "inputs": dispatch_inputs,
        "expected_outputs": manifest.get("expected_outputs", []),
        "context_contract": {
            "worker_system_prompt": prompt_path(workspace_root, "worker-node-prompt.md", WORKER_PROMPT),
            "review_system_prompt": prompt_path(workspace_root, "review-node-prompt.md", REVIEW_PROMPT),
            "worker_final_report_schema": prompt_path(
                workspace_root,
                "../spec/schema/worker-final-report.v2.schema.json",
                WORKER_REPORT_SCHEMA,
            ),
            "worker_instruction": worker_instruction(manifest),
            "review_instruction": review_instruction(manifest),
            "forbidden_state_writes": [
                inputs["state_file"],
                inputs.get("session_brief", ""),
            ],
            "review_result_collector": "collect-review.py",
            "worker_report_collector": "collect-worker-report.py",
        },
    }
    if "required_reports" in manifest:
        payload["required_reports"] = manifest["required_reports"]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Worker dispatch package from task manifest")
    parser.add_argument("--task-manifest", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    manifest_path = Path(args.task_manifest).expanduser().resolve()
    if not manifest_path.exists():
        print(f"[BLOCKER] Manifest file does not exist: {manifest_path}")
        return 1

    if not run_manifest_validator(manifest_path):
        return 1

    manifest = load_json(manifest_path)

    output_path = Path(args.output).expanduser().resolve() if args.output else default_output_path(manifest_path, manifest)
    payload = build_dispatch_payload(manifest_path, manifest)
    save_json(output_path, payload)
    print(f"[PASS] Generated Worker dispatch package: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
