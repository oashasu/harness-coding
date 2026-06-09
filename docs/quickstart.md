# 快速入门

本文引导你完成第一个任务的完整链路：初始化 → 校验状态 → 编排第一步。

**前置条件**：已完成 [install.md](install.md) 中的依赖安装和工作区初始化。

---

## 第一步：确认工作区状态

```bash
python3 <skill_root>/.harness/scripts/preflight.py \
  --stage REQ_DRAFT \
  --state-file .harness/state/harness-state.json
```

期望输出：

```
=== Preflight Check: REQ_DRAFT ===
...
[Result] BLOCKER: 0项，WARNING: N项
[Action] 通过preflight检查
```

有 WARNING 是正常的（`state_contract_version` 和 `last_checkpoint` 在初始状态下均为空）。

---

## 第二步：运行 orchestrator 校验

以 `plan` 阶段为例（plan 阶段只需要 plan-state.json，不依赖业务事实文件，适合快速验证）：

先创建一个最小 plan 状态文件：

```bash
cat > /tmp/my-plan.json << 'EOF'
{
  "batch_id": "my-first-task",
  "steps": [
    {
      "step_id": "step-1",
      "owner": "coding-worker",
      "depends_on": [],
      "reads": [],
      "writes": ["src/HelloWorld.java"],
      "checks": ["mvn compile -q"]
    }
  ]
}
EOF
```

运行 orchestrator：

```bash
python3 <skill_root>/.harness/scripts/orchestrator.py \
  --stage plan \
  --state-file /tmp/my-plan.json \
  --workdir <skill_root>
```

期望输出：

```
[Success] DAG 拓扑排序完成，无循环依赖。
=== 预期执行编排 ===
[1] step-1 | Owner: coding-worker | (首发)
```

---

## 阶段说明

HARNESS 工作流包含以下阶段，通过 preflight `--stage` 参数指定：

| 阶段 | 含义 |
|------|------|
| `REQ_DRAFT` | 需求草稿撰写 |
| `REQ_REVIEW` | 需求评审 |
| `SPEC_DRAFT` | 方案设计草稿 |
| `SPEC_REVIEW` | 方案评审 |
| `CODE_IMPL` | 编码实现 |
| `MACHINE_CHECK` | 机器检查（编译 / 测试 / 静态分析） |
| `DUAL_REVIEW` | 双重人工评审 |
| `FINAL_ACCEPT` | 最终验收 |
| `KNOWLEDGE_ARCHIVE` | 知识归档 |

orchestrator `--stage` 参数用于技术管道校验，与工作流阶段是不同维度：

| 参数 | 含义 |
|------|------|
| `plan` | DAG 编排计划校验 |
| `spec` | Spec 阶段产物校验 |
| `prove` | Prove 阶段产物校验 |
| `gen` | Gen 层节点状态校验 |
| `final` | Final 阶段产物校验 |

---

## 目录结构说明

```
<workspace>/.harness/
├── state/
│   ├── harness-state.json   ← 主状态文件（由 init 生成，运行时更新）
│   └── SESSION_BRIEF.md     ← 阶段简报（phase-handoff 自动维护）
├── output/                  ← preflight / orchestrator 输出
├── archive/                 ← 已完成任务的归档
├── handoff/                 ← 阶段移交包
├── logs/                    ← 运行日志
└── knowledge/
    ├── experience.md        ← 经验积累（knowledge-curator 维护）
    ├── failure_memory.jsonl ← 门禁失败记录
    └── wal/                 ← 经验写入流水
```

---

## 常见问题

**Q：preflight 报 `allow_codegen非法`**  
A：状态文件缺少 `artifacts.phase_2.allow_codegen`。运行 `init-workspace.py` 重新生成，或手动添加：
```json
"artifacts": { "phase_2": { "allow_codegen": "UNSET" } }
```

**Q：orchestrator 报 `invalid choice: 'prep'`**  
A：orchestrator 的 `--stage` 参数只接受 `plan/spec/prove/gen/final`，不是工作流阶段名。

**Q：preflight 报 `状态文件不存在`**  
A：工作区未初始化，运行：
```bash
python3 <skill_root>/.harness/scripts/init-workspace.py --workspace .
```
