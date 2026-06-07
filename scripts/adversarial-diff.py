#!/usr/bin/env python3
"""对抗差异分析 — 交叉比对双 Agent 的 findings，检测冲突"""

import json
import sys


def analyze_diff(test_findings, arch_findings):
    """分析两个 Agent 的 findings 差异"""
    # 按 file:line 建立索引
    test_index = {}
    for f in test_findings:
        key = f"{f.get('file', '')}:{f.get('line', 0)}"
        test_index[key] = f

    arch_index = {}
    for f in arch_findings:
        key = f"{f.get('file', '')}:{f.get('line', 0)}"
        arch_index[key] = f

    # 分类
    both_found = []      # 两者都发现 → 高置信度
    only_test = []       # 只 test-agent 发现 → 低置信度
    only_arch = []       # 只 arch-agent 发现 → 低置信度
    conflicts = []       # 结论矛盾 → 升级

    all_keys = set(test_index.keys()) | set(arch_index.keys())

    for key in all_keys:
        in_test = key in test_index
        in_arch = key in arch_index

        if in_test and in_arch:
            # 两者都发现
            test_f = test_index[key]
            arch_f = arch_index[key]
            # 检查是否矛盾（一个说 approve，一个说 revise）
            both_found.append({
                'file': key.split(':')[0],
                'line': int(key.split(':')[1]) if key.split(':')[1].isdigit() else 0,
                'confidence': 'high',
                'test_finding': test_f,
                'arch_finding': arch_f
            })
        elif in_test:
            only_test.append({
                **test_index[key],
                'confidence': 'low',
                'source_agent': 'test-agent'
            })
        else:
            only_arch.append({
                **arch_index[key],
                'confidence': 'low',
                'source_agent': 'arch-agent'
            })

    # 判断整体结论
    has_conflicts = len(conflicts) > 0
    has_escalation = any(
        f.get('verdict') == 'escalate'
        for f in test_findings + arch_findings
    )

    if has_conflicts:
        action = 'escalate_to_governor'
    elif has_escalation:
        action = 'escalate_to_governor'
    elif both_found:
        action = 'reject_high_confidence'
    elif only_test or only_arch:
        action = 'flag_low_confidence'
    else:
        action = 'approve'

    return {
        'action': action,
        'high_confidence': both_found,
        'low_confidence': only_test + only_arch,
        'conflicts': conflicts,
        'summary': {
            'total_high': len(both_found),
            'total_low': len(only_test) + len(only_arch),
            'total_conflicts': len(conflicts),
            'escalation': has_escalation
        }
    }


def main():
    """从文件读取两个 Agent 的 findings 进行分析"""
    if len(sys.argv) < 3:
        print("Usage: adversarial-diff.py <test-findings.json> <arch-findings.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        test_data = json.load(f)
    with open(sys.argv[2]) as f:
        arch_data = json.load(f)

    test_findings = test_data.get('findings', [])
    arch_findings = arch_data.get('findings', [])

    result = analyze_diff(test_findings, arch_findings)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
