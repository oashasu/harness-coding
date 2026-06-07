#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def is_legacy_prove_routing_payload(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload, dict)
        and "routing" in payload
        and "allow_codegen" not in payload
        and "summary" in payload
    )


def normalize_legacy_prove_routing_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not is_legacy_prove_routing_payload(payload):
        return payload
    summary = payload.get("summary", {})
    routing = payload.get("routing", {})
    allow_codegen = summary.get("allow_codegen", "UNSET")
    blockers = summary.get("blockers", [])
    generated_at = payload.get("generated_at") or payload.get("version") or "legacy"
    business_fact_passed = allow_codegen in {"YES", "YES_WITH_WARNING"} and not blockers
    normalized = {
        "business_fact_validation": {
            "passed": business_fact_passed,
            "blocked_items": list(blockers) if isinstance(blockers, list) else [],
            "bf_check_timestamp": str(generated_at),
        },
        "issue_normalization": {
            "normalized_questions": [],
        },
        "solution_collapse": {
            "collapsed_solutions": [],
        },
        "routing": {
            "prove_resolvable": routing.get("prove_resolvable", []),
            "prove_with_risk": routing.get("prove_with_risk", []),
            "human_required": routing.get("human_required", []),
        },
        "allow_codegen": allow_codegen,
        "gate_context_update": {
            "business_fact_validation_passed": business_fact_passed,
            "scene_coverage_passed": allow_codegen in {"YES", "YES_WITH_WARNING"},
        },
    }
    return normalized
