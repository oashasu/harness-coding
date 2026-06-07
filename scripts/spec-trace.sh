#!/bin/bash
# Spec-Code 追溯 — generate/drift/report
# Harness Coding v2.0.0

set -euo pipefail

TRACE_DIR=".harness/trace"
mkdir -p "$TRACE_DIR"

usage() {
    echo "Usage: spec-trace.sh <command> [args]"
    echo "  generate <spec_file> <diff_file>  生成追溯矩阵"
    echo "  drift <spec_file>                 检测代码漂移"
    echo "  report <spec_file>                生成覆盖率报告"
    exit 1
}

cmd_generate() {
    local spec_file="$1"
    local diff_file="$2"

    if [[ ! -f "$spec_file" ]]; then
        echo "{\"ok\":false,\"error\":\"spec_not_found\"}" >&2
        exit 1
    fi
    if [[ ! -f "$diff_file" ]]; then
        echo "{\"ok\":false,\"error\":\"diff_not_found\"}" >&2
        exit 1
    fi

    local trace_file="$TRACE_DIR/trace-$(date +%Y%m%d%H%M%S).json"

    python3 -c "
import json, re, sys

spec_file = '$spec_file'
diff_file = '$diff_file'

# 解析 Spec 中的需求项
with open(spec_file, 'r', encoding='utf-8', errors='ignore') as f:
    spec_content = f.read()

# 提取需求编号和描述
requirements = []
# 匹配 ### N. 或 - **Req-N**: 等模式
for m in re.finditer(r'###\s+(\d+)\.\s+(.+?)$', spec_content, re.MULTILINE):
    requirements.append({'req_id': f'R-{m.group(1)}', 'title': m.group(2).strip()})
for m in re.finditer(r'Req-(\d+):\s*(.+?)$', spec_content, re.MULTILINE):
    requirements.append({'req_id': f'Req-{m.group(1)}', 'title': m.group(2).strip()})

# 解析 diff 中的变更文件
with open(diff_file, 'r', encoding='utf-8', errors='ignore') as f:
    diff_content = f.read()

changed_files = []
for m in re.finditer(r'^\+\+\+ b/(.+)$', diff_content, re.MULTILINE):
    changed_files.append(m.group(1))

# 构建追溯矩阵
matrix = []
for req in requirements:
    # 简单关键词匹配
    keywords = req['title'].lower().split()[:3]
    matched_files = []
    for cf in changed_files:
        cf_lower = cf.lower()
        if any(kw in cf_lower for kw in keywords if len(kw) > 2):
            matched_files.append(cf)
    matrix.append({
        'req_id': req['req_id'],
        'title': req['title'],
        'status': 'covered' if matched_files else 'uncovered',
        'files': matched_files
    })

covered = sum(1 for m in matrix if m['status'] == 'covered')
total = len(matrix)

result = {
    'ok': True,
    'spec_file': spec_file,
    'total_requirements': total,
    'covered': covered,
    'coverage_pct': round(covered / total * 100, 1) if total > 0 else 0,
    'changed_files': changed_files,
    'matrix': matrix
}
print(json.dumps(result, ensure_ascii=False, indent=2))
"

    echo "$trace_file"
}

cmd_drift() {
    local spec_file="$1"

    if [[ ! -f "$spec_file" ]]; then
        echo "{\"ok\":false,\"error\":\"spec_not_found\"}" >&2
        exit 1
    fi

    # 检查最近的追溯文件
    local latest_trace
    latest_trace=$(ls -t "$TRACE_DIR"/trace-*.json 2>/dev/null | head -1)

    if [[ -z "$latest_trace" ]]; then
        echo "{\"ok\":false,\"error\":\"no_trace_found\",\"message\":\"run generate first\"}" >&2
        exit 1
    fi

    python3 -c "
import json

with open('$latest_trace') as f:
    trace = json.load(f)

# 检查 drift：uncovered 需求
uncovered = [m for m in trace.get('matrix', []) if m['status'] == 'uncovered']
drifted = len(uncovered) > 0

result = {
    'ok': True,
    'has_drift': drifted,
    'uncovered_count': len(uncovered),
    'uncovered_requirements': [m['req_id'] + ': ' + m['title'] for m in uncovered],
    'coverage_pct': trace.get('coverage_pct', 0)
}
print(json.dumps(result, ensure_ascii=False, indent=2))
"
}

cmd_report() {
    local spec_file="$1"

    if [[ ! -f "$spec_file" ]]; then
        echo "{\"ok\":false,\"error\":\"spec_not_found\"}" >&2
        exit 1
    fi

    local latest_trace
    latest_trace=$(ls -t "$TRACE_DIR"/trace-*.json 2>/dev/null | head -1)

    if [[ -z "$latest_trace" ]]; then
        echo "{\"ok\":false,\"error\":\"no_trace_found\"}" >&2
        exit 1
    fi

    python3 -c "
import json

with open('$latest_trace') as f:
    trace = json.load(f)

matrix = trace.get('matrix', [])
total = len(matrix)
covered = sum(1 for m in matrix if m['status'] == 'covered')

# 生成 Markdown 报告
lines = ['# Spec-Code 追溯报告', '']
lines.append(f'覆盖率: {covered}/{total} ({trace.get(\"coverage_pct\", 0)}%)')
lines.append('')
lines.append('| 需求 | 标题 | 状态 | 文件 |')
lines.append('|------|------|------|------|')
for m in matrix:
    status = '✅' if m['status'] == 'covered' else '❌'
    files = ', '.join(m.get('files', [])) or '-'
    lines.append(f'| {m[\"req_id\"]} | {m[\"title\"][:30]} | {status} | {files} |')

report = '\n'.join(lines)
print(report)
"
}

# 主入口
[[ $# -lt 1 ]] && usage

case "$1" in
    generate)
        [[ $# -lt 3 ]] && { echo "Usage: spec-trace.sh generate <spec_file> <diff_file>"; exit 1; }
        cmd_generate "$2" "$3"
        ;;
    drift)
        [[ $# -lt 2 ]] && { echo "Usage: spec-trace.sh drift <spec_file>"; exit 1; }
        cmd_drift "$2"
        ;;
    report)
        [[ $# -lt 2 ]] && { echo "Usage: spec-trace.sh report <spec_file>"; exit 1; }
        cmd_report "$2"
        ;;
    *)
        usage
        ;;
esac
