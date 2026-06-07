#!/usr/bin/env bash
# Gate: G-SPEC-02 — R-ID uniqueness check (L4 Enforce)
# Usage: g-spec-02.sh [--workspace <dir>]
set -euo pipefail

WORKSPACE="${1:-.}"

echo "[GATE] G-SPEC-02: R-ID uniqueness check..."

# Collect all R-IDs from spec files
RIDS_FILE=$(mktemp)
trap "rm -f $RIDS_FILE" EXIT

# Search for R-ID patterns in spec and trace files
grep -roh 'R-[0-9]\{3,\}' "$WORKSPACE/.harness/spec/" "$WORKSPACE/.harness/trace/" 2>/dev/null | sort > "$RIDS_FILE" || true

TOTAL=$(wc -l < "$RIDS_FILE" | tr -d ' ')
UNIQUE=$(sort -u "$RIDS_FILE" | wc -l | tr -d ' ')

if [ "$TOTAL" -eq 0 ]; then
    echo '{"gate_id":"G-SPEC-02","gate_level":"L4_Enforce","status":"PASS","message":"No R-IDs found (empty spec)"}'
    exit 0
fi

DUPLICATES=$((TOTAL - UNIQUE))
if [ "$DUPLICATES" -gt 0 ]; then
    DUP_LIST=$(sort "$RIDS_FILE" | uniq -d | head -5 | tr '\n' ', ')
    echo "[GATE] G-SPEC-02: Duplicate R-IDs found: $DUP_LIST"
    echo '{"gate_id":"G-SPEC-02","gate_level":"L4_Enforce","status":"FAIL","message":"'"$DUPLICATES"' duplicate R-ID(s) found"}'
    exit 1
fi

echo '{"gate_id":"G-SPEC-02","gate_level":"L4_Enforce","status":"PASS","message":"All '"$UNIQUE"' R-IDs are unique"}'
exit 0
