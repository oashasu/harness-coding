#!/usr/bin/env python3
"""HMAC debug helper script - supports verifying and re-signing state files.

Reuses functions from state_integrity.py, does not modify key file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from state_integrity import (
    compute_state_hmac,
    ensure_integrity_key,
    key_fingerprint,
    read_integrity_key,
    seal_state,
    verify_state_integrity,
    integrity_key_exists,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="HMAC debug helper - verify or re-sign state files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify state file signature
  %(prog)s --state-file .harness/state/harness-workflow-state.json --verify-only

  # Show HMAC value
  %(prog)s --state-file .harness/state/harness-workflow-state.json --show-hmac

  # Re-sign and overwrite original file
  %(prog)s --state-file .harness/state/harness-workflow-state.json

  # Re-sign and output to new file
  %(prog)s --state-file .harness/state/harness-workflow-state.json --output new-state.json
""",
    )
    parser.add_argument(
        "--state-file",
        required=True,
        help="State file path",
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: overwrite original file)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify signature, do not re-sign",
    )
    parser.add_argument(
        "--show-hmac",
        action="store_true",
        help="Show computed HMAC value",
    )

    args = parser.parse_args()
    state_file = Path(args.state_file).expanduser().resolve()

    if not state_file.exists():
        print(f"Error: State file does not exist: {state_file}", file=sys.stderr)
        return 1

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: State file JSON parse failed: {e}", file=sys.stderr)
        return 1

    # Show HMAC value
    if args.show_hmac:
        if integrity_key_exists(state_file):
            try:
                key = read_integrity_key(state_file)
                current_hmac = compute_state_hmac(state, key)
                print(f"Key fingerprint: {key_fingerprint(key)}")
                print(f"Computed HMAC: {current_hmac}")
                if "integrity" in state and "state_hmac" in state["integrity"]:
                    print(f"File signature HMAC: {state['integrity']['state_hmac']}")
                    if state["integrity"]["state_hmac"] == current_hmac:
                        print("HMAC MATCH")
                    else:
                        print("HMAC MISMATCH")
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
        else:
            print("Key file does not exist, cannot compute HMAC")
            if not args.verify_only and args.output is None:
                return 1

    # Verify mode
    if args.verify_only:
        error = verify_state_integrity(state_file, state, allow_unsigned=True)
        if error is None:
            print("State file integrity verification PASSED")
            return 0
        else:
            print(f"Verification FAILED: {error}", file=sys.stderr)
            return 1

    # Re-sign
    try:
        sealed_state = seal_state(state_file, state)
        output_file = Path(args.output).expanduser().resolve() if args.output else state_file

        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(
            json.dumps(sealed_state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        print(f"State file re-signed: {output_file}")
        if args.show_hmac and "integrity" in sealed_state:
            print(f"  New HMAC: {sealed_state['integrity']['state_hmac']}")
            print(f"  Key fingerprint: {sealed_state['integrity']['key_fingerprint']}")
        return 0

    except Exception as e:
        print(f"Error: Re-sign failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
