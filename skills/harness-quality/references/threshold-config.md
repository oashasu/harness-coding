# Threshold Config — 阈值配置

> 版本: 2.0.0 | 更新: 2026-06-07

## 分级阈值

不同工作流模式有不同的质量阈值。模式越复杂，阈值越高。

### Light 模式

```json
{
  "workflow": "light",
  "overall": 70,
  "tier0_script": "all_pass",
  "tier1_rules": 15,
  "tier2_metrics": 20,
  "tier3_agent": null,
  "tier4_suggestions": null
}
```

- Tier 0: 所有检查必须通过
- Tier 1: 总分 >= 15（满分 25）
- Tier 2: 总分 >= 20（满分 30）
- Tier 3: 跳过
- Tier 4: 跳过

### Riper-One 模式

```json
{
  "workflow": "riper-one",
  "overall": 80,
  "tier0_script": "all_pass",
  "tier1_rules": 18,
  "tier2_metrics": 25,
  "tier3_agent": 12,
  "tier4_suggestions": null
}
```

- Tier 0: 所有检查必须通过
- Tier 1: 总分 >= 18（满分 25）
- Tier 2: 总分 >= 25（满分 30）
- Tier 3: 总分 >= 12（满分 20）
- Tier 4: 跳过

### Super-Dev 模式

```json
{
  "workflow": "super-dev",
  "overall": 90,
  "tier0_script": "all_pass",
  "tier1_rules": 18,
  "tier2_metrics": 27,
  "tier3_agent": 14,
  "tier4_suggestions": "record"
}
```

- Tier 0: 所有检查必须通过
- Tier 1: 总分 >= 18（满分 25）
- Tier 2: 总分 >= 27（满分 30）
- Tier 3: 总分 >= 14（满分 20）
- Tier 4: 记录建议（不做 pass/fail）

## Tier 内部评分

### Tier 1 评分（满分 25）

| 检查项 | 满分 | CRITICAL 扣分 | HIGH 扣分 | MEDIUM 扣分 |
|--------|------|--------------|-----------|-------------|
| SQL 注入 | 5 | -5 | -3 | -1 |
| 金额计算 | 5 | -5 | -3 | -1 |
| 层违规 | 5 | -5 | -3 | -1 |
| 硬编码 | 5 | -5 | -3 | -1 |
| 空指针 | 5 | -5 | -3 | -1 |

### Tier 2 评分（满分 30）

| 检查项 | 满分 | 达标 | 未达标 |
|--------|------|------|--------|
| 测试覆盖率 | 6 | 6 | 0 |
| 断言密度 | 6 | 6 | 0 |
| 圈复杂度 | 6 | 6 | 0 |
| 文件大小 | 6 | 6 | 0 |
| 代码重复率 | 6 | 6 | 0 |

### Tier 3 评分（满分 20）

| 维度 | 满分 | 评分方式 |
|------|------|----------|
| test-agent verdict | 10 | approve=10, revise=5, escalate=0 |
| arch-agent verdict | 10 | approve=10, revise=5, escalate=0 |

## 总分计算

```
overall = tier1_score + tier2_score + tier3_score
```

- Light: overall >= 70（满分 55，需要 tier1 + tier2 达标）
- Riper-One: overall >= 80（满分 75，需要所有 tier 达标）
- Super-Dev: overall >= 90（满分 75，需要所有 tier 高标准达标）

## 配置文件位置

运行时阈值配置存储在 `.harness/quality-config.json`。
