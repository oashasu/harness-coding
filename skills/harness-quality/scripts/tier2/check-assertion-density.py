#!/usr/bin/env python3
"""Tier 2: 断言密度检查 — 每个测试方法至少 N 个断言"""

import json
import os
import re
import sys

ASSERTION_PATTERNS = [
    r'\bassert\w*\s*\(',
    r'\bverify\w*\s*\(',
    r'\bexpect\w*\s*\(',
    r'\bshould\w*\s*\(',
    r'@Test\b',
]

TEST_METHOD_PATTERN = r'(?:public\s+)?void\s+(test\w+|should\w+|when\w+)\s*\('


def scan_file(filepath):
    findings = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except (IOError, OSError):
        return findings

    # 查找所有测试方法
    methods = list(re.finditer(TEST_METHOD_PATTERN, content))
    if not methods:
        return findings

    lines = content.split('\n')

    for i, match in enumerate(methods):
        method_name = match.group(1)
        start_line = content[:match.start()].count('\n') + 1
        # 方法结束位置：下一个方法或文件末尾
        if i + 1 < len(methods):
            end_pos = methods[i + 1].start()
        else:
            end_pos = len(content)
        method_body = content[match.start():end_pos]

        # 计算断言数
        assertion_count = 0
        for pattern in ASSERTION_PATTERNS:
            assertion_count += len(re.findall(pattern, method_body))

        if assertion_count == 0:
            findings.append({
                'finding_id': f'F-AST-{len(findings)+1:03d}',
                'tier': 2,
                'source': 'check-assertion-density.py',
                'severity': 'MEDIUM',
                'category': 'assertion-density',
                'file': filepath,
                'line': start_line,
                'code': f'void {method_name}()',
                'rule': f'测试方法 {method_name} 无断言',
                'fix_suggestion': '添加 assert/verify 断言验证预期行为'
            })

    return findings


def scan_directory(root_dir):
    all_findings = []
    for dirpath, _, filenames in os.walk(root_dir):
        if any(skip in dirpath for skip in ['target', 'build', 'node_modules', '.git']):
            continue
        for filename in filenames:
            if filename.endswith('Test.java') or filename.endswith('Tests.java') or filename.endswith('Spec.java'):
                filepath = os.path.join(dirpath, filename)
                all_findings.extend(scan_file(filepath))
    return all_findings


def main():
    root_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    findings = scan_directory(root_dir)
    passed = not any(f['severity'] in ('CRITICAL', 'HIGH') for f in findings)
    result = {
        'tier': 2,
        'check': 'assertion-density',
        'passed': passed,
        'findings_count': len(findings),
        'findings': findings
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
