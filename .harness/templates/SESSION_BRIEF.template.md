# SESSION_BRIEF

_此文件由 phase-handoff.py 在阶段切换时自动生成，不应手工编辑。_
_初始化后为空占位，首次 phase-handoff 后替换为真实内容。_

- task: (未设置)
- task_mode: (未设置)
- state_file: .harness/state/harness-state.json
- current_phase: (未初始化)
- handoff_from: (未发生)
- handoff_to: (未发生)
- last_checkpoint: NONE
- awaiting_user_action: false
- allowed_actions: (none)
- pending_checkpoint: NONE
- current_execution_unit: (未设置)
- last_review_status: (未设置)
- next_required_action: (未设置)
- required_script: (未设置)
- open_questions: 0
- resolved_questions: 0
- req_validation_passed: (未运行)
- spec_validation_passed: (未运行)

## Resume First Prompt

_尚未发生任何阶段切换，当前工作区处于初始状态。_
_请先运行 preflight.py --stage prep 完成准备阶段前置检查。_

## Guardrail

- 恢复后先读状态文件和本brief，再决定动作。
- 若awaiting_user_action=true，未收到明确编号动作前不得推进阶段。
- 未跑当前阶段preflight和orchestrator，不得宣称阶段通过。
