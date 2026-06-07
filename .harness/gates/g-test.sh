#!/usr/bin/env bash
# Gate: G-TEST — Test execution (L4 Enforce)
# Usage: g-test.sh [--workspace <dir>]
set -euo pipefail

WORKSPACE="${1:-.}"
cd "$WORKSPACE"

echo "[GATE] G-TEST: Test execution starting..."

if [ -f "pom.xml" ]; then
    mvn test -q 2>&1 | tee .harness/output/logs/test.log
    EXIT_CODE=${PIPESTATUS[0]}
elif [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
    ./gradlew test --quiet 2>&1 | tee .harness/output/logs/test.log
    EXIT_CODE=${PIPESTATUS[0]}
elif [ -f "package.json" ]; then
    npm test 2>&1 | tee .harness/output/logs/test.log
    EXIT_CODE=${PIPESTATUS[0]}
elif [ -f "go.mod" ]; then
    go test ./... 2>&1 | tee .harness/output/logs/test.log
    EXIT_CODE=${PIPESTATUS[0]}
else
    echo "[GATE] G-TEST: No recognized test framework — SKIP"
    exit 0
fi

if [ "$EXIT_CODE" -eq 0 ]; then
    echo '{"gate_id":"G-TEST","gate_level":"L4_Enforce","status":"PASS","message":"Tests passed"}'
else
    echo '{"gate_id":"G-TEST","gate_level":"L4_Enforce","status":"FAIL","message":"Tests failed (exit '"$EXIT_CODE"')"}'
fi
exit "$EXIT_CODE"
