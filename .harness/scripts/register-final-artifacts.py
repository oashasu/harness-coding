#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

from final_report_contract import validate_final_report
from state_integrity import seal_state, verify_state_integrity, resolve_state_file


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 主状态文件统一为 harness-state.json，旧名兼容由 resolve_state_file 集中处理
DEFAULT_STATE_FILE = resolve_state_file(harness_root=SCRIPT_PROJECT_ROOT / ".harness")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_state_json(path: Path, payload: dict[str, Any]) -> None:
    save_json(path, seal_state(path, payload))


def detect_workspace_root(state_file: Path) -> Path:
    return state_file.parents[2]


def detect_state_schema_path(workspace_root: Path) -> Path:
    return workspace_root / ".harness/schemas/harness-state.schema.json"


def validate_state_schema(state: dict[str, Any], schema_path: Path) -> str | None:
    if jsonschema is None:
        return "jsonschema dependency unavailable, cannot validate state schema"
    try:
        schema = load_json(schema_path)
    except Exception as exc:
        return f"State schema cannot be parsed: {schema_path}: {exc}"
    try:
        jsonschema.validate(instance=state, schema=schema)
    except Exception as exc:
        return f"State file does not match schema: {exc}"
    return None


def run_orchestrator_final(state_file: Path, workspace_root: Path) -> str | None:
    orchestrator = workspace_root / ".harness/scripts/orchestrator.py"
    cmd = [
        sys.executable,
        str(orchestrator),
        "--stage",
        "final",
        "--state-file",
        str(state_file),
        "--workdir",
        str(workspace_root),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(workspace_root),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return None
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    details = "\n".join(part for part in [output, error] if part).strip()
    return details or "orchestrator.py --stage final execution failed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register final phase artifacts and update harness-workflow-state runtime")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    parser.add_argument("--dry-run", action="store_true", help="Only print plan, do not write state")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    state_file = Path(args.state_file).expanduser().resolve()
    workspace_root = detect_workspace_root(state_file)
    state_schema = detect_state_schema_path(workspace_root)
    state = load_json(state_file)
    integrity_error = verify_state_integrity(state_file, state)
    if integrity_error:
        print(f"[BLOCKER] {integrity_error}")
        return 1

    state_schema_error = validate_state_schema(state, state_schema)
    if state_schema_error:
        print(f"[BLOCKER] {state_schema_error}")
        return 1

    if state.get("current_phase") != "final":
        print(f"[BLOCKER] Only allowed to register final artifacts in final phase, current_phase={state.get('current_phase')}")
        return 1

    phase_status = state.get("phase_status", {})
    resume_context = state.get("resume_context", {})
    if phase_status.get("gen") != "completed":
        print("[BLOCKER] gen phase not completed, cannot register final artifacts.")
        return 1
    if phase_status.get("final") not in {"in_progress", "completed"}:
        print(f"[BLOCKER] phase_status.final illegal: {phase_status.get('final')}")
        return 1
    if resume_context.get("last_review_status") != "approved":
        print(
            "[BLOCKER] Last phase review not approved, cannot register final artifacts."
            f" last_review_status={resume_context.get('last_review_status')}"
        )
        return 1

    report_validation = validate_final_report(workspace_root, state)
    if not report_validation.ok:
        print(f"[BLOCKER] Final audit report invalid: {report_validation.reason}")
        return 1

    phase_4 = state.get("artifacts", {}).get("phase_4", {})
    if phase_4.get("p0_scan_status") != "passed":
        print(f"[BLOCKER] final phase p0_scan_status must be passed, current: {phase_4.get('p0_scan_status')}")
        return 1
    if phase_4.get("final_compile_status") != "passed":
        print(f"[BLOCKER] final phase final_compile_status must be passed, current: {phase_4.get('final_compile_status')}")
        return 1

    orchestrator_error = run_orchestrator_final(state_file, workspace_root)
    if orchestrator_error:
        print("[BLOCKER] Final phase validation failed:")
        print(orchestrator_error)
        return 1

    state["phase_status"]["final"] = "completed"
    state["resume_context"] = {
        "current_execution_unit": "final",
        "next_required_action": "run_checkpoint:final-ok",
        "required_script": "phase-handoff.py --from-phase final --checkpoint final-ok --await-user-action",
        "pending_checkpoint": "NONE",
        "resume_first_prompt": "Final artifacts passed validation, next step is to write final-ok wait state via phase-handoff.py.",
        "last_review_status": "approved",
    }
    state.setdefault("timestamps", {})["updated_at"] = datetime.now(timezone.utc).isoformat()

    final_schema_error = validate_state_schema(state, state_schema)
    if final_schema_error:
        print(f"[BLOCKER] State does not match schema after registration: {final_schema_error}")
        return 1

    if args.dry_run:
        print("[DRY-RUN] Final artifacts validation passed")
        print("[DRY-RUN] Will set phase_status.final=completed")
        print("[DRY-RUN] Will set next_required_action=run_checkpoint:final-ok")
        return 0

    save_state_json(state_file, state)
    print(f"[PASS] Final artifacts validation passed: {phase_4.get('audit_report')}")
    print(f"[PASS] Updated state file: {state_file}")
    print("[PASS] phase_status.final=completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
