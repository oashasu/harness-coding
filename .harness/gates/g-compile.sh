#!/usr/bin/env bash
# Gate: G-COMPILE — Compile check (L4 Enforce)
# Usage: g-compile.sh [--workspace <dir>]
set -euo pipefail

WORKSPACE="${1:-.}"
cd "$WORKSPACE"

echo "[GATE] G-COMPILE: Compile check starting..."

if [ -f "pom.xml" ]; then
    mvn compile -q 2>&1 | tee .harness/output/logs/compile.log
    EXIT_CODE=${PIPESTATUS[0]}
elif [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
    ./gradlew compileJava --quiet 2>&1 | tee .harness/output/logs/compile.log
    EXIT_CODE=${PIPESTATUS[0]}
elif [ -f "package.json" ]; then
    npm run build 2>&1 | tee .harness/output/logs/compile.log
    EXIT_CODE=${PIPESTATUS[0]}
elif [ -f "go.mod" ]; then
    go build ./... 2>&1 | tee .harness/output/logs/compile.log
    EXIT_CODE=${PIPESTATUS[0]}
else
    echo "[GATE] G-COMPILE: No recognized build file found — SKIP"
    exit 0
fi

if [ "$EXIT_CODE" -eq 0 ]; then
    echo '{"gate_id":"G-COMPILE","gate_level":"L4_Enforce","status":"PASS","message":"Compile succeeded"}'
else
    echo '{"gate_id":"G-COMPILE","gate_level":"L4_Enforce","status":"FAIL","message":"Compile failed (exit '"$EXIT_CODE"')"}'
fi
exit "$EXIT_CODE"
