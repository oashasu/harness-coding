#!/usr/bin/env python3
"""Tier 2: 测试覆盖率检查 — 解析 JaCoCo/cobertura 报告"""

import json
import os
import sys
import xml.etree.ElementTree as ET


def parse_jacoco(report_path):
    """解析 JaCoCo XML 报告"""
    try:
        tree = ET.parse(report_path)
        root = tree.getroot()
        counters = {}
        for counter in root.findall('.//counter'):
            ctype = counter.get('type')
            missed = int(counter.get('missed', 0))
            covered = int(counter.get('covered', 0))
            total = missed + covered
            if total > 0:
                counters[ctype] = {
                    'missed': missed,
                    'covered': covered,
                    'ratio': round(covered / total * 100, 2)
                }
        return counters
    except (ET.ParseError, IOError):
        return {}


def parse_cobertura(report_path):
    """解析 cobertura XML 报告"""
    try:
        tree = ET.parse(report_path)
        root = tree.getroot()
        line_rate = float(root.get('line-rate', 0)) * 100
        branch_rate = float(root.get('branch-rate', 0)) * 100
        return {
            'LINE': {'ratio': round(line_rate, 2)},
            'BRANCH': {'ratio': round(branch_rate, 2)}
        }
    except (ET.ParseError, IOError):
        return {}


def find_report(root_dir):
    """查找覆盖率报告"""
    candidates = [
        'target/site/jacoco/jacoco.xml',
        'build/reports/jacoco/test/jacocoTestReport.xml',
        'coverage/cobertura-coverage.xml',
        'target/site/cobertura/coverage.xml',
    ]
    for c in candidates:
        path = os.path.join(root_dir, c)
        if os.path.exists(path):
            return path, 'jacoco' if 'jacoco' in c else 'cobertura'
    return None, None


def main():
    root_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 80.0

    report_path, report_type = find_report(root_dir)
    findings = []

    if not report_path:
        findings.append({
            'finding_id': 'F-COV-001',
            'tier': 2,
            'source': 'check-coverage.py',
            'severity': 'HIGH',
            'category': 'coverage',
            'file': root_dir,
            'line': 0,
            'code': '',
            'rule': '未找到覆盖率报告（JaCoCo/cobertura）',
            'fix_suggestion': '运行 mvn test jacoco:report 生成覆盖率报告'
        })
    else:
        if report_type == 'jacoco':
            counters = parse_jacoco(report_path)
        else:
            counters = parse_cobertura(report_path)

        line_cov = counters.get('LINE', {}).get('ratio', 0)
        branch_cov = counters.get('BRANCH', {}).get('ratio', 0)

        if line_cov < threshold:
            findings.append({
                'finding_id': 'F-COV-002',
                'tier': 2,
                'source': 'check-coverage.py',
                'severity': 'HIGH',
                'category': 'coverage',
                'file': report_path,
                'line': 0,
                'code': f'line_coverage={line_cov}%',
                'rule': f'行覆盖率 {line_cov}% 低于阈值 {threshold}%',
                'fix_suggestion': '增加单元测试覆盖未测试的代码路径'
            })

        if branch_cov < threshold:
            findings.append({
                'finding_id': 'F-COV-003',
                'tier': 2,
                'source': 'check-coverage.py',
                'severity': 'MEDIUM',
                'category': 'coverage',
                'file': report_path,
                'line': 0,
                'code': f'branch_coverage={branch_cov}%',
                'rule': f'分支覆盖率 {branch_cov}% 低于阈值 {threshold}%',
                'fix_suggestion': '增加条件分支的测试用例'
            })

    passed = not any(f['severity'] in ('CRITICAL', 'HIGH') for f in findings)
    result = {
        'tier': 2,
        'check': 'coverage',
        'passed': passed,
        'findings_count': len(findings),
        'findings': findings
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
