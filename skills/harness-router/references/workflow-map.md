# Workflow Map — 工作流映射

> 版本: 2.0.0 | 更新: 2026-06-07

## 三种工作流模式

### Light 模式（<2h 简单任务）

适用场景：小 bug 修复、配置变更、日志调整、单文件改动

```
需求 → 快速Spec → 实现 → Tier 0-2 脚本检查 → 完成
```

**阶段**:
1. **Spec**: 简化版 Spec（仅需求摘要 + 影响分析 + 机器验收）
2. **实现**: 直接编码
3. **质量**: Tier 0-2 脚本门禁（跳过 Tier 3 Agent 审查）
4. **完成**: 提交代码

**Skill 引用**:
- Spec 模板: [spec-template.md](spec-template.md) (light 裁剪版)
- 质量检查: harness-quality Tier 0-2

### Riper-One 模式（2-8h 中等任务）

适用场景：新接口开发、模块扩展、中等规模重构

```
需求 → 研究 → Spec → 审批 → 实现 → Tier 0-3 质量管道 → 审查 → 完成
```

**阶段**:
1. **Research**: 研究现有代码和架构
2. **Spec**: 完整 Spec 文档（10 个区块）
3. **Approve**: 人工审批 Spec
4. **Implement**: 按 Spec 实现
5. **Verify**: Tier 0-3 质量管道
6. **Review**: 人工审查
7. **Done**: 提交代码

**Skill 引用**:
- Spec 模板: [spec-template.md](spec-template.md) (完整版)
- 质量检查: harness-quality Tier 0-3
- 已有 Skill: `sdd-riper-one` (RIPER 方法论)

### Super-Dev 模式（>8h 复杂任务）

适用场景：核心链路重构、新模块搭建、跨服务改动

```
需求 → 深度研究 → Spec → 审批 → 拆分 → 逐子任务实现 → Tier 0-4 全管道 → 多轮审查 → 完成
```

**阶段**:
1. **Research**: 深度研究（领域分析、架构评估、风险识别）
2. **Spec**: 完整 Spec 文档（10 个区块 + 领域约束注入）
3. **Approve**: 人工审批 Spec
4. **Split**: 大任务自动拆分（如需要）
5. **Implement**: 按子任务逐个实现
6. **Verify**: Tier 0-4 完整质量管道
7. **Review**: 双 Agent 对抗审查 + 人工审查
8. **Extract**: 提取可复用模式
9. **Done**: 提交代码

**Skill 引用**:
- Spec 模板: [spec-template.md](spec-template.md) (完整版 + 领域约束)
- 质量检查: harness-quality Tier 0-4
- 已有 Skill: `super-dev` (9 阶段治理流水线)

## 工作流选择决策树

```
用户输入 /harness <需求>
    │
    ├─ 显式指定模式？ → 使用指定模式
    │
    ├─ 强制路由匹配？
    │   ├─ 认证/支付核心 → super-dev
    │   ├─ 纯机械改动 → light
    │   └─ 新项目搭建 → super-dev
    │
    └─ 五维评分
        ├─ total <= 8 → light
        ├─ total 9-15 → riper-one
        └─ total >= 16 → super-dev
```

## 与已有 Skill 的集成

| 已有 Skill | 集成方式 | 使用的工作流 |
|------------|----------|-------------|
| `sdd-riper-one` | RIPER 方法论 Skill | riper-one |
| `super-dev` | 9 阶段治理流水线 Skill | super-dev |
| `verification-loop` | 整合到 harness-quality Tier 0-2 | 全部 |
| `quality-gate` | 整合到 harness-quality Tier 0-2 | 全部 |
| `redteam-reviewer` | 整合到 harness-quality Tier 3 | riper-one, super-dev |
