#!/bin/bash
# Worktree 生命周期管理 — create/list/merge/cleanup
# Harness Coding v2.0.0

set -euo pipefail

WORKTREE_DIR=".claude/worktrees"

usage() {
    echo "Usage: worktree-manager.sh <command> [args]"
    echo "  create <branch> [task_id]  创建 worktree"
    echo "  list                       列出活跃 worktree"
    echo "  merge <branch>             合并回主分支"
    echo "  cleanup [branch]           清理已完成的 worktree"
    exit 1
}

cmd_create() {
    local branch="$1"
    local task_id="${2:-unknown}"
    local wt_path="$WORKTREE_DIR/$branch"

    if [[ -d "$wt_path" ]]; then
        echo "{\"ok\":false,\"error\":\"worktree_exists\",\"branch\":\"$branch\"}" >&2
        exit 1
    fi

    mkdir -p "$WORKTREE_DIR"

    # 创建 worktree
    git worktree add "$wt_path" -b "$branch" 2>/dev/null || {
        # 分支已存在时尝试 checkout
        git worktree add "$wt_path" "$branch" 2>/dev/null || {
            echo "{\"ok\":false,\"error\":\"create_failed\",\"branch\":\"$branch\"}" >&2
            exit 1
        }
    }

    # 写入元数据
    cat > "$wt_path/.worktree-meta.json" <<EOF
{
    "branch": "$branch",
    "task_id": "$task_id",
    "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "status": "active"
}
EOF

    echo "{\"ok\":true,\"branch\":\"$branch\",\"path\":\"$wt_path\",\"task_id\":\"$task_id\"}"
}

cmd_list() {
    local worktrees=()

    if [[ ! -d "$WORKTREE_DIR" ]]; then
        echo '{"worktrees":[],"total":0}'
        return
    fi

    # 使用 git worktree list 获取真实状态
    local wt_json
    wt_json=$(git worktree list --porcelain 2>/dev/null | python3 -c "
import sys, json

worktrees = []
current = {}
for line in sys.stdin:
    line = line.strip()
    if line.startswith('worktree '):
        if current:
            worktrees.append(current)
        current = {'path': line.split(' ', 1)[1]}
    elif line.startswith('branch '):
        current['branch'] = line.split(' ', 1)[1].replace('refs/heads/', '')
    elif line == '' and current:
        worktrees.append(current)
        current = {}
if current:
    worktrees.append(current)

# 只返回 .claude/worktrees 下的
filtered = [w for w in worktrees if '.claude/worktrees' in w.get('path', '')]
print(json.dumps({'worktrees': filtered, 'total': len(filtered)}, indent=2))
")

    echo "$wt_json"
}

cmd_merge() {
    local branch="$1"
    local wt_path="$WORKTREE_DIR/$branch"

    if [[ ! -d "$wt_path" ]]; then
        echo "{\"ok\":false,\"error\":\"worktree_not_found\",\"branch\":\"$branch\"}" >&2
        exit 1
    fi

    # 获取当前分支
    local current_branch
    current_branch=$(git rev-parse --abbrev-ref HEAD)

    # 尝试合并
    if git merge "$branch" --no-edit 2>/dev/null; then
        echo "{\"ok\":true,\"merged\":true,\"branch\":\"$branch\",\"target\":\"$current_branch\"}"
    else
        echo "{\"ok\":false,\"error\":\"merge_conflict\",\"branch\":\"$branch\",\"message\":\"resolve conflicts manually\"}" >&2
        exit 1
    fi
}

cmd_cleanup() {
    local branch="${1:-}"

    if [[ -n "$branch" ]]; then
        # 清理指定 worktree
        local wt_path="$WORKTREE_DIR/$branch"
        if [[ ! -d "$wt_path" ]]; then
            echo "{\"ok\":false,\"error\":\"worktree_not_found\",\"branch\":\"$branch\"}" >&2
            exit 1
        fi

        git worktree remove "$wt_path" --force 2>/dev/null || true
        git branch -D "$branch" 2>/dev/null || true
        echo "{\"ok\":true,\"removed\":\"$branch\"}"
    else
        # 清理所有已完成的 worktree
        local removed=0
        for meta in "$WORKTREE_DIR"/*/.worktree-meta.json; do
            [[ -f "$meta" ]] || continue
            local status
            status=$(python3 -c "import json; print(json.load(open('$meta')).get('status','unknown'))" 2>/dev/null || echo "unknown")
            if [[ "$status" == "completed" || "$status" == "done" ]]; then
                local wt_dir
                wt_dir=$(dirname "$meta")
                local wt_branch
                wt_branch=$(basename "$wt_dir")
                git worktree remove "$wt_dir" --force 2>/dev/null || true
                git branch -D "$wt_branch" 2>/dev/null || true
                removed=$((removed + 1))
            fi
        done
        echo "{\"ok\":true,\"removed_count\":$removed}"
    fi
}

# 主入口
[[ $# -lt 1 ]] && usage

case "$1" in
    create)
        [[ $# -lt 2 ]] && { echo "Usage: worktree-manager.sh create <branch> [task_id]"; exit 1; }
        cmd_create "$2" "${3:-}"
        ;;
    list)
        cmd_list
        ;;
    merge)
        [[ $# -lt 2 ]] && { echo "Usage: worktree-manager.sh merge <branch>"; exit 1; }
        cmd_merge "$2"
        ;;
    cleanup)
        cmd_cleanup "${2:-}"
        ;;
    *)
        usage
        ;;
esac
