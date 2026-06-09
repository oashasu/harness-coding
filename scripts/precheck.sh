#!/bin/bash
# Layer 1: Precheck — 脚本自动化预检，拦截 trivial 问题
# 失败直接打回，不进入二级审查

set -euo pipefail

ROOT_DIR="${1:-.}"
cd "$ROOT_DIR"

# 优先 .harness/state/harness-state.json，回退旧路径
if [[ -f ".harness/state/harness-state.json" ]]; then
    HARNESS_STATE_FILE=".harness/state/harness-state.json"
elif [[ -f ".harness/harness-state.json" ]]; then
    HARNESS_STATE_FILE=".harness/harness-state.json"
else
    HARNESS_STATE_FILE=".harness/state/harness-state.json"
fi

PASSED=true
FINDINGS=()
FINDING_COUNT=0

add_finding() {
    local severity="$1" category="$2" rule="$3" code="$4"
    FINDING_COUNT=$((FINDING_COUNT + 1))
    FINDINGS+=("{\"finding_id\":\"F-PC-$(printf '%03d' $FINDING_COUNT)\",\"tier\":3,\"source\":\"precheck.sh\",\"severity\":\"$severity\",\"category\":\"$category\",\"file\":\".\",\"line\":0,\"code\":\"$code\",\"rule\":\"$rule\",\"fix_suggestion\":\"修复后重新提交审查\"}")
    if [[ "$severity" == "CRITICAL" || "$severity" == "HIGH" ]]; then
        PASSED=false
    fi
}

echo "=== Layer 1: Precheck ===" >&2

# 1. 文件存在性检查
echo "  [1/5] 文件存在性检查..." >&2
if [[ -f "$HARNESS_STATE_FILE" ]]; then
    echo "    ✓ harness-state.json 存在" >&2
else
    add_finding "HIGH" "file-existence" "harness-state.json 不存在" ""
fi

# 2. 格式规范检查（调用 Tier 0）
echo "  [2/5] 格式规范检查..." >&2
if [[ -f "skills/harness-quality/scripts/tier0/check-format.sh" ]]; then
    if bash skills/harness-quality/scripts/tier0/check-format.sh "$ROOT_DIR" > /tmp/fmt_result.json 2>/dev/null; then
        echo "    ✓ 格式检查通过" >&2
    else
        add_finding "HIGH" "format" "Tier 0 格式检查未通过" ""
    fi
fi

# 3. 引用完整性检查
echo "  [3/5] 引用完整性检查..." >&2
REFS_OK=true
for ref in "skills/harness-router/SKILL.md" "skills/harness-quality/SKILL.md"; do
    if [[ ! -f "$ref" ]]; then
        add_finding "HIGH" "reference" "引用文件 $ref 不存在" "$ref"
        REFS_OK=false
    fi
done
[[ "$REFS_OK" == "true" ]] && echo "    ✓ 引用完整性通过" >&2

# 4. write_paths 范围校验
echo "  [4/5] write_paths 范围校验..." >&2
if [[ -f "skills/harness-quality/scripts/tier0/check-write-paths.sh" ]]; then
    if bash skills/harness-quality/scripts/tier0/check-write-paths.sh "$ROOT_DIR" > /tmp/wp_result.json 2>/dev/null; then
        echo "    ✓ 写入范围检查通过" >&2
    else
        add_finding "HIGH" "write-paths" "Tier 0 写入范围检查未通过" ""
    fi
fi

# 5. 上层 Tier 0-2 通过确认
echo "  [5/5] 上层 Tier 状态确认..." >&2
if [[ -f "$HARNESS_STATE_FILE" ]]; then
    QUALITY_PASSED=$(python3 -c "
import json
with open('$HARNESS_STATE_FILE') as f:
    state = json.load(f)
print(str(state.get('quality_results', {}).get('overall_passed', 'null')).lower())
" 2>/dev/null || echo "null")
    if [[ "$QUALITY_PASSED" == "true" ]]; then
        echo "    ✓ Tier 0-2 质量检查已通过" >&2
    elif [[ "$QUALITY_PASSED" == "null" ]]; then
        echo "    ⚠ Tier 0-2 尚未执行" >&2
    else
        add_finding "HIGH" "tier-status" "Tier 0-2 质量检查未通过" ""
    fi
fi

# 输出结果
FINDINGS_JSON=$(IFS=,; echo "${FINDINGS[*]:-}")
cat <<EOF
{
  "layer": 1,
  "check": "precheck",
  "passed": $PASSED,
  "findings_count": $FINDING_COUNT,
  "findings": [$FINDINGS_JSON]
}
EOF

echo "=== Precheck $( [[ "$PASSED" == "true" ]] && echo "PASSED" || echo "FAILED" ) ===" >&2
exit $( [[ "$PASSED" == "true" ]] && echo 0 || echo 1 )
