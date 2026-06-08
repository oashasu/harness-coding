#!/usr/bin/env python3
"""
Integration test to verify handle_rework can actually read/write v2 state.

Tests:
1. Create a test state file
2. Call handle_rework
3. Verify state file was updated with rework info under v2 fields
"""
import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone

# Setup path for imports
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

def test_handle_rework_writes_to_correct_state():
    """Test that handle_rework actually writes to the resolved state file"""

    # Import after path setup
    from handle_rework import handle_rework, REWORK_PATHS, MAX_REWORKS, DECISIONS_DIR
    from state_integrity import resolve_state_file, load_state

    # Create a minimal test state file
    test_state = {
        "version": "2.0",
        "phase_truth": {
            "current_phase": "prove",
            "phase_status": "in_progress"
        },
        "recovery_truth": {
            "resume_context": {}
        }
    }

    # Get the actual state file path
    state_path = resolve_state_file()
    original_exists = state_path.exists()
    original_content = None
    if original_exists:
        original_content = state_path.read_text()

    # Save and reset rework-counts.json to ensure clean starting count
    rework_file = DECISIONS_DIR / "rework-counts.json"
    rework_original = rework_file.read_text() if rework_file.exists() else None
    rework_file.parent.mkdir(parents=True, exist_ok=True)
    rework_file.write_text(json.dumps({}))

    try:
        # Write test state
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(test_state, indent=2))

        # Call handle_rework
        result = handle_rework("REQ_REVIEW", "Test rejection")
        
        # Verify result
        assert result["action"] == "rework"
        assert result["from_step"] == "REQ_REVIEW"
        assert result["to_step"] == "REQ_DRAFT"
        assert result["rework_count"] == 1
        
        # Verify state was updated under v2 structure
        updated_state, _ = load_state(verify=False, allow_unsigned=True)
        assert updated_state["phase_truth"]["current_phase"] == "REQ_DRAFT"
        resume_context = updated_state["recovery_truth"]["resume_context"]
        assert resume_context["rework_count"] == 1
        assert "last_rework" in resume_context
        assert resume_context["last_rework"]["from_step"] == "REQ_REVIEW"
        assert "resume_context" not in updated_state
        
        print(f"✓ State file location: {state_path}")
        print(f"✓ handle_rework result: {json.dumps(result, indent=2)}")
        print(f"✓ State updated with current_phase: {updated_state['phase_truth']['current_phase']}")
        print(f"✓ State updated with rework_count: {resume_context['rework_count']}")
        print(f"✓ State updated with last_rework.from_step: {resume_context['last_rework']['from_step']}")
        
    finally:
        # Restore original state
        if original_exists and original_content:
            state_path.write_text(original_content)
        elif not original_exists:
            state_path.unlink(missing_ok=True)
        # Restore rework-counts.json
        if rework_original is not None:
            rework_file.write_text(rework_original)
        else:
            rework_file.unlink(missing_ok=True)


def test_handle_rework_escalation():
    """Test escalation after MAX_REWORKS exceeded"""
    from handle_rework import handle_rework, increment_rework_count
    from state_integrity import resolve_state_file, load_state
    import os
    
    # Reset rework count for this test
    decisions_dir = Path(__file__).resolve().parent.parent / "decisions"
    rework_file = decisions_dir / "rework-counts.json"
    original_content = None
    
    if rework_file.exists():
        original_content = rework_file.read_text()
    
    try:
        # Manually set rework count to MAX_REWORKS
        rework_file.parent.mkdir(parents=True, exist_ok=True)
        rework_file.write_text(json.dumps({"REQ_REVIEW": 2}))
        
        # Call handle_rework - should escalate
        result = handle_rework("REQ_REVIEW", "Test escalation")
        
        assert result["action"] == "escalate"
        assert result["rework_count"] == 3  # 2 + 1 = 3
        assert "Max reworks" in result["message"]
        
        print(f"✓ Escalation triggered correctly")
        print(f"✓ Result action: {result['action']}")
        print(f"✓ Rework count: {result['rework_count']}")
        
    finally:
        if original_content is not None:
            rework_file.write_text(original_content)
        else:
            rework_file.unlink(missing_ok=True)


if __name__ == "__main__":
    print("Testing handle_rework integration...")
    print()
    
    test_handle_rework_writes_to_correct_state()
    print()
    
    test_handle_rework_escalation()
    print()
    
    print("=" * 60)
    print("All integration tests passed! ✓")
