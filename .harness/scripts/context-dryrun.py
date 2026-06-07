#!/usr/bin/env python3
"""
Code Agent Context Dry Run
==========================
Simulate Orchestrator dynamically assembling Code Agent context for a specific step_id.
Used to verify anti-corruption layer and rule table correctness, and evaluate the final Prompt "blast radius".
"""

import os
import json
import fnmatch
import argparse
from pathlib import Path


def load_json(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def read_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return f"[Warning: File not found: {filepath}]"


def match_rule(step_id, rules):
    for rule in rules:
        for pattern in rule.get("step_patterns", []):
            if fnmatch.fnmatch(step_id, pattern):
                return rule
    return None


def build_context(step_id, plan_file, prove_file, evidence_file, rules_file, base_prompt_file):
    print(f"=== Context Dry Run for Step: {step_id} ===\n")

    plan = load_json(plan_file)
    prove = load_json(prove_file)
    evidence = load_json(evidence_file)
    rules_cfg = load_json(rules_file)
    base_prompt = read_file(base_prompt_file)

    current_step = next((s for s in plan.get("steps", []) if s["step_id"] == step_id), None)
    if not current_step:
        print(f"Error: Step {step_id} not found in plan-state")
        return

    print(f"Target Agent: {current_step['owner']}")

    rule = match_rule(step_id, rules_cfg.get("rules", []))
    if not rule:
        print(f"Error: No injection rule matching {step_id}")
        return

    print("Matched injection rule, assembling...\n")

    assembled_prompt = []

    # 1. Base inputs (Base Prompt + Plan + Prove)
    assembled_prompt.append(base_prompt)
    assembled_prompt.append("\n--- [Runtime Context] ---")
    assembled_prompt.append(f"\n# Current Task Step (plan-state.current-step)\n```json\n{json.dumps(current_step, ensure_ascii=False, indent=2)}\n```")
    assembled_prompt.append(f"\n# Global Adjudication Facts (prove-state)\n```json\n{json.dumps(prove, ensure_ascii=False, indent=2)}\n```")

    # 2. Reference docs
    assembled_prompt.append("\n--- [Domain Specification Dictionary] ---")
    docs_loaded = []
    for doc_path in rule.get("reference_docs", []):
        content = read_file(doc_path)
        assembled_prompt.append(f"\n# Reference Doc: {os.path.basename(doc_path)}\n{content}")
        docs_loaded.append(os.path.basename(doc_path))
    print(f"Loaded reference docs ({len(docs_loaded)}):")
    for d in docs_loaded:
        print(f"   - {d}")

    # 3. Physical evidence (Evidence Summaries)
    assembled_prompt.append("\n--- [Physical Code Evidence] ---")
    summaries_loaded = []
    for req in rule.get("evidence_summaries", []):
        kind = req["kind"]
        target = req["target"]

        if kind in ["class_signature", "method_skeletons", "annotated_examples", "neighbor_classes", "enum_constants"]:
            summary_data = evidence.get("summaries", {}).get(target, {}).get(kind)
            if summary_data:
                assembled_prompt.append(f"\n# Evidence: {target} ({kind})\n```json\n{json.dumps(summary_data, ensure_ascii=False, indent=2)}\n```")
                summaries_loaded.append(f"{target} -> {kind}")

    print(f"\nExtracted physical evidence ({len(summaries_loaded)}):")
    for s in summaries_loaded:
        print(f"   - {s}")

    # 4. Step-specific constraints
    assembled_prompt.append("\n--- [Step-Specific Constraints] ---")
    constraints = rule.get("step_specific_constraints", [])
    for c in constraints:
        assembled_prompt.append(f"- {c}")

    # Output result
    final_text = "\n".join(assembled_prompt)
    char_count = len(final_text)
    token_estimate = char_count // 2

    output_path = f".harness/state/dryrun-{step_id}.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_text)

    print(f"\n=== Assembly Summary ===")
    print(f"Total characters: {char_count}")
    print(f"Estimated tokens: ~{token_estimate}")
    print(f"Status: {'SAFE' if token_estimate < 10000 else 'WARNING (large)' if token_estimate < 20000 else 'DANGER (may overflow)'}")
    print(f"Full prompt written to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Code Agent Context Dry Run")
    parser.add_argument("--step", required=True, help="Step ID to simulate, e.g. S05_ADAPTER_CREATE")
    parser.add_argument("--plan", default=".harness/state/plan-state.json")
    parser.add_argument("--prove", default=".harness/state/prove-state.json")
    parser.add_argument("--evidence", default=".harness/state/evidence.json")
    parser.add_argument("--rules", default=".harness/config/code-agent-injection-rules.json")
    parser.add_argument("--prompt", default=".harness/prompts/code-agent-prompt.md")

    args = parser.parse_args()
    build_context(args.step, args.plan, args.prove, args.evidence, args.rules, args.prompt)
