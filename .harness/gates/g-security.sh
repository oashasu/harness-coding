#!/usr/bin/env bash
# Gate: G-SECURITY — Security scan (L4 Enforce)
# Usage: g-security.sh [--workspace <dir>]
set -euo pipefail

WORKSPACE="${1:-.}"
cd "$WORKSPACE"

echo "[GATE] G-SECURITY: Security scan starting..."

ISSUES=0

# Check for hardcoded secrets
if grep -rn --include="*.java" --include="*.py" --include="*.js" --include="*.ts" \
    -E "(password|secret|api_key|apikey|token)\s*=\s*['\"][^'\"]{8,}" \
    --exclude-dir=".harness" --exclude-dir="node_modules" --exclude-dir=".git" . 2>/dev/null; then
    echo "[GATE] G-SECURITY: Potential hardcoded secrets found"
    ISSUES=$((ISSUES+1))
fi

# Check for SQL injection patterns
if grep -rn --include="*.java" -E '\+.*".*SELECT|INSERT|UPDATE|DELETE' . 2>/dev/null | grep -v "PreparedStatement" | grep -v "createQuery"; then
    echo "[GATE] G-SECURITY: Potential SQL injection patterns"
    ISSUES=$((ISSUES+1))
fi

if [ "$ISSUES" -eq 0 ]; then
    echo '{"gate_id":"G-SECURITY","gate_level":"L4_Enforce","status":"PASS","message":"Security scan passed"}'
else
    echo '{"gate_id":"G-SECURITY","gate_level":"L4_Enforce","status":"FAIL","message":"Security scan found '"$ISSUES"' issue(s)"}'
fi
exit "$ISSUES"
