#!/bin/bash
# 偏航经验库管理 — add/search/inject/archive
# Harness Coding v2.0.0

set -euo pipefail

LESSONS_DIR="shared/lessons"
DATA_DIR="$LESSONS_DIR/data"

mkdir -p "$DATA_DIR"

usage() {
    echo "Usage: lesson-manager.sh <command> [args]"
    echo "  add <json>           添加新 lesson"
    echo "  search <domain> [type] 搜索相关 lesson"
    echo "  inject <task_id> <spec_file> 注入到 Spec"
    echo "  archive <lesson_id>  归档 lesson"
    exit 1
}

cmd_add() {
    local json_str="$1"
    local lesson_id
    lesson_id=$(echo "$json_str" | python3 -c "import sys,json; print(json.load(sys.stdin)['lesson_id'])" 2>/dev/null)

    if [[ -z "$lesson_id" ]]; then
        echo '{"ok":false,"error":"missing_lesson_id"}' >&2
        exit 1
    fi

    local file="$DATA_DIR/$lesson_id.json"
    echo "$json_str" | python3 -m json.tool > "$file" 2>/dev/null

    # 更新活跃索引
    local domain title confidence
    domain=$(echo "$json_str" | python3 -c "import sys,json; print(json.load(sys.stdin).get('domain','unknown'))")
    title=$(echo "$json_str" | python3 -c "import sys,json; print(json.load(sys.stdin).get('title',''))")
    confidence=$(echo "$json_str" | python3 -c "import sys,json; print(json.load(sys.stdin).get('confidence',0.8))")

    echo "| $lesson_id | $domain | - | $title | $confidence |" >> "$LESSONS_DIR/lifecycle/active.md"

    echo "{\"ok\":true,\"lesson_id\":\"$lesson_id\",\"file\":\"$file\"}"
}

cmd_search() {
    local domain="${1:-}"
    local error_type="${2:-}"

    if [[ ! -d "$DATA_DIR" ]] || [[ -z "$(ls -A "$DATA_DIR" 2>/dev/null)" ]]; then
        echo '{"results":[],"total":0}'
        return
    fi

    python3 -c "
import json, glob, sys

domain = '$domain'
error_type = '$error_type'
results = []

for f in glob.glob('$DATA_DIR/*.json'):
    try:
        with open(f) as fh:
            lesson = json.load(fh)
        if lesson.get('status') == 'archived':
            continue
        if domain and lesson.get('domain', '') != domain:
            continue
        if error_type and lesson.get('error_type', '') != error_type:
            continue
        results.append(lesson)
    except (json.JSONDecodeError, IOError):
        continue

results.sort(key=lambda x: x.get('confidence', 0), reverse=True)
print(json.dumps({'results': results[:10], 'total': len(results)}, ensure_ascii=False, indent=2))
"
}

cmd_inject() {
    local task_id="$1"
    local spec_file="$2"

    if [[ ! -f "$spec_file" ]]; then
        echo "{\"ok\":false,\"error\":\"spec_file_not_found\",\"file\":\"$spec_file\"}" >&2
        exit 1
    fi

    # 搜索活跃 lessons
    local lessons
    lessons=$(python3 -c "
import json, glob

results = []
for f in glob.glob('$DATA_DIR/*.json'):
    try:
        with open(f) as fh:
            lesson = json.load(fh)
        if lesson.get('status') == 'active' and lesson.get('confidence', 0) >= 0.7:
            results.append(lesson)
    except (json.JSONDecodeError, IOError):
        continue

results.sort(key=lambda x: x.get('confidence', 0), reverse=True)
print(json.dumps(results[:10], ensure_ascii=False))
")

    local count
    count=$(echo "$lessons" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")

    if [[ "$count" == "0" ]]; then
        echo "{\"ok\":true,\"injected\":0,\"message\":\"no active lessons\"}"
        return
    fi

    # 追加到 Spec 文件
    cat >> "$spec_file" <<EOF

## 已知风险（自动注入）

> 以下教训来自偏航经验库，task_id: $task_id，共 $count 条

EOF

    echo "$lessons" | python3 -c "
import sys, json
lessons = json.load(sys.stdin)
for i, l in enumerate(lessons, 1):
    print(f'{i}. **[{l.get(\"severity\",\"medium\")}] {l[\"title\"]}**')
    print(f'   - 根因: {l.get(\"root_cause\",\"N/A\")}')
    print(f'   - 预防: {l.get(\"prevention\",\"N/A\")}')
    print(f'   - 置信度: {l.get(\"confidence\",0)}')
    print()
" >> "$spec_file"

    echo "{\"ok\":true,\"injected\":$count,\"spec_file\":\"$spec_file\"}"
}

cmd_archive() {
    local lesson_id="$1"
    local file="$DATA_DIR/$lesson_id.json"

    if [[ ! -f "$file" ]]; then
        echo "{\"ok\":false,\"error\":\"lesson_not_found\",\"lesson_id\":\"$lesson_id\"}" >&2
        exit 1
    fi

    # 更新状态
    python3 -c "
import json
with open('$file') as f:
    data = json.load(f)
data['status'] = 'archived'
data['archived_at'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
with open('$file', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print(json.dumps({'ok': True, 'lesson_id': '$lesson_id'}, ensure_ascii=False))
"
}

# 主入口
[[ $# -lt 1 ]] && usage

case "$1" in
    add)
        [[ $# -lt 2 ]] && { echo "Usage: lesson-manager.sh add '<json>'"; exit 1; }
        cmd_add "$2"
        ;;
    search)
        cmd_search "${2:-}" "${3:-}"
        ;;
    inject)
        [[ $# -lt 3 ]] && { echo "Usage: lesson-manager.sh inject <task_id> <spec_file>"; exit 1; }
        cmd_inject "$2" "$3"
        ;;
    archive)
        [[ $# -lt 2 ]] && { echo "Usage: lesson-manager.sh archive <lesson_id>"; exit 1; }
        cmd_archive "$2"
        ;;
    *)
        usage
        ;;
esac
