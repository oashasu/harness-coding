#!/usr/bin/env python3
"""Tier 1: 硬编码检测 — 检测敏感信息硬编码"""

import json
import os
import re
import sys

# 硬编码模式
PATTERNS = [
    # API Key / Token
    (r'(?:api[_-]?key|apikey|token|secret)\s*[=:]\s*["\'][A-Za-z0-9+/=]{16,}["\']', '硬编码 API Key/Token', 'CRITICAL'),
    # 密码
    (r'(?:password|passwd|pwd)\s*[=:]\s*["\'][^"\']{6,}["\']', '硬编码密码', 'CRITICAL'),
    # AWS 密钥
    (r'AKIA[0-9A-Z]{16}', 'AWS Access Key', 'CRITICAL'),
    # JWT Secret
    (r'(?:jwt[_-]?secret|signing[_-]?key)\s*[=:]\s*["\'][^"\']{8,}["\']', '硬编码 JWT Secret', 'CRITICAL'),
    # 数据库连接串
    (r'jdbc:[a-z]+://[^"\']+\?[^"\']*password=[^&"\']+', '数据库连接串含密码', 'CRITICAL'),
    # IP 地址（非 localhost）
    (r'\b(?:10|172\.(?:1[6-9]|2[0-9]|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b', '内网 IP 地址硬编码', 'MEDIUM'),
    # 端口号硬编码
    (r'(?:port|PORT)\s*[=:]\s*\d{4,5}', '端口号硬编码', 'LOW'),
]

# 排除模式（误报过滤）
EXCLUDE_PATTERNS = [
    r'example\.com',
    r'localhost',
    r'127\.0\.0\.1',
    r'test[_-]?key',
    r'dummy',
    r'placeholder',
    r'xxx+',
    r'your[_-]?',
    r'<[^>]+>',  # 模板占位符
]


def is_excluded(line):
    """检查是否为误报"""
    return any(re.search(p, line, re.IGNORECASE) for p in EXCLUDE_PATTERNS)


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
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('#'):
            continue
        if is_excluded(line):
            continue

        for pattern, desc, severity in PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    'finding_id': f'F-HC-{len(findings)+1:03d}',
                    'tier': 1,
                    'source': 'check-hardcoded.py',
                    'severity': severity,
                    'category': 'hardcoded',
                    'file': filepath,
                    'line': line_num,
                    'code': line.strip()[:200],
                    'rule': desc,
                    'fix_suggestion': '使用环境变量或密钥管理器替代硬编码'
                })
    return findings


def scan_directory(root_dir):
    all_findings = []
    for dirpath, _, filenames in os.walk(root_dir):
        if any(skip in dirpath for skip in ['target', 'build', 'node_modules', '.git']):
            continue
        for filename in filenames:
            ext = os.path.splitext(filename)[1]
            if ext in {'.java', '.kt', '.py', '.ts', '.js', '.yml', '.yaml', '.properties', '.xml'}:
                filepath = os.path.join(dirpath, filename)
                all_findings.extend(scan_file(filepath))
    return all_findings


def main():
    root_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    findings = scan_directory(root_dir)
    passed = not any(f['severity'] in ('CRITICAL', 'HIGH') for f in findings)
    result = {
        'tier': 1,
        'check': 'hardcoded',
        'passed': passed,
        'findings_count': len(findings),
        'findings': findings
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
