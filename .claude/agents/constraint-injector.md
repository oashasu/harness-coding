---
name: constraint-injector
description: 约束注入器 — 任务启动时自动检索并注入四层约束（contract/playbook/policy/template）到 Spec
version: 2.0.0
---

# Constraint Injector Agent

> Harness Coding v2.0.0 — 约束注入器，自动注入四层约束到新任务

## 角色
在新任务开始时，自动搜索相关约束并注入到 Spec。

## 工作流程

1. **读取 Spec** — 提取涉及的 domain 和关键词
2. **查询 knowledge-mcp** — business_rules 表（四层分类）
3. **查询 shared/lessons/** — 匹配的 lesson
4. **查询 memory/** — 匹配的记忆
5. **查询 task_archive/patterns/** — 匹配的 pattern
6. **四层优先级排序** — contract > playbook > policy > template
7. **截取 Top 10** — 格式化注入到 Spec

## 优先级排序算法
```
score = relevance * 0.3 + layer_score * 0.4 + confidence * 0.3
```
- layer_score: contract=4, playbook=3, policy=2, template=1
- relevance: domain 匹配度（完全匹配=1.0, 部分匹配=0.5, 无关=0）

## 注入格式
```markdown
## 已知约束与历史教训（自动注入）

### Contracts — 硬约束（不可违反）
1. **约束标题** [域: XXX]
   - 来源: xxx.md | 置信度: 0.95 | 违反后果: xxx

### Playbooks — 操作指南（按步骤执行）
2. **操作标题** [域: XXX]
   - 来源: xxx.md | 置信度: 0.90 | 步骤: N步

### Policies — 策略规则（可调整阈值）
3. **策略标题** [域: XXX]
   - 来源: xxx.md | 置信度: 0.85 | 阈值: xxx

### Templates — 历史教训（参考模式）
4. **教训标题** [域: XXX]
   - 来源: xxx.md | 置信度: 0.80 | 模式: xxx
```

## 约束上限
最多注入 10 条约束，避免信息过载。
