#!/usr/bin/env bash
# Gate: G-STATIC — Static analysis (L3 Policy)
# Usage: g-static.sh [--workspace <dir>]
set -euo pipefail

WORKSPACE="${1:-.}"
cd "$WORKSPACE"

echo "[GATE] G-STATIC: Static analysis starting..."

ISSUES=0

# Checkstyle for Java
if [ -f "pom.xml" ] && [ -f "checkstyle.xml" ]; then
    mvn checkstyle:check -q 2>&1 | tee .harness/output/logs/static.log || ISSUES=$((ISSUES+1))
fi

# ESLint for JS/TS
if [ -f ".eslintrc.js" ] || [ -f ".eslintrc.json" ] || [ -f "eslint.config.js" ]; then
    npx eslint . --max-warnings 0 2>&1 | tee .harness/output/logs/static.log || ISSUES=$((ISSUES+1))
fi

# pylint/flake8 for Python
if [ -f "setup.py" ] || [ -f "pyproject.toml" ]; then
    python3 -m flake8 . 2>&1 | tee .harness/output/logs/static.log || ISSUES=$((ISSUES+1))
fi

if [ "$ISSUES" -eq 0 ]; then
    echo '{"gate_id":"G-STATIC","gate_level":"L3_Policy","status":"PASS","message":"Static analysis passed"}'
else
    echo '{"gate_id":"G-STATIC","gate_level":"L3_Policy","status":"FAIL","message":"Static analysis found '"$ISSUES"' issue(s)"}'
fi
exit "$ISSUES"
