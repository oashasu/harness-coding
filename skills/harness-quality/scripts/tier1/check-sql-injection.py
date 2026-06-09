#!/usr/bin/env python3
"""Tier 1: SQL 注入检测 — 检测 ${} 字符串拼接 in SQL"""

import json
import os
import re
import sys

# SQL 注入模式
PATTERNS = [
    # MyBatis ${} 注入
    (r'\$\{[^}]+\}', 'MyBatis ${} 参数替换，存在注入风险', 'CRITICAL'),
    # Java 字符串拼接 SQL
    (r'"[^"]*\b(SELECT|INSERT|UPDATE|DELETE)\b[^"]*"\s*\+', 'Java SQL 字符串拼接', 'CRITICAL'),
    (r'\+\s*"[^"]*\b(WHERE|AND|OR|SET|VALUES)\b', 'Java SQL 字符串拼接', 'CRITICAL'),
    # PreparedStatement 字符串拼接
    (r'prepareStatement\s*\([^)]*\+', 'PreparedStatement 字符串拼接', 'HIGH'),
]

# 文件扩展名
JAVA_EXTENSIONS = {'.java', '.kt'}
XML_EXTENSIONS = {'.xml'}


def scan_file(filepath):
    findings = []
    ext = os.path.splitext(filepath)[1]

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except (IOError, OSError):
        return findings

    for line_num, line in enumerate(lines, 1):
        for pattern, desc, severity in PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    'finding_id': f'F-SQL-{len(findings)+1:03d}',
                    'tier': 1,
                    'source': 'check-sql-injection.py',
                    'severity': severity,
                    'category': 'sql-injection',
                    'file': filepath,
                    'line': line_num,
                    'code': line.strip()[:200],
                    'rule': desc,
                    'fix_suggestion': '使用参数化查询（? 占位符）替代字符串拼接'
                })
    return findings


def scan_directory(root_dir):
    all_findings = []
    for dirpath, _, filenames in os.walk(root_dir):
        # 跳过构建目录
        if any(skip in dirpath for skip in ['target', 'build', 'node_modules', '.git']):
            continue
        for filename in filenames:
            ext = os.path.splitext(filename)[1]
            if ext in JAVA_EXTENSIONS or ext in XML_EXTENSIONS:
                filepath = os.path.join(dirpath, filename)
                all_findings.extend(scan_file(filepath))
    return all_findings


def main():
    root_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    findings = scan_directory(root_dir)
    passed = not any(f['severity'] in ('CRITICAL', 'HIGH') for f in findings)
    result = {
        'tier': 1,
        'check': 'sql-injection',
        'passed': passed,
        'findings_count': len(findings),
        'findings': findings
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
