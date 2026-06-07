#!/bin/bash
# Tier 0: 编译检查 — 检测项目能否编译通过

set -euo pipefail

ROOT_DIR="${1:-.}"
cd "$ROOT_DIR"

PASSED=true
FINDINGS=()
FINDING_COUNT=0

add_finding() {
    local severity="$1" rule="$2" code="$3"
    FINDING_COUNT=$((FINDING_COUNT + 1))
    FINDINGS+=("{\"finding_id\":\"F-COM-$(printf '%03d' $FINDING_COUNT)\",\"tier\":0,\"source\":\"check-compile.sh\",\"severity\":\"$severity\",\"category\":\"compile\",\"file\":\".\",\"line\":0,\"code\":\"$code\",\"rule\":\"$rule\",\"fix_suggestion\":\"修复编译错误后重试\"}")
    if [[ "$severity" == "CRITICAL" || "$severity" == "HIGH" ]]; then
        PASSED=false
    fi
}

# 检测构建工具
if [[ -f "pom.xml" ]]; then
    echo "检测到 Maven 项目" >&2
    if ! mvn compile -q 2>/tmp/compile_err.log; then
        ERROR_MSG=$(head -c 200 /tmp/compile_err.log | tr '"' "'" | tr '\n' ' ')
        add_finding "CRITICAL" "Maven 编译失败" "$ERROR_MSG"
    fi
elif [[ -f "build.gradle" || -f "build.gradle.kts" ]]; then
    echo "检测到 Gradle 项目" >&2
    if ! ./gradlew compileJava --quiet 2>/tmp/compile_err.log; then
        ERROR_MSG=$(head -c 200 /tmp/compile_err.log | tr '"' "'" | tr '\n' ' ')
        add_finding "CRITICAL" "Gradle 编译失败" "$ERROR_MSG"
    fi
elif [[ -f "package.json" ]]; then
    echo "检测到 Node.js 项目" >&2
    if ! npx tsc --noEmit 2>/tmp/compile_err.log; then
        ERROR_MSG=$(head -c 200 /tmp/compile_err.log | tr '"' "'" | tr '\n' ' ')
        add_finding "HIGH" "TypeScript 编译失败" "$ERROR_MSG"
    fi
else
    add_finding "INFO" "未检测到构建文件，跳过编译检查" ""
fi

# 输出 JSON 结果
FINDINGS_JSON=$(IFS=,; echo "${FINDINGS[*]:-}")
cat <<EOF
{
  "tier": 0,
  "check": "compile",
  "passed": $PASSED,
  "findings_count": $FINDING_COUNT,
  "findings": [$FINDINGS_JSON]
}
EOF

exit $( [[ "$PASSED" == "true" ]] && echo 0 || echo 1 )
