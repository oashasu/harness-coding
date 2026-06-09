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


def detect_skill_root(state_file: Path) -> Path:
    return state_file.parents[1]


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


def find_spec_output(spec_dir: Path, project_code: str) -> tuple[Path | None, list[str]]:
    expected = spec_dir / f"spec-business-facts-{project_code}.json"
    if expected.exists():
        return expected, []
    candidates = sorted(spec_dir.glob("spec-business-facts-*.json"))
    if not candidates:
        return None, [f"Spec artifact does not exist: {expected}"]
    return None, [f"No exact match for spec artifact, existing candidates: {[str(path.name) for path in candidates]}"]


def run_orchestrator_spec(state_file: Path, workspace_root: Path, spec_output: Path) -> str | None:
    orchestrator = workspace_root / ".harness/scripts/orchestrator.py"
    cmd = [
        sys.executable,
        str(orchestrator),
        "--stage",
        "spec",
        "--state-file",
        str(state_file),
        "--workdir",
        str(workspace_root),
        "--business-facts-input",
        str(spec_output),
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
    return details or "orchestrator.py --stage spec execution failed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register spec phase artifacts and update harness-workflow-state runtime")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    parser.add_argument("--project", default="", help="Project code; defaults to reading from state file")
    parser.add_argument("--dry-run", action="store_true", help="Only print plan, do not write state")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    state_file = Path(args.state_file).expanduser().resolve()
    workspace_root = detect_workspace_root(state_file)
    skill_root = detect_skill_root(state_file)
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

    if state.get("current_phase") != "spec":
        print(f"[BLOCKER] Only allowed to register spec artifacts in spec phase, current_phase={state.get('current_phase')}")
        return 1

    project = state.get("project", {})
    code = (args.project or project.get("code") or "").strip()
    if not code or code.startswith("replace-with-"):
        print("[BLOCKER] Missing valid project code, cannot locate spec artifacts.")
        return 1

    phase_status = state.get("phase_status", {})
    resume_context = state.get("resume_context", {})
    if phase_status.get("prep") != "completed":
        print("[BLOCKER] prep phase not completed, cannot register spec artifacts.")
        return 1
    if phase_status.get("spec") not in {"in_progress", "completed"}:
        print(f"[BLOCKER] phase_status.spec illegal: {phase_status.get('spec')}")
        return 1
    if resume_context.get("last_review_status") != "approved":
        print(
            "[BLOCKER] Last phase review not approved, cannot register spec artifacts."
            f" last_review_status={resume_context.get('last_review_status')}"
        )
        return 1

    spec_dir = skill_root / "output/spec" / code
    spec_output, output_errors = find_spec_output(spec_dir, code)
    if output_errors:
        for error in output_errors:
            print(f"[BLOCKER] {error}")
        return 1
    assert spec_output is not None

    orchestrator_error = run_orchestrator_spec(state_file, workspace_root, spec_output)
    if orchestrator_error:
        print("[BLOCKER] Spec phase validation failed:")
        print(orchestrator_error)
        return 1

    state["phase_status"]["spec"] = "completed"
    state["resume_context"] = {
        "current_execution_unit": "spec",
        "next_required_action": "run_checkpoint:spec-ok",
        "required_script": "phase-handoff.py --from-phase spec --checkpoint spec-ok --await-user-action",
        "pending_checkpoint": "NONE",
        "resume_first_prompt": "Spec artifacts passed validation, next step is to write spec-ok wait state via phase-handoff.py.",
        "last_review_status": "approved",
    }
    state.setdefault("timestamps", {})["updated_at"] = datetime.now(timezone.utc).isoformat()

    final_schema_error = validate_state_schema(state, state_schema)
    if final_schema_error:
        print(f"[BLOCKER] State does not match schema after registration: {final_schema_error}")
        return 1

    if args.dry_run:
        print(f"[DRY-RUN] Spec artifacts confirmed: {spec_output}")
        print("[DRY-RUN] orchestrator.py --stage spec passed")
        print("[DRY-RUN] Will set phase_status.spec=completed")
        return 0

    save_state_json(state_file, state)
    print(f"[PASS] Spec artifacts validation passed: {spec_output}")
    print(f"[PASS] Updated state file: {state_file}")
    print("[PASS] phase_status.spec=completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
