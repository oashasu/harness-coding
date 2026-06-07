#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

from state_integrity import seal_state, verify_state_integrity


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_FILE = PROJECT_ROOT / ".harness/state/harness-workflow-state.json"
STATE_SCHEMA = PROJECT_ROOT / ".harness/skills/harness-workflow-skill/references/task/harness-workflow-state.schema.json"
NODE_NAMES = {
    "G01": "G01_NODE_1",
    "G02": "G02_NODE_2",
    "G03": "G03_NODE_3",
    "G04": "G04_NODE_4",
    "G05": "G05_NODE_5",
    "G06": "G06_NODE_6",
    "G07": "G07_NODE_7",
    "G08": "G08_NODE_8",
    "G09": "G09_NODE_9",
}
NODE_OWNER_ROLES = {
    "G01": "GenWorker",
    "G02": "GenWorker",
    "G03": "GenWorker",
    "G04": "GenWorker",
    "G05": "GenWorker",
    "G06": "GenWorker",
    "G07": "GenWorker",
    "G08": "GenWorker",
    "G09": "GenWorker",
}
NODE_PREREQS = {
    "G01": [],
    "G02": ["G01"],
    "G03": ["G02"],
    "G04": ["G03"],
    "G05": ["G04"],
    "G06": ["G02", "G03"],
    "G07": ["G01"],
    "G08": ["G01"],
    "G09": ["G02", "G07", "G08"],
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_state(state: dict[str, Any]) -> str | None:
    if jsonschema is None:
        return None
    try:
        schema = load_json(STATE_SCHEMA)
        jsonschema.validate(instance=state, schema=schema)
    except Exception as exc:
        return str(exc)
    return None


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_nodes() -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for node_id in NODE_NAMES:
        nodes[node_id] = {
            "owner_role": NODE_OWNER_ROLES[node_id],
            "depends_on": list(NODE_PREREQS[node_id]),
            "status": "pending",
            "generated_files": [],
            "verification": {
                "review_status": "pending",
                "script_status": "not_run",
                "compile_status": "not_run",
            },
            "failed_attempts": 0,
            "last_error": "",
        }
    return nodes


def initialize_gen_nodes(state: dict[str, Any], force: bool) -> dict[str, Any]:
    if state.get("current_phase") != "gen":
        raise ValueError(f"Current phase is not gen: {state.get('current_phase')}")

    migrated = json.loads(json.dumps(state))
    artifacts = migrated.setdefault("artifacts", {})
    phase_3 = artifacts.setdefault("phase_3", {})
    existing_nodes = phase_3.get("nodes", {})
    if not isinstance(existing_nodes, dict):
        raise ValueError("artifacts.phase_3.nodes is not an object, cannot initialize")
    if existing_nodes and not force:
        raise ValueError("artifacts.phase_3.nodes already has content, --force not specified, refusing to overwrite")

    phase_3["nodes"] = build_nodes()
    phase_3["current_node"] = "G01"

    resume_context = migrated.setdefault("resume_context", {})
    resume_context["current_execution_unit"] = "G01"
    resume_context["next_required_action"] = "dispatch_gen_node_worker:G01"
    resume_context["required_script"] = "build-gen-node-task.py"
    resume_context["pending_checkpoint"] = "NONE"
    resume_context["last_review_status"] = "pending"

    timestamps = migrated.setdefault("timestamps", {})
    timestamps["updated_at"] = iso_utc_now()
    return migrated


def save_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(payload, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def save_state_json_atomic(path: Path, payload: dict[str, Any], *, key_source_state_file: Path | None = None) -> None:
    try:
        save_json_atomic(path, seal_state(path, payload, key_source_state_file=key_source_state_file))
    except ValueError:
        save_json_atomic(path, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize gen phase DAG nodes in harness-workflow-state.")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE), help="State file path (default: %s)" % str(DEFAULT_STATE_FILE))
    parser.add_argument("--input", dest="state_file", help="Alias for --state-file, --state-file is recommended")
    parser.add_argument("--output")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.output and args.in_place:
        print("[BLOCKER] --output and --in-place cannot be used together")
        return 1

    input_path = Path(args.state_file)
    if not args.output and not args.in_place:
        print("[BLOCKER] Must explicitly specify --output or --in-place, refusing to implicitly overwrite input state file.")
        print("Example: init-gen-nodes.py --state-file <path> --in-place --force")
        return 1
    output_path = Path(args.output) if args.output else input_path

    state = load_json(input_path)
    integrity_error = verify_state_integrity(input_path, state)
    if integrity_error:
        print(f"[BLOCKER] State integrity check failed: {integrity_error}")
        return 1
    try:
        updated_state = initialize_gen_nodes(state, force=args.force)
    except ValueError as exc:
        print(f"[BLOCKER] Initialization failed: {exc}")
        return 1

    schema_error = validate_state(updated_state)
    if schema_error:
        print(f"[BLOCKER] State does not match schema after initialization: {schema_error}")
        return 1

    save_state_json_atomic(output_path, updated_state, key_source_state_file=input_path)
    print(f"[PASS] Initialized gen phase nodes: {output_path}")
    print("Next: run build-gen-node-task.py --state-file %s" % str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
