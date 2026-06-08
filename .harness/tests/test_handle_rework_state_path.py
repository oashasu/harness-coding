#!/usr/bin/env python3
"""
Minimal test to verify handle_rework.py uses correct state path (not pipeline.json).

Tests:
1. handle_rework imports load_state/save_state from state_integrity
2. No hardcoded pipeline.json path remains
3. Can read/write to actual harness-state.json location
"""
import sys
from pathlib import Path

# Add harness/scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

def test_no_pipeline_json_hardcode():
    """Verify pipeline.json is not hardcoded in handle_rework.py"""
    handle_rework_file = SCRIPTS_DIR / "handle_rework.py"
    content = handle_rework_file.read_text()
    
    # Should not have STATE_FILE pointing to pipeline.json
    assert 'STATE_FILE' not in content, "STATE_FILE constant should be removed"
    assert 'pipeline.json' not in content, "pipeline.json should not be referenced"
    
    # Should import from state_integrity
    assert 'from state_integrity import load_state, save_state' in content, \
        "Should import load_state, save_state from state_integrity"
    
    # Should call load_state with parameters
    assert 'load_state(verify=False, allow_unsigned=True)' in content, \
        "Should call load_state with proper parameters"
    
    # Should call save_state with state_path
    assert 'save_state(state, state_path, seal=True)' in content, \
        "Should call save_state with state_path parameter"
    
    print("✓ No pipeline.json hardcode found")
    print("✓ Correct state_integrity imports present")


def test_state_integrity_resolve():
    """Verify state_integrity can resolve the correct state file"""
    from state_integrity import resolve_state_file
    
    state_path = resolve_state_file()
    
    # Should resolve to harness-state.json (either in .harness/state/ or .harness/)
    assert state_path.name == "harness-state.json", \
        f"Expected harness-state.json, got {state_path.name}"
    
    # Should be under .harness directory
    assert ".harness" in str(state_path), \
        f"Expected path under .harness, got {state_path}"
    
    print(f"✓ State file resolves to: {state_path}")


def test_load_state_returns_path():
    """Verify load_state returns both state dict and path"""
    from state_integrity import load_state
    
    # Call with allow_unsigned=True for empty state
    state, state_path = load_state(verify=False, allow_unsigned=True)
    
    assert isinstance(state, dict), "State should be a dict"
    assert isinstance(state_path, Path), "State path should be a Path"
    assert state_path.name == "harness-state.json", \
        f"Expected harness-state.json, got {state_path.name}"
    
    print(f"✓ load_state returns path: {state_path}")


if __name__ == "__main__":
    print("Testing handle_rework.py state path fixes...")
    print()
    
    test_no_pipeline_json_hardcode()
    print()
    
    test_state_integrity_resolve()
    print()
    
    test_load_state_returns_path()
    print()
    
    print("=" * 60)
    print("All tests passed! ✓")
    print("handle_rework.py now uses correct state path from state_integrity")
