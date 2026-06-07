#!/usr/bin/env bash
# Gate: G-SPEC-01 — task_brief schema validation (L4 Enforce)
# Usage: g-spec-01.sh [--workspace <dir>]
set -euo pipefail

WORKSPACE="${1:-.}"
SPEC_FILE="$WORKSPACE/.harness/spec/task_brief.md"

echo "[GATE] G-SPEC-01: task_brief validation..."

if [ ! -f "$SPEC_FILE" ]; then
    echo '{"gate_id":"G-SPEC-01","gate_level":"L4_Enforce","status":"FAIL","message":"task_brief.md not found"}'
    exit 1
fi

ISSUES=0

# Check required sections
for section in "目标" "接口" "数据模型" "约束"; do
    if ! grep -qi "$section" "$SPEC_FILE" 2>/dev/null; then
        echo "[GATE] G-SPEC-01: Missing section: $section"
        ISSUES=$((ISSUES+1))
    fi
done

CONTENT_LINES=$(grep -cv '^#\|^$' "$SPEC_FILE" 2>/dev/null || echo 0)
if [ "$CONTENT_LINES" -lt 10 ]; then
    echo "[GATE] G-SPEC-01: Insufficient content ($CONTENT_LINES lines)"
    ISSUES=$((ISSUES+1))
fi

if [ "$ISSUES" -eq 0 ]; then
    echo '{"gate_id":"G-SPEC-01","gate_level":"L4_Enforce","status":"PASS","message":"task_brief validation passed"}'
else
    echo '{"gate_id":"G-SPEC-01","gate_level":"L4_Enforce","status":"FAIL","message":"task_brief has '"$ISSUES"' issue(s)"}'
fi
exit "$ISSUES"
