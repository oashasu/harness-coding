# payment-workflow-state-contracts Schema & Prompt Analysis

> Source: `hjly-payment-workflow-skill` branch `origin/feat/payment-workflow-state-contracts`
> Purpose: Extract reusable HARNESS patterns from payment-specific contracts

---

## 1. Schema Inventory (13 files)

All schemas live under `.payment-skill/spec/schema/`.

### 1.1 Fully Generic Schemas (6 files) -- directly reusable

| Schema | Title | Purpose |
|--------|-------|---------|
| `plan-state.v1.schema.json` | PaymentPlanStateV1 | DAG blueprint with steps, owner, depends_on, reads, writes, checks |
| `task-manifest.v1.schema.json` | TaskManifestV1 | Worker dispatch manifest: scope, phase, inputs, expected_outputs |
| `review-result.v1.schema.json` | ReviewResultV1 | Review outcome: approved/rework_required/rejected + rework_items |
| `worker-final-report.v1.schema.json` | WorkerFinalReportV1 | Worker completion report (v1, legacy) |
| `worker-final-report.v2.schema.json` | WorkerFinalReportV2 | Worker completion report (v2, current) |
| `next-action-plan.v1.schema.json` | NextActionPlanV1 | Orchestrator next-action planning with commands, collectors, followup |
| `next-action-execution.v1.schema.json` | NextActionExecutionV1 | Execution result: status, action_kind, commands executed |

**plan-state.v1.schema.json**

- Key fields: `batch_id`, `steps[].{step_id, owner, depends_on, reads, writes, checks}`
- reads/writes enforce relative path pattern (no `..`, no absolute)
- Payment-specific note: `owner` enum includes `SpecAgent`, `ProveAgent`, `EnumAgent`, `ConfigAgent`, `DTOAgent`, `ProviderAgent`, `AdapterAgent`, `NotifyAgent`, `SQLAgent`, `Human`. For HARNESS generalization: replace with configurable role set or use generic names like `Worker-{role}`.

**task-manifest.v1.schema.json**

- Key fields: `manifest_version`, `task_scope` (stage/gen_node), `phase`, `execution_unit`, `institution`, `task_id`, `dispatch_role`, `review_role`, `inputs`, `expected_outputs`
- `dispatch_role` is `const "GLM-5Worker"`, `review_role` is `const "ReviewAgent"` -- payment-specific naming
- `institution` object (code+name) -- payment-specific entity; generalize to `target_entity` or `context`
- `generation_mode` enum only has `yaml_to_java` -- payment-specific
- Pattern is fully reusable: manifest-driven dispatch with contract validation

**review-result.v1.schema.json**

- Key fields: `manifest_version`, `task_id`, `task_scope`, `phase`, `execution_unit`, `review_status`, `summary`, `report_path`, `rework_items`, `patch_allowed`
- `task_id` pattern: `^(stage|gen_node):[a-z]+:[A-Za-z0-9_]+:[a-z0-9_-]+$` -- generic
- Fully reusable as-is for any HARNESS workflow

**worker-final-report.v2.schema.json**

- Key fields: `manifest_version` (const "2.0"), `task_id`, `task_scope`, `phase`, `execution_unit`, `node_id`, `worker_status`, `summary`, `changed_files`, `generated_files`, `commands`, `script_status`, `compile_status`, `review_hints`
- Output limits: summary 500ch, files 50, commands 20, hints 10x200ch
- Fully reusable for any code generation workflow

**next-action-plan.v1.schema.json**

- Key fields: `current_phase`, `next_required_action`, `required_script`, `action_kind`, `commands`, `collectors`, `followup`, `pending_checkpoint`, `allowed_actions`
- `action_kind` enum: dispatch_worker, dispatch_review, run_gate, run_checkpoint, wait_for_user, archive -- generic
- `phase` enum: prep, spec, prove, gen, final, DONE, TERMINATED -- payment-specific names, generic pattern
- `collectors` hardcodes `collect-worker-report.py` and `collect-review.py` -- script naming is payment-specific

**next-action-execution.v1.schema.json**

- Key fields: `execution_version`, `status`, `plan_file`, `action_kind`, `task_scope`, `phase`, `execution_unit`, `commands`
- `commands[].script` enum: 8 specific Python scripts -- all payment-specific script names
- `phase` enum: prep, spec, prove, gen, final, DONE, TERMINATED -- same as above

### 1.2 Payment-Specific Schemas (4 files) -- need generalization or are domain-only

| Schema | Title | Purpose |
|--------|-------|---------|
| `payment-channel-allocation-registry.v1.schema.json` | PaymentChannelAllocationRegistry | Channel enum-to-ID mapping |
| `payment-channel-config.v1.schema.json` | PaymentChannelConfig | Channel config with payment_way, payment_scene, i18n_key |
| `spec-business-facts.v1.schema.json` | SpecBusinessFactsV1 | Structured facts from channel documentation |
| `prove-issue-routing.v1.schema.json` | ProveIssueRoutingV1 | Issue routing with business fact validation gate |

**payment-channel-allocation-registry.v1.schema.json**

- Key fields: `registry_version`, `channels[].{enum_name, channel_id}`
- Entirely payment-domain specific. No generalization path -- this is a domain artifact.

**payment-channel-config.v1.schema.json**

- Key fields: `config_version`, `platform_key`, `channels[].{enum_name, channel_id, payment_way, payment_scene, channel_method, code, name, i18n_key}`
- Entirely payment-domain specific. The pattern of "external entity config with enum mapping" could be abstracted.

**spec-business-facts.v1.schema.json**

- Key fields: `task_context`, `channel_facts`, `enum_facts`, `config_facts`, `notify_facts`, `open_questions`, `evidence_refs`
- `channel_facts`: protocol_family, payment_methods, payment_scenes, amount_unit, time_pattern -- all payment-specific
- `enum_facts`: platform_type_locked, required_channel_enums -- payment-specific
- `config_facts`: certificate_storage_mode, split_config -- payment-specific
- `notify_facts`: notify_chain_declared, notify_url_strategy -- payment-specific
- Generalization: The overall structure of "structured facts from external docs" is reusable. The field names within each fact category are domain-specific. For HARNESS, this becomes `spec-domain-facts` with pluggable fact categories.

**prove-issue-routing.v1.schema.json**

- Key fields: `business_fact_validation`, `issue_normalization`, `solution_collapse`, `routing`, `allow_codegen`, `gate_context_update`
- `routing` splits into `prove_resolvable`, `prove_with_risk`, `human_required` -- generic triage pattern
- `allow_codegen` enum: UNSET/YES/NO/YES_WITH_WARNING -- generic gate pattern
- `gate_context_update`: business_fact_validation_passed, scene_coverage_passed -- payment-specific gates
- Generalization: The issue routing + gate pattern is fully reusable. The gate conditions within `gate_context_update` need to be domain-configurable.

### 1.3 Legacy Schemas (2 files) -- backward compatibility only

| Schema | Title | Purpose |
|--------|-------|---------|
| `spec-state.v1.schema.json` | LegacyPaymentSpecStateV1 | Old spec entry, deprecated |
| `prove-state.v1.schema.json` | LegacyPaymentProveStateV1 | Old prove entry, deprecated |

Both are explicitly marked as legacy in their descriptions. The new mainline uses `spec-business-facts.v1` and `prove-issue-routing.v1` instead.

---

## 2. Prompt Inventory (9 files)

All prompts live under `.payment-skill/prompts/`.

### 2.1 Core Orchestrator Layer (3 prompts) -- directly reusable pattern

| Prompt | Role | Responsibility |
|--------|------|----------------|
| `main-orchestrator-prompt.md` | MainOrchestratorAgent | Sole decision-maker: read state, build manifest, dispatch, collect, gate |
| `worker-node-prompt.md` | GLM-5Worker | Execute current execution_unit per manifest, output Worker final report |
| `review-node-prompt.md` | ReviewAgent | Read-only audit of manifest compliance, output Review result |

**main-orchestrator-prompt.md**

- Role: Sole orchestrator with exclusive decision authority
- Responsibilities: Phase/node tracking, manifest construction, Worker dispatch, Review dispatch, rework/small-fix/solo-takeover decisions, gate script execution, state updates
- Key instructions: Only read minimal inputs per round; use state file as truth source; validate Worker final report v2 and Review result v1 schemas; rework rules (2 rounds max, then solo takeover)
- Payment-specific: References `.payment-skill/state/`, `.payment-skill/scripts/`, `institution` concept in manifests, specific script names
- Generic pattern: The entire orchestration loop (manifest -> dispatch -> collect -> review -> gate -> state update) is domain-agnostic

**worker-node-prompt.md**

- Role: Code generation worker
- Responsibilities: Consume only manifest-declared inputs, process only current execution_unit, output Worker final report v2
- Key instructions: Input boundary enforcement, execution boundary (only current unit), delivery requirements (must produce tangible artifacts), output limits
- Payment-specific: References `GLM-5Worker` role name, `.payment-skill/` paths
- Generic pattern: Manifest-driven worker with strict boundary enforcement and structured output contract

**review-node-prompt.md**

- Role: Read-only reviewer
- Responsibilities: Audit manifest compliance, verify Worker execution scope, output Review result v1
- Key instructions: Read-only discipline (no code changes, no state changes), review scope limited to manifest, review_status semantics (approved/rework_required/rejected/pending)
- Payment-specific: None significant. Review logic is generic.
- Generic pattern: Fully reusable review contract with rework_items and patch_allowed semantics

### 2.2 Domain-Specific Agent Prompts (4 prompts) -- patterns reusable, content domain-specific

| Prompt | Role | Responsibility |
|--------|------|----------------|
| `spec-agent-prompt.md` | SpecAgent | Extract structured facts from external channel documentation |
| `prove-agent-prompt.md` | ProveAgent | Semantic alignment, business fact validation, risk gate |
| `plan-agent-prompt.md` | PlanAgent | Generate DAG execution blueprint from spec+prove outputs |
| `code-agent-prompt.md` | CodeAgent | Execute single step writes per plan+prove+evidence |

**spec-agent-prompt.md**

- Role: "First line of defense" -- fact extractor from external documentation
- Responsibilities: Read channel docs (PDF/MD/web), extract raw facts as structured JSON
- Key instructions: Stateless (no internal system knowledge), no internal decisions, JSON-only output, extreme fidelity (100% verbatim for crypto suites), open_questions with severity for blocking
- Payment-specific: Entirely about payment channel documentation parsing (protocol, sign algorithms, API names, endpoints)
- Generalizable pattern: "Extract structured domain facts from unstructured external documentation" is universal. Replace channel_facts with domain-specific fact categories.

**prove-agent-prompt.md**

- Role: "Second line of defense" -- semantic gatekeeper
- Responsibilities: Validate spec facts against internal norms, route issues, set codegen gate
- Key instructions: JSON-only output, route issues into prove_resolvable/prove_with_risk/human_required, P0 veto (any P0 risk forces allow_codegen=NO), allow_codegen enum (UNSET/YES/NO/YES_WITH_WARNING)
- Payment-specific: References "hjly payment infrastructure", enum-registry, "global semantic baseline", "payment adapter negative case library", P0/P1 risk rules
- Generalizable pattern: "Validate extracted facts against internal norms, route issues, gate progression" is universal. Replace payment norms with domain-specific validation rules.

**plan-agent-prompt.md**

- Role: "Third line of defense and commander" -- DAG planner
- Responsibilities: Generate execution blueprint from spec+prove outputs, ensure dependency correctness
- Key instructions: JSON-only output (starts with `{`, ends with `}`), relative paths only, result-oriented checks (not commands), DAG acyclicity, four-layer generation sequence (pojo_config_dto -> dependency_provider -> adapter_notify -> admin_sql_i18n)
- Payment-specific: Four-layer sequence is payment-specific (Config/DTO/Enum before Adapter/Notify/SQL), references payment artifacts
- Generalizable pattern: DAG-based execution planning with dependency ordering is fully reusable. Layer sequence should be domain-configurable.

**code-agent-prompt.md**

- Role: "Final executor" -- code writer
- Responsibilities: Write code per plan step, respecting prove-state constraints
- Key instructions: Absolute path sandbox (only modify writes-listed files), no magic values (use existing utils), framework constraints (Adapter must extend base class, @PaymentPlatformApi annotation), exception handling norms, logging norms, execute mitigation strategies
- Payment-specific: Entirely payment-focused: AbstractPaymentAdapterService, PaymentPlatformEnum, PaymentException, AmountUtil, BigDecimal patterns, @Slf4j logging
- Generalizable pattern: "Write code per step plan with sandbox constraints" is universal. Framework constraints and utility references need domain injection.

### 2.3 Navigation/Contract Docs (2 prompts) -- fully reusable structure

| Prompt | Purpose |
|--------|---------|
| `AI-GUIDE.md` | Directory navigation: which prompt to read when |
| `AI-GUIDE-prompt-contract.md` | Consolidated contract summary for Worker/Review/Orchestrator |

**AI-GUIDE.md** -- Defines the routing rules: "one prompt per turn", main-orchestrator as default, worker-node when dispatching, review-node when reviewing, legacy prompts for compatibility. Pattern is reusable.

**AI-GUIDE-prompt-contract.md** -- Consolidates all three role contracts (Worker input/output boundary, Review read-only discipline, Orchestrator decision authority) into one reference document. Fully reusable structure.

---

## 3. Role Mapping: payment-workflow-state -> HARNESS

### 3.1 Direct Mapping

| payment-workflow-state Role | HARNESS Role | What Changes |
|-----|---------|--------------|
| MainOrchestratorAgent | Orchestrator | Rename; replace `.payment-skill/` paths with configurable state_dir; replace `institution` with `target_entity`; keep manifest->dispatch->collect->review->gate loop |
| GLM-5Worker | Worker | Rename; replace `GLM-5Worker` const in manifest; keep manifest-driven boundary enforcement and Worker final report contract |
| ReviewAgent | Reviewer | Rename; keep read-only discipline, review-result contract, rework_items, patch_allowed semantics |
| SpecAgent | FactExtractor | Rename; replace channel_facts/enum_facts/config_facts/notify_facts with pluggable domain fact schema; keep the "extract structured facts from external docs" pattern |
| ProveAgent | DomainValidator | Rename; replace payment norms/validation rules with domain-configurable rules; keep issue routing (resolvable/risky/human_required) and gate pattern (allow_codegen -> allow_proceed) |
| PlanAgent | DAGPlanner | Rename; replace four-layer payment sequence with configurable layer ordering; keep DAG blueprint with steps/depends_on/reads/writes/checks |
| CodeAgent | CodeWorker | Rename; replace payment framework constraints (AbstractPaymentAdapterService, @PaymentPlatformApi) with domain-injected constraints; keep sandbox writes-list enforcement |

### 3.2 Role Not Present in payment-workflow-state (needed for HARNESS)

| HARNESS Role | Purpose | Notes |
|---------|---------|-------|
| PrepAgent | Pre-analysis: gather context, classify task complexity | payment-workflow has prep as a phase but no dedicated prompt; prep logic is embedded in orchestrator |

### 3.3 Schema Generalization Map

| payment Schema | HARNESS Schema | Generalization |
|-----|------|------|
| `plan-state.v1` | `dag-plan.v1` | Replace owner enum with configurable role set |
| `task-manifest.v1` | `task-manifest.v1` | Replace institution with target_entity; replace const role names; remove generation_mode or make enum extensible |
| `review-result.v1` | `review-result.v1` | Use as-is |
| `worker-final-report.v2` | `worker-report.v1` | Use as-is |
| `next-action-plan.v1` | `action-plan.v1` | Replace phase enum names; replace hardcoded script names with script registry |
| `next-action-execution.v1` | `action-execution.v1` | Replace script enum with configurable script set; replace phase enum |
| `spec-business-facts.v1` | `domain-facts.v1` | Replace channel_facts/enum_facts/config_facts/notify_facts with pluggable fact categories |
| `prove-issue-routing.v1` | `validation-routing.v1` | Replace gate_context_update with domain-configurable gates; keep routing triage pattern |
| `payment-channel-*` | N/A | Domain artifact, no HARNESS equivalent |
| `spec-state.v1` / `prove-state.v1` | N/A | Legacy, deprecated |

### 3.4 Key Patterns to Preserve in HARNESS

1. **Manifest-driven dispatch**: Orchestrator builds task manifest -> Worker consumes manifest -> Reviewer audits against manifest. The manifest is the single truth source for each dispatch cycle.

2. **Structured output contracts**: Every role has a JSON schema for its output. Orchestrator validates schemas before proceeding. No free-text reports as deliverables.

3. **Boundary enforcement**: Workers can only read manifest-declared inputs and write manifest-declared outputs. Reviewers can only audit manifest-declared scope. Violations are blocking.

4. **Gate-based progression**: Each phase/node requires gate validation before proceeding. Gates are script-driven (preflight, compile, etc.) with structured pass/fail.

5. **Issue routing triage**: Problems are routed into three buckets: auto-resolvable, risky-but-proceed, human-required. This pattern applies to any domain validation.

6. **Rework with escalation**: Up to 2 rework rounds, then orchestrator solo takeover. Review decides rework vs small-fix vs reject. patch_allowed controls whether orchestrator can do inline fixes.

7. **Phase/state machine**: prep -> spec -> prove -> gen -> final, with DONE and TERMINATED as terminal states. For HARNESS: the phase names should be configurable, but the state machine pattern (sequential phases with gates) is universal.

8. **DAG execution for gen phase**: The gen phase uses a DAG of steps with dependency ordering. Steps are dispatched individually to Workers. This allows parallel execution of independent steps.

---

## 4. Summary of Generalization Work

### Trivial (copy as-is or rename only)

- `review-result.v1.schema.json` -> `review-result.v1.schema.json`
- `worker-final-report.v2.schema.json` -> `worker-report.v1.schema.json`
- `review-node-prompt.md` -> `reviewer-prompt.md`
- `AI-GUIDE.md` -> update paths
- `AI-GUIDE-prompt-contract.md` -> update role names

### Moderate (structural reuse, field replacement)

- `task-manifest.v1.schema.json`: replace institution, const role names, generation_mode
- `plan-state.v1.schema.json`: replace owner enum
- `next-action-plan.v1.schema.json`: replace phase enum, script names
- `next-action-execution.v1.schema.json`: replace script enum, phase enum
- `main-orchestrator-prompt.md`: replace payment paths and terminology
- `worker-node-prompt.md`: rename role, update contract references
- `plan-agent-prompt.md`: replace four-layer sequence, payment artifact references
- `prove-issue-routing.v1.schema.json`: replace gate_context_update fields

### Significant (domain-specific content extraction)

- `spec-business-facts.v1.schema.json`: extract fact category structure, replace all field names with pluggable domain schema
- `spec-agent-prompt.md`: replace payment channel doc parsing with generic external doc fact extraction
- `prove-agent-prompt.md`: replace payment norms with domain validation rules
- `code-agent-prompt.md`: replace all payment framework constraints with domain-injected constraints

### Not reusable (domain artifact)

- `payment-channel-allocation-registry.v1.schema.json`
- `payment-channel-config.v1.schema.json`
- `spec-state.v1.schema.json` (legacy)
- `prove-state.v1.schema.json` (legacy)
