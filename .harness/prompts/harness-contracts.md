# HARNESS Prompt 契约汇总

本文档汇总 HARNESS 系统中所有 Agent 的契约约束和禁止行为。

---

## 一、Coding Worker 契约

### 1.1 输入边界

**只消费 manifest 声明的 inputs**：

- `inputs.spec_file`
- `inputs.task_brief`
- `inputs.dispatch_dir`
- `inputs` 中声明的其他字段
- `expected_outputs`
- `prerequisites`
- manifest 中明确声明的其他字段

**禁止行为**：

1. 不得要求主线程额外拼接长上下文替代 manifest。
2. 不得读取与当前任务无关的历史 Prompt、历史会话或其他节点产物（除非 manifest 明确声明）。
3. 不得读取 manifest 未声明的输入文件。

### 1.2 执行边界

**只处理当前 execution_unit**：

1. `task_scope=step` 时，只交付当前步骤产物。
2. `task_scope=sub_task` 时，只交付当前 sub_task 对应的单个产物。
3. 只修改 manifest 允许的产物范围。
4. 返工时只处理 Review result 或门禁脚本结果列出的阻塞项和最小修复范围。

**禁止行为**：

1. 不得修改 `.harness/state/pipeline.json`。
2. 不得修改 `.harness/state/task-queue.json`。
3. 不得推进步骤或 checkpoint。
4. 不得宣布步骤完成或门禁通过。
5. 不得跳过 Review。

### 1.3 输出契约（harness-worker-report.v1.schema.json）

| 字段 | 类型 | 约束 |
|------|------|------|
| `manifest_version` | const | 必须为 `"1.0"` |
| `task_id` | string | 必须等于 manifest 中的 `task_id` |
| `task_scope` | enum | 只允许 `"step"` 或 `"sub_task"` |
| `step` | string | 对应 10 步流程中的一步 |
| `execution_unit` | string | 非空，对应当前执行单元 |
| `worker_status` | enum | 只允许 `"completed"` / `"failed"` / `"blocked"` |
| `summary` | string | **maxLength=500 字符** |
| `changed_files` | array | **maxItems=50**，每项为文件路径字符串 |
| `generated_files` | array | **maxItems=50**，每项为文件路径字符串 |
| `commands` | array | **maxItems=20**，每项包含 `command`、`status`、可选 `log_path` |
| `test_status` | enum | 只允许 `"passed"` / `"failed"` / `"not_run"` |
| `compile_status` | enum | 只允许 `"passed"` / `"failed"` / `"not_run"` |
| `compile_command` | string | 编译命令，未运行时为空字符串 |
| `compile_log_path` | string | 编译日志路径 |
| `review_hints` | array | **maxItems=10**，每项 **maxLength=200 字符** |

**输出上限汇总**：

| 字段 | 上限 | 超出时收敛原则 |
|------|------|----------------|
| `summary` | **500 字符** | 截断至 500 字符，末尾添加 "...（已截断）" |
| `changed_files` | **50 项** | 只保留前 50 个文件路径 |
| `generated_files` | **50 项** | 只保留前 50 个文件路径 |
| `commands` | **20 项** | 只保留前 20 条命令，优先保留 `failed` 状态命令 |
| `review_hints` | **10 项**，每项 **200 字符** | 只保留前 10 条提示，每条截断至 200 字符 |

---

## 二、Test Evaluator 契约

### 2.1 只读纪律

**禁止行为**：

1. 不得修改代码。
2. 不得修改状态文件。
3. 不得推进步骤或 checkpoint。
4. 不得补丁式修复问题。
5. 不得把建议列表伪装成已修复结果。

### 2.2 输入边界

**只读取 manifest 声明产物**：

- 当前 task manifest（`harness-task-manifest.v1.schema.json`）
- Worker final report（`harness-worker-report.v1.schema.json`）
- manifest 声明的输入和产物
- `.harness/spec/` 下的 Spec 文档和 R-ID 定义
- 必要的门禁脚本结果或编译结果

**禁止行为**：

1. 不得扩展审查到无关步骤。
2. 不得扩展审查到无关 sub_task。
3. 不得审查未在 manifest 中声明的目标。

### 2.3 输出契约（harness-review-result.v1.schema.json）

| 字段 | 类型 | 约束 |
|------|------|------|
| `manifest_version` | const | 必须为 `"v1"` |
| `task_id` | string | 必须等于 manifest 中的 `task_id` |
| `task_scope` | enum | 只允许 `"step"` 或 `"sub_task"` |
| `step` | string | 对应 10 步流程中的一步 |
| `execution_unit` | string | 非空，对应当前执行单元 |
| `review_status` | enum | 只允许 `"accept"` / `"rework"` / `"needs_governor"` |
| `summary` | string | **maxLength=500 字符** |
| `report_path` | string | 非空，详细审查报告路径 |
| `rework_items` | array | `review_status=rework` 时必填，**maxItems=10** |
| `escalation_reason` | string | `review_status=needs_governor` 时必填 |
| `rid_coverage` | object | R-ID 覆盖率（可选） |
| `patch_allowed` | boolean | 是否允许 patch-based 修复 |
| `reviewer` | string | 审查者标识 |
| `reviewed_at` | string | ISO 8601 时间戳 |

### 2.4 review_status 判定语义

| review_status | 语义 |
|---------------|------|
| `accept` | 当前执行单元已满足 manifest 目标，R-ID 覆盖完整，且没有阻断后续门禁的问题 |
| `rework` | 当前执行单元存在可修复问题，必须提供 `rework_items` |
| `needs_governor` | 问题超出 Reviewer 处理范围，需要 Governor 决策 |

### 2.5 patch_allowed 判定规则

| patch_allowed | 适用场景 |
|---------------|----------|
| `true` | 问题限于命名、导入、格式、局部字段漏补、小范围编译错误等**少量细节** |
| `false` | 问题涉及核心产物缺失、跨 sub_task 误改、严重越权等**较大问题** |

---

## 三、Arch Evaluator 契约

### 3.1 只读纪律

与 Test Evaluator 相同。

### 3.2 审查职责

1. **G-ARCH-01**：架构原则检查（分层、依赖方向、SOLID）
2. **G-ARCH-02**：错误码规范合规
3. **G-ARCH-03**：跨包调用规范合规
4. **安全扫描**：SQL 注入、XSS、硬编码密钥等
5. **接口契约一致性**：与 spec/interfaces/ 对比

### 3.3 输出契约

与 Test Evaluator 相同的 harness-review-result.v1.schema.json，额外包含：

| 字段 | 类型 | 约束 |
|------|------|------|
| `gate_results` | object | 各门禁检查结果（G-ARCH-01/02/03） |
| `violations` | array | 违规项列表 |

---

## 四、Harness Governor 契约

### 4.1 唯一决策权

**只有 Harness Governor 可以决定**：

1. 当前 10 步流程中的哪一步正在执行。
2. 当前唯一允许动作是什么。
3. 当前应构建哪一种 task manifest。
4. 当前应派发给哪个 Worker。
5. 当前是否必须派发 Review。
6. 当前是否进入返工、主线程少量修补、主线程 solo 接手或门禁执行。
7. 当前是否允许切步骤、推进 checkpoint 或等待用户动作。
8. 当前是否触发经验循环。
9. 当前是否需要人类审批。

### 4.2 task manifest 契约（派单真相源）

**必须符合 harness-task-manifest.v1.schema.json**：

| 字段 | 类型 | 约束 |
|------|------|------|
| `manifest_version` | const | 必须为 `"1.0"` |
| `task_scope` | enum | 只允许 `"step"` 或 `"sub_task"` |
| `step` | string | 对应 10 步流程中的一步 |
| `execution_unit` | string | 非空，执行单元标识 |
| `req_id` | string | 需求 ID |
| `task_id` | string | 格式：`^harness:[a-z]+:[a-z0-9_]+:[a-z0-9_-]+$` |
| `dispatch_role` | enum | `"coding-worker"` / `"test-evaluator"` / `"arch-evaluator"` |
| `review_role` | enum | `"test-evaluator"` / `"arch-evaluator"` |
| `inputs` | object | 任务输入参数 |
| `expected_outputs` | array | Worker 必须产出的文件列表，**minItems=1** |

### 4.3 默认执行链

```
Harness Governor
  -> read pipeline.json / dispatch / handoff
  -> build task manifest
  -> dispatch coding-worker
  -> collect Worker final report
  -> dispatch test-evaluator + arch-evaluator (并行)
  -> collect review results
  -> decide rework / small fix / solo takeover / gate
  -> run gate scripts
  -> update pipeline.json / emit checkpoint / wait user action
  -> trigger knowledge-curator (任务完成后)
```

### 4.4 少量修补边界

**仅限以下情况且 `patch_allowed=true`**：

- 命名、导入、格式、局部字段漏补。
- 小范围编译错误。
- Review 指出的单点修正。
- 不改变节点方案的局部补丁。

**修补范围必须局限在 Review result 或门禁脚本输出指出的具体缺口。**

---

## 五、Knowledge Curator 契约

### 5.1 输入边界

- 当前任务的全部产物（代码、Spec、Review 结果、门禁结果）
- `.harness/state/pipeline.json`（任务元数据）
- 已有的 `failure_memory.jsonl` 和 `experience.md`

### 5.2 输出契约

| 产物 | 操作 | 格式 |
|------|------|------|
| `failure_memory.jsonl` | 追加 | JSONL，每行一个 JSON 对象 |
| `experience.md` | 更新 | Markdown，结构化经验库 |
| `insights.jsonl` | 追加 | JSONL，自动生成的洞察 |

### 5.3 WAL 机制

所有写入必须先写 WAL，再更新目标文件，确保原子写入。

---

## 六、禁止行为汇总

### Coding Worker 禁止行为

1. 不得修改状态文件（pipeline.json）。
2. 不得推进 checkpoint。
3. 不得输出不符合 `harness-worker-report.v1.schema.json` 的 JSON。
4. 不得超出输出上限（500 字符 / 50 项 / 20 项 / 10 项）。
5. 不得跳过 Review。

### Test Evaluator 禁止行为

1. 不得修改代码。
2. 不得修改状态文件。
3. 不得推进 checkpoint。
4. 不得输出不符合 `harness-review-result.v1.schema.json` 的 JSON。
5. 不得审查 manifest 未声明的目标。

### Arch Evaluator 禁止行为

与 Test Evaluator 相同。

### Harness Governor 禁止行为

1. 禁止跳过 Review 直接放行 Worker 结果。
2. 禁止手工推进状态、手工改写步骤或节点结论。
3. 禁止把 Worker final report 当成完成声明。
4. 禁止把 Review result 当成门禁通过。
5. 禁止在两轮返工不可用后继续无限返工。
6. 禁止让 Worker 或 Review 修改最终状态文件。
7. 禁止在主线程承担大规模编码或大规模搜证。

### Knowledge Curator 禁止行为

1. 不得修改代码文件。
2. 不得修改 pipeline.json 的步骤状态。
3. 不得删除已有的经验记录（只追加和更新）。
