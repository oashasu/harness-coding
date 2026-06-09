#!/bin/bash
# Tier 0: 格式规范检查 — 检测代码格式问题

set -euo pipefail

ROOT_DIR="${1:-.}"
cd "$ROOT_DIR"

PASSED=true
FINDINGS=()
FINDING_COUNT=0

add_finding() {
    local severity="$1" rule="$2" code="$3"
    FINDING_COUNT=$((FINDING_COUNT + 1))
    FINDINGS+=("{\"finding_id\":\"F-FMT-$(printf '%03d' $FINDING_COUNT)\",\"tier\":0,\"source\":\"check-format.sh\",\"severity\":\"$severity\",\"category\":\"format\",\"file\":\".\",\"line\":0,\"code\":\"$code\",\"rule\":\"$rule\",\"fix_suggestion\":\"运行格式化工具修复\"}")
    if [[ "$severity" == "CRITICAL" || "$severity" == "HIGH" ]]; then
        PASSED=false
    fi
}

# 检测格式化工具
if [[ -f "pom.xml" ]]; then
    # Maven + Spotless
    if grep -q "spotless" pom.xml 2>/dev/null; then
        echo "运行 Spotless 格式检查" >&2
        if ! mvn spotless:check -q 2>/tmp/fmt_err.log; then
            ERROR_MSG=$(head -c 200 /tmp/fmt_err.log | tr '"' "'" | tr '\n' ' ')
            add_finding "HIGH" "Spotless 格式检查失败" "$ERROR_MSG"
        fi
    fi
elif [[ -f "package.json" ]]; then
    # Node.js + Prettier
    if [[ -f ".prettierrc" || -f ".prettierrc.json" || -f ".prettierrc.yml" ]]; then
        echo "运行 Prettier 格式检查" >&2
        if ! npx prettier --check . 2>/tmp/fmt_err.log; then
            ERROR_MSG=$(head -c 200 /tmp/fmt_err.log | tr '"' "'" | tr '\n' ' ')
            add_finding "HIGH" "Prettier 格式检查失败" "$ERROR_MSG"
        fi
    fi
fi

# EditorConfig 检查
if [[ -f ".editorconfig" ]]; then
    echo "EditorConfig 存在" >&2
    # 基础检查：tab vs space 一致性
    if grep -q "indent_style = space" .editorconfig; then
        # 检查是否有 tab 缩进的文件
        TAB_FILES=$(find . -name "*.java" -not -path "*/target/*" -not -path "*/build/*" -exec grep -l "^\t" {} \; 2>/dev/null | head -5)
        if [[ -n "$TAB_FILES" ]]; then
            add_finding "MEDIUM" "EditorConfig 要求 space 缩进，但存在 tab 缩进文件" "$TAB_FILES"
        fi
    fi
fi

FINDINGS_JSON=$(IFS=,; echo "${FINDINGS[*]:-}")
cat <<EOF
{
  "tier": 0,
  "check": "format",
  "passed": $PASSED,
  "findings_count": $FINDING_COUNT,
  "findings": [$FINDINGS_JSON]
}
EOF

exit $( [[ "$PASSED" == "true" ]] && echo 0 || echo 1 )
