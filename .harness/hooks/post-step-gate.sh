#!/usr/bin/env bash
# Post-step hook: runs gates after each pipeline step
# Called by orchestrator after step completion
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GATES_DIR="$SCRIPT_DIR/../gates"
GATE_RUNNER="$GATES_DIR/gate-runner.sh"

STEP="${1:-}"
WORKSPACE="${2:-$PROJECT_ROOT}"

if [ -z "$STEP" ]; then
    echo "Usage: post-step-gate.sh <STEP> [WORKSPACE]"
    exit 1
fi

mkdir -p "$WORKSPACE/.harness/output/logs"

# Map step to gates
declare -A STEP_GATES=(
    ["REQ_DRAFT"]="G-REQ-01"
    ["REQ_REVIEW"]=""
    ["SPEC_DRAFT"]="G-SPEC-01 G-SPEC-02"
    ["SPEC_REVIEW"]=""
    ["CODE_IMPL"]="G-CODE-01 G-CODE-02 G-CODE-03 G-CODE-04"
    ["MACHINE_CHECK"]="G-TEST-01 G-TEST-02"
    ["DUAL_REVIEW"]="G-ARCH-01 G-ARCH-02 G-ARCH-03"
    ["FINAL_ACCEPT"]=""
    ["KNOWLEDGE_ARCHIVE"]=""
)

GATES="${STEP_GATES[$STEP]:-}"

if [ -z "$GATES" ]; then
    echo "[HOOK] No gates for step $STEP"
    exit 0
fi

echo "[HOOK] Running gates for $STEP: $GATES"

FAILED=0
for GATE in $GATES; do
    # L3 gates are model-judgment, skip in shell hook
    if [[ "$GATE" == G-REQ-02 ]] || [[ "$GATE" == G-SPEC-03 ]] || \
       [[ "$GATE" == G-TEST-01 ]] || [[ "$GATE" == G-ARCH-* ]]; then
        echo "[HOOK] $GATE: L3 gate (model judgment) — skipped in hook"
        continue
    fi
    
    if [ -x "$GATE_RUNNER" ]; then
        "$GATE_RUNNER" --gate "$GATE" --workspace "$WORKSPACE" || FAILED=$((FAILED+1))
    fi
done

if [ "$FAILED" -gt 0 ]; then
    echo "[HOOK] $FAILED gate(s) failed for $STEP"
    exit 1
fi

echo "[HOOK] All L4 gates passed for $STEP"
exit 0
