# Harness Coding 企业级实现方案 V2

> 基线：state-contracts 分支（生产级编排框架，95%完成）
> 架构：三层架构 + 经验循环 + 通用化扩展
> 定位：在已有实现上做架构增强，不重写

---

## 一、基线评估：state-contracts 已有什么

### 已完成（直接复用）

| 组件 | 状态 | 说明 |
|------|------|------|
| 编排脚本（38个） | ✅ 完成 | orchestrator.py / phase-handoff.py / preflight.py 等 |
| JSON Schema（13个） | ✅ 完成 | 状态契约、任务清单、worker报告、review结果等 |
| 角色 Prompts（9个） | ✅ 完成 | main-orchestrator / spec-agent / plan-agent / prove-agent / worker-node / review-node / code-agent |
| 测试套件（113个） | ✅ 完成 | test_script_contracts / test_agent_contracts |
| 交接合约（5个） | ✅ 完成 | prep→spec→prove→gen→final→DONE |
| DAG 节点追踪 | ✅ 完成 | G01-G09 节点级状态/验证/重试 |
| Worker-Review 双角色隔离 | ✅ 完成 | JSON Schema 硬合约 |
| 领域知识 | ✅ 已有 | main 分支 6 个文件（语义基线/SQL/枚举/配置/审计/决策） |

### 已有但需增强

| 组件 | 现状 | 需增强 |
|------|------|--------|
| 5 阶段流程 | prep→spec→prove→gen→final | 扩展为通用 10 步流程 |
| 门禁体系 | 5 层 gate | 对齐 HARNESS 14 门禁 + 4 层架构 |
| 角色体系 | 6 角色（支付渠道专用） | 扩展为 7 角色（通用） |
| resume_context | 6 字段恢复控制面 | 补充经验循环注入点 |

### HARNESS 新增（state-contracts 没有的）

| 组件 | 说明 |
|------|------|
| 经验沉淀循环 | failure_memory + WAL + 衰减审计 |
| knowledge-curator | 知识管理员角色 |
| 人类审批点 | 3 个显式人类介入点（需求/Spec/最终验收） |
| 通用化抽象 | 从支付渠道专用→任意企业 Java 项目 |

---

## 二、角色映射：state-contracts 6 角色 → HARNESS 7 角色

```
state-contracts 角色          →  HARNESS 角色              →  变更
─────────────────────────────────────────────────────────────────
main-orchestrator             →  harness-governor           增强：+经验循环管理
spec-agent                    →  requirement-engineer       增强：+需求辅助能力
plan-agent                    →  spec-architect             增强：+接口契约设计
prove-agent                   →  (合并到 test-evaluator)    证明能力并入测试评估
worker-node                   →  coding-worker              不变
review-node                   →  拆分为 test-evaluator      拆分：测试+架构双评估
code-agent                    →  coding-worker 的子模式     合并：代码生成是编码执行的一部分
(新增)                        →  arch-evaluator             新增：架构原则审查
(新增)                        →  knowledge-curator          新增：经验沉淀
```

### 角色职责对齐

#### harness-governor（= main-orchestrator 增强）
```
继承 state-contracts:
  - 阶段编排（prep→spec→prove→gen→final）
  - DAG 节点调度
  - 门禁检查触发
  - 状态持久化

HARNESS 增强:
  + 经验循环管理：任务完成后触发 knowledge-curator
  + 人类审批点：需求审批、Spec 审批、最终验收
  + 打回升级：同一门禁失败 ≥3 次升级人工介入
  + 决策落盘：所有决策写入 .harness/decisions/
```

#### requirement-engineer（= spec-agent 增强）
```
继承 state-contracts:
  - spec-agent 的 Spec 生成能力
  - 业务事实提取

HARNESS 增强:
  + 辅助人类写需求文档（从模糊想法→结构化 requirement.md）
  + 验收标准可测试性检查（G-REQ-02）
  + 引用 experience.md 避免已知的需求遗漏
```

#### spec-architect（= plan-agent 增强）
```
继承 state-contracts:
  - plan-agent 的工程契约翻译
  - task_brief 生成

HARNESS 增强:
  + R-ID 编号体系（一次编号永不重编）
  + 接口契约设计（.harness/spec/interfaces/）
  + 架构决策记录（.harness/spec/adr/）
  + 验收标准来源标注：[user] / [paraphrase] / [inferred]
```

#### coding-worker（= worker-node + code-agent）
```
继承 state-contracts:
  - worker-node 的任务执行
  - code-agent 的代码生成
  - DAG 节点级执行追踪

HARNESS 增强:
  + TDD 模式强制（RED→GREEN→REFACTOR）
  + Fresh context（每个任务重新读取 spec + git 状态）
  + 实现前搜索类似实现（避免重复造轮子）
```

#### test-evaluator（= review-node + prove-agent 拆分）
```
继承 state-contracts:
  - review-node 的审查能力
  - prove-agent 的证明能力（prove-before-gen）

HARNESS 增强:
  + R-ID 逐条验证（基于 Spec 验收标准）
  + 独立于 coding-worker 的外部视角
  + 输出三态：accept / rework / needs_governor
```

#### arch-evaluator（新增）
```
全新角色，无 state-contracts 对应:
  - 架构原则检查：错误码规范、跨包调用、依赖方向、分层约束
  - 安全扫描：秘钥泄露、SQL 注入、授权绕过
  - 与 test-evaluator 组成双 Agent 审查
  - 输出三态：accept / rework / needs_governor
```

#### knowledge-curator（新增）
```
全新角色，无 state-contracts 对应:
  - 从完成的变更中提取稳定知识
  - 记录偏航：门禁失败原因、修复方式
  - 维护 failure_memory（>5MB 或 >90 天轮转）
  - 更新 experience.md 供下次任务引用
  - WAL（Write-Ahead Log）保证写入原子性
```

---

## 三、流程映射：state-contracts 5 阶段 → HARNESS 10 步

```
state-contracts 流程:
  prep → spec → prove → gen → final

HARNESS 10 步流程:
  [1] requirement-engineer 辅助人类写需求          ← 从 spec-agent 的 capture 能力扩展
  [2] harness-governor 审核需求清晰度              ← 从 prep 阶段的 preflight 扩展
  [3] spec-architect 基于项目规范审核并和人类达成一致  ← 从 spec 阶段扩展
  [4] 人类批准开始干活                              ← HARNESS 新增人类审批点
  [5] spec-architect 把需求翻译成 Spec             ← spec 阶段
  [6] 人类审核 Spec 是否对齐原始需求                ← HARNESS 新增人类审批点
  [7] coding-worker 基于 Spec 实现代码 (TDD)       ← gen 阶段
  [8] harness-check: 机器自动验证                   ← prove 阶段的机器检查部分
  [9] 双 Agent 审查                                ← review-node 拆分为双 Agent
  [10] harness-governor 最终验收                    ← final 阶段 + HARNESS 增强

  knowledge-curator: 经验沉淀                      ← HARNESS 新增
```

### 阶段对应关系

| HARNESS 步骤 | state-contracts 阶段 | 产物 | 变更类型 |
|-------------|---------------------|------|---------|
| 步骤 1-2 | prep（capture 部分） | requirement.md | 增强 |
| 步骤 3-4 | prep（approval 部分） | gate: approved | 增强（+人类审批） |
| 步骤 5-6 | spec | spec.md + task_brief.md | 增强（+R-ID） |
| 步骤 7 | gen | 代码 + 测试 | 增强（+TDD） |
| 步骤 8 | prove（机器检查部分） | test_report.json | 不变 |
| 步骤 9 | review-node | reviews/test/ + reviews/arch/ | 拆分（单→双 Agent） |
| 步骤 10 | final | decisions/acceptance.json | 增强（+经验循环） |
| 经验沉淀 | 无 | knowledge/ | 全新 |

---

## 四、门禁映射：state-contracts 5 层 → HARNESS 4 层 + 14 门禁

### 层级映射

```
state-contracts 5 层 gate:
  Gate-1: preflight check (preflight.py)
  Gate-2: schema validation (JSON Schema)
  Gate-3: prove-before-gen (prove-agent)
  Gate-4: worker-final-report (JSON Schema)
  Gate-5: review-result (JSON Schema)

HARNESS 4 层架构:
  L1 Sensor    → hooks + events.jsonl           ← 从 state-contracts 的日志机制扩展
  L2 Insight   → 纯函数检测器                    ← HARNESS 新增
  L3 Policy    → Agent 按需读取 insights 决策    ← 从 prove-agent 的决策能力扩展
  L4 Enforce   → 确定性 gate 脚本               ← 从 state-contracts 的 gate 脚本复用
```

### 14 门禁对齐

| 门禁 ID | 阶段 | 检查内容 | state-contracts 对应 | 实现方式 |
|---------|------|----------|---------------------|---------|
| G-REQ-01 | 需求→契约 | requirement.md 必填字段完整性 | 无（新增） | JSON Schema 校验 |
| G-REQ-02 | 需求→契约 | 验收标准是否可测试 | 无（新增） | Agent 判断 |
| G-SPEC-01 | 契约→实现 | task_brief.md Schema 验证 | Gate-2 schema validation | JSON Schema 校验 |
| G-SPEC-02 | 契约→实现 | R-ID 验收标准编号唯一性 | 无（新增） | 脚本检查 |
| G-SPEC-03 | 契约→实现 | spec-reviewer 审查通过 | Gate-2 的 review 部分 | Agent 审查 |
| G-CODE-01 | 实现→测试 | 编译通过 | Gate-1 preflight 的编译检查 | mvn compile |
| G-CODE-02 | 实现→测试 | 单测全部通过 | Gate-1 preflight 的测试检查 | mvn test |
| G-CODE-03 | 实现→测试 | 覆盖率 ≥ 80% | 无（新增） | jacoco:check |
| G-CODE-04 | 实现→测试 | 静态扫描无 CRITICAL | 无（新增） | spotbugs:check |
| G-TEST-01 | 测试→验收 | R-ID 逐条验证通过 | Gate-3 prove-before-gen | Agent 验证 |
| G-TEST-02 | 测试→验收 | 安全扫描通过 | 无（新增） | grep 模式匹配 |
| G-ARCH-01 | 架构→验收 | 架构原则未被破坏 | 无（新增） | Agent 审查 |
| G-ARCH-02 | 架构→验收 | 错误码规范合规 | 无（新增） | 脚本 + Agent |
| G-ARCH-03 | 架构→验收 | 跨包调用规范合规 | 无（新增） | 脚本 + Agent |

---

## 五、真相源目录结构

在 state-contracts 的 `.payment-skill/` 基础上扩展为通用 `.harness/`：

```
.harness/
├── state/
│   ├── harness-state.json         ← 真相源（v2 结构，主控制面）
│   ├── pipeline.json              ← [历史] 已迁移至 harness-state.json
│   └── task-queue.json            ← 从 plan-next-action.py 的任务队列扩展
├── req/
│   └── requirement.md             ← HARNESS 新增（需求层）
├── spec/
│   ├── spec.md                    ← 从 state-contracts 的 spec/ 继承
│   ├── task_brief.md              ← 从 task-manifest.json 转换
│   ├── adr/                       ← HARNESS 新增（架构决策记录）
│   └── interfaces/                ← HARNESS 新增（接口契约）
├── decisions/
│   ├── D-001.json                 ← HARNESS 新增（门禁决策落盘）
│   └── acceptance.json            ← HARNESS 新增（最终验收）
├── dispatch/
│   └── DP-001.json                ← 从 state-contracts 的 handoff/ 继承
├── results/
│   └── R-001.json                 ← 从 worker-final-report.json 继承
├── reviews/
│   ├── test/
│   │   └── TV-001.json            ← 从 review-result.json 继承
│   └── arch/
│       └── AV-001.json            ← HARNESS 新增（架构评估）
├── gates/
│   ├── gate-runner.sh             ← 从 orchestrator.py 的 gate 逻辑提取
│   ├── g-compile.sh               ← 从 preflight.py 的编译检查提取
│   ├── g-test.sh                  ← 从 preflight.py 的测试检查提取
│   ├── g-coverage.sh              ← HARNESS 新增
│   ├── g-static.sh                ← HARNESS 新增
│   ├── g-security.sh              ← HARNESS 新增
│   └── gate-results/              ← 从 gate 检查结果扩展
├── knowledge/
│   ├── failure_memory.jsonl       ← HARNESS 新增
│   ├── wal/                       ← HARNESS 新增
│   ├── insights.jsonl             ← HARNESS 新增
│   └── experience.md              ← HARNESS 新增
├── refs/                          ← 从 main 分支的 6 个知识文件继承
│   ├── global-semantics.md
│   ├── payment-channel-config-sql-baseline.md
│   ├── business-decision-checklist.md
│   ├── config-surface-checklist.md
│   ├── payment-platform-switch-audit-checklist.md
│   └── enum-registry-baseline.md
├── logs/
│   └── events.jsonl               ← 从 state-contracts 的日志机制扩展
├── hooks/
│   ├── on-phase-change.sh         ← HARNESS 新增
│   └── on-gate-fail.sh            ← HARNESS 新增
├── scripts/                       ← 从 state-contracts 的 38 个脚本继承
│   ├── orchestrator.py            ← 通用化改造
│   ├── phase-handoff.py           ← 通用化改造
│   ├── preflight.py               ← 通用化改造
│   ├── plan-next-action.py        ← 不变
│   └── ...                        ← 其余脚本按需通用化
├── schemas/                       ← 从 state-contracts 的 13 个 Schema 继承
│   ├── spec-state.schema.json
│   ├── task-manifest.schema.json
│   ├── worker-final-report.schema.json
│   ├── review-result.schema.json
│   └── ...
├── prompts/                       ← 从 state-contracts 的 9 个 prompt 继承
│   ├── harness-governor.md        ← 从 main-orchestrator-prompt.md 改造
│   ├── requirement-engineer.md    ← 从 spec-agent-prompt.md 改造
│   ├── spec-architect.md          ← 从 plan-agent-prompt.md 改造
│   ├── coding-worker.md           ← 从 worker-node-prompt.md + code-agent-prompt.md 合并
│   ├── test-evaluator.md          ← 从 review-node-prompt.md + prove-agent-prompt.md 合并
│   ├── arch-evaluator.md          ← HARNESS 新增
│   └── knowledge-curator.md       ← HARNESS 新增
└── config/
    ├── capabilities.yaml          ← 从 state-contracts 继承
    └── workspace.template.json    ← 从 payment-workspace.template.json 通用化
```

---

## 六、实现路线图（基于 state-contracts 增量改造）

### Phase 1: 基线迁移（1-2 天）

| 任务 | 说明 | 来源 |
|------|------|------|
| 将 state-contracts 的 .payment-skill/ 迁移为 .harness/ | 目录重命名 + 结构调整 | state-contracts |
| 通用化 orchestrator.py | 去除支付渠道硬编码，保留编排逻辑 | state-contracts |
| 通用化 phase-handoff.py | 去除支付渠道硬编码，保留交接逻辑 | state-contracts |
| 通用化 preflight.py | 去除支付渠道硬编码，保留检查逻辑 | state-contracts |
| 迁移 13 个 JSON Schema | 去除支付渠道特化字段 | state-contracts |
| 迁移 9 个 role prompts | 按角色映射表重命名和调整 | state-contracts |

### Phase 2: 架构增强（2-3 天）

| 任务 | 说明 | 来源 |
|------|------|------|
| 补充 6 个 gate 脚本 | 从 Python 提取为独立 shell 脚本 | state-contracts preflight.py |
| 实现 G-REQ-01/02 | requirement.md Schema 校验 + 可测试性检查 | HARNESS 新增 |
| 实现 G-CODE-03/04 | 覆盖率 + 静态扫描门禁 | HARNESS 新增 |
| 实现 G-TEST-02 | 安全扫描门禁 | HARNESS 新增 |
| 实现 G-ARCH-01/02/03 | 架构原则门禁 | HARNESS 新增 |
| 拆分 review-node 为 test-evaluator + arch-evaluator | 双 Agent 审查 | HARNESS 增强 |

### Phase 3: 经验循环（2-3 天）

| 任务 | 说明 | 来源 |
|------|------|------|
| 实现 failure_memory.jsonl | 门禁失败偏航记录 | HARNESS 新增 |
| 实现 WAL（Write-Ahead Log） | 知识写入原子性 | HARNESS 新增 |
| 实现 experience.md | 项目级经验库 | HARNESS 新增 |
| 实现 knowledge-curator 角色 | 知识管理员 Agent | HARNESS 新增 |
| 实现经验注入机制 | 下次任务自动引用经验 | HARNESS 新增 |
| 实现衰减审计 | 月度清理过期经验 | HARNESS 新增 |

### Phase 4: 流程集成（1-2 天）

| 任务 | 说明 | 来源 |
|------|------|------|
| 实现 harness-team SKILL.md | 入口 Skill（启动/恢复） | HARNESS 新增 |
| 实现 3 个人类审批点 | 需求/Spec/最终验收 | HARNESS 新增 |
| 实现打回机制 | 失败计数 + 升级触发 | HARNESS 新增 |
| 实现 on-phase-change.sh | 阶段切换 hook | HARNESS 新增 |
| 实现 on-gate-fail.sh | 门禁失败 hook | HARNESS 新增 |

### Phase 5: 试运行与调优（持续）

| 任务 | 说明 |
|------|------|
| 选一个小需求跑完 10 步全流程 | 验证端到端可行性 |
| 记录每个阶段的耗时和问题 | 优化瓶颈 |
| 调整门禁阈值 | 避免过度阻塞或过度放行 |
| 积累经验库 | 让系统越用越好 |

---

## 七、工作量对比

| 方案 | 工作量 | 风险 |
|------|--------|------|
| **旧方案（从零重写）** | 8-12 天 | 高：重新实现已验证的逻辑 |
| **新方案（基于 state-contracts 增量改造）** | 6-10 天 | 低：复用已验证的编排框架 |

节省的工作量：
- 编排脚本：省去 38 个脚本的重写（~5000 行 Python）
- JSON Schema：省去 13 个 Schema 的重定义
- 角色 Prompts：省去 9 个 prompt 的重写
- 测试套件：省去 113 个测试的重写
- 交接合约：省去 5 个 handoff JSON 的重设计

新增的工作量：
- 经验循环（failure_memory + WAL + 衰减）：~2 天
- 通用化改造（去除支付渠道硬编码）：~1-2 天
- 人类审批点 + 打回机制：~1 天
- 新增 2 个角色（arch-evaluator + knowledge-curator）：~1 天

---

## 八、关键决策记录

### 决策 D-001：基线选择
- **选择**：state-contracts 作为实现基线
- **理由**：95% 完成的生产级编排框架，有 113 个测试验证，作者完全理解内部实现
- **放弃**：variant/variant-v2（vibe coding 产物，作者无法控制内部细节）
- **放弃**：从零重写 shell 脚本（重复造轮子）

### 决策 D-002：脚本 vs 模型的职责边界
- **脚本做硬约束**：编译/测试/覆盖率/状态机/恢复/门禁执行
- **模型做软判断**：需求质量/架构合理性/知识提取/验收标准解读
- **理由**：确定性操作必须脚本实现，非确定性判断交给模型

### 决策 D-003：领域知识策略
- **来源**：main 分支已有 6 个知识文件
- **策略**：直接继承，不重新提取
- **扩展**：按 01-10 分类骨架按需填充，不急于一次性完成
