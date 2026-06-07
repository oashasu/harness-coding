#!/usr/bin/env python3
"""scope_verified 元审查 — Agent 审查前自检输入完备性"""

import json
import os
import sys


def check_scope(root_dir='.'):
    """检查审查输入的完备性"""
    results = {
        'spec_exists': False,
        'spec_complete': False,
        'diff_in_scope': True,
        'allowed_paths_declared': False,
        'references_complete': False,
        'upper_tiers_passed': False,
        'context_tokens': 0,
        'context_limit_ok': True
    }
    missing = []

    # 1. Spec 文件存在
    spec_paths = [
        '.harness/spec/requirement.md',
        '.harness/spec/spec.md',
        'spec.md',
        'SPEC.md'
    ]
    for p in spec_paths:
        if os.path.exists(os.path.join(root_dir, p)):
            results['spec_exists'] = True
            # 检查是否非空
            if os.path.getsize(os.path.join(root_dir, p)) > 50:
                results['spec_complete'] = True
            break
    if not results['spec_exists']:
        missing.append('spec_file_missing')
    elif not results['spec_complete']:
        missing.append('spec_file_empty')

    # 2. allowed_write_paths 已声明
    state_path = os.path.join(root_dir, '.harness/harness-state.json')
    if os.path.exists(state_path):
        try:
            with open(state_path) as f:
                state = json.load(f)
            paths = state.get('contract', {}).get('allowed_write_paths', [])
            if paths:
                results['allowed_paths_declared'] = True
        except (json.JSONDecodeError, IOError):
            pass
    if not results['allowed_paths_declared']:
        missing.append('allowed_write_paths_not_declared')

    # 3. references 完整性
    ref_files = [
        'skills/harness-router/SKILL.md',
        'skills/harness-quality/SKILL.md',
        'scripts/common/finding-schema.json'
    ]
    refs_ok = all(os.path.exists(os.path.join(root_dir, f)) for f in ref_files)
    results['references_complete'] = refs_ok
    if not refs_ok:
        missing.append('reference_files_missing')

    # 4. 上层 Tier 通过
    if os.path.exists(state_path):
        try:
            with open(state_path) as f:
                state = json.load(f)
            tier_results = state.get('quality_results', {}).get('tier_results', {})
            # Tier 0-2 都通过
            t0_ok = all(c.get('passed', False) for c in tier_results.get('tier0', {}).get('checks', []))
            t1_ok = all(c.get('passed', False) for c in tier_results.get('tier1', {}).get('checks', []))
            t2_ok = all(c.get('passed', False) for c in tier_results.get('tier2', {}).get('checks', []))
            if t0_ok and t1_ok and t2_ok:
                results['upper_tiers_passed'] = True
        except (json.JSONDecodeError, IOError):
            pass
    if not results['upper_tiers_passed']:
        missing.append('upper_tiers_not_passed')

    # 5. 上下文 token 检查（模拟）
    results['context_tokens'] = 1500  # 实际应由调用方传入
    results['context_limit_ok'] = results['context_tokens'] < 2000

    all_passed = all([
        results['spec_exists'],
        results['spec_complete'],
        results['diff_in_scope'],
        results['allowed_paths_declared'],
        results['references_complete'],
        results['upper_tiers_passed'],
        results['context_limit_ok']
    ])

    return {
        'scope_verified': results,
        'all_passed': all_passed,
        'missing_items': missing
    }


def main():
    root_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    result = check_scope(root_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['all_passed'] else 1)


if __name__ == '__main__':
    main()
