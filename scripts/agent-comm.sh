#!/bin/bash
# Agent 通信脚本 — 基于文件系统的消息收发
# 用法:
#   agent-comm send --task T-001 --from coding-worker --to test-agent --type review_request --payload '{"key":"val"}'
#   agent-comm inbox --task T-001 --agent test-agent [--unread]
#   agent-comm ack --task T-001 --msg msg-003
#   agent-comm status --task T-001 --agent coding-worker --set '{"state":"implementing"}'

set -euo pipefail

SHARED_DIR="${SHARED_DIR:-shared/tasks}"

cmd_send() {
    local task_id="" from="" to="" msg_type="" payload="{}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --task) task_id="$2"; shift 2 ;;
            --from) from="$2"; shift 2 ;;
            --to) to="$2"; shift 2 ;;
            --type) msg_type="$2"; shift 2 ;;
            --payload) payload="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [[ -z "$task_id" || -z "$from" || -z "$to" || -z "$msg_type" ]]; then
        echo "Error: --task, --from, --to, --type are required" >&2
        exit 1
    fi

    local inbox_dir="$SHARED_DIR/$task_id/inbox"
    mkdir -p "$inbox_dir"

    # 生成消息 ID
    local msg_count=$(find "$inbox_dir" -name "msg-*.json" 2>/dev/null | wc -l)
    local msg_id="msg-$(printf '%03d' $((msg_count + 1)))"

    local msg_file="$inbox_dir/${msg_id}-${msg_type}.json"
    cat > "$msg_file" <<EOF
{
  "msg_id": "$msg_id",
  "msg_type": "$msg_type",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "from_agent": "$from",
  "to_agent": "$to",
  "task_id": "$task_id",
  "correlation_id": "",
  "payload": $payload
}
EOF

    echo "Sent $msg_id to $to inbox: $msg_file"
}

cmd_inbox() {
    local task_id="" agent="" unread=false
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --task) task_id="$2"; shift 2 ;;
            --agent) agent="$2"; shift 2 ;;
            --unread) unread=true; shift ;;
            *) shift ;;
        esac
    done

    if [[ -z "$task_id" || -z "$agent" ]]; then
        echo "Error: --task and --agent are required" >&2
        exit 1
    fi

    local inbox_dir="$SHARED_DIR/$task_id/inbox"
    if [[ ! -d "$inbox_dir" ]]; then
        echo "No inbox for $task_id"
        exit 0
    fi

    for msg_file in "$inbox_dir"/msg-*.json; do
        [[ -f "$msg_file" ]] || continue
        local to_agent=$(python3 -c "import json; print(json.load(open('$msg_file')).get('to_agent',''))" 2>/dev/null)
        if [[ "$to_agent" != "$agent" ]]; then
            continue
        fi
        if [[ "$unread" == "true" ]]; then
            local ack_file="${msg_file%.json}.ack"
            [[ -f "$ack_file" ]] && continue
        fi
        cat "$msg_file"
        echo "---"
    done
}

cmd_ack() {
    local task_id="" msg_id=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --task) task_id="$2"; shift 2 ;;
            --msg) msg_id="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [[ -z "$task_id" || -z "$msg_id" ]]; then
        echo "Error: --task and --msg are required" >&2
        exit 1
    fi

    local inbox_dir="$SHARED_DIR/$task_id/inbox"
    local msg_file=$(find "$inbox_dir" -name "${msg_id}-*.json" 2>/dev/null | head -1)
    if [[ -z "$msg_file" ]]; then
        echo "Message $msg_id not found" >&2
        exit 1
    fi

    touch "${msg_file%.json}.ack"
    echo "Acknowledged $msg_id"
}

cmd_status() {
    local task_id="" agent="" status_data=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --task) task_id="$2"; shift 2 ;;
            --agent) agent="$2"; shift 2 ;;
            --set) status_data="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [[ -z "$task_id" || -z "$agent" ]]; then
        echo "Error: --task and --agent are required" >&2
        exit 1
    fi

    local status_dir="$SHARED_DIR/$task_id/status"
    mkdir -p "$status_dir"
    local status_file="$status_dir/${agent}-status.json"

    if [[ -n "$status_data" ]]; then
        echo "$status_data" | python3 -c "
import json, sys
data = json.load(sys.stdin)
data['agent'] = '$agent'
data['updated'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
" > "$status_file"
        echo "Updated status for $agent"
    else
        [[ -f "$status_file" ]] && cat "$status_file" || echo "No status for $agent"
    fi
}

# 主入口
case "${1:-}" in
    send) shift; cmd_send "$@" ;;
    inbox) shift; cmd_inbox "$@" ;;
    ack) shift; cmd_ack "$@" ;;
    status) shift; cmd_status "$@" ;;
    *)
        echo "Usage: agent-comm {send|inbox|ack|status} [options]"
        echo "  send   --task T --from A --to B --type TYPE [--payload JSON]"
        echo "  inbox  --task T --agent A [--unread]"
        echo "  ack    --task T --msg MSG_ID"
        echo "  status --task T --agent A [--set JSON]"
        exit 1
        ;;
esac
