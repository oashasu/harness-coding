# Harness Enhance V1 — 设计文档

> 基于 Harness 开源调研报告的六维度评估，对 harness-coding 项目做全面增强
> 分支：harness-enhance-v1（基于 main）
> 日期：2026-06-07

---

## 一、目标

将调研报告中识别的 6 项改进集成到 harness-coding 项目，提升知识底座、记忆、Gate 三个维度的能力。

## 二、改进项总览

| ID | 改进项 | 优先级 | 影响范围 |
|----|--------|--------|---------|
| E-01 | bi-temporal 知识模型 | P0 | knowledge-mcp schema + queries |
| E-02 | 声明式门禁 YAML | P0 | .harness/gates/ + gate-runner |
| E-03 | 查询范围约束 | P1 | knowledge-mcp query tools |
| E-04 | 路径条件门禁 | P1 | gate-runner.sh |
| E-05 | 知识图谱引擎 | P2 | knowledge-mcp db layer |
| E-06 | 混合检索 | P2 | knowledge-mcp query layer |

---

## 三、E-01: bi-temporal 知识模型

### 3.1 设计

参考 graphiti 的 bi-temporal 模型，给每条知识增加时间有效性窗口：

```
valid_from: timestamp  — 知识生效时间（默认创建时间）
valid_to:   timestamp  — 知识失效时间（NULL = 永久有效）
```

### 3.2 Schema 变更

**knowledge 表新增字段：**
```sql
ALTER TABLE knowledge ADD COLUMN valid_from TEXT DEFAULT (datetime('now'));
ALTER TABLE knowledge ADD COLUMN valid_to TEXT DEFAULT NULL;
```

**entity 表新增字段（E-05 图引擎一并实现）：**
```sql
ALTER TABLE entity ADD COLUMN valid_from TEXT DEFAULT (datetime('now'));
ALTER TABLE entity ADD COLUMN valid_to TEXT DEFAULT NULL;
```

### 3.3 查询语义

- **当前有效查询**（默认）：`WHERE valid_from <= now AND (valid_to IS NULL OR valid_to > now)`
- **历史快照查询**：`WHERE valid_from <= :snapshot_time AND (valid_to IS NULL OR valid_to > :snapshot_time)`
- **全量查询**（含已失效）：无时间过滤

### 3.4 API 变更

每个 query tool 增加可选参数：
```typescript
{
  temporal_mode: "current" | "snapshot" | "all",  // 默认 "current"
  snapshot_time?: string  // ISO8601，仅 snapshot 模式需要
}
```

---

## 四、E-02: 声明式门禁 YAML

### 4.1 设计

每个门禁一个 YAML 文件，定义在 `.harness/gates/declarative/` 目录。gate-runner 读取 YAML 并执行。

### 4.2 门禁 YAML Schema

```yaml
# .harness/gates/declarative/g-compile.yaml
gate_id: G-CODE-01
name: compile-check
layer: L4-Enforce          # L1-Sensor | L2-Insight | L3-Policy | L4-Enforce
phase: CODE_IMPL           # 生效阶段
blocking: true             # true = 阻塞, false = 仅报告
trigger:
  paths: ["**/*.java"]     # 路径 glob 模式（空 = 始终触发）
  modes: ["riper-one", "super-dev"]  # 生效的工作流模式（空 = 全部）
check:
  type: script             # script | agent | threshold
  script: scripts/tier0/check-compile.sh
  args: ["${project_root}"]
thresholds: {}             # 仅 type=threshold 时使用
on_failure:
  message: "编译失败，请修复后重试"
  hint: "运行 mvn compile 查看详细错误"
  retry_limit: 3           # 同一门禁最大重试次数
```

### 4.3 gate-runner 改造

现有 `gate-runner.sh` 改为：
1. 扫描 `.harness/gates/declarative/*.yaml`
2. 过滤：当前 phase + 当前 workflow mode + 路径匹配
3. 按 `layer` 优先级排序执行
4. 输出统一格式的 gate result

### 4.4 迁移策略

现有 8 个 shell gate 脚本 + 6 个 agent gate 逐步迁移为 YAML 定义。迁移期间两种方式并存。

---

## 五、E-03: 查询范围约束

### 5.1 设计

防止 Agent 全库扫描，强制按域/任务范围查询。

### 5.2 实现

每个 query tool 增加 `scope` 参数：

```typescript
{
  scope: {
    domains?: string[]    // 限制查询的业务域（如 ["payment", "order"]）
    task_id?: string      // 限制查询当前任务相关知识
    max_results?: number  // 最大返回条数，默认 20，上限 100
  }
}
```

**约束规则：**
- `domains` 为空时，查询所有域（但受 `max_results` 限制）
- `task_id` 不为空时，优先返回与该任务关联的知识
- `max_results` 硬上限 100，防止意外大查询

---

## 六、E-04: 路径条件门禁

### 6.1 设计

参考 cherry-studio 的 `dorny/paths-filter` 模式，gate-runner 根据 `git diff` 选择性执行门禁。

### 6.2 实现

在门禁 YAML 的 `trigger.paths` 字段定义路径匹配：

```yaml
trigger:
  paths: ["**/*.java"]      # 仅 Java 文件变更时触发
  paths_exclude: ["**/test/**"]  # 排除测试目录
```

gate-runner 执行流程：
1. `git diff --name-only HEAD~1` 获取变更文件列表
2. 对每个门禁，检查变更文件是否匹配 `trigger.paths`
3. 匹配的门禁才执行

### 6.3 路径映射配置

新增 `.harness/config/path-rules.yaml`：

```yaml
rules:
  - name: java-only
    paths: ["**/*.java"]
    gates: [G-CODE-01, G-CODE-02, G-CODE-03, G-CODE-04]
  - name: schema-only
    paths: ["**/*.sql", "**/migration/**"]
    gates: [G-REQ-01, G-SPEC-01]
  - name: config-only
    paths: ["**/*.yaml", "**/*.properties", "**/*.xml"]
    gates: [G-CODE-04]
```

---

## 七、E-05: 知识图谱引擎

### 7.1 设计

在现有 SQLite 基础上增加邻接表，实现 entity-relation 图结构。

### 7.2 新增表

```sql
-- 实体表（升级现有 entity 表）
CREATE TABLE IF NOT EXISTS entity (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  entity_type TEXT NOT NULL,      -- table | column | domain | concept | api
  domain TEXT,
  description TEXT,
  properties JSON,                -- 扩展属性
  valid_from TEXT DEFAULT (datetime('now')),
  valid_to TEXT DEFAULT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

-- 关系表（新增）
CREATE TABLE IF NOT EXISTS relation (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES entity(id),
  target_id TEXT NOT NULL REFERENCES entity(id),
  relation_type TEXT NOT NULL,    -- has_column | depends_on | belongs_to | calls | maps_to
  weight REAL DEFAULT 1.0,        -- 关系强度
  properties JSON,
  valid_from TEXT DEFAULT (datetime('now')),
  valid_to TEXT DEFAULT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

-- 关系索引
CREATE INDEX idx_relation_source ON relation(source_id);
CREATE INDEX idx_relation_target ON relation(target_id);
CREATE INDEX idx_relation_type ON relation(relation_type);
```

### 7.3 图遍历查询

使用 SQLite 递归 CTE 实现多跳查询：

```sql
-- N跳邻居查询
WITH RECURSIVE graph_walk AS (
  SELECT source_id, target_id, relation_type, 1 as depth
  FROM relation
  WHERE source_id = :start_id AND (valid_to IS NULL OR valid_to > datetime('now'))
  UNION ALL
  SELECT r.source_id, r.target_id, r.relation_type, gw.depth + 1
  FROM relation r
  JOIN graph_walk gw ON r.source_id = gw.target_id
  WHERE gw.depth < :max_depth AND (r.valid_to IS NULL OR r.valid_to > datetime('now'))
)
SELECT DISTINCT e.*, gw.depth, gw.relation_type
FROM graph_walk gw
JOIN entity e ON e.id = gw.target_id;
```

### 7.4 新增 MCP Tool

```typescript
// query-entity-relation.ts 升级
{
  name: "query_entity_relation",
  params: {
    entity_name: string,
    relation_types?: string[],   // 过滤关系类型
    max_depth?: number,          // 最大跳数，默认 2
    temporal_mode?: "current" | "snapshot" | "all"
  }
}
```

---

## 八、E-06: 混合检索

### 8.1 设计

三路检索 + 自动路由：语义向量 + BM25关键词 + 图遍历。

### 8.2 检索策略

```
用户查询
    │
    ├─→ 语义向量检索（embedding 相似度）
    ├─→ BM25 关键词检索（TF-IDF 匹配）
    └─→ 图遍历检索（实体关系展开）
         │
         ▼
    结果融合 + 去重 + 排序
```

### 8.3 BM25 实现

纯 TypeScript 实现，无外部依赖：

```typescript
// tools/knowledge-mcp/src/retrieval/bm25.ts
class BM25 {
  private corpus: { id: string; tokens: string[]; tf: Map<string, number> }[];
  private idf: Map<string, number>;
  private avgDl: number;

  index(documents: { id: string; text: string }[]): void;
  search(query: string, topK: number): { id: string; score: number }[];
}
```

### 8.4 路由逻辑

```typescript
function routeQuery(query: string, context: QueryContext): RetrievalStrategy {
  const hasEntityName = detectEntityMention(query);    // "payment_order 表"
  const hasKeyword = detectKeyword(query);              // "SQL注入"
  const hasSemantic = query.length > 20;                // 长查询适合语义

  if (hasEntityName) return "graph-first";     // 图遍历优先
  if (hasKeyword) return "bm25-first";         // 关键词优先
  if (hasSemantic) return "semantic-first";    // 语义优先
  return "hybrid";                              // 三路并行
}
```

### 8.5 结果融合

使用 RRF (Reciprocal Rank Fusion)：

```typescript
function rrfMerge(results: RankedResult[][]): RankedResult[] {
  const k = 60;  // RRF 常数
  const scores = new Map<string, number>();

  for (const rankedList of results) {
    rankedList.forEach((item, rank) => {
      scores.set(item.id, (scores.get(item.id) || 0) + 1 / (k + rank));
    });
  }

  return [...scores.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([id, score]) => ({ id, score }));
}
```

---

## 九、文件变更清单

### 新增文件

```
tools/knowledge-mcp/src/retrieval/
├── bm25.ts                    # BM25 纯 TS 实现
├── graph-walker.ts            # 图遍历查询
├── hybrid-retriever.ts        # 三路混合检索 + RRF 融合
└── router.ts                  # 查询路由逻辑

tools/knowledge-mcp/src/db/
├── migration-bitemporal.ts    # bi-temporal schema 迁移
└── migration-graph.ts         # 图引擎 schema 迁移

.harness/gates/declarative/
├── g-compile.yaml
├── g-test.yaml
├── g-coverage.yaml
├── g-static.yaml
├── g-security.yaml
├── g-req-01.yaml
├── g-spec-01.yaml
├── g-spec-02.yaml
└── g-schema.yaml              # 门禁 YAML 格式 schema

.harness/config/
└── path-rules.yaml            # 路径-门禁映射配置
```

### 修改文件

```
tools/knowledge-mcp/src/db/schema.ts          # +entity/relation 表定义
tools/knowledge-mcp/src/db/queries.ts         # +bi-temporal 查询 + 图遍历
tools/knowledge-mcp/src/tools/query-*.ts      # +scope + temporal 参数
tools/knowledge-mcp/src/ingest/*.ts            # +entity/relation 提取

.harness/gates/gate-runner.sh                 # 重构为 YAML 驱动
```

---

## 十、实施阶段

| 阶段 | 内容 | 预估 |
|------|------|------|
| Phase 1 | E-01 bi-temporal + E-02 声明式门禁 | 4-6h |
| Phase 2 | E-03 查询约束 + E-04 路径条件门禁 | 3-4h |
| Phase 3 | E-05 知识图谱引擎 | 4-6h |
| Phase 4 | E-06 混合检索 | 4-6h |
| Phase 5 | 集成测试 + 文档更新 | 2-3h |

---

## 十一、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| bi-temporal 迁移破坏现有数据 | 高 | 迁移脚本加 `valid_from` 默认值，不删数据 |
| 递归 CTE 性能问题 | 中 | 限制 `max_depth` 默认为 3 |
| BM25 纯 TS 实现精度 | 低 | 先用简单实现，后续可换库 |
| YAML 门禁与现有 shell 脚本并存 | 低 | 渐进迁移，不删旧脚本 |
