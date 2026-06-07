# HARNESS 经验循环设计

> state-contracts 没有的部分，HARNESS 全新设计

---

## 一、设计目标

让 AI 编码系统**越用越稳**：每次任务完成后，自动沉淀经验，下次任务自动引用，避免重复犯错。

核心闭环：
```
任务完成 → 提取经验 → 写入知识库 → 下次任务引用 → 任务完成 → ...
```

---

## 二、数据结构

### 2.1 failure_memory.jsonl（偏航记录）

每行一条，追加写入，不可修改。

```json
{
  "id": "FM-001",
  "timestamp": "2026-06-07T14:30:00Z",
  "task_id": "T-001",
  "gate_id": "G-CODE-01",
  "phase": "gen",
  "failure_type": "compilation_error",
  "description": "缺少 import com.example.util.DateUtils",
  "root_cause": "coding-worker 未检查项目已有的工具类",
  "resolution": "添加 import 语句",
  "retry_count": 1,
  "resolved_at": "2026-06-07T14:35:00Z",
  "agent": "coding-worker"
}
```

字段说明：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | 是 | 自增 ID |
| timestamp | ISO8601 | 是 | 失败时间 |
| task_id | string | 是 | 关联任务 ID |
| gate_id | string | 是 | 失败门禁 ID |
| phase | string | 是 | 所属阶段 |
| failure_type | string | 是 | 失败类型枚举 |
| description | string | 是 | 失败描述 |
| root_cause | string | 否 | 根因分析（Agent 填写） |
| resolution | string | 否 | 解决方式 |
| retry_count | int | 是 | 第几次重试 |
| resolved_at | ISO8601 | 否 | 解决时间 |
| agent | string | 是 | 执行 Agent |

failure_type 枚举：
```
compilation_error     编译失败
test_failure          测试失败
coverage_insufficient 覆盖率不足
static_scan           静态扫描问题
security_scan         安全扫描问题
schema_violation      Schema 校验失败
spec_mismatch         与 Spec 不符
architecture_violation 架构原则违反
rework_required       需要返工
```

### 2.2 experience.md（项目级经验库）

人类可读的经验文档，由 knowledge-curator 从 failure_memory 提炼。

```markdown
# 项目经验库

> 自动维护，人工可编辑。最后更新: 2026-06-07

## 正向经验

### EXP-P001: Spec 中明确定义错误码后实现返工率降低
- 来源: T-001, T-003 任务对比
- 验证次数: 3
- 可信度: HIGH

### EXP-P002: 跨包调用走接口层后架构门禁通过率提升
- 来源: G-ARCH-03 门禁失败分析
- 验证次数: 5
- 可信度: HIGH

## 负向经验

### EXP-N001: 未定义接口超时时间导致测试阶段遗漏
- 来源: T-002, G-TEST-01 失败
- 验证次数: 2
- 可信度: MEDIUM
- 建议: Spec 阶段必须检查超时配置

## 偏航模式

### EXP-D001: 编码前未搜索已有工具类
- 门禁: G-CODE-01
- 失败次数: 4
- 根因: coding-worker 缺少 pre-implementation search
- 修复: 在 task_brief.md 中列出相关工具类
```

### 2.3 insights.jsonl（洞察记录）

由 L2 Insight 层自动检测生成。

```json
{
  "id": "INS-001",
  "timestamp": "2026-06-07T15:00:00Z",
  "insight_type": "recurring_failure_cluster",
  "description": "G-CODE-01 在 T-001, T-003, T-005 连续失败",
  "affected_gates": ["G-CODE-01"],
  "affected_tasks": ["T-001", "T-003", "T-005"],
  "severity": "HIGH",
  "recommended_action": "升级到 harness-governor 人工介入"
}
```

insight_type 枚举：
```
recurring_failure_cluster  同一门禁连续失败 N 次
co_edit_cluster            频繁修改同一文件（设计不稳定）
override_drift             人类频繁修改 AI 输出（需求理解偏差）
user_correction_pattern    人类纠正模式识别
coverage_trend             覆盖率下降趋势
```

### 2.4 WAL（Write-Ahead Log）

保证经验写入的原子性。

```
knowledge/wal/
├── WAL-001.pending    # 待处理
├── WAL-001.applied    # 已应用
└── WAL-001.failed     # 失败
```

WAL 条目格式：
```json
{
  "wal_id": "WAL-001",
  "timestamp": "2026-06-07T15:30:00Z",
  "operation": "append",
  "target": "failure_memory.jsonl",
  "data": { ... },
  "status": "pending"
}
```

---

## 三、经验衰减机制

### 3.1 衰减规则

每条经验有 decay_score，随时间衰减：

```
初始值: 1.0
每次被引用: +0.2（上限 1.0）
每月未使用: -0.1
```

### 3.2 审计规则（每月执行）

| 条件 | 动作 |
|------|------|
| decay_score < 0.3 且 use_count < 3 | 候选删除 |
| 多条相似经验 | consolidate 合并 |
| 经验被新实践推翻 | replace 替换 |
| decay_score >= 0.5 且 use_count >= 5 | 升级为项目规范 |

### 3.3 经验条目格式

```json
{
  "experience_id": "EXP-001",
  "type": "positive",
  "content": "Spec 中明确定义错误码后，实现阶段返工率降低",
  "source": "T-001 vs T-003 对比分析",
  "created_at": "2026-06-07",
  "last_used": "2026-06-07",
  "use_count": 1,
  "decay_score": 1.0,
  "action": "keep"
}
```

action 枚举：keep | update | consolidate | replace | delete

---

## 四、经验注入机制

### 4.1 注入点

| Agent | 注入时机 | 注入内容 |
|-------|---------|---------|
| requirement-engineer | 写需求前 | 负向经验（需求阶段常见遗漏） |
| spec-architect | 写 Spec 前 | 偏航模式（Spec 常见缺陷） |
| coding-worker | 写代码前 | 正向经验 + 偏航模式（实现最佳实践） |
| test-evaluator | 审查前 | 历史门禁失败原因 |
| arch-evaluator | 审查前 | 架构违规历史 |

### 4.2 注入格式

在 task_brief.md 中追加经验引用：

```yaml
experience_refs:
  - id: "EXP-P001"
    relevance: "错误码定义相关"
    content: "Spec 中明确定义错误码后，实现阶段返工率降低"
  - id: "EXP-D001"
    relevance: "编码前搜索相关"
    content: "编码前未搜索已有工具类导致编译失败"
```

---

## 五、knowledge-curator 工作流程

### 5.1 触发条件

- 任务完成（harness-governor 验收通过）
- 门禁失败 ≥ 3 次（自动触发偏航记录）
- 月度衰减审计（定时触发）

### 5.2 Archive 流程

```
任务完成
    │
    ▼
knowledge-curator 启动
    │
    ├── 1. 读取 failure_memory.jsonl 本次任务的记录
    ├── 2. 读取 reviews/ 本次任务的审查报告
    ├── 3. 读取 gate-results/ 本次任务的门禁结果
    │
    ▼
写入 WAL (knowledge/wal/)
    │
    ▼
提炼经验条目
    │
    ├── 正向经验: 成功模式 → experience.md
    ├── 负向经验: 失败教训 → experience.md
    └── 偏航模式: 重复失败 → experience.md
    │
    ▼
更新 failure_memory 的 root_cause 和 resolution
    │
    ▼
清理过期 WAL 条目
```

### 5.3 输出

- 更新 `knowledge/experience.md`
- 追加 `knowledge/failure_memory.jsonl`
- 追加 `knowledge/insights.jsonl`
- 清理 `knowledge/wal/` 已处理条目

---

## 六、与 harness-governor 的集成

### 6.1 经验循环管理职责

harness-governor 在以下时机触发 knowledge-curator：

```
任务验收通过 → 触发 Archive（正常经验沉淀）
门禁失败 ≥ 3 次 → 触发偏航记录（紧急经验沉淀）
月度审计 → 触发衰减清理（经验维护）
```

### 6.2 打回升级机制

```
同一门禁失败 ≥ 3 次:
  → knowledge-curator 记录偏航模式
  → harness-governor 读取 insights.jsonl
  → 决策: 继续重试 / 人工介入 / 调整策略

同一任务总打回 ≥ 5 次:
  → 触发 experience.md 更新
  → harness-governor 暂停任务
  → 呈现偏航报告给人类
```

---

## 七、文件清单

```
.harness/knowledge/
├── failure_memory.jsonl    # 偏航记录（追加写入）
├── experience.md           # 项目级经验库（可编辑）
├── insights.jsonl          # 洞察记录（自动生成）
└── wal/                    # Write-Ahead Log
    └── .gitkeep
```

---

## 八、实现优先级

| 组件 | 优先级 | 说明 |
|------|--------|------|
| failure_memory.jsonl | P0 | 偏航记录是基础 |
| WAL 机制 | P0 | 保证写入原子性 |
| knowledge-curator Agent | P0 | 经验沉淀执行者 |
| experience.md | P1 | 人类可读的经验库 |
| 经验注入机制 | P1 | 下次任务引用经验 |
| insights.jsonl | P2 | 自动洞察检测 |
| 衰减审计 | P2 | 月度维护 |
