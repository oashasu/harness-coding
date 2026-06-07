# HARNESS 核心架构设计

> 基于 state-contracts 分析，综合 orchestrator/handoff/schemas/prompts 四维分析结果
> 设计目标：从支付渠道专用 → 通用企业 Java 项目的 AI 编码编排系统

---

## 一、架构总览

### 三层架构

```
┌─────────────────────────────────────────────────┐
│                  HARNESS Layer                    │
│  harness-team skill (入口) + 10 步流程状态机        │
│  harness-governor (编排器) + pipeline.json (真相源)  │
├─────────────────────────────────────────────────┤
│                  Agent Layer                      │
│  7 个角色 Agent，各自职责边界清晰                    │
│  JSON Schema 硬合约 + Role Prompt 软引导            │
├─────────────────────────────────────────────────┤
│                  Gate Layer                       │
│  4 层门禁：L1 Sensor → L2 Insight → L3 Policy → L4 Enforce │
│  脚本做硬约束，模型做软判断                          │
├─────────────────────────────────────────────────┤
│               Experience Layer                    │
│  failure_memory + WAL + 经验注入 + 衰减审计          │
│  越用越稳的自进化闭环                                │
└─────────────────────────────────────────────────┘
```

---

## 二、从 state-contracts 继承的核心组件

### 2.1 编排引擎（orchestrator.py → harness-orchestrator.py）

**继承**：
- StageOrchestrator 单类架构
- load_state() + HMAC-SHA256 完整性校验
- DAG 拓扑排序 + 环检测（lines 1244-1317）
- Validator subprocess runner 模式
- `[Blocker]` + `sys.exit(1)` 门禁执行模式

**改造**：
| 原始 | HARNESS | 改动 |
|------|---------|------|
| 5 阶段（prep/spec/prove/gen/final） | 10 步（REQ→SPEC→CODE→REVIEW→ACCEPT→ARCHIVE） | 扩展阶段 |
| `.payment-skill/` 路径 | `.harness/` 路径 | 全局替换 |
| payment_workflow state kind | harness state kind | 去除 payment 字段 |
| GEN_LAYER_NODE_MAP（支付层节点映射） | 可配置 DAG 蓝图 | 外部化配置 |
| TERMINAL_PHASE_ACTIONS（archive-payment-workflow） | archive-harness-workflow | 脚本重命名 |

**核心保留**（直接复用）：
```python
# 状态加载 + Markdown剥离 + JSON清理
load_state() -> dict  # lines 296-359

# DAG 拓扑排序 + 环检测
topological_sort(steps) -> list  # lines 1244-1317

# 外部验证器 subprocess 调用
run_validator(script, args) -> (exit_code, stdout)  # lines 579-607

# 恢复动作绑定校验
validate_resume_context(ctx) -> [Blocker]  # lines 131-161
```

### 2.2 交接机制（phase-handoff.py → harness-handoff.py）

**继承**：
- 线性阶段流水线状态机
- Checkpoint-Action 模式（等待授权 vs 直接推进）
- Handoff 包生成（只读上下文快照）
- SESSION_BRIEF Markdown 摘要
- HMAC 状态完整性保护（seal/verify）
- 三层校验体系（状态Schema + HMAC + 产物Schema）

**改造**：
| 原始 | HARNESS | 改动 |
|------|---------|------|
| `PHASE_ORDER = [prep, spec, prove, gen, final]` | 10 步顺序 | 扩展 |
| `.payment-skill/handoff/` | `.harness/dispatch/` | 路径变更 |
| `institution_code` 上下文 | `task_id` + `req_id` 上下文 | 去除支付实体 |
| `business_fact_validation_passed` | `req_validation_passed` | 通用化门禁条件 |
| `archive-payment-workflow.py` | `archive-harness.py` | 脚本重命名 |

**保留的 7 个领域无关模式**：
1. 阶段状态机（pending → in_progress → completed）
2. Checkpoint-Action 模式（等待授权 vs 直接推进）
3. Handoff 包生成三段式（artifacts + context_summary + resume_first_prompt）
4. 临时文件清理
5. HMAC 状态完整性保护
6. 控制面一致性验证
7. 用户动作消费协议

### 2.3 JSON Schema（13 → 10 个）

**直接复用（6 个）**：
| Schema | HARNESS 名称 | 改动量 |
|--------|-------------|--------|
| plan-state.v1 | harness-plan-state.v1 | owner 枚举通用化 |
| task-manifest.v1 | harness-task-manifest.v1 | 去除 institution，加 req_id |
| review-result.v1 | harness-review-result.v1 | 无改动 |
| worker-final-report.v2 | harness-worker-report.v1 | 无改动 |
| next-action-plan.v1 | harness-next-action-plan.v1 | phase 枚举扩展 |
| next-action-execution.v1 | harness-next-action-execution.v1 | script 枚举更新 |

**需改造（2 个）**：
| Schema | HARNESS 名称 | 改动 |
|--------|-------------|------|
| spec-business-facts | harness-req-facts.v1 | 从支付业务事实 → 通用需求事实 |
| prove-issue-routing | harness-issue-routing.v1 | 保留 triage 模式，去除支付门禁 |

**废弃（2 个）**：
- payment-channel-allocation-registry（纯支付域）
- payment-channel-config（纯支付域）

**新增（2 个）**：
- harness-gate-result.v1（门禁结果标准化格式）
- harness-experience-ref.v1（经验引用格式）

### 2.4 Role Prompts（9 → 7 个）

**映射关系**：
| state-contracts | HARNESS | 改动 |
|----------------|---------|------|
| main-orchestrator-prompt.md | harness-governor.md | +经验循环管理、+人类审批 |
| spec-agent-prompt.md | requirement-engineer.md | +需求辅助、+验收标准检查 |
| plan-agent-prompt.md | spec-architect.md | +R-ID、+接口契约、+ADR |
| worker-node-prompt.md | coding-worker.md | +TDD、+fresh context |
| review-node-prompt.md | test-evaluator.md | +R-ID 验证、三态输出 |
| code-agent-prompt.md | （合并到 coding-worker） | — |
| prove-agent-prompt.md | （合并到 test-evaluator） | — |
| AI-GUIDE.md | harness-team.md | 入口 Skill |
| AI-GUIDE-prompt-contract.md | harness-contracts.md | 合约文档 |

**新增**：
- arch-evaluator.md（架构原则审查，全新）
- knowledge-curator.md（经验沉淀，全新）

---

## 三、HARNESS 新增组件

### 3.1 经验循环系统

state-contracts 完全没有经验循环。HARNESS 新增：

```
knowledge/
├── failure_memory.jsonl    # 偏航记录（追加写入）
├── experience.md           # 项目级经验库（可编辑）
├── insights.jsonl          # 洞察记录（自动生成）
└── wal/                    # Write-Ahead Log
```

**核心机制**：
- 门禁失败 → 自动写入 failure_memory.jsonl
- 任务完成 → knowledge-curator 提炼经验 → 更新 experience.md
- 下次任务 → 注入相关经验到 task_brief.md
- 月度审计 → 衰减清理过期经验

**注入点**：
| Agent | 注入内容 |
|-------|---------|
| requirement-engineer | 负向经验（需求阶段常见遗漏） |
| spec-architect | 偏航模式（Spec 常见缺陷） |
| coding-worker | 正向经验 + 偏航模式 |
| test-evaluator | 历史门禁失败原因 |
| arch-evaluator | 架构违规历史 |

### 3.2 人类审批点

state-contracts 用 checkpoint + user-action 实现人类介入，但无显式审批流程。HARNESS 新增 3 个显式审批点：

| 审批点 | 时机 | 阻塞级别 | 交互格式 |
|--------|------|----------|---------|
| 需求审批 | REQ_REVIEW 后 | BLOCKING | 清晰度评分 + 必填字段检查 |
| Spec 审批 | SPEC_REVIEW 后 | BLOCKING | Spec 与需求对齐检查 |
| 最终验收 | FINAL_ACCEPT 后 | BLOCKING | 双 Agent 审查汇总 |

**实现方式**：
- 复用 state-contracts 的 `awaiting_user_action` + `allowed_actions` 机制
- 扩展 `user_action` 枚举：approve / reject / reject_with_reason
- 审批结果写入 `.harness/decisions/`

### 3.3 14 门禁体系

state-contracts 有 5 层 gate。HARNESS 扩展为 4 层 + 14 门禁：

**L4 Enforce（确定性脚本，8 个）**：
| 门禁 | 实现 | 来源 |
|------|------|------|
| G-REQ-01 | JSON Schema 校验 requirement.md | 新增 |
| G-SPEC-01 | JSON Schema 校验 task_brief.md | state-contracts Gate-2 |
| G-SPEC-02 | R-ID 唯一性脚本检查 | 新增 |
| G-CODE-01 | mvn compile | state-contracts Gate-1 |
| G-CODE-02 | mvn test | state-contracts Gate-1 |
| G-CODE-03 | jacoco:check ≥ 80% | 新增 |
| G-CODE-04 | spotbugs:check 无 CRITICAL | 新增 |
| G-TEST-02 | grep 安全模式匹配 | 新增 |

**L3 Policy（模型判断，6 个）**：
| 门禁 | 实现 | 来源 |
|------|------|------|
| G-REQ-02 | Agent 判断验收标准可测试性 | 新增 |
| G-SPEC-03 | spec-reviewer 审查 | state-contracts Gate-2 review |
| G-TEST-01 | test-evaluator R-ID 逐条验证 | state-contracts Gate-3 |
| G-ARCH-01 | arch-evaluator 架构原则审查 | 新增 |
| G-ARCH-02 | arch-evaluator + 脚本错误码规范 | 新增 |
| G-ARCH-03 | arch-evaluator + 脚本跨包调用 | 新增 |

---

## 四、10 步流程与 state-contracts 阶段映射

```
HARNESS 10 步                    state-contracts 5 阶段
──────────────────────────────────────────────────────────
[1] REQ_DRAFT   需求草稿          ← prep (capture 扩展)
[2] REQ_REVIEW  需求审核          ← prep (preflight 扩展)
[3] SPEC_DRAFT  Spec 草稿         ← spec
[4] SPEC_REVIEW Spec 审核         ← spec (review 扩展)
[5] CODE_IMPL   代码实现          ← gen (TDD 增强)
[6] MACHINE_CHECK 机器检查        ← prove (机器检查部分)
[7] DUAL_REVIEW 双 Agent 审查     ← review-node 拆分
[8] FINAL_ACCEPT 最终验收         ← final
[9] KNOWLEDGE_ARCHIVE 经验沉淀    ← 全新
[10] DONE       完成              ← DONE
```

### 阶段状态机

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

---

## 五、目录结构

```
.harness/
├── state/
│   ├── pipeline.json              ← 真相源（扩展 state-contracts 的 DAG 状态）
│   └── task-queue.json            ← 任务队列
├── req/
│   └── requirement.md             ← 需求文档（HARNESS 新增）
├── spec/
│   ├── spec.md                    ← 工程设计文档
│   ├── task_brief.md              ← 任务契约（从 task-manifest 转换）
│   ├── adr/                       ← 架构决策记录（HARNESS 新增）
│   └── interfaces/                ← 接口契约（HARNESS 新增）
├── decisions/
│   ├── D-REQ-001.json             ← 门禁决策落盘
│   └── acceptance.json            ← 最终验收
├── dispatch/
│   └── DP-001.json                ← Handoff 包（从 handoff/ 迁移）
├── results/
│   └── R-001.json                 ← Worker 报告
├── reviews/
│   ├── test/
│   │   └── TV-001.json            ← 测试评估
│   └── arch/
│       └── AV-001.json            ← 架构评估（HARNESS 新增）
├── gates/
│   ├── gate-runner.sh             ← 门禁执行器
│   ├── g-compile.sh               ← 编译门禁
│   ├── g-test.sh                  ← 测试门禁
│   ├── g-coverage.sh              ← 覆盖率门禁
│   ├── g-static.sh                ← 静态扫描门禁
│   ├── g-security.sh              ← 安全扫描门禁
│   └── gate-results/              ← 门禁结果
├── knowledge/
│   ├── failure_memory.jsonl       ← 偏航记录
│   ├── experience.md              ← 经验库
│   ├── insights.jsonl             ← 洞察记录
│   └── wal/                       ← Write-Ahead Log
├── refs/                          ← 领域知识（从 main 分支继承）
├── logs/
│   └── events.jsonl               ← 事件日志
├── hooks/
│   ├── on-phase-change.sh         ← 阶段切换 hook
│   └── on-gate-fail.sh            ← 门禁失败 hook
├── scripts/                       ← 编排脚本（从 state-contracts 迁移）
│   ├── orchestrator.py            ← 通用化改造
│   ├── phase-handoff.py           ← 通用化改造
│   ├── preflight.py               ← 通用化改造
│   └── ...
├── schemas/                       ← JSON Schema（从 state-contracts 迁移）
├── prompts/                       ← Role Prompts（从 state-contracts 迁移）
└── config/
    ├── capabilities.yaml          ← 角色能力配置
    └── workspace.template.json    ← 工作区模板
```

---

## 六、pipeline.json（真相源）

```json
{
  "pipeline_id": "PL-001",
  "task_id": "T-001",
  "req_id": "REQ-001",
  "current_step": "CODE_IMPL",
  "status": "in_progress",
  "started_at": "2026-06-07T14:00:00Z",
  "updated_at": "2026-06-07T15:30:00Z",
  "steps": {
    "REQ_DRAFT": {"status": "completed", "at": "..."},
    "REQ_REVIEW": {"status": "completed", "at": "..."},
    "SPEC_DRAFT": {"status": "completed", "at": "..."},
    "SPEC_REVIEW": {"status": "completed", "at": "..."},
    "CODE_IMPL": {"status": "in_progress", "at": "..."},
    "MACHINE_CHECK": {"status": "pending"},
    "DUAL_REVIEW": {"status": "pending"},
    "FINAL_ACCEPT": {"status": "pending"},
    "KNOWLEDGE_ARCHIVE": {"status": "pending"}
  },
  "resume_context": {
    "last_step": "CODE_IMPL",
    "last_artifact": ".harness/results/R-001.json",
    "failure_reason": null,
    "allowed_action": "continue",
    "lock": false,
    "experience_refs": ["EXP-P001", "EXP-D001"]
  },
  "integrity": {
    "hmac_sha256": "..."
  }
}
```

---

## 七、实现路线图

### Phase 1: 基线迁移（1-2 天）

| 任务 | 来源 | 改动量 |
|------|------|--------|
| 目录重命名 .payment-skill/ → .harness/ | state-contracts | 小 |
| orchestrator.py 通用化 | state-contracts | 中（去除 9 处支付耦合） |
| phase-handoff.py 通用化 | state-contracts | 中（去除 9 处支付耦合） |
| preflight.py 通用化 | state-contracts | 小 |
| 13 Schema → 10 Schema | state-contracts | 中（6 直接复用，2 改造，2 废弃，2 新增） |
| 9 Prompt → 7 Prompt | state-contracts | 中（角色重命名 + 内容调整） |

### Phase 2: 架构增强（2-3 天）

| 任务 | 来源 |
|------|------|
| 6 个 gate shell 脚本 | 从 preflight.py 提取 |
| G-REQ-01/02 需求门禁 | HARNESS 新增 |
| G-CODE-03/04 覆盖率+静态扫描 | HARNESS 新增 |
| G-TEST-02 安全扫描 | HARNESS 新增 |
| G-ARCH-01/02/03 架构门禁 | HARNESS 新增 |
| test-evaluator + arch-evaluator 双 Agent | HARNESS 新增 |

### Phase 3: 经验循环（2-3 天）

| 任务 | 来源 |
|------|------|
| failure_memory.jsonl + WAL | HARNESS 新增 |
| experience.md + 衰减机制 | HARNESS 新增 |
| knowledge-curator Agent | HARNESS 新增 |
| 经验注入机制 | HARNESS 新增 |

### Phase 4: 流程集成（1-2 天）

| 任务 | 来源 |
|------|------|
| harness-team SKILL.md | HARNESS 新增 |
| 3 个人类审批点 | HARNESS 新增 |
| 打回 + 升级机制 | HARNESS 新增 |
| hooks | HARNESS 新增 |

---

## 八、关键设计决策

### D-001: 脚本 vs 模型的职责边界

- **脚本做硬约束**：编译/测试/覆盖率/状态机/恢复/门禁执行
- **模型做软判断**：需求质量/架构合理性/知识提取/验收标准解读
- **理由**：确定性操作必须脚本实现，非确定性判断交给模型

### D-002: 基线选择

- **选择**：state-contracts 作为实现基线
- **理由**：95% 完成的生产级编排框架，有 113 个测试验证，作者完全理解内部实现
- **放弃**：variant/variant-v2（vibe coding 产物，作者无法控制内部细节）

### D-003: 经验循环策略

- **P0**：failure_memory + WAL（基础偏航记录）
- **P1**：experience.md + 注入机制（可引用的经验库）
- **P2**：insights.jsonl + 衰减审计（自动洞察）
