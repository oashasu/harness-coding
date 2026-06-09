#!/usr/bin/env python3
"""合并多个 Tier 的质量报告为统一报告"""

import json
import sys


def merge_reports(reports):
    """合并多个报告，生成统一的质量报告"""
    all_findings = []
    tier_results = {}
    overall_passed = True

    for report in reports:
        tier = report.get('tier', 0)
        check = report.get('check', 'unknown')
        passed = report.get('passed', True)
        findings = report.get('findings', [])

        tier_key = f'tier{tier}'
        if tier_key not in tier_results:
            tier_results[tier_key] = {'checks': [], 'all_passed': True}

        tier_results[tier_key]['checks'].append({
            'check': check,
            'passed': passed,
            'findings_count': len(findings)
        })
        if not passed:
            tier_results[tier_key]['all_passed'] = False
            overall_passed = False

        all_findings.extend(findings)

    # 按严重级别排序
    severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}
    all_findings.sort(key=lambda f: severity_order.get(f.get('severity', 'INFO'), 5))

    # 统计
    severity_counts = {}
    for f in all_findings:
        s = f.get('severity', 'INFO')
        severity_counts[s] = severity_counts.get(s, 0) + 1

    return {
        'overall_passed': overall_passed,
        'total_findings': len(all_findings),
        'severity_counts': severity_counts,
        'tier_results': tier_results,
        'findings': all_findings
    }


def main():
    """从 stdin 读取多个 JSON 报告（每行一个），合并输出"""
    reports = []
    for line in sys.stdin:
        line = line.strip()
        if line:
            try:
                reports.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    result = merge_reports(reports)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['overall_passed'] else 1)


if __name__ == '__main__':
    main()
