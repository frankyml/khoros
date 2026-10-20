#!/usr/bin/env python3
"""
Select the harness-relevant Phase 1 pool from a Harbor dataset.

We benchmark a harness, not a model: only tasks where the *process* (planning, verification, persistence across
many steps, following a repo's conventions) can plausibly change the outcome are worth running. Tasks bound by
model knowledge or raw compute (cryptanalysis, model training, maths proofs, ...) mostly add noise to a harness
comparison, so their categories are excluded up front. The rule is pre-registered in bench/HYPOTHESES.md.

Then tasks whose reference solution failed on this machine (oracle runs) are dropped, and the remaining ones
without an oracle result are listed for an oracle run.

Usage:
  python3 bench/harbor/select_pool.py --dataset datasets/terminal-bench-local --oracle-jobs jobs/oracle-arm64-all
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Dict, Optional

HARNESS_RELEVANT = {
    "software-engineering", "debugging", "system-administration", "file-operations",
    "data-processing", "data-querying", "personal-assistant",
}


def category(task_dir: Path) -> str:
    match = re.search(r'^category\s*=\s*"([^"]+)"', (task_dir / "task.toml").read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else "unknown"


def khoros_tier(task_dir: Path, khoros: Path) -> str:
    """The tier Khoros's own triage assigns to the task's instruction (pre-registered stratum, no tokens)."""
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8").strip()
    with tempfile.TemporaryDirectory() as scratch:  # never let Khoros write into the task folder
        res = subprocess.run([str(khoros), "triage", instruction], capture_output=True, text=True, cwd=scratch)
    match = re.search(r"Complexity Tier\s*:\s*(\S+)", res.stdout)
    return match.group(1) if match else "unknown"


def oracle_results(job_dirs) -> Dict[str, bool]:
    """task -> passed, from finished oracle trials (unfinished or cancelled trials are ignored)."""
    passed: Dict[str, bool] = {}
    for job in job_dirs:
        for path in Path(job).glob("*/result.json"):
            res = json.loads(path.read_text(encoding="utf-8"))
            reward: Optional[float] = ((res.get("verifier_result") or {}).get("rewards") or {}).get("reward")
            if res.get("exception_info") and reward is None:
                continue  # cancelled or broken run: no verdict
            passed[res["task_name"]] = passed.get(res["task_name"], False) or (reward is not None and reward >= 1.0)
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--oracle-jobs", nargs="*", default=[], help="Harbor job dirs of oracle runs")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "pool")
    parser.add_argument("--khoros", type=Path, default=Path(__file__).resolve().parents[2] / "bin" / "khoros")
    args = parser.parse_args()

    tasks = {p.name: category(p) for p in sorted(args.dataset.iterdir()) if (p / "task.toml").exists()}
    relevant = {t for t, c in tasks.items() if c in HARNESS_RELEVANT}
    oracle = oracle_results(args.oracle_jobs)
    valid = sorted(t for t in relevant if oracle.get(t) is True)
    failed = sorted(t for t in relevant if oracle.get(t) is False)
    todo = sorted(t for t in relevant if t not in oracle)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "oracle-valid.txt").write_text("".join(f"{t}\n" for t in valid), encoding="utf-8")
    (args.out / "oracle-todo.txt").write_text("".join(f"{t}\n" for t in todo), encoding="utf-8")
    (args.out / "oracle-failed.txt").write_text("".join(f"{t}\n" for t in failed), encoding="utf-8")

    tiers = {t: khoros_tier(args.dataset / t, args.khoros) for t in valid}
    (args.out / "triage-tiers.tsv").write_text("".join(f"{t}\t{tiers[t]}\t{tasks[t]}\n" for t in valid), encoding="utf-8")

    excluded = Counter(c for t, c in tasks.items() if t not in relevant)
    print(f"{len(tasks)} tasks; {len(relevant)} harness-relevant; excluded by category: {dict(excluded)}")
    print(f"oracle: {len(valid)} valid, {len(failed)} failed, {len(todo)} still to check -> {args.out}")
    print(f"khoros triage tiers of valid tasks: {dict(Counter(tiers.values()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
