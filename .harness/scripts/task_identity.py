#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from typing import Any


def derive_task_id(
    state: dict[str, Any],
    *,
    task_scope: str,
    phase: str,
    execution_unit: str,
) -> str:
    resume_context = state.get("resume_context", {})
    checkpoints = state.get("checkpoints", {})
    workflow_id = str(state.get("workflow_id", "") or "")
    project_code = str(state.get("project", {}).get("code", "") or "")
    material = "|".join(
        [
            workflow_id,
            project_code,
            task_scope,
            phase,
            execution_unit,
            str(resume_context.get("next_required_action", "") or ""),
            str(resume_context.get("required_script", "") or ""),
            str(resume_context.get("pending_checkpoint", "") or ""),
            str(resume_context.get("last_review_status", "") or ""),
            str(checkpoints.get("last_checkpoint", "") or ""),
        ]
    )
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]
    return f"{task_scope}:{phase}:{execution_unit}:{digest}"
