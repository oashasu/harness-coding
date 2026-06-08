#!/usr/bin/env bash
# Blackbox integration tests for gate-runner.sh
# Tests: nested check.script, inline trigger.paths array, failure memory writeback, check.args passing
# Note: Temporarily creates test gate YAML files in project's declarative directory, cleans up after.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GATE_RUNNER="$PROJECT_ROOT/.harness/gates/gate-runner.sh"
DECLARATIVE_DIR="$PROJECT_ROOT/.harness/gates/declarative"

# Test counters
TESTS_RUN=0
TESTS_PASS=0
TESTS_FAIL=0

# Test gate IDs - use unique prefix to avoid collision
TEST_PREFIX="BBTEST-"

pass() { echo "✓ $1"; TESTS_PASS=$((TESTS_PASS + 1)); }
fail() { echo "✗ $1"; TESTS_FAIL=$((TESTS_FAIL + 1)); }
run_test() { TESTS_RUN=$((TESTS_RUN + 1)); echo ""; echo "Running: $1"; "$@" && pass "$1" || fail "$1"; }

# Cleanup function to remove test gates
cleanup_test_gates() {
    rm -f "$DECLARATIVE_DIR"/${TEST_PREFIX}*.yaml 2>/dev/null || true
}

# Setup workspace with test gate
setup_workspace() {
    local gate_id="$1"
    local yaml_content="$2"
    
    local ws
    ws=$(mktemp -d)
    mkdir -p "$ws/.harness/gates"
    mkdir -p "$ws/.harness/output/logs"
    mkdir -p "$ws/.harness/output/gate-results"
    mkdir -p "$ws/.harness/knowledge"
    
    # Create test gate YAML in project's declarative directory
    echo "$yaml_content" > "$DECLARATIVE_DIR/${gate_id}.yaml"
    
    echo "$ws"
}

teardown_workspace() {
    local ws="$1"
    rm -rf "$ws"
}

# Test 1: nested check.script parsing
test_nested_check_script() {
    local gate_id="${TEST_PREFIX}01"
    local ws
    ws=$(setup_workspace "$gate_id" "$(cat <<'YAML'
gate_id: BBTEST-01
name: nested-script-test
phase: TEST
blocking: false
trigger:
  paths: ["**/*.txt"]
check:
  type: script
  script: .harness/gates/test-script.sh
YAML
)")
    trap "teardown_workspace $ws; rm -f '$DECLARATIVE_DIR/${gate_id}.yaml'" RETURN

    # Create test script in workspace
    cat > "$ws/.harness/gates/test-script.sh" << 'SCRIPT'
#!/usr/bin/env bash
echo '{"status": "ok"}'
SCRIPT
    chmod +x "$ws/.harness/gates/test-script.sh"

    # Create matching file
    echo "test" > "$ws/file.txt"

    # Run gate runner
    local output
    output=$(bash "$GATE_RUNNER" --workspace "$ws" --gate "$gate_id" --changed-files "file.txt" 2>&1) || true

    if echo "$output" | grep -q "$gate_id.*PASS"; then
        return 0
    fi
    echo "Output: $output" >&2
    return 1
}

# Test 2: inline trigger.paths array parsing
test_inline_trigger_paths() {
    local gate_id="${TEST_PREFIX}02"
    local ws
    ws=$(setup_workspace "$gate_id" "$(cat <<'YAML'
gate_id: BBTEST-02
name: path-match-test
phase: TEST
blocking: false
trigger:
  paths: ["**/*.java", "**/*.ts"]
check:
  type: script
  script: .harness/gates/test-script.sh
YAML
)")
    trap "teardown_workspace $ws; rm -f '$DECLARATIVE_DIR/${gate_id}.yaml'" RETURN

    # Create test script
    cat > "$ws/.harness/gates/test-script.sh" << 'SCRIPT'
#!/usr/bin/env bash
echo '{"status": "ok"}'
SCRIPT
    chmod +x "$ws/.harness/gates/test-script.sh"

    # Test matching path: *.java pattern matches App.java directly
    echo "// java" > "$ws/App.java"

    local output1
    output1=$(bash "$GATE_RUNNER" --workspace "$ws" --gate "$gate_id" --changed-files "App.java" 2>&1) || true
    
    if echo "$output1" | grep -q "$gate_id.*PASS"; then
        # Test non-matching path triggers SKIP
        local output2
        output2=$(bash "$GATE_RUNNER" --workspace "$ws" --gate "$gate_id" --changed-files "README.md" 2>&1) || true
        if echo "$output2" | grep -q "$gate_id.*SKIP"; then
            return 0
        fi
        echo "Skip test failed. Output2: $output2" >&2
    else
        echo "Pass test failed. Output1: $output1" >&2
    fi
    return 1
}

# Test 3: failure memory writeback
test_failure_memory_writeback() {
    local gate_id="${TEST_PREFIX}03"
    local ws
    ws=$(setup_workspace "$gate_id" "$(cat <<'YAML'
gate_id: BBTEST-03
name: failure-test
phase: TEST
blocking: false
trigger:
  paths: ["**/*"]
check:
  type: script
  script: .harness/gates/fail-script.sh
on_failure:
  message: "Intentional failure for test"
YAML
)")
    trap "teardown_workspace $ws; rm -f '$DECLARATIVE_DIR/${gate_id}.yaml'" RETURN

    # Create failing script
    cat > "$ws/.harness/gates/fail-script.sh" << 'SCRIPT'
#!/usr/bin/env bash
echo "This gate fails intentionally" >&2
exit 1
SCRIPT
    chmod +x "$ws/.harness/gates/fail-script.sh"

    # Create matching file
    echo "test" > "$ws/file.txt"

    # Run gate runner - should fail
    bash "$GATE_RUNNER" --workspace "$ws" --gate "$gate_id" --changed-files "file.txt" 2>&1 || true

    # Check failure_memory.jsonl was created with entry (JSON has spaces after colons)
    if [ -f "$ws/.harness/knowledge/failure_memory.jsonl" ]; then
        # Match with flexible whitespace: "gate_id": "BBTEST-03" or "gate_id":"BBTEST-03"
        if grep -qE '"gate_id"[[:space:]]*:[[:space:]]*"'"$gate_id"'"' "$ws/.harness/knowledge/failure_memory.jsonl"; then
            return 0
        fi
        echo "Gate ID not found in failure_memory.jsonl:" >&2
        cat "$ws/.harness/knowledge/failure_memory.jsonl" >&2
    else
        echo "failure_memory.jsonl not created" >&2
        ls -la "$ws/.harness/knowledge/" >&2
    fi
    return 1
}

# Test 4: check.args passing
test_check_args_passing() {
    local gate_id="${TEST_PREFIX}04"
    local ws
    ws=$(setup_workspace "$gate_id" "$(cat <<'YAML'
gate_id: BBTEST-04
name: args-test
phase: TEST
blocking: false
trigger:
  paths: ["**/*"]
check:
  type: script
  script: .harness/gates/args-script.sh
  args: ["--flag", "${workspace}", "--other=value"]
YAML
)")
    trap "teardown_workspace $ws; rm -f '$DECLARATIVE_DIR/${gate_id}.yaml'; rm -f /tmp/test-args-received.txt" RETURN

    # Create script that records args
    cat > "$ws/.harness/gates/args-script.sh" << 'SCRIPT'
#!/usr/bin/env bash
echo "Args received: $*" > /tmp/test-args-received.txt
echo '{"status": "ok"}'
SCRIPT
    chmod +x "$ws/.harness/gates/args-script.sh"

    # Create matching file
    echo "test" > "$ws/file.txt"

    # Run gate runner
    bash "$GATE_RUNNER" --workspace "$ws" --gate "$gate_id" --changed-files "file.txt" 2>&1 || true

    # Check args were passed (workspace should be substituted)
    if [ -f /tmp/test-args-received.txt ]; then
        if grep -q "\-\-flag" /tmp/test-args-received.txt && \
           grep -q "\-\-other=value" /tmp/test-args-received.txt && \
           grep -q "$ws" /tmp/test-args-received.txt; then
            return 0
        fi
        echo "Args file content:" >&2
        cat /tmp/test-args-received.txt >&2
    else
        echo "Args file not created" >&2
    fi
    return 1
}

# Test 5: skip behavior (no matching paths)
test_skip_behavior() {
    local gate_id="${TEST_PREFIX}05"
    local ws
    ws=$(setup_workspace "$gate_id" "$(cat <<'YAML'
gate_id: BBTEST-05
name: skip-test
phase: TEST
blocking: false
trigger:
  paths: ["*.java"]
check:
  type: script
  script: .harness/gates/test-script.sh
YAML
)")
    trap "teardown_workspace $ws; rm -f '$DECLARATIVE_DIR/${gate_id}.yaml'" RETURN

    cat > "$ws/.harness/gates/test-script.sh" << 'SCRIPT'
#!/usr/bin/env bash
echo '{"status": "ok"}'
SCRIPT
    chmod +x "$ws/.harness/gates/test-script.sh"

    # Changed file doesn't match pattern
    local output
    output=$(bash "$GATE_RUNNER" --workspace "$ws" --gate "$gate_id" --changed-files "README.md" 2>&1) || true

    if echo "$output" | grep -q "$gate_id.*SKIP"; then
        return 0
    fi
    echo "Output: $output" >&2
    return 1
}

# Main test runner
main() {
    # Ensure cleanup on exit
    trap cleanup_test_gates EXIT
    
    echo "=== Gate Runner Blackbox Tests ==="
    echo "Project: $PROJECT_ROOT"
    echo "Runner: $GATE_RUNNER"
    
    run_test test_nested_check_script
    run_test test_inline_trigger_paths
    run_test test_failure_memory_writeback
    run_test test_check_args_passing
    run_test test_skip_behavior

    echo ""
    echo "=== Results ==="
    echo "Passed: $TESTS_PASS / $TESTS_RUN"
    echo "Failed: $TESTS_FAIL"

    if [ "$TESTS_FAIL" -gt 0 ]; then
        exit 1
    fi
    exit 0
}

main "$@"
