# Harness Gate Mechanism Analysis

> Based on analysis of `hjly-payment-workflow-skill` branch `feat/payment-workflow-state-contracts`.
> Source: `.payment-skill/scripts/preflight.py`, `orchestrator.py`, `phase-handoff.py`, `check-*.py`, `state_integrity.py`, `final_report_contract.py`.

---

## 1. Gate Mechanism Overview

The payment workflow uses a **three-tier gate architecture**:

```
Tier 1: Preflight (preflight.py)        -- environment/state readiness
Tier 2: Orchestrator (orchestrator.py)   -- schema + controlled-field validation
Tier 3: Business checks (check-*.py)    -- domain-specific semantic validation
```

### How Gates Are Defined

Gates are **not** declared in a central registry. Instead, they are defined implicitly through:

- **JSON Schemas** (`payment-workflow-state.schema.json`, `spec-business-facts.v1.schema.json`, `prove-issue-routing.v1.schema.json`) -- structural contracts for state files and artifacts.
- **Python check scripts** -- each `check-*.py` file encodes a set of numbered rules (e.g., `BF-01` through `BF-07` in `check-business-facts.py`, `A01` through `A13` in `check-admin-sql-i18n-completeness.py`).
- **Allowed-value sets** in `preflight.py` -- hardcoded constants like `ALLOWED_STAGES`, `ALLOWED_CHECKPOINTS`, `ALLOWED_ALLOW_CODEGEN` define valid state values.
- **DAG prerequisites** -- `GEN_NODE_PREREQS` and `GEN_LAYER_NODE_MAP` define ordering constraints for the gen phase.

### How Gates Are Executed

Gates are executed as **Python scripts invoked via CLI**:

```bash
# Preflight before a stage
preflight.py --stage <stage> --state-file <path> [--source-doc <path>] [--output-dir <path>] [--strict] [--json-output]

# Orchestrator validates a stage manifest
orchestrator.py --stage <stage> --manifest <path>

# Phase handoff performs checkpoint gates
phase-handoff.py --from-phase <phase> --checkpoint <checkpoint> --await-user-action

# Business-specific checks
check-business-facts.py --input <json-path>
check-payment-channel-coverage.py --input <json-path>
check-enum-allocation.py --input <json-path>
check-config-boundary.py --input <json-path>
check-admin-sql-i18n-completeness.py --input <json-path>
```

### How Results Are Recorded

Results are recorded in multiple places:

1. **stdout** -- text or JSON output from the script itself.
2. **`preflight-result.json`** -- written to `.payment-skill/output/preflight-result.json` by `preflight.py`. Contains `stage`, `can_proceed`, `allowed_actions`, and `timestamp`.
3. **State file** -- gate outcomes are written back into `payment-workflow-state.json` under `checkpoints.gate_context` (e.g., `business_fact_validation_passed: true`).

---

## 2. Preflight Checks by Phase

The `preflight.py` script runs four validation categories before every phase, then phase-specific input checks.

### 2.1 Common Checks (All Phases)

| Category | Item | What It Checks |
|----------|------|----------------|
| `skill_entry` | `skill_md_exists` | `SKILL.md` entry point exists |
| `skill_entry` | `state_contract_exists` | State contract doc exists |
| `skill_entry` | `phase_dependency_rule_exists` | Phase dependency list exists |
| `skill_entry` | `preflight_rule_exists` | Preflight rules doc exists |
| `toolchain` | `python3_available` | `python3` is on PATH |
| `toolchain` | `jsonschema_available` | `jsonschema` Python package importable |
| `toolchain` | `build_tool_available` | `mvn` or `gradle` or `gradlew` exists (WARNING only) |

### 2.2 Runtime State Checks (All Phases)

| Item | What It Checks |
|------|----------------|
| `state_file_exists` | State file path exists |
| `state_file_json` | State file is valid JSON |
| `state_integrity_valid` | HMAC-SHA256 integrity seal passes |
| `state_schema_valid` | State conforms to `payment-workflow-state.schema.json` |
| `current_phase_valid` | `current_phase` is in allowed set |
| `phase_status_valid` | Phase status is `pending`/`in_progress`/`completed`/`blocked` |
| `last_checkpoint_valid` | `last_checkpoint` is in `NONE`/`spec-ok`/`prove-ok`/`layer-ok`/`final-ok` |
| `state_contract_version_valid` | Contract version string present and non-empty |
| `allow_codegen_valid` | Codegen flag is `UNSET`/`YES`/`NO`/`YES_WITH_WARNING` |
| `awaiting_user_action` | If `true`, blocks automatic progression |
| `resume_context_exists` | `resume_context` dict present with all required keys |
| `resume_action_binding` | `next_required_action` matches `required_script` |

### 2.3 Phase-Specific Input Checks

#### `prep` Stage
- `--source-doc` arg provided and path exists
- Source directory is non-empty
- Doc files (`.doc`/`.docx`/`.pdf`) have a parsing toolchain available
- `--output-dir` exists and is writable

#### `spec` Stage
- `prep` phase status is `completed`
- `prep-facts-*.md` and `prep-evidence-*.md` exist in phase_1 outputs

#### `prove` Stage
- `spec` phase status is `completed`
- `last_checkpoint` is `spec-ok`
- `spec-business-facts-{code}.json` exists and validates against `spec-business-facts.v1.schema.json`
- If `prove-ok` reached, `business_fact_validation_passed` must be `true`

#### `gen` Stage
- `prove` phase status is `completed`
- `last_checkpoint` is `prove-ok`
- `prove-issue-routing-{code}.json` exists and validates against its schema
- `allow_codegen` is not `NO`
- No `human_required` questions still `pending`
- DAG prerequisite nodes are completed before successor nodes start
- Generated files declared by completed nodes actually exist on disk

#### `final` Stage
- `gen` phase status is `completed`
- All 9 gen nodes (`G01`-`G09`) are `completed` with `verification.review_status == approved` and `verification.script_status == passed`
- All 4 layers are `completed`
- `admin_sql_i18n` compile status is not `failed`
- `audit_report` passes `final_report_contract` validation (path format, file exists, `result: accept|rework` header, severity counts)

---

## 3. Gate Results Format

### 3.1 CheckResult Dataclass

```python
@dataclass
class CheckResult:
    category: str      # e.g., "skill_entry", "runtime_state", "stage_input", "toolchain", "doc_parse"
    item: str          # e.g., "state_file_exists", "prep_completed"
    status: str        # "PASS" | "FAIL"
    severity: str|None # None (for PASS), "BLOCKER", "WARNING", "INFO"
    message: str       # Human-readable description
```

### 3.2 Summary

```python
{
    "pass_count": int,
    "blocker_count": int,
    "warning_count": int,
    "info_count": int
}
```

### 3.3 Decision

```python
{
    "can_proceed": bool,
    "reason": str
}
```

### 3.4 Preflight Result File (written to disk)

```json
{
    "stage": "prove",
    "can_proceed": true,
    "allowed_actions": ["run_checkpoint:prove-ok"],
    "timestamp": "2026-06-07T12:00:00+00:00"
}
```

### 3.5 JSON Output Mode (--json-output)

```json
{
    "stage": "prove",
    "checks": [
        {"category": "...", "item": "...", "status": "PASS", "severity": null, "message": "..."}
    ],
    "summary": {"pass_count": 12, "blocker_count": 0, "warning_count": 1, "info_count": 0},
    "decision": {"can_proceed": true, "reason": "..."},
    "allowed_actions": ["run_checkpoint:prove-ok"]
}
```

### 3.6 Business Check Output (check-*.py scripts)

Each business check script outputs a findings list:

```json
{
    "status": "PASS|WARN|FAIL",
    "findings": [
        {"code": "BF-01", "severity": "BLOCKER", "message": "...", "...extra fields...": "..."}
    ],
    "manual_review_required": ["..."],
    "checked_rules": ["BF-01", "BF-02", "..."]
}
```

---

## 4. Failure Handling

### 4.1 Severity-Based Decision Logic

```python
def decide(summary, strict):
    if blocker_count > 0:
        return False, "BLOCKER present -- must fix"
    if strict and warning_count > 0:
        return False, "Strict mode: WARNING present -- must confirm"
    if warning_count > 0:
        return True, "Passed with WARNING(s) logged"
    return True, "Passed"
```

### 4.2 Exit Codes

- `preflight.py` exits with **code 0** if `can_proceed == True`, **code 1** otherwise.
- `check-*.py` scripts exit with **code 1** if any BLOCKER finding, **code 0** otherwise.

### 4.3 Blocking Semantics

| Severity | Normal Mode | Strict Mode |
|----------|-------------|-------------|
| BLOCKER | Blocks execution | Blocks execution |
| WARNING | Proceeds (logged) | Blocks execution |
| INFO | Proceeds (logged) | Proceeds (logged) |

### 4.4 Failure Recovery

There is no automatic recovery. When a gate fails:

1. The script outputs the full list of BLOCKERs.
2. The orchestrator/agent must fix the issues and re-run the gate.
3. For `awaiting_user_action == true`, the workflow pauses until a human invokes `phase-handoff.py --user-action <action>`.
4. For `rework_required`/`rejected` review status, the workflow is restricted to re-dispatching the current node only.

### 4.5 Action Gating via compute_allowed_actions

The preflight script computes a list of **allowed actions** based on current state:

- `awaiting_user_action == true` --> only `run_checkpoint:*` or `wait_for_user_action`
- `last_review_status in {rework_required, rejected}` --> only re-dispatch current node
- `pending_checkpoint != NONE` --> only checkpoint or wait actions
- Normal flow --> only the single `next_required_action` from `resume_context`

This is written to `preflight-result.json` and prevents the orchestrator from taking illegal actions.

---

## 5. Payment-Specific Checks

These checks encode domain knowledge specific to the payment processing system and are **not generalizable**.

### 5.1 check-business-facts.py (BF-01 through BF-07)

| Rule | Domain Concept | What It Validates |
|------|---------------|-------------------|
| BF-01 | Platform and Protocol | Platform (UnionPay/WeChat/Alipay) and protocol family explicitly stated |
| BF-02 | Payment Method/Scenario | Payment method and scenario explicitly stated |
| BF-03 | PaymentChannelEnum Coverage | Whether the target enum covers the required payment scenarios |
| BF-04 | Amount Unit and Time Semantics | Currency unit (fen/yuan), time zone, timestamp format explicitly stated |
| BF-05 | ConfigJson/SplitConfigJson Boundary | Which fields belong to main config vs split config explicitly concluded |
| BF-06 | Certificate Strategy | Certificate format (pfx/jks/cer), storage path, and loading strategy stated |
| BF-07 | Notification Chain | Notification URL resolution, callback handling, and config consumption points stated |

### 5.2 check-payment-channel-coverage.py

Validates that `PaymentChannelEnum` covers all required scenarios:
- Maintains an alias map (`SCENE_ALIASES`) from Chinese/English/code names to canonical scene names.
- Cross-references against system baseline scenes and task-explicit scenes.
- Detects non-channel-capable scenarios that should not have enum entries.

### 5.3 check-enum-allocation.py

Detects enum value/segment collisions:
- Parses Java enum files to extract `(NAME, numeric_value)` pairs.
- Checks if a target value or name is already occupied.
- Checks if a target range overlaps with existing entries.
- Reads enum file paths from `payment-workspace.json` configuration.

### 5.4 check-config-boundary.py

Validates ConfigJson field placement boundaries:
- **CONSTANT_FIELDS** (e.g., `encoding`, `charset`, `version`) must NOT be in ConfigJson -- they are compile-time constants.
- **RUNTIME_DERIVED_FIELDS** (e.g., `notify_url`, `out_trade_no`, `request_time`) must NOT be in ConfigJson -- they are generated at runtime.
- **SPLIT_FIELDS** (e.g., `sub_merchant_no`, `split_receiver_list`) must NOT be in main ConfigJson -- they belong in SplitConfigJson.
- **CERT_PATH_FIELDS** (e.g., `certificate_path`, `mch_private_key_path`) require explicit evidence before inclusion.

### 5.5 check-admin-sql-i18n-completeness.py (A01 through A13)

Validates the admin/SQL/i18n generation layer:
- WebInDTO/WebOutDTO/WebBizService classes exist.
- Platform and channel i18n keys are bidirectionally complete.
- SQL draft exists.
- Template and page assets exist.
- Conditional deliverables triggered by config are present.

### 5.6 State Integrity (state_integrity.py)

Uses **HMAC-SHA256** to seal the state file:
- A secret key is stored in `.payment-skill/state/.payment-state.integrity.key`.
- The state is canonicalized (sorted JSON, `integrity` field stripped), then HMAC'd.
- The seal is stored in `state["integrity"]` with `algorithm`, `version`, `fingerprint`, `sealed_at`.
- Any tampering with the state file causes integrity verification to fail.

### 5.7 Final Report Contract (final_report_contract.py)

Validates the final audit report:
- Path must be exactly `.payment-skill/output/final/{institution_code}/12-生成后审核报告.md`.
- File must exist at the resolved path.
- File must contain `result: accept` or `result: rework`.
- File must contain severity count headers: `critical:`, `high:`, `medium:`, `low:`.

---

## 6. Generalizable Checks (Reusable for Any Java Project)

The following mechanisms from `preflight.py` can be extracted into a reusable Harness gate framework.

### 6.1 State File Lifecycle Management

The pattern of a **single JSON state file** that tracks:
- `current_phase` / `phase_status` -- which phase, what status
- `checkpoints` / `last_checkpoint` -- gate progression markers
- `resume_context` -- exactly one `next_required_action` + `required_script`
- `artifacts` -- phase-specific outputs
- `integrity` -- HMAC seal

This is fully generalizable. Any multi-phase Java project can adopt this pattern.

### 6.2 Resume Context Validation

The `resume_context` pattern enforces:
- Exactly one `next_required_action` at any time.
- `required_script` must match `next_required_action` (derived via `infer_expected_script`).
- `current_execution_unit` must align with `current_phase`.
- `pending_checkpoint` / `awaiting_user_action` create mandatory pause points.

This prevents "drift" where the orchestrator and state disagree on what should happen next.

### 6.3 Phase Dependency Chain

The sequential phase dependency check:

```
prep -> spec -> prove -> gen -> final
```

Each phase requires the previous phase to be `completed` and the corresponding checkpoint to be reached. This is a universal pattern.

### 6.4 DAG-Based Node Scheduling

The gen phase uses a DAG with:
- 4 layers (`pojo_config_dto`, `dependency_provider`, `adapter_notify`, `admin_sql_i18n`)
- 9 nodes (`G01`-`G09`) with explicit prerequisite edges
- Layer completion requires all contained nodes to be completed
- Node start requires all prerequisites to be completed

This DAG pattern is generalizable to any multi-module code generation workflow.

### 6.5 Checkpoint Gate System

Checkpoints (`spec-ok`, `prove-ok`, `layer-ok`, `final-ok`) serve as:
- **Phase transition gates** -- a phase cannot advance until its checkpoint is reached.
- **User confirmation points** -- `awaiting_user_action` pauses automation.
- **Branching points** -- each checkpoint has defined `CHECKPOINT_ACTIONS` (e.g., `spec-ok` can `continue_prove_resolvable`, `revise_spec`, or `terminate_workflow`).

### 6.6 Toolchain Availability Detection

```python
has_command("python3")
has_command("mvn")
has_command("gradle")
(workspace_root / "gradlew").exists()
```

This is trivially generalizable to any Java project. Can be extended to check JDK version, Maven wrapper, Gradle wrapper, etc.

### 6.7 JSON Schema Validation Pattern

The pattern of:
1. Define a JSON Schema for each artifact type.
2. Validate produced artifacts against their schema before proceeding.
3. Support legacy format normalization (`prove_routing_compat.py`).

This is generalizable to any workflow that produces structured artifacts.

### 6.8 Strict Mode

The `--strict` flag promotes WARNINGs to blockers. This is useful for CI/CD pipelines where you want to enforce "zero warnings" before merge.

### 6.9 CheckResult Data Model

The `CheckResult(category, item, status, severity, message)` pattern with `summarize()` and `decide()` functions provides a reusable gate result framework. Any new gate check can produce `CheckResult` objects and feed them into the same summarization pipeline.

---

## 7. Extraction Blueprint for Harness Framework

To generalize this into a reusable Harness gate system:

### Core (generalizable)

| Component | Current Location | Extraction Target |
|-----------|-----------------|-------------------|
| `CheckResult` dataclass | `preflight.py` | `harness-gates/check_result.py` |
| `summarize()` / `decide()` | `preflight.py` | `harness-gates/decision.py` |
| State file schema + validation | `preflight.py` + `payment-workflow-state.schema.json` | `harness-gates/state_schema.py` |
| `state_integrity.py` HMAC seal | `state_integrity.py` | `harness-gates/integrity.py` |
| Resume context validation | `preflight.py` | `harness-gates/resume_context.py` |
| Phase dependency chain | `preflight.py` | `harness-gates/phase_chain.py` |
| DAG node scheduling | `preflight.py` + `orchestrator.py` | `harness-gates/dag_scheduler.py` |
| Checkpoint system | `phase-handoff.py` | `harness-gates/checkpoint.py` |
| JSON artifact schema validation | `preflight.py` | `harness-gates/artifact_validator.py` |
| Toolchain detection | `preflight.py` | `harness-gates/toolchain.py` |
| Preflight result file | `preflight.py` | `harness-gates/preflight_result.py` |
| Action gating | `preflight.py` | `harness-gates/action_gate.py` |

### Domain-specific (payment only)

| Component | Keep In Domain |
|-----------|---------------|
| `check-business-facts.py` | Payment skill |
| `check-payment-channel-coverage.py` | Payment skill |
| `check-enum-allocation.py` | Payment skill |
| `check-config-boundary.py` | Payment skill |
| `check-admin-sql-i18n-completeness.py` | Payment skill |
| `final_report_contract.py` | Payment skill |
| `prove_routing_compat.py` | Payment skill |

### Extension Points for Other Domains

A new domain (e.g., inventory, CRM) would:
1. Define its own JSON Schema for state and artifacts.
2. Write domain-specific `check-*.py` scripts.
3. Define its own phase chain and DAG (if code generation is involved).
4. Reuse the core gate framework for state validation, integrity, checkpoints, and action gating.

---

## 8. Key Design Decisions

1. **No central gate registry** -- gates are encoded in code, not configuration. This makes them precise but harder to discover.
2. **State file as single source of truth** -- all gate outcomes flow back into `payment-workflow-state.json`.
3. **HMAC integrity seal** -- prevents silent state corruption between sessions.
4. **Single-action enforcement** -- `resume_context.next_required_action` is always exactly one action, preventing ambiguous state.
5. **Blocking review statuses** -- `rework_required` and `rejected` restrict the workflow to re-dispatch only, preventing forward escape.
6. **Layered severity** -- BLOCKER/WARNING/INFO with strict-mode promotion gives fine-grained control.
7. **Preflight result file** -- enables downstream scripts to read allowed actions without re-running preflight.
