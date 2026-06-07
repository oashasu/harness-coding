# Phase-Handoff 机制分析与 Harness 设计文档

> 源文件: `.payment-skill/scripts/phase-handoff.py` (1132行)
> 分支: `origin/feat/payment-workflow-state-contracts`
> 分析日期: 2026-06-07

---

## 1. Handoff 机制：阶段过渡工作原理

### 1.1 阶段生命周期

脚本定义了一个线性5阶段流水线：

```
prep -> spec -> prove -> gen -> final -> DONE
```

`PHASE_ORDER = ["prep", "spec", "prove", "gen", "final"]`

每个阶段都有 `phase_status` 字段，取值为 `pending | in_progress | completed`。阶段推进的入口是 `--from-phase` 参数，目标阶段默认为下一个阶段（`next_phase_for()`），也可显式指定 `--to-phase`。

### 1.2 阶段过渡的两种模式

**模式A：Checkpoint 等待授权模式**

当某阶段完成时，通过 `--checkpoint` 写入一个检查点，同时设置 `awaiting_user_action=true`，暂停流水线等待人工决策。用户通过 `--user-action` 传入允许的动作编号来恢复。

```
spec完成 -> --checkpoint spec-ok -> 等待用户动作 -> 用户选择 continue_prove_resolvable -> 进入prove
```

**模式B：直接推进模式**

通过 `--advance-state --user-action <action>` 直接推进到下一阶段，跳过等待。

### 1.3 阶段间传递的数据（Handoff 包）

`build_context_package()` 生成一个 JSON 文件写入 `.payment-skill/handoff/{source}-to-{target}.json`，结构如下：

```json
{
  "context_package": {
    "version": "1.0",
    "source_phase": "spec",
    "target_phase": "prove",
    "created_at": "ISO-8601",
    "artifacts": {
      "state_file": "相对路径",
      "required_artifacts": ["产物路径列表"]
    },
    "context_summary": {
      "institution_code": "收单机构编码",
      "institution_mode": "模式",
      "current_phase": "当前阶段",
      "last_checkpoint": "最近检查点",
      "awaiting_user_action": false,
      "allowed_actions": [],
      "open_questions": 0,
      "resolved_questions": 0,
      "business_fact_validation_passed": true,
      "scene_coverage_passed": true
    },
    "resume_first_prompt": "恢复后的首条提示词",
    "handoff_token": "spec-prove-ICBCODE-20260607120000"
  }
}
```

**关键发现**：handoff 包是只读上下文快照，不包含状态文件的完整副本。下一阶段通过 `state_file` 引用读取最新状态。

### 1.4 SESSION_BRIEF 机制

`write_session_brief()` 生成一个 Markdown 摘要文件 `.payment-skill/state/SESSION_BRIEF.md`，供新会话快速了解当前上下文。包含：

- 机构信息、当前阶段、最近检查点
- `resume_context` 的全部6个字段
- 恢复后的首条提示词（`resume_first_prompt`）
- 防护栏规则（Guardrail）

---

## 2. State Sealing：状态封印与完整性校验

### 2.1 HMAC-SHA256 签名机制

状态文件通过 `state_integrity.py` 模块实现完整性保护：

**签名过程** (`seal_state`)：
1. 从工作区根目录推断密钥文件路径 `.payment-skill/state/.payment-state.integrity.key`
2. 若密钥不存在，自动生成 64 字符随机十六进制密钥
3. 将状态对象 canonicalize：移除 `integrity` 字段，JSON 序列化，`sort_keys=True`，紧凑分隔符
4. 用 `hmac.new(key, canonical, hashlib.sha256)` 计算 HMAC
5. 写入 `integrity` 字段：

```json
{
  "integrity": {
    "version": "1.0",
    "algorithm": "HMAC-SHA256",
    "key_fingerprint": "sha256前16位",
    "signed_at": "ISO-8601",
    "state_hmac": "完整hmac hex"
  }
}
```

**验证过程** (`verify_state_integrity`)：
1. 检查 `integrity` 字段结构完整性
2. 校验 version/algorithm 与常量匹配
3. 校验 key_fingerprint 与当前工作区密钥一致
4. 重新计算 HMAC 并比对

### 2.2 Sealed Save 流程

`save_state_json()` 在每次写入状态文件前自动 seal：
- 正常路径：`seal_state()` -> `save_json()`
- 降级路径：如果 seal 失败（如密钥问题），直接写入原始数据（移除 integrity 字段）

### 2.3 Handoff 前的完整性验证

`validate_handoff()` 调用链：
1. `validate_state_schema()` - JSON Schema 校验 + HMAC 完整性校验
2. `validate_transition_control_plane()` - 控制面一致性校验
3. 阶段特定门禁校验（产物存在性、Schema 合规性）

**设计要点**：完整性校验失败会直接阻断 handoff，不允许带病推进。

---

## 3. Resume Capability：resume_context 的6个字段

### 3.1 字段定义

`update_resume_context()` 构建 `resume_context` 对象，包含6个字段：

| 字段 | 类型 | 含义 |
|------|------|------|
| `current_execution_unit` | string | 当前执行单元。gen阶段=具体节点ID（如G01），其他阶段=阶段名 |
| `next_required_action` | string | 恢复后必须执行的下一个动作 |
| `required_script` | string | 对应的脚本命令 |
| `pending_checkpoint` | string | 等待中的检查点名，无等待时为"NONE" |
| `resume_first_prompt` | string | 恢复后给AI的首条提示词 |
| `last_review_status` | string | 最近一次审查状态：pending/approved/rework_required/rejected |

### 3.2 next_required_action 的取值模式

| 模式 | 示例 | 含义 |
|------|------|------|
| `run_preflight:{phase}` | `run_preflight:prove` | 需要先跑目标阶段的preflight校验 |
| `dispatch_gen_node_{id}` | `dispatch_gen_node_G03` | gen阶段需要派发特定节点 |
| `wait_for_user_action` | - | 等待人工决策 |
| `archive_runtime` | - | 终态，需要归档 |

### 3.3 Resume 首条提示词

`default_resume_first_prompt()` 根据当前状态生成不同的恢复引导：

- **终态**：提示工作流已结束，仅允许归档
- **等待授权态**：提示先读 SESSION_BRIEF，确认等待哪个 checkpoint，不要自行推进
- **gen 阶段**：提示先确认 gen 层状态与 handoff 包，再决定是否继续执行当前节点
- **其他阶段**：提示先跑 preflight，再根据 handoff 包进入下一阶段

### 3.4 resume_action_binding 验证

`validate_resume_action_binding()` 确保 resume_context 内部一致性：
- `next_required_action` 不能为空
- 终态时 action/script 必须匹配 `TERMINAL_PHASE_ACTIONS`
- preflight action 的阶段必须与 current_phase 一致
- gen 节点 action 必须与 current_execution_unit 一致

---

## 4. Payment-Specific Code：需要泛化的支付渠道专用代码

### 4.1 支付业务领域耦合

| 位置 | 代码 | 耦合度 | 说明 |
|------|------|--------|------|
| 收单机构模型 | `state["institution"]["code"]` / `state["institution"]["mode"]` | 高 | 贯穿全文，用于产物路径、handoff_token、SESSION_BRIEF |
| 产物路径模板 | `.payment-skill/output/{phase}/{code}/` | 高 | spec/prove/final产物都以机构编码为路径组件 |
| spec-business-facts | `SPEC_BUSINESS_FACTS_SCHEMA` | 高 | 支付收单业务事实专用Schema |
| prove-issue-routing | `PROVE_ISSUE_ROUTING_SCHEMA` | 高 | 支付路由兼容性专用Schema |
| final_report_contract | `validate_final_report()` | 高 | 固定文件名`12-生成后审核报告.md`，固定标题`# 12-生成后审核报告` |
| gen层节点映射 | `GEN_LAYER_NODE_MAP` / `GEN_NODE_PREREQS` | 中 | pojo_config_dto/dependency_provider/adapter_notify/admin_sql_i18n |
| 门禁上下文 | `business_fact_validation_passed` / `scene_coverage_passed` | 高 | 支付业务事实校验和场景覆盖校验 |
| allow_codegen | `phase_2.get("allow_codegen")` | 中 | 控制是否允许代码生成，YES/YES_WITH_WARNING |
| prove_routing_compat | `normalize_legacy_prove_routing_payload()` | 高 | 支付路由旧格式兼容转换 |

### 4.2 文件路径硬编码

```
.payment-skill/state/payment-workflow-state.json   # 状态文件
.payment-skill/handoff/                              # handoff包目录
.payment-skill/state/SESSION_BRIEF.md                # 会话摘要
.payment-skill/spec/schema/spec-business-facts.v1.schema.json
.payment-skill/spec/schema/prove-issue-routing.v1.schema.json
.payment-skill/scripts/orchestrator.py
.payment-skill/scripts/preflight.py
.payment-skill/scripts/archive-payment-workflow.py
.payment-skill/output/{phase}/{institution_code}/    # 产物目录
```

### 4.3 需要抽取的泛化点

1. **`institution` -> `project_context`**：将机构编码/模式泛化为项目上下文标识
2. **Schema 注册表**：将 spec/prove 的 Schema 路径从硬编码改为按阶段注册
3. **GEN_LAYER_NODE_MAP 外置**：gen 层的节点定义应由工作流配置驱动，不应硬编码
4. **final_report_contract 外置**：审核报告的验证逻辑应可插拔
5. **门禁条件参数化**：`business_fact_validation_passed`、`scene_coverage_passed`、`allow_codegen` 应定义为可配置的门禁条件

---

## 5. Generic Patterns：领域无关的手柄模式

### 5.1 阶段状态机

```python
PHASE_ORDER = ["prep", "spec", "prove", "gen", "final"]
# phase_status: pending -> in_progress -> completed
# current_phase 线性推进，next_phase_for() 计算后继
```

这是一个标准的线性阶段状态机，可泛化为任意N阶段流水线。

### 5.2 Checkpoint-Action 模式

```
阶段完成 -> 写入 checkpoint -> 等待用户动作 -> 从 allowed_actions 选择 -> 消费动作 -> 推进/回退/终止
```

核心组件：
- `CHECKPOINT_PHASE_MAP`：检查点到阶段的映射
- `CHECKPOINT_ACTIONS`：每个检查点的允许动作
- `ADVANCE_ACTIONS`：推进阶段的动作集合
- `derive_allowed_actions()`：根据当前状态动态裁剪可用动作

### 5.3 Handoff 包生成模式

```
校验当前阶段门禁 -> 构建上下文快照 -> 写入 handoff JSON -> (可选) 写 SESSION_BRIEF -> 推进状态
```

这是一个"先校验、再生成、后推进"的三段式模式，确保原子性。

### 5.4 临时文件清理模式

`cleanup_phase_temp()` 清理 `.cache`、`.scratch` 目录和 `.tmp`、`.log` 文件。按阶段隔离清理范围。

### 5.5 状态完整性保护模式

```
写入前 seal（HMAC-SHA256）-> 读取后 verify -> 不匹配则阻断
```

密钥按工作区隔离，通过 `key_fingerprint` 防止跨工作区误用。

### 5.6 控制面一致性验证模式

`validate_transition_control_plane()` 检查：
- `current_phase` 与 handoff 来源阶段一致（防状态漂移）
- `resume_context` 结构完整
- checkpoint/awaiting_user_action 状态一致性
- gen 阶段的 current_node 与 current_execution_unit 一致性

这是一个通用的"控制面 vs 数据面一致性校验"模式。

### 5.7 用户动作消费模式

```
检查 awaiting_user_action -> 验证 action 在 allowed_actions 中 -> 更新状态 -> 重置等待标记
```

`consume_user_action()` 实现了一个安全的动作消费协议，防止未授权的状态变更。

---

## 6. JSON Schema Validation：Handoff 包校验机制

### 6.1 三层校验体系

**第一层：状态文件 Schema 校验**

`validate_state_schema()` 加载 `payment-workflow-state.schema.json`，对状态文件做完整的 JSON Schema 验证。

**第二层：状态完整性 HMAC 校验**

`verify_state_integrity()` 验证 HMAC-SHA256 签名，确保状态文件未被篡改。

**第三层：产物 Schema 校验**

`validate_artifact_schema()` 对阶段产物做 JSON Schema 验证：
- spec 阶段 -> `spec-business-facts.v1.schema.json`
- prove 阶段 -> `prove-issue-routing.v1.schema.json`
- 对 prove 产物先做 `normalize_legacy_prove_routing_payload()` 旧格式兼容转换

### 6.2 jsonschema 降级处理

```python
try:
    import jsonschema
except ImportError:
    jsonschema = None
```

如果 `jsonschema` 库不可用，所有 Schema 校验返回错误信息但不阻断（返回字符串而非抛异常）。HMAC 校验不依赖 jsonschema，始终可用。

### 6.3 脚本化门禁校验

`validate_scripted_gates()` 除了 JSON Schema 校验外，还调用外部脚本：

1. **orchestrator.py**：对 spec/prove/gen/final 阶段运行编排器校验
2. **preflight.py**：对目标阶段运行预检校验

这两个脚本通过 `subprocess.run()` 调用，返回码为0表示通过。

### 6.4 Handoff 包本身的校验

handoff 包（`context_package`）**没有独立的 JSON Schema**。它是一个只读快照，不需要完整性签名。校验逻辑嵌入在 `validate_handoff()` 的阶段门禁中，确保生成 handoff 包之前所有前置条件已满足。

---

## 7. Harness 泛化建议

### 7.1 核心抽象层

```
WorkflowEngine (泛化)
  ├── PhaseStateMachine        # 从 PHASE_ORDER 抽取
  ├── CheckpointManager        # 从 CHECKPOINT_ACTIONS 抽取
  ├── HandoffGenerator         # 从 build_context_package 抽取
  ├── StateIntegrityGuard      # HMAC 机制直接复用
  ├── ResumeContextManager     # 从 resume_context 抽取
  └── GateValidator            # 从 validate_handoff 抽取

WorkflowConfig (可配置)
  ├── phases: List[PhaseConfig]
  ├── checkpoints: Dict[str, CheckpointConfig]
  ├── artifacts: ArtifactRegistry
  ├── schemas: SchemaRegistry
  └── gates: GateConditionRegistry
```

### 7.2 需要配置化的硬编码项

| 硬编码项 | 泛化方案 |
|----------|----------|
| `PHASE_ORDER` | `WorkflowConfig.phases` 列表 |
| `GEN_LAYER_NODE_MAP` / `GEN_NODE_PREREQS` | `PhaseConfig.gen_nodes` DAG 配置 |
| `CHECKPOINT_ACTIONS` / `ADVANCE_ACTIONS` | `CheckpointConfig.actions` 注册表 |
| `institution.code` | `ProjectContext.primary_key` |
| `SPEC_BUSINESS_FACTS_SCHEMA` / `PROVE_ISSUE_ROUTING_SCHEMA` | `SchemaRegistry[phase]` |
| `FINAL_REPORT_FILENAME` / 标题正则 | `FinalReportConfig` 可插拔 |
| `business_fact_validation_passed` 等门禁条件 | `GateCondition` 接口 |
| `.payment-skill/` 路径前缀 | `WorkspaceLayout` 配置 |
| `archive-payment-workflow.py` | `TerminalAction` 注册表 |

### 7.3 保留的核心机制（直接复用）

1. **HMAC-SHA256 状态封印** -- 与业务域无关
2. **resume_context 6字段模型** -- 通用恢复协议
3. **Checkpoint-Action 等待授权模式** -- 通用人机交互协议
4. **Handoff 包生成模式** -- 通用上下文传递
5. **SESSION_BRIEF 生成** -- 通用会话摘要
6. **控制面一致性校验** -- 通用状态漂移检测
7. **临时文件清理** -- 通用工作区维护
8. **jsonschema 降级策略** -- 通用容错
