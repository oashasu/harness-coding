#!/usr/bin/env python3
"""Tier 2: 代码重复检查 — 检测重复代码块"""

import hashlib
import json
import os
import sys


def get_code_blocks(filepath, block_size=6):
    """提取文件中的代码块（连续非空行的哈希）"""
    blocks = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [l.strip() for l in f if l.strip() and not l.strip().startswith('//') and not l.strip().startswith('*')]
    except (IOError, OSError):
        return blocks

    for i in range(len(lines) - block_size + 1):
        block = '\n'.join(lines[i:i + block_size])
        block_hash = hashlib.md5(block.encode()).hexdigest()
        blocks.append({
            'hash': block_hash,
            'start_line': i + 1,
            'block': block
        })
    return blocks


def scan_directory(root_dir):
    """扫描目录，检测跨文件重复"""
    all_findings = []
    # hash -> [(filepath, line, block)]
    hash_map = {}

    for dirpath, _, filenames in os.walk(root_dir):
        if any(skip in dirpath for skip in ['target', 'build', 'node_modules', '.git']):
            continue
        for filename in filenames:
            if not filename.endswith('.java'):
                continue
            filepath = os.path.join(dirpath, filename)
            blocks = get_code_blocks(filepath)
            for b in blocks:
                h = b['hash']
                if h not in hash_map:
                    hash_map[h] = []
                hash_map[h].append({
                    'file': filepath,
                    'line': b['start_line'],
                    'block': b['block'][:200]
                })

    # 找出重复
    seen_hashes = set()
    for h, locations in hash_map.items():
        if len(locations) < 2 or h in seen_hashes:
            continue
        seen_hashes.add(h)
        # 只报告不同文件的重复
        unique_files = set(loc['file'] for loc in locations)
        if len(unique_files) > 1:
            all_findings.append({
                'finding_id': f'F-DUP-{len(all_findings)+1:03d}',
                'tier': 2,
                'source': 'check-duplication.py',
                'severity': 'MEDIUM',
                'category': 'duplication',
                'file': locations[0]['file'],
                'line': locations[0]['line'],
                'code': locations[0]['block'][:200],
                'rule': f'代码块在 {len(unique_files)} 个文件中重复',
                'fix_suggestion': '提取公共方法或工具类消除重复',
                'duplicates': [{'file': loc['file'], 'line': loc['line']} for loc in locations[:5]]
            })

    return all_findings


def main():
    root_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    findings = scan_directory(root_dir)
    passed = not any(f['severity'] in ('CRITICAL', 'HIGH') for f in findings)
    result = {
        'tier': 2,
        'check': 'duplication',
        'passed': passed,
        'findings_count': len(findings),
        'findings': findings
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
