#!/usr/bin/env python3
"""Tier 2: 文件大小检查 — 检测超大文件"""

import json
import os
import sys


def count_lines(filepath):
    """计算文件行数"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return sum(1 for _ in f)
    except (IOError, OSError):
        return 0


def scan_directory(root_dir, warn_threshold=400, max_threshold=800):
    all_findings = []
    for dirpath, _, filenames in os.walk(root_dir):
        if any(skip in dirpath for skip in ['target', 'build', 'node_modules', '.git']):
            continue
        for filename in filenames:
            if not filename.endswith(('.java', '.py', '.ts', '.js')):
                continue
            filepath = os.path.join(dirpath, filename)
            line_count = count_lines(filepath)

            if line_count > max_threshold:
                all_findings.append({
                    'finding_id': f'F-FSZ-{len(all_findings)+1:03d}',
                    'tier': 2,
                    'source': 'check-file-size.py',
                    'severity': 'HIGH',
                    'category': 'file-size',
                    'file': filepath,
                    'line': 0,
                    'code': f'{line_count} lines',
                    'rule': f'文件 {filename} 有 {line_count} 行，超过上限 {max_threshold}',
                    'fix_suggestion': '拆分为多个职责单一的小文件'
                })
            elif line_count > warn_threshold:
                all_findings.append({
                    'finding_id': f'F-FSZ-{len(all_findings)+1:03d}',
                    'tier': 2,
                    'source': 'check-file-size.py',
                    'severity': 'MEDIUM',
                    'category': 'file-size',
                    'file': filepath,
                    'line': 0,
                    'code': f'{line_count} lines',
                    'rule': f'文件 {filename} 有 {line_count} 行，超过警告阈值 {warn_threshold}',
                    'fix_suggestion': '考虑拆分，保持文件在 400 行以内'
                })

    return all_findings


def main():
    root_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    findings = scan_directory(root_dir)
    passed = not any(f['severity'] in ('CRITICAL', 'HIGH') for f in findings)
    result = {
        'tier': 2,
        'check': 'file-size',
        'passed': passed,
        'findings_count': len(findings),
        'findings': findings
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
