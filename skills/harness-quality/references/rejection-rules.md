# Rejection Rules — 打回规则和修复指导

> 版本: 2.0.0 | 更新: 2026-06-07

## 打回原则

- 每个 Tier 有明确的打回条件
- 打回时必须给出具体错误列表和修复指导
- 修复后重新从失败的 Tier 开始执行

## Tier 0 打回规则

| 打回条件 | 错误类型 | 修复指导 |
|----------|----------|----------|
| 编译失败 | compile_error | 列出所有编译错误，逐一修复 |
| Lint 错误 | lint_error | 列出所有 lint 问题，逐一修复 |
| 越界写入 | write_path_violation | 列出越界文件，删除或移入允许范围 |
| 格式错误 | format_error | 运行格式化工具自动修复 |

### Tier 0 打回输出

```json
{
  "tier": 0,
  "passed": false,
  "rejection": {
    "reason": "compile_error",
    "errors": [
      {"file": "OrderService.java", "line": 45, "message": "cannot find symbol: method getOrder()"},
      {"file": "RefundController.java", "line": 12, "message": "package com.example.new does not exist"}
    ],
    "fix_instructions": "修复上述编译错误后重新执行 Tier 0 检查"
  }
}
```

## Tier 1 打回规则

| 打回条件 | 错误类型 | 修复指导 |
|----------|----------|----------|
| 任一 CRITICAL finding | critical_finding | 立即修复安全问题 |
| 任一 HIGH finding | high_finding | 修复质量问题 |

### Tier 1 打回输出

```json
{
  "tier": 1,
  "passed": false,
  "rejection": {
    "reason": "critical_finding",
    "findings": [
      {
        "finding_id": "F-001",
        "severity": "CRITICAL",
        "category": "sql-injection",
        "file": "OrderMapper.java",
        "line": 47,
        "fix_suggestion": "使用参数化查询: WHERE id = ?"
      }
    ],
    "fix_instructions": "修复所有 CRITICAL 和 HIGH 级别 findings 后重新执行 Tier 1 检查"
  }
}
```

## Tier 2 打回规则

| 打回条件 | 错误类型 | 修复指导 |
|----------|----------|----------|
| 未达标项 > 阈值 | metric_below_threshold | 列出未达标指标和目标值 |

### Tier 2 打回输出

```json
{
  "tier": 2,
  "passed": false,
  "rejection": {
    "reason": "metric_below_threshold",
    "failed_metrics": [
      {"id": "T2-01", "name": "coverage", "actual": 65.3, "threshold": 80, "unit": "%"},
      {"id": "T2-03", "name": "complexity", "actual": 15, "threshold": 10, "unit": "cc"}
    ],
    "fix_instructions": "提高测试覆盖率到 80% 以上，降低圈复杂度到 10 以下"
  }
}
```

## Tier 3 打回规则

| 打回条件 | 错误类型 | 修复指导 |
|----------|----------|----------|
| 任一 Agent verdict = revise | agent_revise | 合并双 Agent findings，按 severity 排序打回 |
| scope_verified 任一项为 false | scope_incomplete | 列出缺失项，补齐后重新审查 |
| 双 Agent 结论矛盾 | verdict_conflict | 升级到人类 Governor |

### Tier 3 打回输出

```json
{
  "tier": 3,
  "passed": false,
  "rejection": {
    "reason": "agent_revise",
    "merged_findings": [
      {
        "finding_id": "F-001",
        "severity": "HIGH",
        "category": "missing-test",
        "claim": "退款接口缺少并发场景测试",
        "evidence": {"file": "RefundService.java", "line": "47-62", "code": "..."},
        "confidence": "high",
        "corroborated_by": "both"
      }
    ],
    "fix_instructions": "按 severity 从高到低修复所有 findings，修复后重新执行 Tier 3 审查"
  }
}
```

## 修复后重新执行规则

| 失败 Tier | 重新执行起点 | 说明 |
|-----------|-------------|------|
| Tier 0 | Tier 0 | 基础门禁，必须全部通过 |
| Tier 1 | Tier 1 | 规则检查独立，无需重跑 Tier 0 |
| Tier 2 | Tier 2 | 度量检查独立，无需重跑 Tier 0-1 |
| Tier 3 | Tier 3 | Agent 审查独立，无需重跑 Tier 0-2 |

**注意**: 如果修复过程中修改了代码，建议重新从 Tier 0 开始执行完整管道。
