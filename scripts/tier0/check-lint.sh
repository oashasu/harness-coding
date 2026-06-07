#!/bin/bash
# Tier 0: Lint 检查 — 检测代码风格和静态分析问题

set -euo pipefail

ROOT_DIR="${1:-.}"
cd "$ROOT_DIR"

PASSED=true
FINDINGS=()
FINDING_COUNT=0

add_finding() {
    local severity="$1" rule="$2" code="$3"
    FINDING_COUNT=$((FINDING_COUNT + 1))
    FINDINGS+=("{\"finding_id\":\"F-LNT-$(printf '%03d' $FINDING_COUNT)\",\"tier\":0,\"source\":\"check-lint.sh\",\"severity\":\"$severity\",\"category\":\"lint\",\"file\":\".\",\"line\":0,\"code\":\"$code\",\"rule\":\"$rule\",\"fix_suggestion\":\"修复 lint 错误后重试\"}")
    if [[ "$severity" == "CRITICAL" || "$severity" == "HIGH" ]]; then
        PASSED=false
    fi
}

# 检测 lint 工具
if [[ -f "pom.xml" ]]; then
    # Maven + Checkstyle
    if grep -q "checkstyle" pom.xml 2>/dev/null; then
        echo "运行 Checkstyle" >&2
        if ! mvn checkstyle:check -q 2>/tmp/lint_err.log; then
            ERROR_MSG=$(head -c 200 /tmp/lint_err.log | tr '"' "'" | tr '\n' ' ')
            add_finding "HIGH" "Checkstyle 检查失败" "$ERROR_MSG"
        fi
    else
        echo "Maven 项目未配置 Checkstyle，跳过" >&2
    fi
elif [[ -f "package.json" ]]; then
    # Node.js + ESLint
    if [[ -f ".eslintrc.js" || -f ".eslintrc.json" || -f ".eslintrc.yml" ]]; then
        echo "运行 ESLint" >&2
        if ! npx eslint . --quiet 2>/tmp/lint_err.log; then
            ERROR_MSG=$(head -c 200 /tmp/lint_err.log | tr '"' "'" | tr '\n' ' ')
            add_finding "HIGH" "ESLint 检查失败" "$ERROR_MSG"
        fi
    fi
elif [[ -f "setup.py" || -f "pyproject.toml" ]]; then
    # Python + flake8
    if command -v flake8 &>/dev/null; then
        echo "运行 flake8" >&2
        if ! flake8 . --max-line-length=120 2>/tmp/lint_err.log; then
            ERROR_MSG=$(head -c 200 /tmp/lint_err.log | tr '"' "'" | tr '\n' ' ')
            add_finding "MEDIUM" "flake8 检查失败" "$ERROR_MSG"
        fi
    fi
else
    echo "未检测到 lint 配置，跳过" >&2
fi

FINDINGS_JSON=$(IFS=,; echo "${FINDINGS[*]:-}")
cat <<EOF
{
  "tier": 0,
  "check": "lint",
  "passed": $PASSED,
  "findings_count": $FINDING_COUNT,
  "findings": [$FINDINGS_JSON]
}
EOF

exit $( [[ "$PASSED" == "true" ]] && echo 0 || echo 1 )
