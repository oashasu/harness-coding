#!/usr/bin/env python3
"""Smoke tests for the orchestrator split — verifies all new modules are importable
and that key pure functions produce correct outputs.

Run with: python3 .harness/tests/test_orchestrator_split_smoke.py
"""
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


def test_orchestrator_importable():
    import orchestrator
    assert hasattr(orchestrator, "StageOrchestrator")
    print("✓ orchestrator module importable, StageOrchestrator present")


def test_all_modules_importable():
    from dag_blueprint import load_dag_blueprint
    from stage_helpers import (
        TERMINAL_PHASE_ACTIONS,
        detect_state_kind,
        infer_stage_dispatch_role,
        validate_resume_action_binding,
    )
    from manifest_validators import (
        GEN_NODE_MANIFEST_REQUIRED_FIELDS,
        STAGE_MANIFEST_REQUIRED_FIELDS,
        validate_current_gen_node_gate,
        validate_preflight_entry_gate,
        validate_task_manifest_consistency,
    )
    from workflow_validators import (
        CONTROLLED_ALLOW_CODEGEN,
        CONTROLLED_CHECKPOINTS,
        CONTROLLED_REVIEW_STATUS,
        run_harness_workflow_final_validation,
        run_harness_workflow_gen_validation,
        run_harness_workflow_prove_validation,
        run_harness_workflow_spec_validation,
        run_plan_validation,
        validate_prove_routing_consistency,
        validate_resume_context_consistency,
    )
    print("✓ All new modules importable")


def test_stage_helpers():
    from stage_helpers import (
        detect_state_kind,
        infer_stage_dispatch_role,
        validate_resume_action_binding,
    )

    assert detect_state_kind({"current_phase": "spec", "phase_status": {}, "checkpoints": {}}) == "harness_workflow"
    assert detect_state_kind({}) == "legacy"
    assert detect_state_kind({"current_phase": "spec"}) == "legacy"

    assert infer_stage_dispatch_role("dispatch_stage_worker:spec", "spec") == "SpecWorkerAgent"
    assert infer_stage_dispatch_role("dispatch_stage_review:prove", "prove") == "ProveReviewAgent"

    try:
        infer_stage_dispatch_role("unknown_action", "spec")
        assert False, "Should raise ValueError"
    except ValueError:
        pass

    assert validate_resume_action_binding("spec", "spec", "run_preflight:spec", "preflight.py --stage spec") is None
    assert "next_required_action不能为空" in validate_resume_action_binding("spec", "spec", "", "")
    assert "prove != spec" in validate_resume_action_binding("spec", "spec", "run_preflight:prove", "preflight.py --stage prove")

    result = validate_resume_action_binding("DONE", None, "archive_runtime", "archive-harness-workflow.py --archive-only")
    assert result is None

    result = validate_resume_action_binding("DONE", None, "wrong_action", "archive-harness-workflow.py --archive-only")
    assert result is not None and "archive_runtime" in result

    print("✓ stage_helpers all assertions pass")


def test_manifest_validators_pure():
    from manifest_validators import validate_current_gen_node_gate

    assert "缺少verification" in validate_current_gen_node_gate("G01", {}, None)

    node_approved = {"status": "completed", "verification": {"review_status": "approved", "script_status": "passed"}}
    assert "不应再次派发worker" in validate_current_gen_node_gate("G01", node_approved, "dispatch_gen_node_worker:G01")
    assert "不应再次派发review" in validate_current_gen_node_gate("G01", node_approved, "dispatch_gen_node_review:G01")

    node_pending = {
        "status": "in_progress",
        "verification": {"review_status": "pending"},
        "last_review_report": "",
    }
    assert validate_current_gen_node_gate("G01", node_pending, "dispatch_gen_node_worker:G01") is None
    assert validate_current_gen_node_gate("G01", node_pending, "dispatch_gen_node_review:G01") is None

    node_rework = {"status": "in_progress", "verification": {"review_status": "rework_required"}}
    result = validate_current_gen_node_gate("G01", node_rework, "run_preflight:gen")
    assert result is not None and "rework_required" in result

    node_failed_compile = {
        "status": "in_progress",
        "verification": {"review_status": "pending", "compile_status": "failed"},
        "compile_log_path": "",
    }
    result = validate_current_gen_node_gate("G01", node_failed_compile, None)
    assert result is not None and "compile_log_path" in result

    print("✓ manifest_validators pure function assertions pass")


def test_run_plan_validation():
    from workflow_validators import run_plan_validation

    # Linear plan: s1 → s2 → s3
    data = {
        "steps": [
            {"step_id": "s1", "owner": "A", "reads": [], "writes": ["out/a.txt"]},
            {"step_id": "s2", "owner": "B", "depends_on": ["s1"], "reads": ["out/a.txt"], "writes": ["out/b.txt"]},
            {"step_id": "s3", "owner": "C", "depends_on": ["s2"], "reads": [], "writes": []},
        ]
    }
    result = run_plan_validation(data)
    assert result == ["s1", "s2", "s3"], f"Expected linear order, got {result}"

    # Empty plan
    assert run_plan_validation({"steps": []}) == []

    # Absolute path blocked
    data_abs = {"steps": [{"step_id": "s1", "owner": "A", "reads": ["/etc/passwd"], "writes": []}]}
    try:
        run_plan_validation(data_abs)
        assert False, "Should sys.exit on absolute path"
    except SystemExit as e:
        assert e.code == 1

    # Path traversal blocked
    data_traverse = {"steps": [{"step_id": "s1", "owner": "A", "reads": ["../secrets"], "writes": []}]}
    try:
        run_plan_validation(data_traverse)
        assert False, "Should sys.exit on path traversal"
    except SystemExit as e:
        assert e.code == 1

    # Cycle detection
    data_cycle = {
        "steps": [
            {"step_id": "s1", "owner": "A", "depends_on": ["s2"]},
            {"step_id": "s2", "owner": "B", "depends_on": ["s1"]},
        ]
    }
    try:
        run_plan_validation(data_cycle)
        assert False, "Should sys.exit on cycle"
    except SystemExit as e:
        assert e.code == 1

    # Undefined dependency
    data_undef = {
        "steps": [{"step_id": "s1", "owner": "A", "depends_on": ["nonexistent"]}]
    }
    try:
        run_plan_validation(data_undef)
        assert False, "Should sys.exit on undefined dep"
    except SystemExit as e:
        assert e.code == 1

    # Duplicate step_id
    data_dup = {
        "steps": [
            {"step_id": "s1", "owner": "A"},
            {"step_id": "s1", "owner": "B"},
        ]
    }
    try:
        run_plan_validation(data_dup)
        assert False, "Should sys.exit on duplicate step_id"
    except SystemExit as e:
        assert e.code == 1

    print("✓ run_plan_validation assertions pass")


if __name__ == "__main__":
    print("Running orchestrator split smoke tests...")
    print()

    test_orchestrator_importable()
    test_all_modules_importable()
    test_stage_helpers()
    test_manifest_validators_pure()
    test_run_plan_validation()

    print()
    print("=" * 60)
    print("All smoke tests passed! ✓")
