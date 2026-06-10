# 安装指南

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|----------|------|
| Python | 3.9+ | 所有 `.harness/scripts/` 脚本 |
| Node.js | 18+ | `tools/knowledge-mcp/` 知识库 MCP 服务（可选） |
| Git | 2.x | 版本管理 |

## Python 依赖

```bash
pip install jsonschema pyyaml
```

| 包 | 用途 |
|----|------|
| `jsonschema` | 状态文件 Schema 校验（orchestrator、preflight） |
| `pyyaml` | DAG 蓝图配置解析（dag_blueprint.py、preflight.py） |

其他脚本使用标准库（`json`, `pathlib`, `subprocess`, `hmac`），无需额外安装。

验证：

```bash
python3 -c "import jsonschema, yaml; print('依赖 OK')"
```

## Node 依赖（可选，仅 knowledge-mcp）

```bash
cd tools/knowledge-mcp
npm install
```

知识库 MCP 服务为可选组件，不影响主流程的使用。

## 获取 Skill

```bash
git clone <仓库地址>
cd harness-coding
./scripts/bootstrap.sh          # 装齐 Python 依赖并自检
```

> 完整安装动线：clone → bootstrap → init-workspace → 注册 skill → 重启验证 `/harness-router` 出现。

## 初始化工作区

在**项目目录**下（需要 HARNESS 管理的代码仓库）运行：

```bash
python3 <skill_root>/.harness/scripts/init-workspace.py --workspace .
```

其中 `<skill_root>` 是本仓库的路径。

init-workspace.py 会创建：

```
.harness/
├── state/
│   ├── harness-state.json      ← 初始状态文件
│   └── SESSION_BRIEF.md        ← 阶段简报（phase-handoff 后自动更新）
├── output/
├── archive/
├── handoff/
├── logs/
└── knowledge/
    ├── experience.md
    ├── failure_memory.jsonl
    └── wal/
```

如果工作区已存在（`.harness/state/harness-state.json` 已有），会提示已初始化。
使用 `--force` 可覆盖模板文件（不清空 `archive/` 和 `knowledge/`）。

## 注册 Skill 到 Claude Code（过渡步骤）

仅完成上面两步后，`/harness-router` 还**不会**出现——Claude Code 只识别项目内
`.claude/skills/<name>/SKILL.md` 和 `.claude/agents/*.md`。需要把本仓库的 skill 与
agent 拷进项目的 `.claude/` 目录：

```bash
# 在项目目录下执行；<skill_root> 是本仓库路径
mkdir -p .claude/skills .claude/agents
cp -R <skill_root>/skills/* .claude/skills/
cp <skill_root>/.claude/agents/*.md .claude/agents/
```

拷贝后**重启 Claude Code**，`/harness-router` 才会出现在命令列表中。

> 过渡说明：此手动拷贝步骤是临时方案。插件化（见
> [harness-skill-market-packaging.md](harness-skill-market-packaging.md)）落地后，
> skills/ 与 agents/ 将由插件机制自动发现，此步骤会被取代删除。

## 验证安装

```bash
python3 <skill_root>/.harness/scripts/preflight.py \
  --stage REQ_DRAFT \
  --state-file .harness/state/harness-state.json
```

期望结果：`BLOCKER: 0项`（WARNING 为正常）

再在 Claude Code 里输入 `/harness-router`，确认 skill 已注册、能正常唤起。

## 下一步

安装完成后，参阅 [quickstart.md](quickstart.md) 开始第一个任务。
