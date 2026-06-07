#!/usr/bin/env bash
# Gate: G-REQ-01 — requirement.md JSON Schema validation (L4 Enforce)
# Usage: g-req-01.sh [--workspace <dir>] [--req-file <path>]
set -euo pipefail

WORKSPACE="${1:-.}"
REQ_FILE="${2:-$WORKSPACE/.harness/req/requirement.md}"

echo "[GATE] G-REQ-01: requirement.md validation..."

if [ ! -f "$REQ_FILE" ]; then
    echo '{"gate_id":"G-REQ-01","gate_level":"L4_Enforce","status":"FAIL","message":"requirement.md not found: '"$REQ_FILE"'"}'
    exit 1
fi

# Check required sections
ISSUES=0

# Must have: objective, scope, acceptance_criteria, constraints
for section in "目标" "范围" "验收标准" "约束"; do
    if ! grep -qi "$section\|## $section\|### $section\|$section" "$REQ_FILE" 2>/dev/null; then
        echo "[GATE] G-REQ-01: Missing required section: $section"
        ISSUES=$((ISSUES+1))
    fi
done

# Check minimum content length (not just headers)
CONTENT_LINES=$(grep -cv '^#\|^$' "$REQ_FILE" 2>/dev/null || echo 0)
if [ "$CONTENT_LINES" -lt 5 ]; then
    echo "[GATE] G-REQ-01: Insufficient content ($CONTENT_LINES non-empty, non-header lines)"
    ISSUES=$((ISSUES+1))
fi

# Check for placeholder markers
if grep -q 'TODO\|FIXME\|XXX\|\[填入\]\|\[待定\]' "$REQ_FILE" 2>/dev/null; then
    echo "[GATE] G-REQ-01: Contains placeholder markers (TODO/FIXME)"
    ISSUES=$((ISSUES+1))
fi

if [ "$ISSUES" -eq 0 ]; then
    echo '{"gate_id":"G-REQ-01","gate_level":"L4_Enforce","status":"PASS","message":"requirement.md validation passed"}'
else
    echo '{"gate_id":"G-REQ-01","gate_level":"L4_Enforce","status":"FAIL","message":"requirement.md has '"$ISSUES"' issue(s)"}'
fi
exit "$ISSUES"
