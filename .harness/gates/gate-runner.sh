#!/usr/bin/env bash
# Gate runner v2 — YAML-driven execution with path-conditional filtering
# Usage: gate-runner.sh [--workspace <dir>] [--phase <phase>] [--mode <mode>] [--gate <gate-id>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DECLARATIVE_DIR="$SCRIPT_DIR/declarative"
CONFIG_DIR="$(dirname "$SCRIPT_DIR")/config"
EXPERIENCE_WAL="$SCRIPT_DIR/../scripts/experience_wal.py"
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

# Read a scalar or list from the small declarative gate YAML subset without yq.
parse_yaml() {
    local file="$1" path="$2" expected_kind="$3"
    python3 - "$file" "$path" "$expected_kind" <<'PY'
import json
import sys
from pathlib import Path

file_path = Path(sys.argv[1])
path = sys.argv[2].split(".")
expected_kind = sys.argv[3]

root = {}
stack = [(-1, root)]

def strip_comment(raw: str) -> str:
    in_single = False
    in_double = False
    for i, ch in enumerate(raw):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return raw[:i].rstrip()
    return raw.rstrip()

def parse_scalar(raw: str):
    raw = strip_comment(raw).strip()
    if raw == "":
        return {}
    if raw in {"true", "false"}:
        return raw == "true"
    if raw in {"[]", "{}"}:
        return [] if raw == "[]" else {}
    if raw.startswith("[") and raw.endswith("]"):
        return json.loads(raw)
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw

for original in file_path.read_text(encoding="utf-8").splitlines():
    if not original.strip() or original.lstrip().startswith("#"):
        continue
    indent = len(original) - len(original.lstrip(" "))
    content = original[indent:]
    if ":" not in content:
        continue
    key, raw_value = content.split(":", 1)
    key = key.strip()
    value = parse_scalar(raw_value)

    while stack and indent <= stack[-1][0]:
        stack.pop()
    parent = stack[-1][1]
    parent[key] = value
    if isinstance(value, dict):
        stack.append((indent, value))

node = root
for key in path:
    if not isinstance(node, dict) or key not in node:
        sys.exit(0)
    node = node[key]

if expected_kind == "list":
    if isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                print(json.dumps(item, ensure_ascii=False))
            else:
                print(item)
elif not isinstance(node, (dict, list)):
    if isinstance(node, bool):
        print("true" if node else "false")
    else:
        print(node)
PY
}

parse_yaml_value() {
    parse_yaml "$1" "$2" "scalar"
}

parse_yaml_list() {
    parse_yaml "$1" "$2" "list"
}

record_gate_failure() {
    local gate_id="$1" gate_phase="$2" failure_message="$3" result_file="$4"
    if [ ! -f "$EXPERIENCE_WAL" ]; then
        return 0
    fi
    HARNESS_WORKSPACE="$WORKSPACE" python3 "$EXPERIENCE_WAL" gate-failure \
        --gate-id "$gate_id" \
        --step "$gate_phase" \
        --message "$failure_message" \
        >/dev/null 2>&1 || true
    if [ -f "$result_file" ]; then
        cp "$result_file" "$WORKSPACE/.harness/output/logs/${gate_id}.failure.log" 2>/dev/null || true
    fi
}

path_matches_pattern() {
    local changed_path="$1" pattern="$2"
    python3 - "$changed_path" "$pattern" <<'PY'
import sys
from pathlib import PurePosixPath

changed = sys.argv[1]
pattern = sys.argv[2]
path = PurePosixPath(changed)

matched = path.match(pattern)
if not matched and pattern.startswith("**/"):
    matched = path.match(pattern[3:])

sys.exit(0 if matched else 1)
PY
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
        MODES=$(parse_yaml_list "$yaml_file" "trigger.modes")
        if [ -n "$MODES" ] && ! echo "$MODES" | grep -qw "$MODE"; then
            continue
        fi
    fi

    # Path-conditional filter
    if [ -n "$CHANGED_FILES" ]; then
        TRIGGER_PATHS=$(parse_yaml_list "$yaml_file" "trigger.paths")
        if [ -n "$TRIGGER_PATHS" ]; then
            MATCHED=false
            while IFS= read -r changed; do
                while IFS= read -r pattern; do
                    if path_matches_pattern "$changed" "$pattern"; then
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
    SCRIPT=$(parse_yaml_value "$yaml_file" "check.script")
    if [ -z "$SCRIPT" ]; then
        echo "[GATE] $GATE_ID: ERROR — no script defined"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILURE_MESSAGE=$(parse_yaml_value "$yaml_file" "on_failure.message")
        record_gate_failure "$GATE_ID" "$GATE_PHASE" "${FAILURE_MESSAGE:-no script defined}" "$WORKSPACE/.harness/output/gate-results/${GATE_ID}.json"
        continue
    fi

    # Resolve relative script path
    if [[ "$SCRIPT" != /* ]]; then
        SCRIPT="$WORKSPACE/$SCRIPT"
    fi

    GATE_ARGS=()
    while IFS= read -r arg; do
        [ -n "$arg" ] || continue
        GATE_ARGS+=("${arg//\$\{workspace\}/$WORKSPACE}")
    done < <(parse_yaml_list "$yaml_file" "check.args")
    if [ "${#GATE_ARGS[@]}" -eq 0 ]; then
        GATE_ARGS=("$WORKSPACE")
    fi

    echo "[GATE] $GATE_ID ($GATE_NAME): executing..."
    RESULT_FILE="$WORKSPACE/.harness/output/gate-results/${GATE_ID}.json"

    if bash "$SCRIPT" "${GATE_ARGS[@]}" > "$RESULT_FILE" 2>&1; then
        echo "[GATE] $GATE_ID: PASS"
        PASS_COUNT=$((PASS_COUNT + 1))
        RESULTS+=("{\"gate_id\":\"$GATE_ID\",\"status\":\"PASS\"}")
    else
        echo "[GATE] $GATE_ID: FAIL"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        RESULTS+=("{\"gate_id\":\"$GATE_ID\",\"status\":\"FAIL\"}")
        FAILURE_MESSAGE=$(parse_yaml_value "$yaml_file" "on_failure.message")
        if [ -z "$FAILURE_MESSAGE" ]; then
            FAILURE_MESSAGE=$(tail -n 1 "$RESULT_FILE" 2>/dev/null || echo "Gate failed")
        fi
        record_gate_failure "$GATE_ID" "$GATE_PHASE" "$FAILURE_MESSAGE" "$RESULT_FILE"
        # Stop immediately on blocking gate failure
        if [ "$GATE_BLOCKING" = "true" ]; then
            echo "[GATE] Blocking gate $GATE_ID failed — aborting"
            break
        fi
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
