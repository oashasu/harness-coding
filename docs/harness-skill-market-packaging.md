# HARNESS Skill Market Packaging

面向 Skill 市场分发时，HARNESS 不应把“静态引擎资产”和“项目运行态”混在一起发布。

这份文档给出一个可执行的发布边界：

1. 哪些内容跟 Skill 包一起分发
2. 哪些内容必须在用户项目中初始化生成
3. 初始化脚本应该做什么
4. 发布到市场前需要满足哪些最低要求

---

## 1. 设计原则

一句话原则：

**模板跟 Skill 走，运行态跟项目走。**

也就是说：

1. Skill 安装目录只保存稳定、可复用、可版本化的内容
2. 用户项目目录保存任务状态、日志、输出、归档和知识 WAL
3. Skill 自己不能长期持有“活状态”

如果把运行态直接塞进市场 Skill 包，会出现几个问题：

1. 用户安装后拿到脏状态文件
2. 多项目之间互相污染
3. 升级 Skill 版本时容易覆盖运行中任务
4. 市场审核时很难解释哪些文件是只读资产、哪些是任务数据

---

## 2. 推荐分层

### 2.1 Skill 包内：静态资产

这些内容适合进入 Skill 市场包：

```text
skill-root/
├── SKILL.md
├── prompts/
├── schemas/
├── gates/
├── scripts/
├── templates/
├── config/
└── docs/
```

具体包括：

1. `SKILL.md`
2. `.harness/scripts/`
3. `.harness/schemas/`
4. `.harness/prompts/`
5. `.harness/gates/`
6. `.harness/config/` 中的静态配置
7. 模板文件
8. 安装与使用文档

这些文件应该满足：

1. 可版本化
2. 可重复安装
3. 不携带单个项目的任务历史

### 2.2 用户项目内：运行态

这些内容不应该作为市场 Skill 的默认活文件存在：

```text
<workspace>/.harness/
├── state/
├── output/
├── archive/
├── knowledge/
├── handoff/
├── logs/
└── runtime/
```

具体包括：

1. `state/*.json`
2. `state/SESSION_BRIEF.md`
3. `output/**`
4. `archive/**`
5. `knowledge/wal/**`
6. `output/task-manifest/**`
7. `output/dispatch/**`
8. `output/review/**`
9. `output/worker-report/**`

这些内容的特点是：

1. 和当前项目绑定
2. 会在运行中频繁变化
3. 需要归档和恢复
4. 不能被 Skill 升级覆盖

---

## 3. 模板策略

当前仓库中如果存在这类“看起来像运行态”的文件：

1. `.harness/harness-state.json`
2. `.harness/state/SESSION_BRIEF.md`
3. `.harness/output/preflight-result.json`

在市场化时，不应直接按原名发布为默认活文件，而应改成模板或示例：

推荐命名：

```text
.harness/templates/
├── harness-state.template.json
├── SESSION_BRIEF.template.md
├── preflight-result.template.json
└── workspace-layout.template.json
```

命名规则：

1. 真模板用 `*.template.*`
2. 示例文件用 `*.example.*`
3. fixture 仅用于测试，不参与市场安装

不推荐的做法：

1. 市场包里直接带一个可写的 `.harness/harness-state.json`
2. 把历史 `archive/` 或 `knowledge/wal/` 一起发布
3. 让用户手工复制一堆目录再开始运行

---

## 4. 初始化流程

### 4.1 目标

首次使用 HARNESS Skill 时，应该由初始化脚本在当前项目目录下生成运行态骨架，而不是要求用户自己拼目录。

推荐入口：

```bash
python3 .harness/scripts/init-workspace.py --workspace .
```

或者如果以后提供统一命令：

```bash
harness init
```

### 4.2 初始化脚本职责

`init-workspace.py` 最低应该完成这些动作：

1. 创建项目内 `.harness/` 运行目录
2. 从模板生成初始状态文件
3. 创建空目录并写入 `.gitkeep`
4. 拒绝覆盖已存在运行态，除非显式 `--force`
5. 输出下一步可执行命令

建议生成结果：

```text
<workspace>/.harness/
├── state/
│   ├── harness-workflow-state.json
│   └── SESSION_BRIEF.md
├── output/
│   └── .gitkeep
├── archive/
│   └── .gitkeep
├── handoff/
│   └── .gitkeep
├── logs/
│   └── .gitkeep
└── knowledge/
    ├── experience.md
    ├── failure_memory.jsonl
    └── wal/
        └── .gitkeep
```

### 4.3 初始化规则

推荐规则：

1. 如果 `<workspace>/.harness/state/harness-workflow-state.json` 已存在，则默认失败退出
2. 如果用户传 `--force`，只覆盖模板生成物，不清空 `archive/` 和 `knowledge/`
3. 如果发现旧版本目录结构，输出迁移提示，而不是静默覆盖
4. 初始化脚本必须是幂等的

---

## 5. Skill 包与运行态的连接方式

Skill 运行时，需要明确区分：

1. `skill_root`
2. `workspace_root`

推荐约定：

1. `skill_root` 指向安装到市场后的 Skill 目录
2. `workspace_root` 指向当前被 HARNESS 管理的项目目录
3. 所有运行态写入都只能发生在 `workspace_root/.harness/`

脚本读取优先级建议：

1. 优先读取 `HARNESS_WORKSPACE`
2. 否则根据 `--state-file` 反推出 `workspace_root`
3. 最后才回退到当前工作目录

禁止事项：

1. 把任务状态写回 Skill 安装目录
2. 在 Skill 安装目录下创建 `output/`、`archive/`、`knowledge/wal/`
3. 让多个项目共享同一个活状态文件

---

## 6. 市场发布目录建议

如果未来要把当前仓库整理成市场 Skill，推荐重组为：

```text
harness-team-skill/
├── SKILL.md
├── docs/
│   ├── install.md
│   ├── quickstart.md
│   └── harness-skill-market-packaging.md
├── harness_assets/
│   ├── scripts/
│   ├── schemas/
│   ├── prompts/
│   ├── gates/
│   ├── config/
│   └── templates/
└── examples/
    └── minimal-workspace/
```

如果暂时不做大重组，也至少要做到：

1. 明确哪些目录属于 Skill 资产
2. 明确哪些目录只是仓库开发时的本地运行态
3. 不把本地运行态目录作为默认安装内容发布

---

## 7. 仓库内建议的最小改造

为了让当前仓库更接近可上架 Skill，建议最少做这些调整：

### 7.1 新增模板目录

建议新增：

```text
.harness/templates/
├── harness-workflow-state.template.json
├── SESSION_BRIEF.template.md
├── experience.template.md
└── preflight-result.template.json
```

### 7.2 增加初始化脚本

建议新增：

```text
.harness/scripts/init-workspace.py
```

负责：

1. 初始化运行目录
2. 从模板复制文件
3. 做版本标识
4. 给出下一步命令

### 7.3 把当前活状态降级为示例或模板

建议处理方式：

1. `.harness/harness-state.json` 改为模板或 example
2. `.harness/state/` 下只保留模板，不保留开发者本地运行态
3. `output/ archive/ knowledge/wal/` 默认不进入市场包

### 7.4 补文档

至少补三份文档：

1. 安装说明
2. 首次初始化说明
3. 运行态目录说明

---

## 8. 发布前检查清单

上市场前，至少满足下面这些条件：

### 8.1 结构

1. 没有开发者本地活状态文件
2. 没有历史归档、日志、WAL
3. 模板目录与运行目录边界清晰

### 8.2 安装

1. Python 依赖有正式清单
2. Node 依赖有正式清单
3. 安装步骤可以从零开始复现

### 8.3 使用

1. 首次初始化命令明确
2. 至少一条 quickstart 可直接跑通
3. 失败恢复路径有说明

### 8.4 兼容

1. Skill 升级不会覆盖项目运行态
2. 多项目可并行使用
3. 旧版本运行态有迁移策略或显式不兼容说明

---

## 9. 当前阶段的结论

基于当前仓库状态，可以得出：

1. HARNESS 已经接近“内部可安装 Skill”
2. 但还没有完成“市场级 Skill 包”的运行态分离
3. 下一步应优先补模板目录和初始化脚本，而不是继续扩散业务脚本

最推荐的落地顺序：

1. 新增 `.harness/templates/`
2. 新增 `.harness/scripts/init-workspace.py`
3. 把当前活状态文件改为模板或 example
4. 补 `install.md` 和 `quickstart.md`
5. 再整理市场打包目录

这样处理后，HARNESS 才适合作为 Skill 安装到市场，同时保留项目级运行态的独立性和可维护性。
