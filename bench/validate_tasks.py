#!/usr/bin/env python3
"""
Oracle validation for the benchmark corpus (no LLM calls, ~seconds).

For every task it proves the grader can tell success from failure:
  1. untouched workspace (fixture + seeded setup)  -> hidden tests must FAIL
  2. workspace + reference solution                -> hidden AND visible tests must PASS
It also provisions every arm once and checks the Khoros install works (`khoros verify`).

Usage: python3 bench/validate_tasks.py [--tasks id1,id2] [--suite core|hard] [--skip-arms]
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchlib import ARMS, REPO_ROOT, Task, build_workspace, grade, load_tasks


def validate_task(task: Task, scratch: Path) -> Dict[str, Any]:
    problems: List[str] = []
    before = grade(task, _ws(task, scratch / f"{task.id}-before", solution=False))
    if before["hidden_pass_rate"] >= 1.0:
        problems.append("hidden tests already pass without any change (task is a no-op)")

    after = grade(task, _ws(task, scratch / f"{task.id}-after", solution=True))
    if not after["success"]:
        problems.append(f"reference solution fails: hidden={after['hidden_failed_ids']} visible={after['visible_failed_ids']}")
    if task.kind == "fixture" and not after["agent_suite_ok"]:
        problems.append("reference solution breaks the repo's own test suite")
    return {"task": task.id, "tier": task.tier, "before": before["hidden_pass_rate"],
            "after": after["hidden_pass_rate"], "expected": task.expected_hidden_tests(), "problems": problems}


def _ws(task: Task, path: Path, solution: bool) -> Path:
    build_workspace(task, ARMS["vanilla"], path, solution=solution)
    return path


def validate_arms(task: Task, scratch: Path) -> List[str]:
    problems = []
    for arm in ARMS.values():
        ws = scratch / f"arm-{arm.name}"
        info = build_workspace(task, arm, ws, khoros_root=REPO_ROOT)
        has_md, has_harness = (ws / "CLAUDE.md").exists(), (ws / ".harness").exists()
        if has_md != arm.claude_md or has_harness != arm.harness:
            problems.append(f"{arm.name}: CLAUDE.md={has_md} .harness={has_harness} does not match arm definition")
        plugin_dirs = [d for flag, d in zip(info["extra_args"], info["extra_args"][1:]) if flag == "--plugin-dir"]
        if any(d.endswith("/plugin") for d in plugin_dirs) != arm.plugin or any(d.endswith("khoros-view") for d in plugin_dirs) != arm.view:
            problems.append(f"{arm.name}: plugin flag mismatch")
        if arm.harness:
            res = subprocess.run([str(ws / "bin" / "khoros"), "verify"], cwd=ws, capture_output=True, text=True)
            if res.returncode != 0:
                problems.append(f"{arm.name}: `khoros verify` fails on the pristine workspace:\n{res.stdout}{res.stderr}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", help="Comma-separated task ids (default: all)")
    parser.add_argument("--suite", choices=["core", "hard", "repo-features"], help="Only tasks from this suite")
    parser.add_argument("--skip-arms", action="store_true", help="Skip arm provisioning checks")
    args = parser.parse_args()

    tasks = load_tasks(args.tasks.split(",") if args.tasks else None, suite=args.suite)
    failed = False
    with tempfile.TemporaryDirectory(prefix="khoros-bench-validate-") as tmp:
        scratch = Path(tmp)
        print(f"{'task':<24} {'tier':<4} {'tests':>5} {'before':>7} {'after':>6}  status")
        for task in tasks:
            row = validate_task(task, scratch)
            status = "OK" if not row["problems"] else "FAIL"
            failed |= bool(row["problems"])
            print(f"{row['task']:<24} {row['tier']:<4} {row['expected']:>5} {row['before']:>7.0%} {row['after']:>6.0%}  {status}")
            for p in row["problems"]:
                print(f"    - {p}")
        if not args.skip_arms:
            arm_problems = validate_arms(tasks[0], scratch)
            print(f"\narms: {', '.join(ARMS)} -> {'OK' if not arm_problems else 'FAIL'}")
            for p in arm_problems:
                print(f"    - {p}")
            failed |= bool(arm_problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
