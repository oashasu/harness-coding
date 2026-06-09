---
name: harness-quality
description: Harness Coding 质量管道 — 5-Tier 分层质量检查（脚本 T0-2 + Agent T3-4），由 harness-router 或工作流自动触发
version: 2.0.0
---

# Harness Quality

> 脚本做确定性检查，Agent 做语义判断。

## 触发方式

由 harness-router 路由后自动触发，也可手动调用：

```
/harness-quality check          # 执行完整质量管道
/harness-quality check --tier 0 # 只执行 Tier 0
/harness-quality check --tier 1 # 只执行 Tier 1
/harness-quality check --tier 2 # 只执行 Tier 2
```

## 5-Tier 质量管道

### 执行流程

```
代码变更完成
    │
    ▼
Tier 0: 脚本硬门禁 (100%确定，不可绕过)
    │ pass
    ▼
Tier 1: 规则脚本检查 (确定性 pattern matching)
    │ pass
    ▼
Tier 2: 度量脚本检查 (数值对比 + 阈值判定)
    │ pass
    ▼
Tier 3: Agent 软审查 (语义判断，需要领域知识)
    │ pass
    ▼
Tier 4: Agent 建议 (仅供参考，不做 pass/fail)
```

### Tier 0: 脚本硬门禁

**100% 确定，不可绕过。失败立即打回。**

| 检查项 | 脚本 | 失败处理 |
|--------|------|----------|
| 编译检查 | `scripts/tier0/check-compile.sh` | 列出编译错误 |
| Lint 检查 | `scripts/tier0/check-lint.sh` | 列出 lint 错误 |
| 写入范围校验 | `scripts/tier0/check-write-paths.sh` | 列出越界文件 |
| 格式规范检查 | `scripts/tier0/check-format.sh` | 列出格式问题 |

### Tier 1: 规则脚本检查

**确定性 pattern matching，每条规则输出结构化 findings。**

| 检查项 | 脚本 | 严重级别 |
|--------|------|----------|
| SQL 注入检测 | `scripts/tier1/check-sql-injection.py` | CRITICAL |
| 金额计算检查 | `scripts/tier1/check-bigdecimal.py` | HIGH |
| 层违规检测 | `scripts/tier1/check-layer-violation.py` | HIGH |
| 硬编码检测 | `scripts/tier1/check-hardcoded.py` | CRITICAL |
| 空指针风险 | `scripts/tier1/check-null-safety.py` | MEDIUM |

### Tier 2: 度量脚本检查

**数值对比 + 阈值判定，输出数值 + 是否达标。**

| 检查项 | 脚本 | 阈值 |
|--------|------|------|
| 测试覆盖率 | `scripts/tier2/check-coverage.py` | line >= 80% |
| 断言密度 | `scripts/tier2/check-assertion-density.py` | >= 1.0 |
| 圈复杂度 | `scripts/tier2/check-complexity.py` | CC <= 10 |
| 文件大小 | `scripts/tier2/check-file-size.py` | 文件 <= 800, 方法 <= 50 |
| 代码重复率 | `scripts/tier2/check-duplication.py` | <= 5% |

### Tier 3: Agent 软审查

**语义判断，需要领域知识。仅在 riper-one 和 super-dev 模式下执行。**

1. **scope_verified 元审查**: Agent 审查前自检输入完备性
2. **双 Agent 对抗审查**:
   - test-agent: 功能覆盖 + 边界用例 + 回归风险
   - arch-agent: 架构合规 + 命名规范 + 依赖方向
3. **差异分析**: 交叉比对两个 Agent 的 findings
4. **证据锚定**: 每个 finding 必须有 file/line/code 证据

### Tier 4: Agent 建议

**仅供参考，不做 pass/fail 判定。仅在 super-dev 模式下执行。**

- 设计优劣评估
- 技术方案对比
- 改进建议

## 分级阈值

不同工作流模式有不同的质量阈值（详见 [references/threshold-config.md](references/threshold-config.md)）：

| 模式 | 总分阈值 | Tier 0 | Tier 1 | Tier 2 | Tier 3 |
|------|----------|--------|--------|--------|--------|
| light | 70 | all_pass | 15 | 20 | - |
| riper-one | 80 | all_pass | 18 | 25 | 12 |
| super-dev | 90 | all_pass | 18 | 27 | 14 |

## 打回规则

每个 Tier 有明确的打回条件和修复指导（详见 [references/rejection-rules.md](references/rejection-rules.md)）。

## Finding 结构化格式

脚本和 Agent 共用统一的 Finding 格式（详见 [scripts/common/finding-schema.json](scripts/common/finding-schema.json)）。

## 引用文件

- [references/quality-tiers.md](references/quality-tiers.md) — 5-Tier 质量管道详细定义
- [references/rejection-rules.md](references/rejection-rules.md) — 打回规则和修复指导
- [references/threshold-config.md](references/threshold-config.md) — 阈值配置
- [scripts/](scripts/) — 质量检查脚本
