# orchestrator.py HARNESS Design Analysis

> Source: `origin/feat/payment-workflow-state-contracts:.payment-skill/scripts/orchestrator.py`
> 1405 lines, single-file orchestrator for payment workflow state machine

---

## 1. Core Orchestration Logic

### Single Class: `StageOrchestrator`

The entire script is built around one class with no inheritance hierarchy. It manages a
pipeline with 5 stages: `spec`, `prove`, `gen`, `final`, `plan`.

### Main Entry Flow (`execute()`)

```
load_state()                          # JSON parsing + markdown stripping + HMAC integrity
  -> validate_task_manifest_consistency()  # task manifest vs runtime state cross-check
  -> validate_preflight_entry_gate()       # gen node preflight blocking rules
  -> run_preflight()                       # optional subprocess: preflight.py
  -> load_schema()                         # JSON Schema loading per stage
  -> validate_schema()                     # jsonschema.validate()
  -> [stage-specific validation]
  -> maybe_drive_next_action()             # optional: plan-next-action + execute-next-action
```

### Stage Dispatch Pattern

Each stage has its own validation method:

| Stage  | Method                                      | State Kind Required      |
|--------|---------------------------------------------|--------------------------|
| spec   | `run_spec_validation()`                     | legacy or payment_workflow |
| prove  | `run_prove_validation()`                    | legacy or payment_workflow |
| gen    | `run_payment_workflow_gen_validation()`      | payment_workflow only     |
| final  | `run_payment_workflow_final_validation()`    | payment_workflow only     |
| plan   | `run_plan_validation()`                     | any                      |

### Two State Kinds

The orchestrator detects two kinds of state via `detect_state_kind()`:
- **`legacy`**: Simple `{open_questions, allow_codegen, risk_findings}` structure
- **`payment_workflow`**: Complex state machine with `current_phase`, `phase_status`, `checkpoints`, `artifacts`

Each stage's validation method branches on `state_kind` to call either a legacy path or a
payment-workflow-specific path.

---

## 2. Payment-Specific Code (Must Generalize)

### 2.1 Constants / Enumerations

| Constant | Value | Domain Coupling |
|----------|-------|-----------------|
| `SCHEMA_PATHS` | `spec/prove/plan` schema paths under `.payment-skill/spec/schema/` | MEDIUM - path structure is generic, filenames contain "payment" |
| `PAYMENT_WORKFLOW_SCHEMA` | Path with `01-收单机构开发任务/工作流/` | HIGH - hardcoded Chinese path segment, payment-specific schema |
| `SPEC_BUSINESS_FACTS_SCHEMA` | `spec-business-facts.v1.schema.json` | HIGH - payment business domain concept |
| `PROVE_ISSUE_ROUTING_SCHEMA` | `prove-issue-routing.v1.schema.json` | HIGH - payment routing/proof domain concept |
| `CONTROLLED_CHECKPOINTS` | `{NONE, spec-ok, prove-ok, layer-ok, final-ok}` | MEDIUM - checkpoint names are generic but `layer-ok` implies layer-based gen |
| `CONTROLLED_ALLOW_CODEGEN` | `{UNSET, YES, NO, YES_WITH_WARNING}` | LOW - generic codegen gate concept |
| `CONTROLLED_REVIEW_STATUS` | `{pending, approved, rework_required, rejected}` | LOW - generic review workflow |
| `GEN_LAYER_NODE_MAP` | `pojo_config_dto -> [G01..G03]`, `dependency_provider -> [G04]`, etc. | HIGH - payment adapter layer names |
| `GEN_NODE_PREREQS` | `G01: [], G02: [G01], G03: [G02]...` | HIGH - payment gen DAG structure |
| `TERMINAL_PHASE_ACTIONS` | `DONE/TERMINATED -> archive-payment-workflow.py` | HIGH - payment-specific archive script |

### 2.2 Payment-Only Methods

| Method | Lines | Purpose | Generalization Strategy |
|--------|-------|---------|------------------------|
| `run_payment_workflow_spec_validation()` | ~45 | Validates spec phase against payment-workflow-state | Abstract to `run_domain_spec_validation()` with pluggable checks |
| `run_payment_workflow_prove_validation()` | ~95 | Prove phase: business facts, config boundary, coverage, routing | Split into generic phase-gate checks + domain validators |
| `run_payment_workflow_gen_validation()` | ~90 | Gen phase: node DAG, layer completion, prereq enforcement | The DAG/layer pattern is reusable; node names are domain-specific |
| `run_payment_workflow_final_validation()` | ~70 | Final phase: report validation, p0 scan, compile status | Report validation is generic; p0 scan is payment-specific |
| `validate_resume_context_consistency()` | ~80 | Cross-field consistency for resume_context | Mostly generic state machine invariants |
| `validate_prove_routing_consistency()` | ~65 | Cross-validates prove-issue-routing against runtime state | HIGHLY payment-specific (business_fact_validation, scene_coverage, etc.) |
| `validate_preflight_entry_gate()` | ~25 | Blocks preflight when gen node is in rework/rejected | Generic gate pattern, payment-specific field paths |
| `validate_current_gen_node_gate()` | ~40 | Per-node verification state machine | Generic node state machine with payment field names |
| `validate_task_manifest_consistency()` | ~130 | Task manifest vs runtime state cross-validation | Mostly generic, but handoff paths are payment-specific |

### 2.3 Payment-Specific Imports

| Module | Purpose | Generalization |
|--------|---------|---------------|
| `final_report_contract` | Validates `12-生成后审核报告.md` with institution code pattern, accept/rework result parsing | Report validation is generic; institution code regex is domain-specific |
| `prove_routing_compat` | Normalizes legacy prove routing payloads to new schema format | Payment-specific backward compatibility shim |
| `check-business-facts.py` | Business fact validator script | Payment domain concept |
| `check-config-boundary.py` | Config boundary validator script | Payment domain concept |
| `check-payment-channel-coverage.py` | Channel coverage validator script | Highly payment-specific |
| `archive-payment-workflow.py` | Archive script for terminal states | Payment-specific |

### 2.4 Payment-Specific Path Patterns

```python
# All hardcoded to .payment-skill/ namespace
".payment-skill/spec/schema/*.schema.json"
".payment-skill/scripts/*.py"
".payment-skill/state/SESSION_BRIEF.md"
".payment-skill/handoff/prep-to-spec.json"
".payment-skill/handoff/spec-to-prove.json"
".payment-skill/handoff/gen-to-final.json"
".payment-skill/handoff/prove-to-gen.json"
".payment-skill/skills/payment-workflow-skill/references/01-收单机构开发任务/工作流/payment-workflow-state.schema.json"
```

---

## 3. Generic Code (Reusable Directly)

### 3.1 State Loading and Sanitization (`load_state`, lines 296-359)

The markdown-stripping logic is entirely generic and valuable:
- Detects ` ```json ` wrappers
- Strips prefix/suffix chatter (non-JSON text around the payload)
- Extracts first `{` to last `}` content
- Records violations for strict mode reporting
- JSON parsing with actionable error messages

**Reuse**: Extract to `StateLoader` class, parameterize the integrity check.

### 3.2 Schema Validation (`load_schema`, `validate_schema`, lines 259-294)

Generic JSON Schema validation using `jsonschema` library:
- Loads schema from path
- Validates instance against schema
- Reports path + error on failure

**Reuse**: Already generic. Just need to parameterize schema path mapping.

### 3.3 DAG Topological Sort (`run_plan_validation`, lines 1244-1317)

The plan stage validation is entirely generic:
- **Path sandbox validation**: Blocks absolute paths, `~`, Windows drive letters, `..` traversal
- **step_id uniqueness**: Ensures no duplicate step IDs
- **DAG topological sort**: Kahn's algorithm with cycle detection
- **Execution ordering output**: Prints resolved execution order

**Reuse**: 100% reusable. Extract to `DAGValidator` class.

### 3.4 Validator Subprocess Runner (`run_validator`, lines 579-607)

Generic pattern for running external validator scripts:
- Locates script in `.payment-skill/scripts/`
- Runs via `subprocess.run()` with `--input` flag
- Parses JSON output
- Reports stdout/stderr on failure

**Reuse**: Parameterize the scripts directory path.

### 3.5 Preflight Runner (`run_preflight`, lines 609-643)

Generic subprocess pattern for preflight checks:
- Runs `preflight.py --stage <stage> --state-file <path>`
- Passes through optional `--source-doc`, `--output-dir`, `--strict`
- Blocks on non-zero exit code

**Reuse**: Already generic.

### 3.6 Next-Action Plan and Execute Chain (`emit_next_action_plan`, `execute_next_action_chain`, `maybe_drive_next_action`, lines 645-739)

Generic two-phase orchestration:
1. **Plan**: Runs `plan-next-action.py` to generate an action plan JSON
2. **Execute**: Runs `execute-next-action.py` to execute the plan
3. **Temp file cleanup**: Creates temp plan if no output path specified

**Reuse**: The plan-then-execute pattern is generic.

### 3.7 Stage Dispatch Role Inference (`infer_stage_dispatch_role`, lines 111-129)

Maps phase names to worker/review agent role names. The pattern is generic; only the
specific role names are domain-tied.

### 3.8 Resume Action Binding Validation (`validate_resume_action_binding`, lines 131-161)

Generic state machine transition validation:
- Validates `next_required_action` is not empty
- Validates terminal phase actions match expected values
- Validates preflight action stage matches current phase
- Validates gen node action binding

**Reuse**: Parameterize terminal actions and preflight expectations.

### 3.9 `require_validator_pass` (lines 741-753)

Generic "run validator, check status in allowed set, fail with findings" pattern.

---

## 4. Dependencies

### 4.1 Standard Library

| Import | Usage |
|--------|-------|
| `json` | State file I/O, schema loading, validator output parsing |
| `sys` | `sys.exit(1)` for blocker enforcement, `sys.executable` for subprocess |
| `argparse` | CLI argument parsing |
| `subprocess` | Running external validators (preflight, check-*, plan-next-action, execute-next-action) |
| `os` | `os.close()` for temp file fd cleanup |
| `pathlib.Path` | All file path operations |
| `collections.defaultdict` | DAG adjacency list |
| `collections.deque` | BFS queue for topological sort |
| `datetime.datetime/timezone` | Referenced in imports but not directly used in orchestrator (used by dependencies) |
| `tempfile` | `mkstemp` for temporary plan files |

### 4.2 Third-Party

| Package | Usage |
|---------|-------|
| `jsonschema` | `validate()`, `ValidationError`, `Draft7Validator` for JSON Schema validation |

### 4.3 Local Modules (Same Directory)

| Module | Export Used | Purpose |
|--------|-------------|---------|
| `final_report_contract` | `validate_final_report(workdir, data)` | Returns `FinalReportValidation(ok, reason, result, critical, high, medium, low)` |
| `prove_routing_compat` | `normalize_legacy_prove_routing_payload(payload)` | Converts legacy prove routing format to current schema |
| `state_integrity` | `verify_state_integrity(state_path, data)` | HMAC-SHA256 integrity verification of state file |
| `task_identity` | `derive_task_id(state, task_scope, phase, execution_unit)` | Deterministic task ID derivation from state |

### 4.4 External Scripts (Subprocess Calls)

| Script | Trigger | Purpose |
|--------|---------|---------|
| `preflight.py` | `--run-preflight` flag | Pre-stage checks |
| `check-business-facts.py` | `--business-facts-input` arg | Business fact validation |
| `check-config-boundary.py` | `--config-boundary-input` arg | Config boundary validation |
| `check-payment-channel-coverage.py` | `--coverage-input` arg | Channel coverage validation |
| `plan-next-action.py` | `--next-action-plan-output` arg | Generate next-action plan |
| `execute-next-action.py` | `--execute-next-action` flag | Execute action plan |
| `archive-payment-workflow.py` | Terminal phase (DONE/TERMINATED) | Archive workflow |

---

## 5. State Management

### 5.1 State File Loading

```
File on disk -> raw_content -> markdown strip -> JSON extract -> json.loads() -> self.data
                                                                        |
                                                              verify_state_integrity()
                                                              (HMAC-SHA256 check)
```

The state file is loaded once in `load_state()` and held in `self.data` as a dict.
Modifications happen via `self.data` mutation, then `save_state()` writes back.

### 5.2 State Structure Detection

`detect_state_kind()` checks for the presence of `current_phase`, `phase_status`, and
`checkpoints` keys to distinguish `payment_workflow` from `legacy` state.

### 5.3 State Integrity

The `state_integrity` module provides HMAC-SHA256 signing:
- Key stored at `.payment-skill/state/.payment-state.integrity.key`
- Workspace root inferred from state file path by walking up to find `.payment-skill/scripts/`
- Verified on every `load_state()` call

### 5.4 State Write-Back

Only `save_state()` writes state (line 206-208). It uses `json.dump()` with
`ensure_ascii=False, indent=2`. However, the current orchestrator code never calls
`save_state()` -- it only reads and validates. State mutations happen in other scripts
(register-*.py, advance-gen-node.py, etc.).

### 5.5 Resume Context

The `resume_context` object in state controls the state machine:
- `current_execution_unit`: Which stage/node is active
- `next_required_action`: What the orchestrator should dispatch next
- `required_script`: Which script to run
- `pending_checkpoint`: Which checkpoint is pending (or "NONE")
- `last_review_status`: Current review state

---

## 6. Gate Integration

### 6.1 Gate Flow

```
Stage validation -> Schema validation -> Business logic validation
       |                    |                     |
       v                    v                     v
   [Blocker]           [Blocker]              [Blocker]
   sys.exit(1)         sys.exit(1)            sys.exit(1)
```

Every gate follows the same pattern:
1. Check a condition against `self.data`
2. On failure: print `[Blocker]` message with context, call `sys.exit(1)`
3. On success: print `[Success]` message, continue

### 6.2 Gate Categories

**Structural Gates** (schema-based):
- JSON Schema validation via `jsonschema.validate()`
- Required field presence checks
- Type checking (dict, str, list, bool)

**Transition Gates** (state machine):
- Phase prerequisite completion (e.g., "prep must be completed before spec")
- Checkpoint value validation against allowed set
- `allow_codegen` state transitions
- `review_status` state transitions

**Cross-Field Consistency Gates**:
- Task manifest vs runtime state alignment
- `resume_context` fields vs actual state
- `prove-issue-routing` output vs `gate_context` in state
- Gen node `verification` fields vs `resume_context.last_review_status`

**External Validator Gates**:
- `require_validator_pass()` pattern: run script, check `status in allowed_statuses`
- Used for: business facts, config boundary, channel coverage

**DAG Integrity Gates** (plan stage):
- Path sandbox (no absolute paths, no `..` traversal)
- step_id uniqueness
- Topological sort (no cycles)

### 6.3 Gate Result Propagation

Gates do not return values -- they are pure pass/fail with `sys.exit(1)` on failure.
The orchestrator is a "validation pipeline" not a "state transition engine". It reads
state, validates it, and either passes or blocks.

The only "side effect" path is `maybe_drive_next_action()` which can:
1. Generate a next-action plan (via `plan-next-action.py`)
2. Execute the plan (via `execute-next-action.py`)

---

## 7. Generalization Recommendations

### 7.1 Extract Generic Framework

```
orchestrator.py (1405 lines)
    |
    +-- harness/orchestrator.py        # Generic stage orchestrator
    |   +-- StateLoader                # Markdown stripping, JSON parsing, integrity
    |   +-- SchemaValidator            # JSON Schema validation
    |   +-- DAGValidator               # Topological sort, path sandbox
    |   +-- StageGateEngine            # Gate registration + execution
    |   +-- NextActionDriver           # Plan-then-execute pattern
    |
    +-- harness/gates/                 # Reusable gate types
    |   +-- phase_prereq_gate.py       # Phase prerequisite completion
    |   +-- checkpoint_gate.py         # Checkpoint value validation
    |   +-- cross_field_gate.py        # Cross-field consistency
    |   +-- external_validator_gate.py # Subprocess validator pattern
    |
    +-- payment/orchestrator.py        # Payment-specific config
        +-- SCHEMA_PATHS               # Override with payment schemas
        +-- GEN_LAYER_NODE_MAP         # Payment gen DAG
        +-- GEN_NODE_PREREQS           # Payment gen prereqs
        +-- run_*_validation()         # Payment-specific validations
```

### 7.2 Configuration-Driven Stage Definition

Replace hardcoded constants with a stage config file:

```yaml
stages:
  spec:
    schema: spec-state.v1.schema.json
    validators: [check-business-facts.py]
    checkpoint: spec-ok
    prereq_phases: [prep]
  prove:
    schema: prove-state.v1.schema.json
    validators: [check-business-facts.py, check-config-boundary.py, check-payment-channel-coverage.py]
    checkpoint: prove-ok
    prereq_phases: [spec]
  gen:
    schema: null  # uses payment-workflow-state schema
    checkpoint: layer-ok
    prereq_phases: [prove]
    dag:
      layers: { ... }
      nodes: { ... }
      prereqs: { ... }
  final:
    schema: null
    checkpoint: final-ok
    prereq_phases: [gen]
```

### 7.3 Key Extraction Points

1. **StateLoader** (lines 296-359): Pure utility, zero domain coupling. Extract immediately.
2. **DAGValidator** (lines 1244-1317): Pure utility, zero domain coupling. Extract immediately.
3. **GateEngine**: Abstract the `[Blocker] ... sys.exit(1)` pattern into a gate registry
   with pluggable gate functions.
4. **ValidatorRunner** (lines 579-607): Generic subprocess validator pattern.
5. **NextActionDriver** (lines 645-739): Generic plan-then-execute pattern.

### 7.4 Things That Must Stay Domain-Specific

- `GEN_LAYER_NODE_MAP` and `GEN_NODE_PREREQS` -- these define the payment adapter
  layer structure (POJO/Config/DTO, Dependency Provider, Adapter/Notify, Admin/SQL/i18n)
- `validate_prove_routing_consistency()` -- deeply coupled to payment business facts,
  scene coverage, and routing concepts
- `TERMINAL_PHASE_ACTIONS` -- references `archive-payment-workflow.py`
- Handoff file paths (`prep-to-spec.json`, `spec-to-prove.json`, etc.)
- All `check-*.py` validator scripts
