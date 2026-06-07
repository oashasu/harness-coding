#!/usr/bin/env python3
"""证据校验 — 验证 Agent findings 的 evidence 是否有效"""

import json
import os
import sys


def validate_evidence(finding):
    """校验单个 finding 的证据"""
    evidence = finding.get('evidence')
    if not evidence:
        return {
            'valid': False,
            'reason': 'missing_evidence',
            'action': 'discard'
        }

    file_path = evidence.get('file', '')
    line_start = evidence.get('line_start', 0)
    line_end = evidence.get('line_end', 0)
    code = evidence.get('code', '')

    # 1. 文件存在性
    if not file_path or not os.path.exists(file_path):
        return {
            'valid': False,
            'reason': f'file_not_found: {file_path}',
            'action': 'discard'
        }

    # 2. 行号范围校验
    if line_start <= 0:
        return {
            'valid': False,
            'reason': 'invalid_line_number',
            'action': 'discard'
        }

    # 3. 代码片段匹配
    if code:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            if line_start <= len(lines):
                actual_line = lines[line_start - 1].strip()
                # 宽松匹配：evidence code 是 actual line 的子串
                if code.strip() in actual_line or actual_line in code.strip():
                    return {'valid': True, 'reason': 'evidence_matches', 'action': 'keep'}
                else:
                    return {
                        'valid': False,
                        'reason': 'code_mismatch',
                        'action': 'flag_for_review'
                    }
        except (IOError, OSError):
            pass

    # 4. 文件存在但代码未验证（仍然有效）
    return {'valid': True, 'reason': 'file_exists_code_unverified', 'action': 'keep'}


def validate_findings(findings):
    """校验所有 findings 的证据"""
    results = []
    kept = []
    discarded = []

    for f in findings:
        ev_result = validate_evidence(f)
        entry = {
            'finding_id': f.get('finding_id', 'unknown'),
            'evidence_valid': ev_result['valid'],
            'reason': ev_result['reason'],
            'action': ev_result['action']
        }
        results.append(entry)
        if ev_result['action'] == 'keep':
            kept.append(f)
        else:
            discarded.append(f)

    return {
        'total': len(findings),
        'kept': len(kept),
        'discarded': len(discarded),
        'details': results,
        'valid_findings': kept
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: evidence-validator.py <findings.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    findings = data.get('findings', [])
    result = validate_findings(findings)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['discarded'] == 0 else 1)


if __name__ == '__main__':
    main()
