#!/usr/bin/env python3
"""
Test knowledge_curator auto-trigger from archive-harness-workflow.

Tests:
1. When failure_memory.jsonl has entries, archive triggers curator and updates experience.md
2. Curator failures don't block archive command
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

# Add scripts directory to path
scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))


def setup_test_workspace():
    """Create a minimal test workspace with required structure."""
    test_dir = Path(tempfile.mkdtemp(prefix="test_curator_"))
    
    # Create .harness structure
    harness_dir = test_dir / ".harness"
    (harness_dir / "state").mkdir(parents=True)
    (harness_dir / "output").mkdir(parents=True)
    (harness_dir / "archive").mkdir(parents=True)
    (harness_dir / "knowledge").mkdir(parents=True)
    
    # Create minimal state file
    state = {
        "workflow_id": "test-workflow-001",
        "current_phase": "done",
        "project": {"code": "test-project"}
    }
    state_file = harness_dir / "state" / "harness-state.json"
    state_file.write_text(json.dumps(state, indent=2))
    
    # Create dummy output file
    (harness_dir / "output" / "test.txt").write_text("test output")
    
    # Copy scripts
    scripts_src = Path(__file__).resolve().parent.parent / "scripts"
    scripts_dst = harness_dir / "scripts"
    shutil.copytree(scripts_src, scripts_dst)
    
    return test_dir, state_file


def test_curator_updates_experience():
    """Test 1: Archive triggers curator and updates experience.md"""
    test_dir, state_file = setup_test_workspace()
    try:
        knowledge_dir = test_dir / ".harness" / "knowledge"
        failure_memory = knowledge_dir / "failure_memory.jsonl"
        experience_md = knowledge_dir / "experience.md"
        
        # Create failure_memory.jsonl with test entries
        entry = {
            "type": "gate_failure",
            "gate_id": "test-gate",
            "step": "test-step",
            "message": "Test failure message",
            "recorded_at": datetime.now(timezone.utc).isoformat()
        }
        failure_memory.write_text(json.dumps(entry) + "\n")
        
        # Ensure experience.md doesn't exist initially
        if experience_md.exists():
            experience_md.unlink()
        
        # Run archive with --state-file pointing to test workspace
        import subprocess
        result = subprocess.run(
            [sys.executable, str(test_dir / ".harness" / "scripts" / "archive-harness-workflow.py"),
             "--state-file", str(state_file)],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # Check archive succeeded
        assert result.returncode == 0, f"Archive failed: {result.stderr}\n{result.stdout}"
        
        # Check curator was triggered (experience.md should exist)
        assert experience_md.exists(), f"experience.md was not created by curator\nstdout: {result.stdout}\nstderr: {result.stderr}"
        
        content = experience_md.read_text()
        assert "Test failure message" in content, "Failure entry not in experience.md"
        
        print("✓ Test 1 PASSED: Archive triggers curator and updates experience.md")
        return True
        
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_curator_failure_doesnt_block():
    """Test 2: Curator failure doesn't block archive"""
    test_dir, state_file = setup_test_workspace()
    try:
        # Break the curator by making it unparseable
        curator_script = test_dir / ".harness" / "scripts" / "knowledge_curator.py"
        curator_script.write_text("invalid python syntax !!!")
        
        # Run archive
        import subprocess
        result = subprocess.run(
            [sys.executable, str(test_dir / ".harness" / "scripts" / "archive-harness-workflow.py"),
             "--state-file", str(state_file)],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # Archive should still succeed despite curator failure
        assert result.returncode == 0, f"Archive should not fail when curator fails: {result.stderr}\n{result.stdout}"
        assert "[Warning]" in result.stdout or "[Warning]" in result.stderr, \
            f"Should have warning about curator failure\nstdout: {result.stdout}\nstderr: {result.stderr}"
        
        print("✓ Test 2 PASSED: Curator failure doesn't block archive")
        return True
        
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_curator_with_empty_failure_memory():
    """Test 3: Curator handles empty failure_memory gracefully"""
    test_dir, state_file = setup_test_workspace()
    try:
        knowledge_dir = test_dir / ".harness" / "knowledge"
        failure_memory = knowledge_dir / "failure_memory.jsonl"
        experience_md = knowledge_dir / "experience.md"
        
        # Ensure failure_memory.jsonl doesn't exist
        if failure_memory.exists():
            failure_memory.unlink()
        
        # Run archive
        import subprocess
        result = subprocess.run(
            [sys.executable, str(test_dir / ".harness" / "scripts" / "archive-harness-workflow.py"),
             "--state-file", str(state_file)],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # Archive should succeed
        assert result.returncode == 0, f"Archive failed: {result.stderr}\n{result.stdout}"
        
        # Curator should create experience.md even with no entries
        assert experience_md.exists(), f"experience.md should be created even with empty failure_memory\nstdout: {result.stdout}"
        
        print("✓ Test 3 PASSED: Curator handles empty failure_memory")
        return True
        
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    print("Running knowledge_curator auto-trigger tests...")
    print()
    
    all_passed = True
    
    try:
        test_curator_updates_experience()
    except Exception as e:
        print(f"✗ Test 1 FAILED: {e}")
        all_passed = False
    
    try:
        test_curator_failure_doesnt_block()
    except Exception as e:
        print(f"✗ Test 2 FAILED: {e}")
        all_passed = False
    
    try:
        test_curator_with_empty_failure_memory()
    except Exception as e:
        print(f"✗ Test 3 FAILED: {e}")
        all_passed = False
    
    print()
    if all_passed:
        print("=" * 50)
        print("All tests PASSED ✓")
        sys.exit(0)
    else:
        print("=" * 50)
        print("Some tests FAILED ✗")
        sys.exit(1)
