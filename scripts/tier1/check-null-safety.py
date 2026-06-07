#!/usr/bin/env python3
"""Tier 1: 空指针风险检测 — 检测未检查 null 的链式调用"""

import json
import os
import re
import sys

# 空指针风险模式
PATTERNS = [
    # 链式调用未判空
    (r'\.\w+\(\)\.\w+\(\)\.\w+\(\)', '三层链式调用，中间可能 NPE', 'MEDIUM'),
    # 直接调用可能为 null 的返回值
    (r'(?:get\w+|find\w+|query\w+)\(\)\.\w+\(', '查询结果直接链式调用，未判空', 'MEDIUM'),
    # 集合操作未判空
    (r'(?:getList|findAll|queryList)\(\)\.(?:stream|forEach|size|get)', '集合结果直接操作，未判空', 'MEDIUM'),
    # 字符串操作未判空
    (r'(?:getString|getMessage|getMsg)\(\)\.(?:equals|length|substring|trim)', '字符串结果直接操作，未判空', 'MEDIUM'),
]


def scan_file(filepath):
    findings = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except (IOError, OSError):
        return findings

    for line_num, line in enumerate(lines, 1):
        # 跳过注释行
        stripped = line.strip()
        if stripped.startswith('//') or stripped.startswith('*'):
            continue
        # 跳过已有 null 检查的行
        if 'null' in line.lower() and ('if' in line.lower() or 'optional' in line.lower()):
            continue

        for pattern, desc, severity in PATTERNS:
            if re.search(pattern, line):
                findings.append({
                    'finding_id': f'F-NPE-{len(findings)+1:03d}',
                    'tier': 1,
                    'source': 'check-null-safety.py',
                    'severity': severity,
                    'category': 'null-safety',
                    'file': filepath,
                    'line': line_num,
                    'code': line.strip()[:200],
                    'rule': desc,
                    'fix_suggestion': '添加 null 检查或使用 Optional 包装'
                })
    return findings


def scan_directory(root_dir):
    all_findings = []
    for dirpath, _, filenames in os.walk(root_dir):
        if any(skip in dirpath for skip in ['target', 'build', 'node_modules', '.git']):
            continue
        for filename in filenames:
            if filename.endswith('.java'):
                filepath = os.path.join(dirpath, filename)
                all_findings.extend(scan_file(filepath))
    return all_findings


def main():
    root_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    findings = scan_directory(root_dir)
    passed = not any(f['severity'] in ('CRITICAL', 'HIGH') for f in findings)
    result = {
        'tier': 1,
        'check': 'null-safety',
        'passed': passed,
        'findings_count': len(findings),
        'findings': findings
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
