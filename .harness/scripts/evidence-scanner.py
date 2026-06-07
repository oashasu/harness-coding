#!/usr/bin/env python3
"""
HARNESS Evidence Scanner (AST / Regex Lightweight Version v2)
=============================================================
Scan target code repository, extract base class paths, interface paths, and key enum ground truth.
Outputs pure JSON for Prove Agent and Code Agent consumption as irrefutable "source skeleton".

Generalized from state-contracts evidence-scanner.py.
To customize for your project, edit TARGET_MODULES, TARGET_CLASSES, and TARGET_ANNOTATIONS below.
"""

import os
import re
import json
import argparse
from pathlib import Path

# Predefined target module roots (relative to workspace)
# CUSTOMIZE: replace with your project's module names
TARGET_MODULES = ["module-core", "module-common"]

# Class names to search for (without .java suffix)
# CUSTOMIZE: replace with your project's key classes
TARGET_CLASSES = [
    "BaseEnum",
    "ConfigEnum",
    "AbstractAdapterService",
    "IHandler",
    "AccountConfigJson",
]

# High-value annotations to extract
# CUSTOMIZE: replace with your project's key annotations
TARGET_ANNOTATIONS = ["@PlatformApi", "@Service", "@Slf4j"]


def clean_comments(content: str) -> str:
    """Remove single-line and multi-line comments"""
    content = re.sub(r'//.*', '', content)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    return content


def extract_class_signature(content: str) -> str:
    """Extract class declaration signature (only the part before the opening brace)"""
    match = re.search(r'((?:public|protected|private)?\s*(?:abstract\s+)?(?:class|interface|enum)\s+.*?)\s*\{', content, re.DOTALL)
    if match:
        return re.sub(r'\s+', ' ', match.group(1).strip())
    return ""


def extract_method_skeletons(content: str) -> list:
    """Roughly extract public/protected method signatures (discard method body)"""
    skeletons = []
    content_no_newlines = re.sub(r'\s+', ' ', content)
    matches = re.finditer(r'(?:public|protected)\s+(?:abstract\s+)?[\w\<\>\[\]\,\s]+\s+\w+\s*\([^)]*\)(?:\s*throws\s+[\w\s,]+)?\s*(?=[\{;])', content_no_newlines)

    for match in matches:
        sig = match.group(0).strip()
        if "class " not in sig and "interface " not in sig and "enum " not in sig:
            skeletons.append(sig)
            if len(skeletons) >= 10:
                break
    return skeletons


def extract_annotated_examples(content: str) -> list:
    """Extract specified high-value annotations"""
    annotations = []
    for ann in TARGET_ANNOTATIONS:
        pattern = re.compile(rf'({ann}(?:\([^)]*\))?)')
        matches = pattern.finditer(content)
        for match in matches:
            annotations.append(match.group(1).strip())
            if len(annotations) >= 5:
                break
    return list(set(annotations))


def extract_neighbor_classes(directory: Path, current_file: str) -> list:
    """Extract other Java files in the same directory as neighbor classes"""
    neighbors = []
    if not directory.exists():
        return neighbors

    for item in os.listdir(directory):
        if item.endswith(".java") and item != current_file:
            neighbors.append(item)
            if len(neighbors) >= 5:
                break
    return neighbors


def parse_enum_constants(content: str, class_name: str) -> list:
    """Extract constants from Java enum class"""
    enum_block_match = re.search(rf'enum\s+{class_name}\s*(?:implements\s+[^{{]+)?\s*{{(.*?);', content, re.DOTALL)
    constants_list = []
    if enum_block_match:
        enum_block = enum_block_match.group(1)
        pattern = re.compile(r'([A-Z0-9_]+)(?:\s*\(([^)]*)\))?')
        for match in pattern.finditer(enum_block):
            enum_name = match.group(1)
            params = match.group(2)
            item = {"name": enum_name}
            if params:
                first_param = params.split(',')[0].strip()
                if first_param.isdigit():
                    item["type_or_id"] = int(first_param)
                else:
                    item["raw_params"] = params
            constants_list.append(item)
            if len(constants_list) >= 20:
                break
    return constants_list


def scan_workspace(workspace_root: Path):
    evidence = {
        "module_roots": TARGET_MODULES,
        "class_locations": {},
        "enums_registry": [],
        "summaries": {}
    }

    for module in TARGET_MODULES:
        module_path = workspace_root / module
        if not module_path.exists():
            continue

        for root, dirs, files in os.walk(module_path):
            for file in files:
                if file.endswith(".java"):
                    class_name = file[:-5]
                    if class_name in TARGET_CLASSES:
                        rel_path = str(Path(root) / file)
                        if rel_path.startswith(str(workspace_root)):
                            rel_path = rel_path[len(str(workspace_root)):].lstrip('/')
                        evidence["class_locations"][class_name] = rel_path

                        file_path = Path(root) / file
                        with open(file_path, 'r', encoding='utf-8') as f:
                            raw_content = f.read()

                        clean_content = clean_comments(raw_content)

                        summary = {
                            "class_signature": extract_class_signature(clean_content),
                            "annotated_examples": extract_annotated_examples(clean_content),
                            "method_skeletons": extract_method_skeletons(clean_content),
                            "neighbor_classes": extract_neighbor_classes(Path(root), file)
                        }

                        if "Enum" in class_name:
                            constants = parse_enum_constants(clean_content, class_name)
                            summary["enum_constants"] = constants
                            evidence["enums_registry"].append({
                                "enum_class": class_name,
                                "constants": constants
                            })

                        evidence["summaries"][class_name] = summary

    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evidence Scanner for HARNESS (v2)")
    parser.add_argument("--workspace", default=".", help="Target workspace root directory")
    parser.add_argument("--output", default=".harness/state/evidence.json", help="Output JSON path")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    evidence_data = scan_workspace(workspace)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(evidence_data, f, ensure_ascii=False, indent=2)

    print(f"[*] Scan complete. Parsed {len(evidence_data['summaries'])} class source summaries.")
