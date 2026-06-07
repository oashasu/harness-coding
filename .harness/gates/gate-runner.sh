#!/usr/bin/env bash
# Gate runner — orchestrates gate execution
# Usage: gate-runner.sh --gate <gate-id> [--workspace <dir>] [--threshold <n>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GATE=""
WORKSPACE="."
THRESHOLD=80

while [[ $# -gt 0 ]]; do
    case "$1" in
        --gate) GATE="$2"; shift 2 ;;
        --workspace) WORKSPACE="$2"; shift 2 ;;
        --threshold) THRESHOLD="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

mkdir -p "$WORKSPACE/.harness/output/logs"

case "$GATE" in
    G-REQ-01)    exec "$SCRIPT_DIR/g-req-01.sh" "$WORKSPACE" ;;
    G-SPEC-01)   exec "$SCRIPT_DIR/g-spec-01.sh" "$WORKSPACE" ;;
    G-SPEC-02)   exec "$SCRIPT_DIR/g-spec-02.sh" "$WORKSPACE" ;;
    G-CODE-01|G-COMPILE)   exec "$SCRIPT_DIR/g-compile.sh" "$WORKSPACE" ;;
    G-CODE-02|G-TEST)      exec "$SCRIPT_DIR/g-test.sh" "$WORKSPACE" ;;
    G-CODE-03|G-COVERAGE)  exec "$SCRIPT_DIR/g-coverage.sh" "$WORKSPACE" "$THRESHOLD" ;;
    G-CODE-04|G-STATIC)    exec "$SCRIPT_DIR/g-static.sh" "$WORKSPACE" ;;
    G-TEST-02|G-SECURITY)  exec "$SCRIPT_DIR/g-security.sh" "$WORKSPACE" ;;
    *) echo "Unknown gate: $GATE"; exit 1 ;;
esac
