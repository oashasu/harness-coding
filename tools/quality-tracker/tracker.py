#!/usr/bin/env python3
"""质量趋势跟踪器 — 记录、分析、检测退化"""

import json
import os
import sys
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
REPORTS_DIR = os.path.join(os.path.dirname(__file__), 'reports')
HISTORY_FILE = os.path.join(DATA_DIR, 'quality-history.json')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def record(task_id, workflow, scores, passed, domain='', revision_count=0, issues_found=0):
    """记录一次质量评估结果"""
    history = load_history()
    entry = {
        'task_id': task_id,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'workflow': workflow,
        'scores': scores,
        'passed': passed,
        'revision_count': revision_count,
        'issues_found': issues_found,
        'domain': domain,
    }
    history.append(entry)
    save_history(history)

    # 检测退化
    regression = detect_regression(history)
    if regression:
        print(json.dumps({'recorded': True, 'regression_detected': regression}, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({'recorded': True, 'regression_detected': None}, indent=2, ensure_ascii=False))


def detect_regression(history, window=5):
    """检测质量退化（滑动窗口比较）"""
    if len(history) < window * 2:
        return None

    recent = history[-window:]
    baseline = history[-window * 2:-window]

    recent_avg = sum(t['scores'].get('overall', 0) for t in recent) / len(recent)
    baseline_avg = sum(t['scores'].get('overall', 0) for t in baseline) / len(baseline)

    if baseline_avg == 0:
        return None

    if recent_avg < baseline_avg * 0.9:  # 下降超过10%
        return {
            'type': 'regression',
            'severity': 'warning',
            'recent_avg': round(recent_avg, 1),
            'baseline_avg': round(baseline_avg, 1),
            'drop_pct': round((baseline_avg - recent_avg) / baseline_avg * 100, 1),
            'layer_breakdown': analyze_layer_contributions(recent, baseline)
        }
    return None


def analyze_layer_contributions(recent, baseline):
    """分析哪一层贡献了退化"""
    layers = ['tier0_script', 'tier1_rules', 'tier2_metrics', 'tier3_agent']
    contributions = {}
    for layer in layers:
        recent_avg = sum(t['scores'].get(layer, 0) for t in recent) / len(recent)
        baseline_avg = sum(t['scores'].get(layer, 0) for t in baseline) / len(baseline)
        if baseline_avg > 0:
            drop = (baseline_avg - recent_avg) / baseline_avg * 100
            if drop > 5:
                contributions[layer] = {'drop_pct': round(drop, 1)}
    return contributions


def trend_report(month=None):
    """生成月度趋势报告"""
    history = load_history()
    if not history:
        print('No data available')
        return

    if month:
        history = [h for h in history if h['timestamp'][:7] == month]

    if not history:
        print(f'No data for month {month}')
        return

    total = len(history)
    passed = sum(1 for h in history if h.get('passed'))
    avg_overall = sum(h['scores'].get('overall', 0) for h in history) / total

    tier_avgs = {}
    for tier in ['tier0_script', 'tier1_rules', 'tier2_metrics', 'tier3_agent']:
        tier_avgs[tier] = round(sum(h['scores'].get(tier, 0) for h in history) / total, 1)

    report = f"""# 质量趋势报告 {'(' + month + ')' if month else ''}

## 总览
- 评估次数: {total}
- 通过率: {passed}/{total} ({round(passed / total * 100, 1)}%)
- 平均总分: {round(avg_overall, 1)}

## 各 Tier 平均分
| Tier | 平均分 |
|------|--------|
| Tier 0 (脚本) | {tier_avgs['tier0_script']} |
| Tier 1 (规则) | {tier_avgs['tier1_rules']} |
| Tier 2 (度量) | {tier_avgs['tier2_metrics']} |
| Tier 3 (Agent) | {tier_avgs['tier3_agent']} |

## 退化检测
"""
    regression = detect_regression(history)
    if regression:
        report += f"- **检测到退化**: 最近{len(history[-5:])}次平均 {regression['recent_avg']} vs 基线 {regression['baseline_avg']}，下降 {regression['drop_pct']}%\n"
        for layer, info in regression.get('layer_breakdown', {}).items():
            report += f"  - {layer}: 下降 {info['drop_pct']}%\n"
    else:
        report += "- 未检测到退化\n"

    report_file = os.path.join(REPORTS_DIR, f"trend-{(month or datetime.now().strftime('%Y-%m'))}.md")
    with open(report_file, 'w') as f:
        f.write(report)
    print(report)


def main():
    if len(sys.argv) < 2:
        print("Usage: tracker.py {record|trend} [args]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'record':
        if len(sys.argv) < 3:
            print("Usage: tracker.py record '<json>'")
            sys.exit(1)
        data = json.loads(sys.argv[2])
        record(
            data['task_id'],
            data.get('workflow', 'unknown'),
            data.get('scores', {}),
            data.get('passed', False),
            data.get('domain', ''),
            data.get('revision_count', 0),
            data.get('issues_found', 0)
        )

    elif cmd == 'trend':
        month = sys.argv[2] if len(sys.argv) > 2 else None
        trend_report(month)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    main()
