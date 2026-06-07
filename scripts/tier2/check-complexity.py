#!/usr/bin/env python3
"""Tier 2: 圈复杂度检查 — 检测高复杂度方法"""

import json
import os
import re
import sys

# 每个分支关键字 +1 复杂度
BRANCH_KEYWORDS = [
    r'\bif\s*\(',
    r'\belse\s+if\s*\(',
    r'\bfor\s*\(',
    r'\bwhile\s*\(',
    r'\bcase\s+',
    r'\bcatch\s*\(',
    r'\b\?\s*',
    r'\b&&\b',
    r'\b\|\|\b',
]

# 方法签名
METHOD_PATTERN = r'(?:public|protected|private|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\{'


def count_complexity(method_body):
    """计算方法的圈复杂度"""
    complexity = 1
    for pattern in BRANCH_KEYWORDS:
        complexity += len(re.findall(pattern, method_body))
    return complexity


def scan_file(filepath, threshold=10):
    findings = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except (IOError, OSError):
        return findings

    methods = list(re.finditer(METHOD_PATTERN, content))

    for i, match in enumerate(methods):
        method_name = match.group(1)
        start_line = content[:match.start()].count('\n') + 1

        # 简单方法体提取：从 { 到匹配的 }
        brace_count = 0
        body_start = content.find('{', match.start())
        if body_start == -1:
            continue
        pos = body_start
        while pos < len(content):
            if content[pos] == '{':
                brace_count += 1
            elif content[pos] == '}':
                brace_count -= 1
                if brace_count == 0:
                    break
            pos += 1
        method_body = content[body_start:pos + 1]

        cc = count_complexity(method_body)

        if cc > threshold:
            findings.append({
                'finding_id': f'F-CC-{len(findings)+1:03d}',
                'tier': 2,
                'source': 'check-complexity.py',
                'severity': 'HIGH' if cc > threshold * 2 else 'MEDIUM',
                'category': 'complexity',
                'file': filepath,
                'line': start_line,
                'code': f'{method_name}() CC={cc}',
                'rule': f'方法 {method_name} 圈复杂度 {cc} 超过阈值 {threshold}',
                'fix_suggestion': '拆分方法、提取子函数、使用策略模式降低复杂度'
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
    threshold = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    findings = scan_directory(root_dir)
    passed = not any(f['severity'] in ('CRITICAL', 'HIGH') for f in findings)
    result = {
        'tier': 2,
        'check': 'complexity',
        'passed': passed,
        'findings_count': len(findings),
        'findings': findings
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
