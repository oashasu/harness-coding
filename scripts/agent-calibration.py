#!/usr/bin/env python3
"""Agent 准确率跟踪和自动降级"""

import json
import os
import sys

CALIBRATION_FILE = '.harness/agent-calibration.json'
DOWNGRADE_THRESHOLD = 0.75


def load_calibration():
    """加载校准数据"""
    if os.path.exists(CALIBRATION_FILE):
        with open(CALIBRATION_FILE) as f:
            return json.load(f)
    return {}


def save_calibration(data):
    """保存校准数据"""
    os.makedirs(os.path.dirname(CALIBRATION_FILE), exist_ok=True)
    with open(CALIBRATION_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def record_review(agent, verdict, was_correct):
    """记录一次审查结果"""
    cal = load_calibration()
    if agent not in cal:
        cal[agent] = {
            'total_reviews': 0,
            'correct_reviews': 0,
            'accuracy': 1.0,
            'status': 'active',
            'history': []
        }

    entry = cal[agent]
    entry['total_reviews'] += 1
    if was_correct:
        entry['correct_reviews'] += 1
    entry['accuracy'] = round(entry['correct_reviews'] / entry['total_reviews'], 3)

    entry['history'].append({
        'verdict': verdict,
        'correct': was_correct
    })
    # 保留最近 20 条
    entry['history'] = entry['history'][-20:]

    # 自动降级检查
    if entry['accuracy'] < DOWNGRADE_THRESHOLD and entry['total_reviews'] >= 5:
        entry['status'] = 'degraded'
        print(f"WARNING: {agent} accuracy {entry['accuracy']} < {DOWNGRADE_THRESHOLD}, degraded to Governor", file=sys.stderr)
    else:
        entry['status'] = 'active'

    save_calibration(cal)
    return entry


def check_status(agent):
    """检查 Agent 状态"""
    cal = load_calibration()
    if agent not in cal:
        return {'agent': agent, 'status': 'active', 'accuracy': 1.0, 'total_reviews': 0}
    entry = cal[agent]
    return {
        'agent': agent,
        'status': entry.get('status', 'active'),
        'accuracy': entry.get('accuracy', 1.0),
        'total_reviews': entry.get('total_reviews', 0)
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: agent-calibration.py {record|check} [args]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'record':
        if len(sys.argv) < 5:
            print("Usage: agent-calibration.py record <agent> <verdict> <correct:true|false>")
            sys.exit(1)
        agent = sys.argv[2]
        verdict = sys.argv[3]
        correct = sys.argv[4].lower() == 'true'
        result = record_review(agent, verdict, correct)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == 'check':
        if len(sys.argv) < 3:
            print("Usage: agent-calibration.py check <agent>")
            sys.exit(1)
        result = check_status(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result['status'] == 'active' else 1)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    main()
