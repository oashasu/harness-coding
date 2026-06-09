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
```

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

## 验证安装

```bash
python3 <skill_root>/.harness/scripts/preflight.py \
  --stage REQ_DRAFT \
  --state-file .harness/state/harness-state.json
```

期望结果：`BLOCKER: 0项`（WARNING 为正常）

## 下一步

安装完成后，参阅 [quickstart.md](quickstart.md) 开始第一个任务。
