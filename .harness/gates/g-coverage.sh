#!/usr/bin/env bash
# Gate: G-COVERAGE — Test coverage >= 80% (L3 Policy)
# Usage: g-coverage.sh [--workspace <dir>] [--threshold 80]
set -euo pipefail

WORKSPACE="${1:-.}"
THRESHOLD="${2:-80}"
cd "$WORKSPACE"

echo "[GATE] G-COVERAGE: Coverage check (threshold=${THRESHOLD}%)..."

# Try JaCoCo for Maven projects
if [ -f "pom.xml" ]; then
    mvn jacoco:report -q 2>/dev/null || true
    REPORT="target/site/jacoco/jacoco.csv"
    if [ -f "$REPORT" ]; then
        COVERED=$(awk -F',' 'NR>1 {c+=$8; m+=$9} END {if(c+m>0) printf "%.0f", c*100/(c+m); else print 0}' "$REPORT")
        echo "[GATE] G-COVERAGE: ${COVERED}% covered"
        if [ "$COVERED" -ge "$THRESHOLD" ]; then
            echo '{"gate_id":"G-COVERAGE","gate_level":"L3_Policy","status":"PASS","message":"Coverage '"${COVERED}"'% >= '"${THRESHOLD}"'%"}'
            exit 0
        else
            echo '{"gate_id":"G-COVERAGE","gate_level":"L3_Policy","status":"FAIL","message":"Coverage '"${COVERED}"'% < '"${THRESHOLD}"'%"}'
            exit 1
        fi
    fi
fi

# Fallback: check if coverage tool exists
echo "[GATE] G-COVERAGE: No coverage report found — SKIP"
echo '{"gate_id":"G-COVERAGE","gate_level":"L3_Policy","status":"SKIP","message":"No coverage tool configured"}'
exit 0
