#!/usr/bin/env python3
"""Tier 1: 层违规检测 — 检查 import 方向是否符合分层架构"""

import json
import os
import re
import sys

# Java 分层规则：上层不能被下层引用
# Controller → Service → Repository → Entity
# Controller 不能 import Repository 内部实现
# Service 不能 import Controller
# Repository 不能 import Service

LAYER_PATTERNS = {
    'controller': r'(?:Controller|Resource|Endpoint)\b',
    'service': r'(?:Service|ServiceImpl|UseCase)\b',
    'repository': r'(?:Repository|RepositoryImpl|Dao|Mapper)\b',
    'entity': r'(?:Entity|Model|Domain|DO|DTO|VO)\b',
}

# 违规规则
VIOLATIONS = [
    # Service 不应 import Controller
    (r'import\s+.*\.controller\.', 'service', 'controller', 'Service 层不应引用 Controller 层', 'HIGH'),
    # Repository 不应 import Service
    (r'import\s+.*\.service\.', 'repository', 'service', 'Repository 层不应引用 Service 层', 'HIGH'),
    # Controller 不应直接 import Repository 实现
    (r'import\s+.*\.repository\.impl\.', 'controller', 'repository', 'Controller 不应直接引用 Repository 实现', 'HIGH'),
    # Entity 不应 import Service/Repository
    (r'import\s+.*\.service\.', 'entity', 'service', 'Entity 层不应引用 Service 层', 'HIGH'),
    (r'import\s+.*\.repository\.', 'entity', 'repository', 'Entity 层不应引用 Repository 层', 'HIGH'),
]


def detect_layer(filepath):
    """根据文件路径和类名检测所在层"""
    path_lower = filepath.lower()
    for layer, pattern in LAYER_PATTERNS.items():
        if re.search(pattern, os.path.basename(filepath), re.IGNORECASE):
            return layer
    # 根据目录路径判断
    if '/controller/' in path_lower or '/web/' in path_lower:
        return 'controller'
    if '/service/' in path_lower:
        return 'service'
    if '/repository/' in path_lower or '/dao/' in path_lower or '/mapper/' in path_lower:
        return 'repository'
    if '/entity/' in path_lower or '/model/' in path_lower or '/domain/' in path_lower:
        return 'entity'
    return None


def scan_file(filepath):
    findings = []
    source_layer = detect_layer(filepath)
    if not source_layer:
        return findings

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except (IOError, OSError):
        return findings

    for line_num, line in enumerate(lines, 1):
        for pattern, from_layer, to_layer, desc, severity in VIOLATIONS:
            if from_layer == source_layer and re.search(pattern, line):
                findings.append({
                    'finding_id': f'F-LAY-{len(findings)+1:03d}',
                    'tier': 1,
                    'source': 'check-layer-violation.py',
                    'severity': severity,
                    'category': 'layer-violation',
                    'file': filepath,
                    'line': line_num,
                    'code': line.strip()[:200],
                    'rule': desc,
                    'fix_suggestion': f'通过接口抽象解耦 {from_layer} 层对 {to_layer} 层的直接依赖'
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
        'check': 'layer-violation',
        'passed': passed,
        'findings_count': len(findings),
        'findings': findings
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
