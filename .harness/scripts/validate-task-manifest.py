#!/usr/bin/env python3
"""
Task Manifest Validator
======================
Validate task manifest against task-manifest.v1.schema.json contract.
"""
import argparse
import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    print("[BLOCKER] jsonschema library not installed, run: pip install jsonschema")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SCHEMA_PATH = PROJECT_ROOT / ".harness/spec/schema/task-manifest.v1.schema.json"


def validate_manifest(manifest_path: Path) -> bool:
    """Validate manifest file against schema contract"""
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except FileNotFoundError:
        print(f"[BLOCKER] Manifest file does not exist: {manifest_path}")
        return False
    except json.JSONDecodeError as e:
        print(f"[BLOCKER] Manifest JSON format error: {e}")
        return False

    try:
        with open(MANIFEST_SCHEMA_PATH, 'r', encoding='utf-8') as f:
            schema = json.load(f)
    except FileNotFoundError:
        print(f"[BLOCKER] Schema file does not exist: {MANIFEST_SCHEMA_PATH}")
        return False
    except json.JSONDecodeError as e:
        print(f"[BLOCKER] Schema JSON format error: {e}")
        return False

    try:
        jsonschema.validate(instance=manifest, schema=schema)
        print(f"[PASS] {manifest_path}")
        return True
    except jsonschema.ValidationError as e:
        print(f"[BLOCKER] {manifest_path}")
        print(f"  Error path: {'.'.join(str(p) for p in e.absolute_path)}")
        print(f"  Error message: {e.message}")
        return False
    except jsonschema.SchemaError as e:
        print(f"[BLOCKER] Schema itself is invalid: {e.message}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate Task Manifest contract")
    parser.add_argument("--manifest-file", required=True, type=Path,
                        help="Path to manifest file to validate")
    args = parser.parse_args()

    sys.exit(0 if validate_manifest(args.manifest_file) else 1)
