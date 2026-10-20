#!/bin/bash
# Phase 1 calibration queue: waits for the Phase 2 run (shared subscription quota), then runs 3 discarded vanilla
# Sonnet trials per valid task (HYPOTHESES.md, amendment of 2026-10-19 #2): Terminal-Bench first, then SWE-rebench
# once its oracle check has finished.
set -u
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
log() { echo "$(date '+%m-%d %H:%M') $*"; }

while pgrep -f "run_ab.py --suite repo-features" >/dev/null; do sleep 120; done
log "Phase 2 run finished; starting Terminal-Bench calibration"
python3 run_harbor.py --task-list pool/oracle-valid.txt --dataset datasets/terminal-bench-local --suite terminal-bench \
  --arms vanilla --model sonnet --reps 3 --force-build --corporate-ca --env-file certs/claude.env --concurrency 3 \
  --out ../results/phase1-calibration-tb
log "Terminal-Bench calibration done"

while pgrep -f "run_harbor.py --task-list pool/swe-rebench-sample" >/dev/null; do sleep 120; done
python3 - <<'PY'
import json, glob
valid = sorted({json.load(open(p))["task_name"].split("/")[-1] for p in glob.glob("jobs/oracle-swe-rebench-vanilla/*/result.json")
                if (((json.load(open(p)).get("verifier_result") or {}).get("rewards") or {}).get("reward") or 0) >= 1})
open("pool/swe-rebench-valid.txt", "w").write("".join(t + "\n" for t in valid))
print(len(valid), "valid SWE-rebench tasks")
PY
log "starting SWE-rebench calibration"
python3 run_harbor.py --task-list pool/swe-rebench-valid.txt --dataset datasets/swe-rebench-local --suite swe-rebench \
  --arms vanilla --model sonnet --reps 3 --npm-install --corporate-ca --env-file certs/claude.env --concurrency 2 \
  --timeout-multiplier 2 --out ../results/phase1-calibration-swe
log "SWE-rebench calibration done"
