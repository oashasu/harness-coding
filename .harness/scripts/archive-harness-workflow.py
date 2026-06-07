#!/usr/bin/env python3
"""
Archive and optionally reset .harness runtime state.

Current version capabilities:
1. Archive `state/harness-workflow-state.json`
2. Archive all runtime artifacts under `output/` except `.gitkeep`
3. Optionally reset `state/` and `output/` after successful archiving

Does not handle:
1. Restoring runtime state from archive
2. Archiving `config/`, `skills/`, `spec/` and other long-lived assets
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from state_integrity import verify_state_integrity


@dataclass
class RuntimePaths:
    skill_root: Path
    state_dir: Path
    output_dir: Path
    archive_dir: Path
    state_file: Path


def script_root() -> Path:
    return Path(__file__).resolve().parent.parent


def workspace_root_for_state_file(state_file: Path) -> Path:
    resolved = state_file.expanduser().resolve()
    for candidate in [resolved.parent, *resolved.parents]:
        skill_root = candidate / ".harness"
        if skill_root.exists() and (skill_root / "scripts").exists():
            return candidate
    raise ValueError(f"Cannot infer workspace root from state_file: {state_file}")


def build_paths(state_file: Path | None = None) -> RuntimePaths:
    if state_file is not None:
        root = workspace_root_for_state_file(state_file) / ".harness"
    else:
        root = script_root()
    return RuntimePaths(
        skill_root=root,
        state_dir=root / "state",
        output_dir=root / "output",
        archive_dir=root / "archive",
        state_file=root / "state" / "harness-workflow-state.json",
    )


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def slugify_project(code: str) -> str:
    value = (code or "unknown").strip().lower()
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-") or "unknown"


def detect_project_code(state: dict[str, Any], explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    project = state.get("project", {})
    if isinstance(project, dict):
        code = project.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
    return "unknown"


def detect_active_phase(state: dict[str, Any]) -> str:
    phase = state.get("current_phase")
    return phase.strip() if isinstance(phase, str) and phase.strip() else "unknown"


def has_runtime_output(output_dir: Path) -> bool:
    for child in output_dir.iterdir():
        if child.name != ".gitkeep":
            return True
    return False


def ensure_gitkeep(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    gitkeep = target_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")


def copy_state_file(src: Path, dst_dir: Path, dry_run: bool) -> list[str]:
    copied: list[str] = []
    if not src.exists():
        return copied
    dst = dst_dir / src.name
    copied.append(str(dst))
    if not dry_run:
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return copied


def copy_output_tree(src_dir: Path, dst_dir: Path, dry_run: bool) -> list[str]:
    copied: list[str] = []
    for child in sorted(src_dir.iterdir()):
        if child.name == ".gitkeep":
            continue
        target = dst_dir / child.name
        copied.append(str(target))
        if dry_run:
            continue
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)
    return copied


def write_summary(summary_path: Path, payload: dict[str, Any], dry_run: bool) -> None:
    if dry_run:
        return
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_completion_certificate(certificate_path: Path, payload: dict[str, Any], dry_run: bool) -> None:
    if dry_run:
        return
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    certificate_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def reset_runtime(paths: RuntimePaths, dry_run: bool) -> None:
    if dry_run:
        return

    if paths.state_file.exists():
        paths.state_file.unlink()

    for child in list(paths.output_dir.iterdir()):
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    ensure_gitkeep(paths.state_dir)
    ensure_gitkeep(paths.output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive and optionally reset .harness runtime state")
    parser.add_argument("--state-file", default="", help="Runtime state file path; defaults to current script workspace")
    parser.add_argument("--project", default="", help="Project code; defaults to inferring from state file")
    parser.add_argument("--date", default="", help="Archive date, format YYYYMMDD; defaults to today")
    parser.add_argument("--archive-only", action="store_true", help="Archive only, do not reset")
    parser.add_argument("--reset-after-archive", action="store_true", help="Reset runtime after successful archiving")
    parser.add_argument("--force", action="store_true", help="Continue even if workflow is still active")
    parser.add_argument("--dry-run", action="store_true", help="Only print plan, do not actually write")
    args = parser.parse_args()

    if args.archive_only and args.reset_after_archive:
        parser.error("--archive-only and --reset-after-archive cannot be used together")

    explicit_state_file = Path(args.state_file) if args.state_file else None
    try:
        paths = build_paths(explicit_state_file)
    except ValueError as exc:
        print(f"[Blocker] {exc}")
        return 2
    state = load_state(paths.state_file)
    integrity_error = verify_state_integrity(paths.state_file, state)
    if integrity_error:
        print(f"[Blocker] {integrity_error}")
        return 2
    project_code = detect_project_code(state, args.project)
    phase = detect_active_phase(state)
    date_token = args.date.strip() or datetime.now().strftime("%Y%m%d")
    time_token = datetime.now().strftime("%H%M%S")
    case_root = paths.archive_dir / f"{date_token}-{slugify_project(project_code)}"
    runtime_root = case_root / "runtime" / time_token

    state_exists = paths.state_file.exists()
    output_exists = paths.output_dir.exists() and has_runtime_output(paths.output_dir)

    if not state_exists and not output_exists:
        print("[Info] No runtime content to archive.")
        return 0

    if phase in {"prep", "spec", "prove", "gen"} and not args.force:
        print(f"[Blocker] Workflow is still in active phase: {phase}")
        print("[Action] If you are sure, use --force to proceed.")
        return 2

    copied_state_targets: list[str] = []
    copied_output_targets: list[str] = []

    print(f"[Info] Archive target: {runtime_root}")
    print(f"[Info] Project code: {project_code}")
    print(f"[Info] Current phase: {phase}")
    print(f"[Info] Mode: {'dry-run' if args.dry_run else ('archive+reset' if args.reset_after_archive else 'archive-only')}")

    if state_exists:
        copied_state_targets = copy_state_file(paths.state_file, runtime_root / "state", args.dry_run)
        print(f"[Archive] state -> {runtime_root / 'state'}")

    if output_exists:
        copied_output_targets = copy_output_tree(paths.output_dir, runtime_root / "output", args.dry_run)
        print(f"[Archive] output -> {runtime_root / 'output'}")

    summary_payload = {
        "archived_at": datetime.now().isoformat(),
        "project_code": project_code,
        "phase": phase,
        "source": {
            "state_file": str(paths.state_file) if state_exists else None,
            "output_dir": str(paths.output_dir) if output_exists else None,
        },
        "target": {
            "runtime_root": str(runtime_root),
            "state_targets": copied_state_targets,
            "output_targets": copied_output_targets,
        },
        "reset_after_archive": bool(args.reset_after_archive),
        "dry_run": bool(args.dry_run),
    }
    write_summary(runtime_root / "summary" / "archive-summary.json", summary_payload, args.dry_run)

    certificate_payload = {
        "certificate_version": "1.0",
        "completed_at": datetime.now().isoformat(),
        "workflow_id": state.get("workflow_id", ""),
        "project_code": project_code,
        "terminal_phase": phase,
        "state_file": str(paths.state_file) if state_exists else None,
        "state_file_sha256": file_sha256(paths.state_file) if state_exists and not args.dry_run else "",
        "archive_summary": str(runtime_root / "summary" / "archive-summary.json"),
        "archive_runtime_root": str(runtime_root),
        "reset_after_archive": bool(args.reset_after_archive),
    }
    write_completion_certificate(runtime_root / "summary" / "DONE-certificate.json", certificate_payload, args.dry_run)

    if args.reset_after_archive:
        print("[Reset] Resetting state/ and output/ after successful archiving")
        reset_runtime(paths, args.dry_run)

    result = {
        "status": "PASS",
        "summary": "Runtime archiving complete" + (" and reset" if args.reset_after_archive else ""),
        "project_code": project_code,
        "phase": phase,
        "archive_root": str(runtime_root),
        "state_archived": state_exists,
        "output_archived": output_exists,
        "reset_after_archive": bool(args.reset_after_archive),
        "dry_run": bool(args.dry_run),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
