# Harness Coding v2.0.0

Enterprise AI coding orchestration system — scripts for deterministic checks, agents for semantic judgment.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Harness Router                        │
│         5-dimension scoring → workflow routing           │
├─────────────┬─────────────┬─────────────────────────────┤
│   light     │  riper-one  │         super-dev           │
│  (≤8 pts)   │  (9-15 pts) │        (≥16 pts)            │
├─────────────┴─────────────┴─────────────────────────────┤
│                 5-Tier Quality Pipeline                  │
│  T0:硬门禁 → T1:规则脚本 → T2:指标 → T3:Agent审查 → T4:建议 │
└─────────────────────────────────────────────────────────┘
```

## Three-Phase Design

| Phase | Focus | Deliverables |
|-------|-------|-------------|
| Stage 1 | Unified Orchestrator + 5-Tier Pipeline | Skills, scripts, state files |
| Stage 2 | Three-layer Review + Evidence Anchoring | Agents, adversarial review, lessons |
| Stage 3 | Knowledge MCP + Constraint Injection | MCP server, pattern extraction |

## Project Structure

```
harness-coding/
├── skills/
│   ├── harness-router/          # 5-dimension task routing
│   │   ├── SKILL.md
│   │   └── references/
│   │       ├── routing-matrix.md
│   │       ├── workflow-map.md
│   │       └── spec-template.md
│   └── harness-quality/         # 5-Tier quality pipeline
│       ├── SKILL.md
│       └── references/
│           ├── quality-tiers.md
│           ├── rejection-rules.md
│           └── threshold-config.md
├── scripts/
│   ├── tier0/                   # Hard gates (blocking)
│   │   ├── check-compile.sh
│   │   ├── check-lint.sh
│   │   ├── check-write-paths.sh
│   │   └── check-format.sh
│   ├── tier1/                   # Rule scripts (blocking)
│   │   ├── check-sql-injection.py
│   │   ├── check-bigdecimal.py
│   │   ├── check-layer-violation.py
│   │   ├── check-hardcoded.py
│   │   └── check-null-safety.py
│   ├── tier2/                   # Metric scripts (blocking)
│   │   ├── check-coverage.py
│   │   ├── check-assertion-density.py
│   │   ├── check-complexity.py
│   │   ├── check-file-size.py
│   │   └── check-duplication.py
│   └── common/                  # Shared utilities
│       ├── finding-schema.json
│       └── report-merger.py
└── .harness/
    ├── harness-state.json       # Runtime state
    └── quality-config.json      # Threshold configuration
```

## Quality Pipeline

### Tier 0 — Hard Gates (Blocking)
Compile, lint, write-paths, format. Fail = block.

### Tier 1 — Rule Scripts (Blocking)
SQL injection, BigDecimal misuse, layer violations, hardcoded secrets, null safety.

### Tier 2 — Metric Scripts (Blocking)
Coverage, assertion density, cyclomatic complexity, file size, code duplication.

### Tier 3 — Agent Review (Blocking, Stage 2)
Dual agent adversarial review with evidence anchoring and scope_verified.

### Tier 4 — Suggestions (Non-blocking, Stage 2)
Agent suggestions for improvement.

## Workflow Modes

| Mode | Score | Tiers | Use Case |
|------|-------|-------|----------|
| light | ≤8 | T0-2 | Quick fixes, config changes |
| riper-one | 9-15 | T0-3 | Standard features |
| super-dev | ≥16 | T0-4 | Complex architecture changes |

## Usage

```bash
# Run a specific tier check
python3 scripts/tier1/check-sql-injection.py /path/to/project

# Run tier 0 gate
bash scripts/tier0/check-compile.sh /path/to/project

# Merge reports
echo '{"tier":1,"check":"sql","passed":true,"findings":[]}' | python3 scripts/common/report-merger.py
```

## Enhancements (v2.1 — harness-enhance-v1)

Six improvements integrated from Harness research evaluation:

| ID | Feature | Description |
|----|---------|-------------|
| E-01 | Bi-temporal Knowledge | `valid_from`/`valid_to` fields for time-windowed knowledge validity |
| E-02 | Declarative Gates | YAML-defined gates in `.harness/gates/declarative/` |
| E-03 | Query Scope Constraints | Domain/task-scoped queries with `max_results` limits |
| E-04 | Path-conditional Gates | `git diff`-based selective gate execution |
| E-05 | Knowledge Graph Engine | SQLite adjacency table + recursive CTE for N-hop traversal |
| E-06 | Hybrid Retrieval | Semantic + BM25 + graph traversal with RRF fusion |

### Knowledge MCP Tools

| Tool | New Parameters |
|------|---------------|
| `query_domain` | `temporal_mode`, `snapshot_time`, `max_results` |
| `query_table` | `temporal_mode` |
| `query_entity_relation` | `relation_types`, `max_depth`, `temporal_mode` |
| `search_knowledge` | `strategy` (semantic/bm25/graph/hybrid), `domains`, `max_results` |

### Gate Runner v2

```bash
# Run all gates for a phase
.harness/gates/gate-runner.sh --phase MACHINE_CHECK --workspace .

# Run with path-conditional filtering
.harness/gates/gate-runner.sh --phase MACHINE_CHECK --changed-files "$(git diff --name-only HEAD~1)"

# Run a single gate
.harness/gates/gate-runner.sh --gate G-CODE-01 --workspace .
```

## Design Documents

- [Phase 1 Design](../../task_archive/2026-06/harness-coding-system/phase1-design.md)
- [Phase 2 Design](../../task_archive/2026-06/harness-coding-system/phase2-design.md)
- [Phase 3 Design](../../task_archive/2026-06/harness-coding-system/phase3-design.md)
- [Goal Prompts](../../task_archive/2026-06/harness-coding-system/goal-prompts.md)
- [Enhance V1 Design](docs/superpowers/specs/2026-06-07-harness-enhance-v1-design.md)
- [Enhance V1 Plan](docs/superpowers/plans/2026-06-07-harness-enhance-v1.md)
- [Skill Market Packaging](docs/harness-skill-market-packaging.md)
