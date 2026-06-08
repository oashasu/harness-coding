# Harness Team Skill 设计

> 入口 Skill：启动、恢复、编排 HARNESS 10 步流程

---

## 一、Skill 定义

```markdown
---
name: harness-team
description: 启动 Harness Coding 团队模式，执行 10 步企业级编码流程
---

# Harness Team

## 启动条件
- 项目根目录存在 .harness/ 目录
- 或用户输入 /harness-team

## 启动流程
1. 检查 .harness/ 目录结构是否完整
2. 读取 .harness/state/harness-state.json 确定当前阶段
3. 如果是新任务：进入步骤 [1]
4. 如果是恢复任务：从断点继续

## 初始化命令
```bash
harness init
```
创建 .harness/ 目录结构 + 初始化 harness-state.json
```

---

## 二、10 步流程编排

### 流程状态机

```
INIT → REQ_DRAFT → REQ_REVIEW → SPEC_DRAFT → SPEC_REVIEW
  → CODE_IMPL → MACHINE_CHECK → DUAL_REVIEW → FINAL_ACCEPT
  → KNOWLEDGE_ARCHIVE → DONE

异常路径:
  REQ_REVIEW → REQ_DRAFT (需求打回)
  SPEC_REVIEW → SPEC_DRAFT (Spec 打回)
  MACHINE_CHECK → CODE_IMPL (机器检查打回)
  DUAL_REVIEW → CODE_IMPL (审查打回)
```

### 每步详细设计

#### Step 1: REQ_DRAFT（需求草稿）
```
Agent: requirement-engineer
输入: 人类原始需求（聊天/文档/口述）
输出: .harness/req/requirement.md
门禁: G-REQ-01 (必填字段完整性)
人类介入: 无（AI 辅助生成）
```

requirement.md 模板：
```yaml
req_id: "REQ-001"
title: "需求标题"
description: "为什么做这个"
scope:
  included: ["做什么1", "做什么2"]
  excluded: ["不做什么1"]
acceptance_criteria:
  - id: "AC-001"
    description: "验收标准描述"
    priority: "MUST"
    testable: true
business_context:
  background: "业务背景"
  stakeholders: ["相关方"]
  impact: "影响范围"
```

#### Step 2: REQ_REVIEW（需求审核）
```
Agent: harness-governor
输入: .harness/req/requirement.md
输出: .harness/decisions/D-REQ-001.json
门禁: G-REQ-01 + G-REQ-02
人类介入: 是（人类确认需求清晰度）
```

决策格式：
```json
{
  "decision_id": "D-REQ-001",
  "gate": "G-REQ-01",
  "result": "PASS | FAIL",
  "reason": "决策原因",
  "action": "proceed | reject",
  "reject_to": "REQ_DRAFT",
  "timestamp": "2026-06-07T14:00:00Z"
}
```

#### Step 3: SPEC_DRAFT（Spec 草稿）
```
Agent: spec-architect
输入: .harness/req/requirement.md + .harness/refs/ (领域知识)
输出:
  - .harness/spec/spec.md (工程设计文档)
  - .harness/spec/task_brief.md (任务契约)
  - .harness/spec/adr/ (架构决策记录)
  - .harness/spec/interfaces/ (接口契约)
门禁: G-SPEC-01 (Schema 验证) + G-SPEC-02 (R-ID 唯一性)
人类介入: 无
```

#### Step 4: SPEC_REVIEW（Spec 审核）
```
Agent: harness-governor + spec-architect
输入: .harness/spec/ 全部文件
输出: .harness/decisions/D-SPEC-001.json
门禁: G-SPEC-03 (spec-reviewer 审查通过)
人类介入: 是（人类审核 Spec 是否对齐原始需求）
```

#### Step 5: CODE_IMPL（代码实现）
```
Agent: coding-worker
输入: .harness/spec/task_brief.md + .harness/spec/spec.md
输出:
  - 代码文件（直接写入项目目录）
  - .harness/results/R-001.json (实现结果)
门禁: 无（实现中不阻塞）
约束: TDD 模式、fresh context、按 task_brief 范围实现
```

#### Step 6: MACHINE_CHECK（机器检查）
```
Agent: 无（确定性脚本）
输入: 代码文件
输出: .harness/gates/gate-results/MC-001.json
门禁:
  - G-CODE-01: 编译通过 (mvn compile)
  - G-CODE-02: 单测通过 (mvn test)
  - G-CODE-03: 覆盖率 ≥ 80% (jacoco:check)
  - G-CODE-04: 静态扫描无 CRITICAL (spotbugs:check)
人类介入: 无
打回: 任一 CRITICAL 失败 → 回到 CODE_IMPL
```

#### Step 7: DUAL_REVIEW（双 Agent 审查）
```
Agent: test-evaluator + arch-evaluator（并行）
输入: 代码文件 + .harness/spec/ + 机器检查结果
输出:
  - .harness/reviews/test/TV-001.json
  - .harness/reviews/arch/AV-001.json
门禁:
  - G-TEST-01: R-ID 逐条验证通过
  - G-TEST-02: 安全扫描通过
  - G-ARCH-01: 架构原则未被破坏
  - G-ARCH-02: 错误码规范合规
  - G-ARCH-03: 跨包调用规范合规
人类介入: 无
打回: 任一 rework → 回到 CODE_IMPL
升级: 任一 needs_governor → harness-governor 决策
```

#### Step 8: FINAL_ACCEPT（最终验收）
```
Agent: harness-governor
输入: 所有 reviews + gate results
输出: .harness/decisions/acceptance.json
门禁: 双 Agent 全部 accept + 无 CRITICAL
人类介入: 是（人类确认验收）
```

验收格式：
```json
{
  "decision_id": "D-FINAL-001",
  "task_id": "T-001",
  "result": "ACCEPTED | REJECTED",
  "test_evaluation": {
    "result": "accept",
    "rid_coverage": "100%"
  },
  "arch_evaluation": {
    "result": "accept",
    "violations": 0
  },
  "machine_checks": {
    "compile": "PASS",
    "test": "PASS",
    "coverage": "85%",
    "static_scan": "PASS"
  },
  "timestamp": "2026-06-07T16:00:00Z"
}
```

#### Step 9: KNOWLEDGE_ARCHIVE（经验沉淀）
```
Agent: knowledge-curator
输入: 全部任务产物
输出:
  - knowledge/failure_memory.jsonl (追加)
  - knowledge/experience.md (更新)
  - knowledge/insights.jsonl (追加)
门禁: 无
人类介入: 无
```

#### Step 10: DONE（完成）
```
Agent: harness-governor
输出: 最终报告呈现给人类
```

---

## 三、断点恢复机制

### harness-state.json 格式（v2 结构）

```json
{
  "version": "2.0.0",
  "contract": {
    "contract_hash": "",
    "prompt_version": "2.0.0",
    "constraints": [],
    "allowed_write_paths": ["src/**", "scripts/**", "skills/**", ".harness/**", "docs/**", "*.md"],
    "blocked_paths": [".env", "**/secrets/**", "**/*.key", "**/*.pem"],
    "acceptance_refs": []
  },
  "phase_truth": {
    "current_phase": "CODE_IMPL",
    "phase_status": "in_progress",
    "previous_phases": ["REQ_DRAFT", "REQ_REVIEW", "SPEC_DRAFT", "SPEC_REVIEW"]
  },
  "node_truth": {
    "subtasks": []
  },
  "recovery_truth": {
    "resume_context": {
      "last_step": "CODE_IMPL",
      "last_artifact": ".harness/results/R-001.json",
      "allowed_action": "continue"
    },
    "checkpoints": []
  },
  "route_decision": {
    "workflow": null,
    "confidence": null,
    "scores": {"loc_estimate": 0, "file_count": 0, "db_changes": 0, "cross_module": 0, "risk_level": 0},
    "total_score": 0,
    "reasoning": null,
    "overrides": {"force_super_dev": false, "force_light": false},
    "split_required": false,
    "subtasks": []
  },
  "quality_results": {
    "last_run": null,
    "tier_results": {},
    "overall_passed": null
  },
  "history": []
}
```

> 注：pipeline.json 为历史版本结构，现已迁移至 harness-state.json（v2 结构）。新实现应使用 harness-state.json 作为主控制面。

### 恢复流程

```
harness resume
    │
    ├── 读取 harness-state.json
    ├── 确定 current_phase
    ├── 检查 recovery_truth.resume_context
    │   ├── allowed_action=wait → 等待人工解锁
    │   └── allowed_action=continue → 继续执行
    ├── 加载当前步骤的输入产物
    └── 从断点继续执行
```

---

## 四、人类审批点

### 三个显式审批点

| 审批点 | 时机 | 阻塞级别 | 超时处理 |
|--------|------|----------|---------|
| 需求审批 | REQ_REVIEW 完成后 | BLOCKING | 24h 后自动提醒 |
| Spec 审批 | SPEC_REVIEW 完成后 | BLOCKING | 24h 后自动提醒 |
| 最终验收 | FINAL_ACCEPT 完成后 | BLOCKING | 48h 后自动提醒 |

### 审批交互格式

```
harness-governor 呈现给人类:

## 需求审核结果

**需求 ID**: REQ-001
**标题**: 需求标题
**清晰度评分**: 8/10

### 必填字段检查
- [x] 为什么做
- [x] 做什么
- [x] 不做什么
- [x] 验收标准（3 条）
- [ ] 业务背景（建议补充）

### 建议
1. 建议补充业务背景描述
2. AC-002 的验收标准建议更具体

### 决策
请确认: [批准] [打回修改]
```

---

## 五、目录结构完整性检查

harness init 时检查：

```bash
# 必需目录
.harness/state/
.harness/req/
.harness/spec/adr/
.harness/spec/interfaces/
.harness/decisions/
.harness/dispatch/
.harness/results/
.harness/reviews/test/
.harness/reviews/arch/
.harness/gates/gate-results/
.harness/knowledge/wal/
.harness/logs/
.harness/hooks/
.harness/refs/
.harness/schemas/
.harness/prompts/
.harness/config/

# 必需文件
.harness/state/harness-state.json (初始化为空 harness-state)
```

