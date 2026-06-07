---
name: harness-router
description: Harness Coding 统一路由入口 — 五维评分路由 + 大任务自动拆分
version: 2.0.0
trigger: /harness <需求描述>
---

# Harness Router

> 人类掌舵，智能体执行。根据任务复杂度自动选择工作流。

## 触发方式

```
/harness <需求描述>
/harness:light <需求描述>      # 强制 light 模式
/harness:riper-one <需求描述>  # 强制 riper-one 模式
/harness:super-dev <需求描述>  # 强制 super-dev 模式
```

## 执行流程

### Step 1: 需求解析

1. 解析用户输入的需求描述
2. 提取关键信息：涉及模块、预估规模、风险点

### Step 2: 五维评分

按以下五个维度评分（每项 1-4 分，总分 5-20）：

| 维度 | 权重 | 1 分 | 2 分 | 3 分 | 4 分 |
|------|------|------|------|------|------|
| 代码行数预估 | 20% | 0-50 行 | 50-200 行 | 200-500 行 | 500+ 行 |
| 涉及文件数 | 20% | 单文件 | 2-5 文件 | 5-15 文件 | 15+ 文件 |
| 数据库变更 | 20% | 无 | 仅 DML | DDL | 迁移脚本 |
| 跨模块依赖 | 20% | 单文件 | 单模块 | 跨模块 | 跨服务 |
| 风险等级 | 20% | 配置/日志 | 业务逻辑 | 认证/支付 | 核心基础设施 |

### Step 3: 强制路由检查

在评分之前，先检查强制路由规则（详见 [references/routing-matrix.md](references/routing-matrix.md)）：

| 场景 | 强制路由 |
|------|----------|
| 用户显式指定模式 | 使用指定模式 |
| 涉及认证/支付核心代码 | super-dev |
| 纯 typo/日志/配置值变更 | light (zero) |
| 新项目/新模块搭建 | super-dev |
| Bug 修复但根因明确 | light (fast) |

### Step 4: 路由决策

```
total_score <= 8  → light 模式（<2h 简单任务）
total_score 9-15  → riper-one 模式（2-8h 中等任务）
total_score >= 16 → super-dev 模式（>8h 复杂任务）
```

### Step 5: 大任务拆分检查

**触发条件**: LOC > 500 或 文件数 > 15

拆分策略（详见 [references/routing-matrix.md](references/routing-matrix.md)）：
- 按功能模块拆分
- 按文件变更范围拆分
- 按数据库表拆分
- 按流程阶段拆分

### Step 6: 输出路由决策 + 初始化状态

1. 输出路由决策 JSON（workflow、scores、reasoning、subtasks）
2. 创建 `.harness/harness-state.json` 初始化状态
3. 创建 Spec 文档（使用 [references/spec-template.md](references/spec-template.md) 模板）
4. 启动对应工作流（参考 [references/workflow-map.md](references/workflow-map.md)）

## 路由输出格式

```json
{
  "route_decision": {
    "workflow": "riper-one",
    "confidence": 0.85,
    "scores": {
      "loc_estimate": 2,
      "file_count": 3,
      "db_changes": 2,
      "cross_module": 2,
      "risk_level": 2
    },
    "total_score": 11,
    "reasoning": "涉及3个文件、DDL变更、跨模块但非核心链路，适合标准RIPER流程",
    "overrides": {
      "force_super_dev": false,
      "force_light": false
    },
    "split_required": false,
    "subtasks": []
  }
}
```

## 引用文件

- [references/routing-matrix.md](references/routing-matrix.md) — 评分矩阵 + 拆分规则
- [references/workflow-map.md](references/workflow-map.md) — 工作流映射
- [references/spec-template.md](references/spec-template.md) — 统一 Spec 模板（10 个区块）
