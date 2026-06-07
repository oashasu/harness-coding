#!/usr/bin/env python3
"""Tier 1: 金额计算检查 — 检测 double 用于金额计算"""

import json
import os
import re
import sys

# 金额相关关键词
AMOUNT_KEYWORDS = [
    'amount', 'price', 'cost', 'fee', 'total', 'money',
    'balance', 'payment', 'refund', 'discount', 'tax',
    '金额', '价格', '费用', '余额', '退款'
]

# double 用于金额的模式
PATTERNS = [
    (r'\bdouble\b\s+\w*(?:amount|price|cost|fee|total|money|balance)\w*', 'double 声明金额变量', 'HIGH'),
    (r'\bfloat\b\s+\w*(?:amount|price|cost|fee|total|money|balance)\w*', 'float 声明金额变量', 'HIGH'),
    (r'new\s+Double\s*\(.*(?:amount|price|cost|fee|total)', 'Double 对象包装金额', 'HIGH'),
    (r'(?:amount|price|cost|fee|total|money|balance)\w*\s*=\s*\d+\.\d+', '金额变量直接赋值浮点数', 'MEDIUM'),
]


def is_amount_context(line, filename):
    """检查是否在金额上下文中"""
    line_lower = line.lower()
    filename_lower = filename.lower()
    return any(kw in line_lower or kw in filename_lower for kw in AMOUNT_KEYWORDS)


def scan_file(filepath):
    findings = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except (IOError, OSError):
        return findings

    for line_num, line in enumerate(lines, 1):
        if not is_amount_context(line, filepath):
            continue
        for pattern, desc, severity in PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    'finding_id': f'F-AMT-{len(findings)+1:03d}',
                    'tier': 1,
                    'source': 'check-bigdecimal.py',
                    'severity': severity,
                    'category': 'bigdecimal',
                    'file': filepath,
                    'line': line_num,
                    'code': line.strip()[:200],
                    'rule': desc,
                    'fix_suggestion': '使用 BigDecimal 替代 double/float 进行金额计算'
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
        'check': 'bigdecimal',
        'passed': passed,
        'findings_count': len(findings),
        'findings': findings
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
