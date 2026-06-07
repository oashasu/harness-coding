# HARNESS Scripts

Pipeline orchestration scripts for the HARNESS workflow engine.
Generalized from state-contracts (payment-skill) framework.

## Core Orchestration

| Script | Description | Origin |
|--------|-------------|--------|
| `orchestrator.py` | Main orchestrator agent, coordinates full workflow lifecycle | pre-existing |
| `plan-next-action.py` | Read current state and generate next action plan | generalized |
| `execute-next-action.py` | Execute planned action by dispatching to the appropriate script | generalized |
| `phase-handoff.py` | Handle phase transitions, checkpoints, and user-await states | pre-existing |
| `preflight.py` | Pre-flight gate checks before phase transitions | pre-existing |
| `task_identity.py` | Derive deterministic task ID via SHA1 hash from state context | generalized |

## State Management

| Script | Description | Origin |
|--------|-------------|--------|
| `state_integrity.py` | HMAC-SHA256 seal/verify for state file integrity | generalized |
| `re-sign-state.py` | HMAC debug helper - verify or re-sign state files | generalized |
| `validate-task-manifest.py` | Validate task manifest against JSON schema contract | generalized |

## Stage Task Pipeline

| Script | Description | Origin |
|--------|-------------|--------|
| `build-stage-task.py` | Generate stage task manifest from workflow state | generalized |
| `dispatch-worker.py` | Generate Worker dispatch package from task manifest | generalized |
| `collect-worker-report.py` | Collect Worker final report and advance to Review or rework | generalized |
| `collect-review.py` | Collect Review result into workflow state | generalized |

## Gen Node Management

| Script | Description | Origin |
|--------|-------------|--------|
| `init-gen-nodes.py` | Initialize gen phase DAG nodes (G01-G09) in workflow state | generalized |
| `build-gen-node-task.py` | Generate gen node task manifest for current node | generalized |
| `advance-gen-node.py` | Advance to next gen DAG node after review passes | generalized |

## Registration

| Script | Description | Origin |
|--------|-------------|--------|
| `register-spec-artifacts.py` | Register spec phase artifacts and mark spec completed | generalized |
| `register-final-artifacts.py` | Register final phase artifacts and mark final completed | generalized |

## Workflow

| Script | Description | Origin |
|--------|-------------|--------|
| `archive-harness-workflow.py` | Archive and optionally reset workflow runtime state | generalized |
| `gate_runner.py` | Gate runner for phase validation | pre-existing |
| `experience_wal.py` | Experience write-ahead log for learning cycles | pre-existing |
| `record_decision.py` | Record decision artifacts into workflow state | pre-existing |

## Utilities

| Script | Description | Origin |
|--------|-------------|--------|
| `evidence-scanner.py` | Scan code repository for class signatures, enums, and method skeletons | generalized |
| `final_report_contract.py` | Validate final audit report against contract requirements | generalized |
| `context-dryrun.py` | Simulate Code Agent context assembly for a step (dry run) | generalized |
| `prove_routing_compat.py` | Normalize legacy prove routing payload format | generalized |

## Generalization Notes

All scripts marked "generalized" were adapted from the state-contracts (payment-skill) framework with these changes:

- `.payment-skill/` replaced with `.harness/`
- `payment-workflow-state` replaced with `harness-workflow-state`
- `state.get("institution", {})` replaced with `state.get("project", {})`
- `institution_code` replaced with `project_code`
- Payment-specific worker roles replaced with generic `Worker` / `GenWorker`
- Chinese error messages replaced with English
- `archive-payment-workflow.py` renamed to `archive-harness-workflow.py`
- Payment-specific Java class targets in `evidence-scanner.py` replaced with configurable placeholders
