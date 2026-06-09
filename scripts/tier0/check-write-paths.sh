#!/bin/bash
# Tier 0: 写入范围校验 — 检查 git diff 变更文件是否在白名单内

set -euo pipefail

ROOT_DIR="${1:-.}"
cd "$ROOT_DIR"

# 优先 .harness/state/harness-state.json，回退旧路径
if [[ -f ".harness/state/harness-state.json" ]]; then
    STATE_FILE=".harness/state/harness-state.json"
elif [[ -f ".harness/harness-state.json" ]]; then
    STATE_FILE=".harness/harness-state.json"
else
    STATE_FILE=".harness/state/harness-state.json"
fi
PASSED=true
FINDINGS=()
FINDING_COUNT=0

add_finding() {
    local severity="$1" rule="$2" code="$3"
    FINDING_COUNT=$((FINDING_COUNT + 1))
    FINDINGS+=("{\"finding_id\":\"F-WP-$(printf '%03d' $FINDING_COUNT)\",\"tier\":0,\"source\":\"check-write-paths.sh\",\"severity\":\"$severity\",\"category\":\"write-paths\",\"file\":\".\",\"line\":0,\"code\":\"$code\",\"rule\":\"$rule\",\"fix_suggestion\":\"将文件移入允许的写入范围或更新 allowed_write_paths\"}")
    if [[ "$severity" == "CRITICAL" || "$severity" == "HIGH" ]]; then
        PASSED=false
    fi
}

# 读取白名单
if [[ -f "$STATE_FILE" ]]; then
    ALLOWED_PATHS=$(python3 -c "
import json, sys
with open('$STATE_FILE') as f:
    state = json.load(f)
paths = state.get('contract', {}).get('allowed_write_paths', [])
for p in paths:
    print(p)
" 2>/dev/null || echo "")
else
    ALLOWED_PATHS="src/**
scripts/**
skills/**
.harness/**
docs/**
*.md
pom.xml
build.gradle
package.json"
fi

if [[ -z "$ALLOWED_PATHS" ]]; then
    echo "无白名单配置，跳过检查" >&2
    cat <<EOF
{
  "tier": 0,
  "check": "write-paths",
  "passed": true,
  "findings_count": 0,
  "findings": []
}
EOF
    exit 0
fi

# 获取变更文件列表
CHANGED_FILES=""
if git rev-parse --is-inside-work-tree &>/dev/null; then
    CHANGED_FILES=$(git diff --name-only HEAD 2>/dev/null || git diff --name-only 2>/dev/null || echo "")
fi

if [[ -z "$CHANGED_FILES" ]]; then
    echo "无变更文件" >&2
    cat <<EOF
{
  "tier": 0,
  "check": "write-paths",
  "passed": true,
  "findings_count": 0,
  "findings": []
}
EOF
    exit 0
fi

# 检查每个变更文件是否在白名单内
while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    MATCHED=false
    while IFS= read -r pattern; do
        [[ -z "$pattern" ]] && continue
        # 使用 bash glob 匹配
        # shellcheck disable=SC2254
        case "$file" in
            $pattern) MATCHED=true; break ;;
        esac
    done <<< "$ALLOWED_PATHS"
    if [[ "$MATCHED" == "false" ]]; then
        add_finding "HIGH" "文件 $file 不在 allowed_write_paths 白名单内" "$file"
    fi
done <<< "$CHANGED_FILES"

FINDINGS_JSON=$(IFS=,; echo "${FINDINGS[*]:-}")
cat <<EOF
{
  "tier": 0,
  "check": "write-paths",
  "passed": $PASSED,
  "findings_count": $FINDING_COUNT,
  "findings": [$FINDINGS_JSON]
}
EOF

exit $( [[ "$PASSED" == "true" ]] && echo 0 || echo 1 )
