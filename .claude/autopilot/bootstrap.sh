#!/usr/bin/env bash
# Autopilot one-time bootstrap: create the issue labels the loops apply (loops
# FAIL if labels are missing), check prerequisites, init the state dir.
# Idempotent — safe to re-run. Run once before the first loop.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY="$HERE/policy.json"
REPO="$(python3 -c "import json;print(json.load(open('$POLICY'))['repo'])")"

echo "== Autopilot bootstrap for $REPO =="

# 1. Prerequisites
fail=0
for bin in python3 gh git jq; do
  if ! command -v "$bin" >/dev/null 2>&1; then echo "  MISSING: $bin"; fail=1; else echo "  ok: $bin"; fi
done
gh auth status >/dev/null 2>&1 && echo "  ok: gh authenticated" || { echo "  MISSING: gh auth login"; fail=1; }
[ "$fail" = 0 ] || { echo "Prerequisites missing — fix and re-run."; exit 1; }

# 2. State dir
python3 "$HERE/ledger.py" init

# 3. Labels (loops apply these; create if absent). Colour by kind.
mklabel() { gh label create "$1" --repo "$REPO" --color "$2" --description "$3" 2>/dev/null \
            && echo "  created label: $1" || echo "  label exists: $1"; }
mklabel "autopilot"            "5319e7" "Filed/opened by the Autopilot maintenance system"
mklabel "needs-human"          "b60205" "Autopilot escalation — protected path or judgement call; human review required"
mklabel "autopilot:bug"        "d73a4a" "Autopilot bug-hunt finding"
mklabel "autopilot:review"     "0e8a16" "Autopilot PR-review note"
mklabel "autopilot:quality"    "1d76db" "Autopilot core-quality regression"
mklabel "autopilot:security"   "b60205" "Autopilot security/compliance finding"
mklabel "autopilot:deps"       "0366d6" "Autopilot dependency/CVE finding"
mklabel "autopilot:enhancement" "a2eeef" "Autopilot enhancement idea"
mklabel "autopilot:research"   "fbca04" "Autopilot research/competitor digest"
mklabel "autopilot:digest"     "c5def5" "Autopilot prioritized digest"

echo "== bootstrap complete =="
