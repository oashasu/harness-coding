# Quality Tiers — 5-Tier 质量管道定义

> 版本: 2.0.0 | 更新: 2026-06-07

## 设计原则

**脚本做确定性检查，Agent 做语义判断。**

- Tier 0-2: 脚本执行，100% 确定性，结果可复现
- Tier 3-4: Agent 执行，语义判断，需要领域知识

## Tier 0: 脚本硬门禁

**特性**: 100% 确定，不可绕过。失败立即打回。

### 检查项

| ID | 检查项 | 脚本 | 输入 | 输出 |
|----|--------|------|------|------|
| T0-01 | 编译检查 | `check-compile.sh` | 项目根目录 | 编译成功/失败 + 错误列表 |
| T0-02 | Lint 检查 | `check-lint.sh` | 变更文件列表 | lint 通过/失败 + 问题列表 |
| T0-03 | 写入范围校验 | `check-write-paths.sh` | git diff + allowed_paths | 合规/越界 + 越界文件列表 |
| T0-04 | 格式规范检查 | `check-format.sh` | 变更文件列表 | 格式正确/错误 + 问题列表 |

### 执行规则

- 所有检查并行执行
- 任一检查失败 → 立即打回，不进入 Tier 1
- 输出结构化 JSON 结果

### 输出格式

```json
{
  "tier": 0,
  "passed": true,
  "checks": [
    {"id": "T0-01", "name": "compile", "passed": true, "duration_ms": 5000},
    {"id": "T0-02", "name": "lint", "passed": true, "duration_ms": 2000},
    {"id": "T0-03", "name": "write-paths", "passed": true, "duration_ms": 500},
    {"id": "T0-04", "name": "format", "passed": true, "duration_ms": 1000}
  ],
  "failures": []
}
```

## Tier 1: 规则脚本检查

**特性**: 确定性 pattern matching，每条规则独立执行。

### 检查项

| ID | 检查项 | 脚本 | 检测目标 | 严重级别 |
|----|--------|------|----------|----------|
| T1-01 | SQL 注入检测 | `check-sql-injection.py` | `${}` 字符串拼接 in SQL | CRITICAL |
| T1-02 | 金额计算检查 | `check-bigdecimal.py` | double 用于金额计算 | HIGH |
| T1-03 | 层违规检测 | `check-layer-violation.py` | import 方向违规 | HIGH |
| T1-04 | 硬编码检测 | `check-hardcoded.py` | 敏感信息硬编码 | CRITICAL |
| T1-05 | 空指针风险 | `check-null-safety.py` | 未检查 null 的链式调用 | MEDIUM |

### 执行规则

- 所有检查并行执行
- 每条检查输出独立的 findings 列表
- CRITICAL finding → 立即打回
- HIGH finding → 立即打回
- 仅 MEDIUM/LOW findings → 记录但不打回

### 输出格式

```json
{
  "tier": 1,
  "passed": false,
  "checks": [
    {"id": "T1-01", "name": "sql-injection", "passed": false, "findings_count": 1},
    {"id": "T1-02", "name": "bigdecimal", "passed": true, "findings_count": 0},
    {"id": "T1-03", "name": "layer-violation", "passed": true, "findings_count": 0},
    {"id": "T1-04", "name": "hardcoded", "passed": true, "findings_count": 0},
    {"id": "T1-05", "name": "null-safety", "passed": true, "findings_count": 0}
  ],
  "findings": [
    {
      "finding_id": "F-001",
      "tier": 1,
      "source": "check-sql-injection.py",
      "severity": "CRITICAL",
      "category": "sql-injection",
      "file": "OrderMapper.java",
      "line": 47,
      "code": "String sql = \"SELECT * FROM orders WHERE id = \" + orderId;",
      "rule": "SQL字符串拼接，存在注入风险",
      "fix_suggestion": "使用参数化查询: WHERE id = ?"
    }
  ]
}
```

## Tier 2: 度量脚本检查

**特性**: 数值对比 + 阈值判定。

### 检查项

| ID | 检查项 | 脚本 | 阈值 | 度量方式 |
|----|--------|------|------|----------|
| T2-01 | 测试覆盖率 | `check-coverage.py` | line >= 80% | jacoco report 解析 |
| T2-02 | 断言密度 | `check-assertion-density.py` | >= 1.0 | assertions / test_methods |
| T2-03 | 圈复杂度 | `check-complexity.py` | CC <= 10 | 方法级计算 |
| T2-04 | 文件大小 | `check-file-size.py` | 文件 <= 800 行, 方法 <= 50 行 | 行数统计 |
| T2-05 | 代码重复率 | `check-duplication.py` | <= 5% | CPD 检测 |

### 执行规则

- 所有检查并行执行
- 未达标项数 > 阈值 → 打回
- 输出每个指标的实际值和阈值

### 输出格式

```json
{
  "tier": 2,
  "passed": true,
  "checks": [
    {"id": "T2-01", "name": "coverage", "actual": 85.2, "threshold": 80, "unit": "%", "passed": true},
    {"id": "T2-02", "name": "assertion-density", "actual": 1.5, "threshold": 1.0, "unit": "ratio", "passed": true},
    {"id": "T2-03", "name": "complexity", "actual": 7, "threshold": 10, "unit": "cc", "passed": true},
    {"id": "T2-04", "name": "file-size", "actual": 450, "threshold": 800, "unit": "lines", "passed": true},
    {"id": "T2-05", "name": "duplication", "actual": 3.2, "threshold": 5.0, "unit": "%", "passed": true}
  ],
  "findings": []
}
```

## Tier 3: Agent 软审查

**特性**: 语义判断，需要领域知识。仅在 riper-one 和 super-dev 模式下执行。

### 执行流程

1. **scope_verified 元审查**: Agent 审查前自检输入完备性
2. **双 Agent 对抗审查**:
   - test-agent: 功能覆盖 + 边界用例 + 回归风险
   - arch-agent: 架构合规 + 命名规范 + 依赖方向
3. **差异分析**: 交叉比对 findings
4. **证据锚定**: 每个 finding 必须有 file/line/code 证据

### scope_verified 检查项

```json
{
  "scope_verified": {
    "spec_exists": true,
    "spec_complete": true,
    "diff_in_scope": true,
    "allowed_paths_declared": true,
    "references_complete": true,
    "upper_tiers_passed": true,
    "context_tokens": 1850,
    "context_limit_ok": true
  },
  "all_passed": true,
  "missing_items": []
}
```

### 证据锚定规则

| 规则 | 处理 |
|------|------|
| finding 无 evidence 字段 | 直接丢弃，不进入合并 |
| evidence.file 不存在 | 标记为 stale finding |
| evidence.line 范围与实际代码不符 | 标记为 low-confidence |
| claim 与 evidence 逻辑不相关 | 标记为 possible-hallucination |

### 差异分析决策

| 情况 | 处理 |
|------|------|
| 两者都发现同一问题 | 高置信度，直接打回 |
| 只一方发现问题 | 低置信度，标记待确认 |
| 结论矛盾 | 强制升级 Governor（人类） |
| 任一 Agent escalate | 升级人类 |

### 输出格式

```json
{
  "tier": 3,
  "passed": false,
  "scope_verified": {
    "all_passed": true,
    "missing_items": []
  },
  "test_agent": {
    "verdict": "revise",
    "score": 78,
    "findings": []
  },
  "arch_agent": {
    "verdict": "approve",
    "score": 85,
    "findings": []
  },
  "adversarial_diff": {
    "action": "reject_with_low_confidence",
    "high_confidence": [],
    "low_confidence": [],
    "conflicts": []
  }
}
```

## Tier 4: Agent 建议

**特性**: 仅供参考，不做 pass/fail 判定。仅在 super-dev 模式下执行。

### 建议维度

- 设计优劣评估
- 技术方案对比
- 改进建议

### 输出格式

```json
{
  "tier": 4,
  "suggestions": [
    {
      "id": "S-001",
      "category": "design",
      "title": "建议使用策略模式替代 if-else",
      "reasoning": "当前实现有 5 个分支，策略模式更易扩展",
      "priority": "low"
    }
  ]
}
```
