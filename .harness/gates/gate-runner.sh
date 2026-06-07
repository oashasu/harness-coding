#!/usr/bin/env bash
# Gate runner v2 — YAML-driven execution with path-conditional filtering
# Usage: gate-runner.sh [--workspace <dir>] [--phase <phase>] [--mode <mode>] [--gate <gate-id>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DECLARATIVE_DIR="$SCRIPT_DIR/declarative"
CONFIG_DIR="$(dirname "$SCRIPT_DIR")/config"
WORKSPACE="."
PHASE=""
MODE=""
SINGLE_GATE=""
CHANGED_FILES=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --workspace) WORKSPACE="$2"; shift 2 ;;
        --phase) PHASE="$2"; shift 2 ;;
        --mode) MODE="$2"; shift 2 ;;
        --gate) SINGLE_GATE="$2"; shift 2 ;;
        --changed-files) CHANGED_FILES="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

mkdir -p "$WORKSPACE/.harness/output/logs" "$WORKSPACE/.harness/output/gate-results"

# Get changed files if not provided
if [ -z "$CHANGED_FILES" ] && [ -d "$WORKSPACE/.git" ]; then
    CHANGED_FILES=$(cd "$WORKSPACE" && git diff --name-only HEAD~1 2>/dev/null || echo "")
fi

# Simple YAML parser (avoids yq dependency)
parse_yaml_value() {
    local file="$1" key="$2"
    grep "^${key}:" "$file" 2>/dev/null | head -1 | sed "s/^${key}:[[:space:]]*//" | tr -d '"' | tr -d "'"
}

# Extract list items from YAML (handles "- item" format)
parse_yaml_list() {
    local file="$1" key="$2"
    sed -n "/^${key}:/,/^[^ ]/{/^- /{s/^- //;p}}" "$file" 2>/dev/null
}

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
RESULTS=()

for yaml_file in "$DECLARATIVE_DIR"/*.yaml; do
    [ -f "$yaml_file" ] || continue

    GATE_ID=$(parse_yaml_value "$yaml_file" "gate_id")
    GATE_NAME=$(parse_yaml_value "$yaml_file" "name")
    GATE_PHASE=$(parse_yaml_value "$yaml_file" "phase")
    GATE_BLOCKING=$(parse_yaml_value "$yaml_file" "blocking")

    # Single gate filter
    if [ -n "$SINGLE_GATE" ] && [ "$GATE_ID" != "$SINGLE_GATE" ]; then
        continue
    fi

    # Phase filter
    if [ -n "$PHASE" ] && [ "$GATE_PHASE" != "$PHASE" ]; then
        continue
    fi

    # Mode filter (extract modes list from YAML)
    if [ -n "$MODE" ]; then
        MODES=$(parse_yaml_list "$yaml_file" "modes")
        if [ -n "$MODES" ] && ! echo "$MODES" | grep -qw "$MODE"; then
            continue
        fi
    fi

    # Path-conditional filter
    if [ -n "$CHANGED_FILES" ]; then
        TRIGGER_PATHS=$(parse_yaml_list "$yaml_file" "paths")
        if [ -n "$TRIGGER_PATHS" ]; then
            MATCHED=false
            while IFS= read -r changed; do
                while IFS= read -r pattern; do
                    if [[ "$changed" == $pattern ]]; then
                        MATCHED=true
                        break 2
                    fi
                done <<< "$TRIGGER_PATHS"
            done <<< "$CHANGED_FILES"
            if [ "$MATCHED" = false ]; then
                echo "[GATE] $GATE_ID ($GATE_NAME): SKIP — no matching changed files"
                SKIP_COUNT=$((SKIP_COUNT + 1))
                continue
            fi
        fi
    fi

    # Execute gate
    SCRIPT=$(parse_yaml_value "$yaml_file" "script")
    if [ -z "$SCRIPT" ]; then
        echo "[GATE] $GATE_ID: ERROR — no script defined"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        continue
    fi

    # Resolve relative script path
    if [[ "$SCRIPT" != /* ]]; then
        SCRIPT="$WORKSPACE/$SCRIPT"
    fi

    echo "[GATE] $GATE_ID ($GATE_NAME): executing..."
    RESULT_FILE="$WORKSPACE/.harness/output/gate-results/${GATE_ID}.json"

    if bash "$SCRIPT" "$WORKSPACE" > "$RESULT_FILE" 2>&1; then
        echo "[GATE] $GATE_ID: PASS"
        PASS_COUNT=$((PASS_COUNT + 1))
        RESULTS+=("{\"gate_id\":\"$GATE_ID\",\"status\":\"PASS\"}")
    else
        echo "[GATE] $GATE_ID: FAIL"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        RESULTS+=("{\"gate_id\":\"$GATE_ID\",\"status\":\"FAIL\"}")
    fi
done

# Summary
echo ""
echo "=== Gate Summary ==="
echo "Pass: $PASS_COUNT | Fail: $FAIL_COUNT | Skip: $SKIP_COUNT"

if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0
