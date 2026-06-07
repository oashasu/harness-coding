# Harness Enhance V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Integrate 6 improvements from Harness research into harness-coding: bi-temporal knowledge, declarative gates, query constraints, path-conditional gates, knowledge graph engine, hybrid retrieval.

**Architecture:** Extend knowledge-mcp SQLite layer with bi-temporal fields + adjacency table graph. Refactor gate-runner to YAML-driven execution. Add BM25 + graph traversal retrieval.

**Tech Stack:** TypeScript, better-sqlite3, zod, YAML

---

### Task 1: Bi-temporal Schema Migration

**Files:**
- Modify: `tools/knowledge-mcp/src/db/schema.ts`
- Create: `tools/knowledge-mcp/src/db/migrations.ts`

- [ ] **Step 1: Add migration function to schema.ts**

```typescript
// Append to schema.ts after FTS_SCHEMA_SQL

export const BITEMPORAL_MIGRATION_SQL = `
ALTER TABLE knowledge_files ADD COLUMN valid_from TEXT DEFAULT (datetime('now'));
ALTER TABLE knowledge_files ADD COLUMN valid_to TEXT DEFAULT NULL;
`;

export const GRAPH_SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS entity (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  domain TEXT,
  description TEXT,
  properties TEXT,
  valid_from TEXT DEFAULT (datetime('now')),
  valid_to TEXT DEFAULT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_entity_name ON entity(name);
CREATE INDEX IF NOT EXISTS idx_entity_type ON entity(entity_type);
CREATE INDEX IF NOT EXISTS idx_entity_domain ON entity(domain);

CREATE TABLE IF NOT EXISTS relation (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  weight REAL DEFAULT 1.0,
  properties TEXT,
  valid_from TEXT DEFAULT (datetime('now')),
  valid_to TEXT DEFAULT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_relation_source ON relation(source_id);
CREATE INDEX IF NOT EXISTS idx_relation_target ON relation(target_id);
CREATE INDEX IF NOT EXISTS idx_relation_type ON relation(relation_type);
`;
```

- [ ] **Step 2: Create migrations.ts**

```typescript
// tools/knowledge-mcp/src/db/migrations.ts
import Database from 'better-sqlite3';
import { BITEMPORAL_MIGRATION_SQL, GRAPH_SCHEMA_SQL } from './schema.js';

interface Migration {
  id: string;
  sql: string;
}

const MIGRATIONS: Migration[] = [
  { id: 'bitemporal_001', sql: BITEMPORAL_MIGRATION_SQL },
  { id: 'graph_001', sql: GRAPH_SCHEMA_SQL },
];

export function runMigrations(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS _migrations (
      id TEXT PRIMARY KEY,
      applied_at TEXT DEFAULT (datetime('now'))
    );
  `);

  const applied = new Set(
    db.prepare('SELECT id FROM _migrations').all().map((r: any) => r.id)
  );

  for (const m of MIGRATIONS) {
    if (applied.has(m.id)) continue;
    const stmts = m.sql.split(';').filter(s => s.trim());
    for (const stmt of stmts) {
      if (stmt.trim()) db.exec(stmt);
    }
    db.prepare('INSERT INTO _migrations (id) VALUES (?)').run(m.id);
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add tools/knowledge-mcp/src/db/schema.ts tools/knowledge-mcp/src/db/migrations.ts
git commit -m "feat(knowledge-mcp): add bi-temporal + graph schema migrations"
```

---

### Task 2: Update Queries with Bi-temporal Support

**Files:**
- Modify: `tools/knowledge-mcp/src/db/queries.ts`

- [ ] **Step 1: Add temporal filter helper and update searchKnowledge**

```typescript
// Add at top of queries.ts

export interface TemporalFilter {
  mode?: 'current' | 'snapshot' | 'all';
  snapshot_time?: string;
}

function temporalClause(alias: string, filter?: TemporalFilter): string {
  const mode = filter?.mode || 'current';
  if (mode === 'all') return '';
  const now = filter?.snapshot_time || "datetime('now')";
  return ` AND ${alias}.valid_from <= ${now} AND (${alias}.valid_to IS NULL OR ${alias}.valid_to > ${now})`;
}

function temporalParams(filter?: TemporalFilter): any[] {
  return filter?.mode === 'snapshot' && filter.snapshot_time ? [filter.snapshot_time] : [];
}
```

- [ ] **Step 2: Update searchKnowledge to accept temporal filter**

Replace the searchKnowledge function:

```typescript
export function searchKnowledge(db: Database.Database, queryText: string, temporal?: TemporalFilter) {
  const tc = temporalClause('kf', temporal);
  try {
    const results = db.prepare(`
      SELECT kf.*, rank
      FROM knowledge_fts
      JOIN knowledge_files kf ON knowledge_fts.rowid = kf.id
      WHERE knowledge_fts MATCH ? ${tc}
      ORDER BY rank
      LIMIT 20
    `).all(queryText);
    return results;
  } catch {
    return db.prepare(`
      SELECT * FROM knowledge_files kf
      WHERE (kf.title LIKE ? OR kf.tags LIKE ?) ${tc}
      LIMIT 20
    `).all(`%${queryText}%`, `%${queryText}%`);
  }
}
```

- [ ] **Step 3: Add graph query functions**

```typescript
// Append to queries.ts

export function queryEntityGraph(
  db: Database.Database,
  entityId: string,
  options?: { max_depth?: number; relation_types?: string[]; temporal?: TemporalFilter }
) {
  const maxDepth = options?.max_depth || 2;
  const tc = temporalClause('r', options?.temporal);
  const typeFilter = options?.relation_types?.length
    ? ` AND r.relation_type IN (${options.relation_types.map(() => '?').join(',')})`
    : '';

  const sql = `
    WITH RECURSIVE graph_walk AS (
      SELECT source_id, target_id, relation_type, 1 as depth
      FROM relation r
      WHERE source_id = ? ${tc} ${typeFilter}
      UNION ALL
      SELECT r.source_id, r.target_id, r.relation_type, gw.depth + 1
      FROM relation r
      JOIN graph_walk gw ON r.source_id = gw.target_id
      WHERE gw.depth < ? ${tc} ${typeFilter}
    )
    SELECT DISTINCT e.*, gw.depth, gw.relation_type
    FROM graph_walk gw
    JOIN entity e ON e.id = gw.target_id
    ORDER BY gw.depth
  `;

  const params: any[] = [entityId, ...temporalParams(options?.temporal)];
  if (options?.relation_types?.length) params.push(...options.relation_types);
  params.push(maxDepth);
  if (options?.relation_types?.length) params.push(...options.relation_types);

  return db.prepare(sql).all(...params);
}

export function insertEntity(db: Database.Database, entity: {
  id: string; name: string; entity_type: string; domain?: string;
  description?: string; properties?: any;
}) {
  db.prepare(`
    INSERT OR REPLACE INTO entity (id, name, entity_type, domain, description, properties)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(entity.id, entity.name, entity.entity_type, entity.domain || null,
    entity.description || null, entity.properties ? JSON.stringify(entity.properties) : null);
}

export function insertRelation(db: Database.Database, relation: {
  id: string; source_id: string; target_id: string; relation_type: string;
  weight?: number; properties?: any;
}) {
  db.prepare(`
    INSERT OR REPLACE INTO relation (id, source_id, target_id, relation_type, weight, properties)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(relation.id, relation.source_id, relation.target_id, relation.relation_type,
    relation.weight || 1.0, relation.properties ? JSON.stringify(relation.properties) : null);
}

export function invalidateEntity(db: Database.Database, id: string) {
  db.prepare(`UPDATE entity SET valid_to = datetime('now') WHERE id = ?`).run(id);
}

export function invalidateRelation(db: Database.Database, id: string) {
  db.prepare(`UPDATE relation SET valid_to = datetime('now') WHERE id = ?`).run(id);
}
```

- [ ] **Step 4: Commit**

```bash
git add tools/knowledge-mcp/src/db/queries.ts
git commit -m "feat(knowledge-mcp): add bi-temporal queries + graph traversal"
```

---

### Task 3: Declarative Gate YAML System

**Files:**
- Create: `.harness/gates/declarative/g-compile.yaml`
- Create: `.harness/gates/declarative/g-test.yaml`
- Create: `.harness/gates/declarative/g-coverage.yaml`
- Create: `.harness/gates/declarative/g-security.yaml`
- Create: `.harness/gates/declarative/g-static.yaml`
- Create: `.harness/gates/declarative/g-req-01.yaml`
- Create: `.harness/gates/declarative/g-spec-01.yaml`
- Create: `.harness/gates/declarative/g-spec-02.yaml`
- Create: `.harness/config/path-rules.yaml`

- [ ] **Step 1: Create g-compile.yaml**

```yaml
gate_id: G-CODE-01
name: compile-check
layer: L4-Enforce
phase: MACHINE_CHECK
blocking: true
trigger:
  paths: ["**/*.java", "**/*.ts", "**/*.go"]
  modes: []
check:
  type: script
  script: .harness/gates/g-compile.sh
  args: ["${workspace}"]
on_failure:
  message: "编译失败，请修复后重试"
  hint: "运行 mvn compile 查看详细错误"
  retry_limit: 3
```

- [ ] **Step 2: Create g-test.yaml**

```yaml
gate_id: G-CODE-02
name: test-check
layer: L4-Enforce
phase: MACHINE_CHECK
blocking: true
trigger:
  paths: ["**/*.java", "**/*.ts", "**/*.go"]
  modes: []
check:
  type: script
  script: .harness/gates/g-test.sh
  args: ["${workspace}"]
on_failure:
  message: "测试失败，请修复失败的测试"
  hint: "运行 mvn test 查看详细错误"
  retry_limit: 3
```

- [ ] **Step 3: Create g-coverage.yaml**

```yaml
gate_id: G-CODE-03
name: coverage-check
layer: L4-Enforce
phase: MACHINE_CHECK
blocking: true
trigger:
  paths: ["**/*.java"]
  modes: ["riper-one", "super-dev"]
check:
  type: threshold
  script: .harness/gates/g-coverage.sh
  args: ["${workspace}", "80"]
  thresholds:
    line_coverage: 80
on_failure:
  message: "测试覆盖率不足80%"
  hint: "补充单元测试以提高覆盖率"
  retry_limit: 2
```

- [ ] **Step 4: Create remaining gate YAMLs**

```yaml
# g-security.yaml
gate_id: G-TEST-02
name: security-check
layer: L4-Enforce
phase: MACHINE_CHECK
blocking: true
trigger:
  paths: ["**/*.java", "**/*.ts"]
  modes: ["riper-one", "super-dev"]
check:
  type: script
  script: .harness/gates/g-security.sh
  args: ["${workspace}"]
on_failure:
  message: "安全扫描发现问题"
  hint: "检查硬编码密钥、SQL注入等安全问题"
  retry_limit: 2
```

```yaml
# g-static.yaml
gate_id: G-CODE-04
name: static-analysis
layer: L4-Enforce
phase: MACHINE_CHECK
blocking: true
trigger:
  paths: ["**/*.java"]
  modes: ["riper-one", "super-dev"]
check:
  type: script
  script: .harness/gates/g-static.sh
  args: ["${workspace}"]
on_failure:
  message: "静态扫描发现CRITICAL问题"
  hint: "运行 spotbugs:check 查看详情"
  retry_limit: 2
```

```yaml
# g-req-01.yaml
gate_id: G-REQ-01
name: requirement-schema
layer: L4-Enforce
phase: REQ_REVIEW
blocking: true
trigger:
  paths: []
  modes: []
check:
  type: script
  script: .harness/gates/g-req-01.sh
  args: ["${workspace}"]
on_failure:
  message: "需求文档格式不合规"
  hint: "检查 requirement.md 必填字段"
  retry_limit: 3
```

```yaml
# g-spec-01.yaml
gate_id: G-SPEC-01
name: spec-schema
layer: L4-Enforce
phase: SPEC_REVIEW
blocking: true
trigger:
  paths: []
  modes: []
check:
  type: script
  script: .harness/gates/g-spec-01.sh
  args: ["${workspace}"]
on_failure:
  message: "Spec文档格式不合规"
  hint: "检查 task_brief.md Schema"
  retry_limit: 3
```

```yaml
# g-spec-02.yaml
gate_id: G-SPEC-02
name: rid-uniqueness
layer: L4-Enforce
phase: SPEC_REVIEW
blocking: true
trigger:
  paths: []
  modes: []
check:
  type: script
  script: .harness/gates/g-spec-02.sh
  args: ["${workspace}"]
on_failure:
  message: "R-ID不唯一"
  hint: "检查验收标准编号唯一性"
  retry_limit: 3
```

- [ ] **Step 5: Create path-rules.yaml**

```yaml
rules:
  - name: java-source
    paths: ["**/*.java"]
    gates: [G-CODE-01, G-CODE-02, G-CODE-03, G-CODE-04]
  - name: typescript-source
    paths: ["**/*.ts"]
    gates: [G-CODE-01, G-CODE-02]
  - name: go-source
    paths: ["**/*.go"]
    gates: [G-CODE-01, G-CODE-02]
  - name: security-relevant
    paths: ["**/*.java", "**/*.ts", "**/*.env*", "**/*config*"]
    gates: [G-TEST-02]
  - name: requirement-docs
    paths: ["**/requirement*.md", "**/req/**"]
    gates: [G-REQ-01]
  - name: spec-docs
    paths: ["**/spec*.md", "**/task_brief*"]
    gates: [G-SPEC-01, G-SPEC-02]
```

- [ ] **Step 6: Commit**

```bash
git add .harness/gates/declarative/ .harness/config/path-rules.yaml
git commit -m "feat(gates): add declarative YAML gate definitions + path rules"
```

---

### Task 4: Refactor gate-runner to YAML-driven

**Files:**
- Modify: `.harness/gates/gate-runner.sh`

- [ ] **Step 1: Rewrite gate-runner.sh**

```bash
#!/usr/bin/env bash
# Gate runner v2 — YAML-driven execution with path-conditional filtering
# Usage: gate-runner.sh [--workspace <dir>] [--phase <phase>] [--mode <mode>] [--gate <gate-id>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DECLARATIVE_DIR="$SCRIPT_DIR/declarative"
CONFIG_DIR="$(dirname "$SCRIPT_DIR")/config"
WORKSPACE="."
PHASE=""
MODE=""
SINGLE_GATE=""
CHANGED_FILES=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --workspace) WORKSPACE="$2"; shift 2 ;;
        --phase) PHASE="$2"; shift 2 ;;
        --mode) MODE="$2"; shift 2 ;;
        --gate) SINGLE_GATE="$2"; shift 2 ;;
        --changed-files) CHANGED_FILES="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

mkdir -p "$WORKSPACE/.harness/output/logs" "$WORKSPACE/.harness/output/gate-results"

# Get changed files if not provided
if [ -z "$CHANGED_FILES" ] && [ -d "$WORKSPACE/.git" ]; then
    CHANGED_FILES=$(cd "$WORKSPACE" && git diff --name-only HEAD~1 2>/dev/null || echo "")
fi

# Simple YAML parser (avoids yq dependency)
parse_yaml_value() {
    local file="$1" key="$2"
    grep "^${key}:" "$file" 2>/dev/null | head -1 | sed "s/^${key}:[[:space:]]*//" | tr -d '"' | tr -d "'"
}

# Check if path matches any glob pattern in a YAML list
path_matches() {
    local file="$1"
    shift
    for pattern in "$@"; do
        # Simple glob matching: convert ** to recursive
        if [[ "$file" == $pattern ]]; then
            return 0
        fi
    done
    return 1
}

# Extract list items from YAML (handles "- item" format)
parse_yaml_list() {
    local file="$1" key="$2"
    sed -n "/^${key}:/,/^[^ ]/{/^- /{s/^- //;p}}" "$file" 2>/dev/null
}

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
RESULTS=()

for yaml_file in "$DECLARATIVE_DIR"/*.yaml; do
    [ -f "$yaml_file" ] || continue

    GATE_ID=$(parse_yaml_value "$yaml_file" "gate_id")
    GATE_NAME=$(parse_yaml_value "$yaml_file" "name")
    GATE_PHASE=$(parse_yaml_value "$yaml_file" "phase")
    GATE_BLOCKING=$(parse_yaml_value "$yaml_file" "blocking")

    # Single gate filter
    if [ -n "$SINGLE_GATE" ] && [ "$GATE_ID" != "$SINGLE_GATE" ]; then
        continue
    fi

    # Phase filter
    if [ -n "$PHASE" ] && [ "$GATE_PHASE" != "$PHASE" ]; then
        continue
    fi

    # Mode filter (extract modes list from YAML)
    if [ -n "$MODE" ]; then
        MODES=$(parse_yaml_list "$yaml_file" "modes")
        if [ -n "$MODES" ] && ! echo "$MODES" | grep -qw "$MODE"; then
            continue
        fi
    fi

    # Path-conditional filter
    if [ -n "$CHANGED_FILES" ]; then
        TRIGGER_PATHS=$(parse_yaml_list "$yaml_file" "paths")
        if [ -n "$TRIGGER_PATHS" ]; then
            MATCHED=false
            while IFS= read -r changed; do
                while IFS= read -r pattern; do
                    if [[ "$changed" == $pattern ]]; then
                        MATCHED=true
                        break 2
                    fi
                done <<< "$TRIGGER_PATHS"
            done <<< "$CHANGED_FILES"
            if [ "$MATCHED" = false ]; then
                echo "[GATE] $GATE_ID ($GATE_NAME): SKIP — no matching changed files"
                SKIP_COUNT=$((SKIP_COUNT + 1))
                continue
            fi
        fi
    fi

    # Execute gate
    SCRIPT=$(parse_yaml_value "$yaml_file" "script")
    if [ -z "$SCRIPT" ]; then
        echo "[GATE] $GATE_ID: ERROR — no script defined"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        continue
    fi

    # Resolve relative script path
    if [[ "$SCRIPT" != /* ]]; then
        SCRIPT="$WORKSPACE/$SCRIPT"
    fi

    echo "[GATE] $GATE_ID ($GATE_NAME): executing..."
    RESULT_FILE="$WORKSPACE/.harness/output/gate-results/${GATE_ID}.json"

    if bash "$SCRIPT" "$WORKSPACE" > "$RESULT_FILE" 2>&1; then
        echo "[GATE] $GATE_ID: PASS"
        PASS_COUNT=$((PASS_COUNT + 1))
        RESULTS+=("{\"gate_id\":\"$GATE_ID\",\"status\":\"PASS\"}")
    else
        echo "[GATE] $GATE_ID: FAIL"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        RESULTS+=("{\"gate_id\":\"$GATE_ID\",\"status\":\"FAIL\"}")
    fi
done

# Summary
echo ""
echo "=== Gate Summary ==="
echo "Pass: $PASS_COUNT | Fail: $FAIL_COUNT | Skip: $SKIP_COUNT"

if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0
```

- [ ] **Step 2: Commit**

```bash
git add .harness/gates/gate-runner.sh
git commit -m "feat(gates): refactor gate-runner to YAML-driven with path-conditional filtering"
```

---

### Task 5: BM25 + Hybrid Retrieval

**Files:**
- Create: `tools/knowledge-mcp/src/retrieval/bm25.ts`
- Create: `tools/knowledge-mcp/src/retrieval/graph-walker.ts`
- Create: `tools/knowledge-mcp/src/retrieval/hybrid-retriever.ts`
- Create: `tools/knowledge-mcp/src/retrieval/router.ts`

- [ ] **Step 1: Create bm25.ts**

```typescript
// tools/knowledge-mcp/src/retrieval/bm25.ts
// BM25 ranking algorithm — pure TypeScript, no external deps

interface BM25Doc {
  id: string;
  tokens: string[];
}

export class BM25 {
  private docs: BM25Doc[] = [];
  private avgDl = 0;
  private df = new Map<string, number>(); // document frequency
  private k1 = 1.5;
  private b = 0.75;

  index(documents: { id: string; text: string }[]): void {
    this.docs = documents.map(d => ({
      id: d.id,
      tokens: this.tokenize(d.text),
    }));

    const totalLen = this.docs.reduce((s, d) => s + d.tokens.length, 0);
    this.avgDl = totalLen / this.docs.length || 1;

    this.df.clear();
    for (const doc of this.docs) {
      const seen = new Set(doc.tokens);
      for (const t of seen) {
        this.df.set(t, (this.df.get(t) || 0) + 1);
      }
    }
  }

  search(query: string, topK = 20): { id: string; score: number }[] {
    const qTokens = this.tokenize(query);
    const N = this.docs.length;

    const scores = this.docs.map(doc => {
      let score = 0;
      const tf = new Map<string, number>();
      for (const t of doc.tokens) tf.set(t, (tf.get(t) || 0) + 1);

      for (const qt of qTokens) {
        const docTf = tf.get(qt) || 0;
        const docFreq = this.df.get(qt) || 0;
        if (docTf === 0 || docFreq === 0) continue;

        const idf = Math.log((N - docFreq + 0.5) / (docFreq + 0.5) + 1);
        const tfNorm = (docTf * (this.k1 + 1)) /
          (docTf + this.k1 * (1 - this.b + this.b * (doc.tokens.length / this.avgDl)));
        score += idf * tfNorm;
      }
      return { id: doc.id, score };
    });

    return scores
      .filter(s => s.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, topK);
  }

  private tokenize(text: string): string[] {
    return text
      .toLowerCase()
      .replace(/[^\w一-鿿]/g, ' ')
      .split(/\s+/)
      .filter(t => t.length > 1);
  }
}
```

- [ ] **Step 2: Create graph-walker.ts**

```typescript
// tools/knowledge-mcp/src/retrieval/graph-walker.ts
import Database from 'better-sqlite3';
import { queryEntityGraph } from '../db/queries.js';

export interface GraphResult {
  id: string;
  name: string;
  entity_type: string;
  depth: number;
  relation_type: string;
}

export function graphRetrieve(
  db: Database.Database,
  entityName: string,
  options?: { maxDepth?: number; relationTypes?: string[] }
): GraphResult[] {
  // Find entity by name
  const entity = db.prepare('SELECT id FROM entity WHERE name = ?').get(entityName) as any;
  if (!entity) return [];

  const results = queryEntityGraph(db, entity.id, {
    max_depth: options?.maxDepth || 2,
    relation_types: options?.relationTypes,
    temporal: { mode: 'current' },
  });

  return results.map((r: any) => ({
    id: r.id,
    name: r.name,
    entity_type: r.entity_type,
    depth: r.depth,
    relation_type: r.relation_type,
  }));
}
```

- [ ] **Step 3: Create router.ts**

```typescript
// tools/knowledge-mcp/src/retrieval/router.ts
export type RetrievalStrategy = 'semantic-first' | 'bm25-first' | 'graph-first' | 'hybrid';

export function routeQuery(query: string): RetrievalStrategy {
  // Entity mention detection (table names, domain names)
  const entityPattern = /\b[A-Z][A-Z_]+\b|[a-z_]+_table\b|表|域/;
  // Keyword detection (short technical terms)
  const keywordPattern = /注入|泄漏|越权|超时|异常|错误|配置|枚举|分账|退款|支付/;

  const hasEntity = entityPattern.test(query);
  const hasKeyword = keywordPattern.test(query);
  const isLongQuery = query.length > 20;

  if (hasEntity && !hasKeyword) return 'graph-first';
  if (hasKeyword && !isLongQuery) return 'bm25-first';
  if (isLongQuery) return 'semantic-first';
  return 'hybrid';
}
```

- [ ] **Step 4: Create hybrid-retriever.ts**

```typescript
// tools/knowledge-mcp/src/retrieval/hybrid-retriever.ts
import Database from 'better-sqlite3';
import { BM25 } from './bm25.js';
import { graphRetrieve } from './graph-walker.js';
import { routeQuery, RetrievalStrategy } from './router.js';
import { searchKnowledge } from '../db/queries.js';

export interface RankedResult {
  id: string;
  score: number;
  source: 'semantic' | 'bm25' | 'graph';
  data: any;
}

export function hybridRetrieve(
  db: Database.Database,
  query: string,
  options?: { strategy?: RetrievalStrategy; topK?: number; scope?: { domains?: string[] } }
): RankedResult[] {
  const strategy = options?.strategy || routeQuery(query);
  const topK = options?.topK || 20;

  switch (strategy) {
    case 'semantic-first':
      return semanticRetrieve(db, query, topK, options?.scope);
    case 'bm25-first':
      return bm25Retrieve(db, query, topK, options?.scope);
    case 'graph-first':
      return graphFirstRetrieve(db, query, topK);
    case 'hybrid':
    default:
      return hybridMerge(db, query, topK, options?.scope);
  }
}

function semanticRetrieve(db: Database.Database, query: string, topK: number, scope?: { domains?: string[] }): RankedResult[] {
  let results = searchKnowledge(db, query, { mode: 'current' });
  if (scope?.domains?.length) {
    results = results.filter((r: any) => scope.domains.includes(r.domain_id));
  }
  return results.slice(0, topK).map((r: any, i: number) => ({
    id: String(r.id), score: 1 / (i + 1), source: 'semantic' as const, data: r,
  }));
}

function bm25Retrieve(db: Database.Database, query: string, topK: number, scope?: { domains?: string[] }): RankedResult[] {
  let docs = db.prepare('SELECT id, title, tags FROM knowledge_files').all() as any[];
  if (scope?.domains?.length) {
    docs = docs.filter(d => scope.domains.includes(d.domain_id));
  }

  const bm25 = new BM25();
  bm25.index(docs.map(d => ({ id: String(d.id), text: `${d.title || ''} ${d.tags || ''}` })));
  const ranked = bm25.search(query, topK);

  return ranked.map(r => ({
    id: r.id, score: r.score, source: 'bm25' as const,
    data: docs.find(d => String(d.id) === r.id),
  }));
}

function graphFirstRetrieve(db: Database.Database, query: string, topK: number): RankedResult[] {
  // Extract entity name from query
  const entityMatch = query.match(/\b([A-Z][A-Z_]+)\b/);
  if (!entityMatch) return bm25Retrieve(db, query, topK);

  const graphResults = graphRetrieve(db, entityMatch[1], { maxDepth: 2 });
  return graphResults.slice(0, topK).map((r, i) => ({
    id: r.id, score: 1 / (i + 1), source: 'graph' as const, data: r,
  }));
}

function hybridMerge(db: Database.Database, query: string, topK: number, scope?: { domains?: string[] }): RankedResult[] {
  const semantic = semanticRetrieve(db, query, topK * 2, scope);
  const bm25 = bm25Retrieve(db, query, topK * 2, scope);
  const graph = graphFirstRetrieve(db, query, topK * 2);

  return rrfMerge([semantic, bm25, graph]).slice(0, topK);
}

function rrfMerge(resultSets: RankedResult[][], k = 60): RankedResult[] {
  const scores = new Map<string, { score: number; source: string; data: any }>();

  for (const results of resultSets) {
    results.forEach((item, rank) => {
      const existing = scores.get(item.id);
      const rrfScore = 1 / (k + rank);
      if (existing) {
        existing.score += rrfScore;
      } else {
        scores.set(item.id, { score: rrfScore, source: item.source, data: item.data });
      }
    });
  }

  return [...scores.entries()]
    .map(([id, v]) => ({ id, score: v.score, source: v.source as any, data: v.data }))
    .sort((a, b) => b.score - a.score);
}
```

- [ ] **Step 5: Commit**

```bash
git add tools/knowledge-mcp/src/retrieval/
git commit -m "feat(knowledge-mcp): add BM25 + graph walker + hybrid retrieval with RRF fusion"
```

---

### Task 6: Query Scope Constraints + MCP Tool Updates

**Files:**
- Modify: `tools/knowledge-mcp/src/tools/query-domain.ts`
- Modify: `tools/knowledge-mcp/src/tools/query-table.ts`
- Modify: `tools/knowledge-mcp/src/tools/query-entity-relation.ts`
- Modify: `tools/knowledge-mcp/src/tools/search-knowledge.ts`

- [ ] **Step 1: Update query-domain.ts with scope + temporal**

```typescript
import { z } from 'zod';
import Database from 'better-sqlite3';
import { queryDomain, TemporalFilter } from '../db/queries.js';

export const queryDomainSchema = {
  domain_id: z.string().describe('领域ID，如 AT_支付域'),
  temporal_mode: z.enum(['current', 'snapshot', 'all']).optional().default('current'),
  snapshot_time: z.string().optional().describe('ISO8601 时间戳，仅 snapshot 模式'),
  max_results: z.number().optional().default(50),
};

export function queryDomainHandler(db: Database.Database, args: {
  domain_id: string;
  temporal_mode?: string;
  snapshot_time?: string;
  max_results?: number;
}) {
  const temporal: TemporalFilter = {
    mode: (args.temporal_mode as any) || 'current',
    snapshot_time: args.snapshot_time,
  };
  const result = queryDomain(db, args.domain_id);
  if (!result) {
    return { content: [{ type: 'text' as const, text: JSON.stringify({ error: 'domain_not_found', domain_id: args.domain_id }) }] };
  }
  return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] };
}
```

- [ ] **Step 2: Update search-knowledge.ts with hybrid retrieval**

```typescript
import { z } from 'zod';
import Database from 'better-sqlite3';
import { hybridRetrieve } from '../retrieval/hybrid-retriever.js';

export const searchKnowledgeSchema = {
  query: z.string().describe('搜索关键词或自然语言查询'),
  strategy: z.enum(['semantic-first', 'bm25-first', 'graph-first', 'hybrid']).optional(),
  domains: z.array(z.string()).optional().describe('限制查询的业务域'),
  max_results: z.number().optional().default(20).describe('最大返回条数，上限100'),
};

export function searchKnowledgeHandler(db: Database.Database, args: {
  query: string;
  strategy?: string;
  domains?: string[];
  max_results?: number;
}) {
  const maxResults = Math.min(args.max_results || 20, 100);
  const results = hybridRetrieve(db, args.query, {
    strategy: args.strategy as any,
    topK: maxResults,
    scope: args.domains?.length ? { domains: args.domains } : undefined,
  });

  return { content: [{ type: 'text' as const, text: JSON.stringify(results, null, 2) }] };
}
```

- [ ] **Step 3: Update query-entity-relation.ts with graph traversal**

```typescript
import { z } from 'zod';
import Database from 'better-sqlite3';
import { queryEntityGraph } from '../db/queries.js';

export const queryEntityRelationSchema = {
  entity_name: z.string().describe('实体名称'),
  relation_types: z.array(z.string()).optional().describe('过滤关系类型'),
  max_depth: z.number().optional().default(2).describe('最大跳数，默认2'),
  temporal_mode: z.enum(['current', 'snapshot', 'all']).optional().default('current'),
};

export function queryEntityRelationHandler(db: Database.Database, args: {
  entity_name: string;
  relation_types?: string[];
  max_depth?: number;
  temporal_mode?: string;
}) {
  // Find entity by name
  const entity = db.prepare('SELECT id FROM entity WHERE name = ?').get(args.entity_name) as any;
  if (!entity) {
    return { content: [{ type: 'text' as const, text: JSON.stringify({ error: 'entity_not_found', name: args.entity_name }) }] };
  }

  const results = queryEntityGraph(db, entity.id, {
    max_depth: Math.min(args.max_depth || 2, 5),
    relation_types: args.relation_types,
    temporal: { mode: (args.temporal_mode as any) || 'current' },
  });

  return { content: [{ type: 'text' as const, text: JSON.stringify(results, null, 2) }] };
}
```

- [ ] **Step 4: Update query-table.ts**

```typescript
import { z } from 'zod';
import Database from 'better-sqlite3';
import { queryTable, TemporalFilter } from '../db/queries.js';

export const queryTableSchema = {
  table_name: z.string().describe('表名'),
  temporal_mode: z.enum(['current', 'snapshot', 'all']).optional().default('current'),
};

export function queryTableHandler(db: Database.Database, args: {
  table_name: string;
  temporal_mode?: string;
}) {
  const result = queryTable(db, args.table_name);
  if (!result) {
    return { content: [{ type: 'text' as const, text: JSON.stringify({ error: 'table_not_found', table_name: args.table_name }) }] };
  }
  return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] };
}
```

- [ ] **Step 5: Commit**

```bash
git add tools/knowledge-mcp/src/tools/
git commit -m "feat(knowledge-mcp): add scope constraints + temporal params to query tools"
```

---

### Task 7: Integrate Migrations into Init Flow

**Files:**
- Modify: `tools/knowledge-mcp/src/ingest/index.ts`

- [ ] **Step 1: Add migration call to init**

Read the current ingest/index.ts first, then add `runMigrations(db)` after the database initialization.

- [ ] **Step 2: Commit**

```bash
git add tools/knowledge-mcp/src/ingest/index.ts
git commit -m "feat(knowledge-mcp): integrate schema migrations into init flow"
```

---

### Task 8: Final Integration + Documentation

- [ ] **Step 1: Update README.md with new capabilities**

- [ ] **Step 2: Verify all scripts and TypeScript compile**

```bash
cd tools/knowledge-mcp && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: update README with bi-temporal, graph engine, hybrid retrieval, declarative gates"
```
