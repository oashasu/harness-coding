#!/usr/bin/env python3
"""
HARNESS workflow archiver.

Archives completed workflow state, outputs, and experience data.
Generalized from state-contracts archive-payment-workflow.py.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def archive_dir() -> Path:
    root = workspace_root()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return root / ".harness" / "archive" / f"run_{ts}"


def archive_state(archive_path: Path) -> None:
    src = workspace_root() / ".harness" / "state"
    if src.exists():
        shutil.copytree(src, archive_path / "state")


def archive_outputs(archive_path: Path) -> None:
    src = workspace_root() / ".harness" / "output"
    if src.exists():
        shutil.copytree(src, archive_path / "output")


def archive_experience(archive_path: Path) -> None:
    src = workspace_root() / ".harness" / "experience"
    if src.exists():
        shutil.copytree(src, archive_path / "experience")


def archive_dispatch(archive_path: Path) -> None:
    src = workspace_root() / ".harness" / "dispatch"
    if src.exists():
        shutil.copytree(src, archive_path / "dispatch")


def main() -> None:
    parser = argparse.ArgumentParser(description="HARNESS workflow archiver")
    parser.add_argument("--archive-only", action="store_true", help="Archive without cleaning state")
    parser.add_argument("--clean", action="store_true", help="Clean state after archiving")
    args = parser.parse_args()

    archive_path = archive_dir()
    archive_path.mkdir(parents=True, exist_ok=True)

    print(f"Archiving to: {archive_path}")
    archive_state(archive_path)
    archive_outputs(archive_path)
    archive_experience(archive_path)
    archive_dispatch(archive_path)

    # Write archive manifest
    manifest = {
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "archive_path": str(archive_path),
        "clean": args.clean,
    }
    (archive_path / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    if args.clean:
        state_dir = workspace_root() / ".harness" / "state"
        if state_dir.exists():
            for f in state_dir.iterdir():
                if f.name != ".gitkeep":
                    f.unlink()
        print("State cleaned.")
    
    print(f"Archive complete: {archive_path}")


if __name__ == "__main__":
    main()
