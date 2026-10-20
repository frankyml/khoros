#!/usr/bin/env python3
"""
A/B benchmark runner: Claude Code on the task corpus, with vs. without Khoros.

Each (task, arm, repetition) runs headless `claude -p` in a fresh, isolated git workspace:
  * identical prompt for every arm (task prompt + a neutral non-interactive suffix)
  * user/global settings, plugins, hooks and MCP servers excluded (--setting-sources project,
    --strict-mcp-config), so only the arm's Khoros surfaces differ
  * graded afterwards with hidden tests the agent never saw + pristine visible tests
Runs are shuffled (interleaved across arms) to spread rate-limit / time-of-day noise evenly.

Usage:
  python3 bench/run_ab.py --dry-run                       # provision workspaces + print commands, no LLM
  python3 bench/run_ab.py --reps 3 --model sonnet         # full A/B (vanilla vs khoros)
  python3 bench/run_ab.py --suite hard --reps 5           # only the hard suite
  python3 bench/run_ab.py --arms vanilla,khoros,khoros-noplugin --tasks t2-tax-policy --reps 5
  python3 bench/run_ab.py --out bench/results/<dir> --resume
Then: python3 bench/report.py bench/results/<dir>
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchlib import ARMS, BENCH_DIR, PROMPT_VERSION, REPO_ROOT, khoros_state, Arm, Task, build_workspace, grade, load_tasks, parse_stream

_write_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def claude_command(args, task: Task, arm: Arm, extra_args: List[str]) -> List[str]:
    return [
        args.claude_bin, "-p", arm.prompt_for(task),
        "--model", args.model,
        "--output-format", "stream-json", "--verbose",
        "--setting-sources", "project",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--dangerously-skip-permissions",
        "--max-budget-usd", str(args.max_budget_usd),
        *extra_args,
    ]


def run_one(args, task: Task, arm: Arm, rep: int, out_dir: Path, work_root: Path) -> Dict[str, Any]:
    key = f"{task.id}__{arm.name}__r{rep}"
    ws = work_root / key
    record: Dict[str, Any] = {"key": key, "task": task.id, "tier": task.tier, "type": task.type, "suite": task.suite, "arm": arm.name,
                              "prompt_version": PROMPT_VERSION,
                              "rep": rep, "model": args.model, "started_at": utc_now(), "workspace": str(ws)}
    try:
        info = build_workspace(task, arm, ws, khoros_root=args.khoros_root)
    except Exception as exc:  # provisioning failure is a harness bug, not an agent failure
        record.update(status="provision_error", error=str(exc)[-2000:], success=False)
        return record

    cmd = claude_command(args, task, arm, info["extra_args"])
    env = dict(os.environ, **info["env"])
    env.pop("CLAUDECODE", None)  # don't let the child think it is nested in this session
    transcript = out_dir / "transcripts" / f"{key}.jsonl"
    if args.dry_run:
        record.update(status="dry_run", success=False, command=cmd[:2] + ["<prompt>"] + cmd[3:], prompt=cmd[2])
        return record

    started = time.monotonic()
    status = "ok"
    with open(transcript, "w", encoding="utf-8") as fh, open(transcript.with_suffix(".stderr"), "w", encoding="utf-8") as err:
        proc = subprocess.Popen(cmd, cwd=ws, env=env, stdout=fh, stderr=err, stdin=subprocess.DEVNULL, text=True)
        try:
            proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            status = "timeout"
    wall_s = round(time.monotonic() - started, 2)

    metrics = parse_stream(transcript.read_text(encoding="utf-8").splitlines())
    if status == "ok" and not metrics["has_result"]:
        status = "crashed"
    elif status == "ok" and metrics.get("result_subtype") not in (None, "success"):
        status = metrics["result_subtype"]  # e.g. error_max_budget_usd, error_max_turns

    graded = grade(task, ws)
    patch = graded.pop("_patch")
    (out_dir / "patches" / f"{key}.diff").write_text(patch, encoding="utf-8")
    record.update(status=status, exit_code=proc.returncode, wall_s=wall_s, finished_at=utc_now(), **metrics, **graded)
    if not args.keep_workspaces:
        shutil.rmtree(ws, ignore_errors=True)
    return record


def load_done(results_path: Path) -> Set[str]:
    if not results_path.exists():
        return set()
    done = set()
    for line in results_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("status") not in ("provision_error", "dry_run"):
            done.add(rec["key"])
    return done


def git_porcelain(path: Path) -> str:
    res = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True)
    return res.stdout


def keep_awake() -> None:
    """Hold the Mac awake while this process runs: on sleep, runs pause and their timeouts stop counting."""
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-ims", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", help="Comma-separated task ids (default: all)")
    parser.add_argument("--suite", choices=["core", "hard", "repo-features"], help="Only tasks from this suite (default: all suites)")
    parser.add_argument("--arms", default="vanilla,khoros", help=f"Comma-separated arms from: {', '.join(ARMS)}")
    parser.add_argument("--reps", type=int, default=3, help="Repetitions per (task, arm) (default 3)")
    parser.add_argument("--model", default="sonnet", help="Claude model alias or id (default sonnet)")
    parser.add_argument("--parallel", type=int, default=2, help="Concurrent agent runs (default 2)")
    parser.add_argument("--timeout", type=int, default=1200, help="Wall-clock seconds per run (default 1200)")
    parser.add_argument("--max-budget-usd", type=float, default=3.0, help="Per-run spend cap passed to claude (default 3.0)")
    parser.add_argument("--khoros-root", type=Path, default=REPO_ROOT, help="Khoros checkout to install in khoros arms")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--expect-claude-version", help="Abort unless `claude --version` starts with this (pins the CLI across runs)")
    parser.add_argument("--out", type=Path, help="Results dir (default bench/results/<timestamp>)")
    parser.add_argument("--work-dir", type=Path, help="Where workspaces are created (default: system temp)")
    parser.add_argument("--resume", action="store_true", help="Skip runs already recorded in --out")
    parser.add_argument("--keep-workspaces", action="store_true", help="Keep workspaces for inspection")
    parser.add_argument("--seed", type=int, default=1, help="Shuffle seed for run order")
    parser.add_argument("--dry-run", action="store_true", help="Provision workspaces and print commands; no LLM calls")
    args = parser.parse_args()
    args.khoros_root = args.khoros_root.resolve()

    unknown = [a for a in args.arms.split(",") if a not in ARMS]
    if unknown:
        parser.error(f"unknown arm(s): {', '.join(unknown)}")
    arms = [ARMS[a] for a in args.arms.split(",")]
    tasks = load_tasks(args.tasks.split(",") if args.tasks else None, suite=args.suite)
    if not args.dry_run and shutil.which(args.claude_bin) is None:
        parser.error(f"claude CLI not found: {args.claude_bin}")
    claude_version = "" if args.dry_run else subprocess.run([args.claude_bin, "--version"], capture_output=True, text=True).stdout.strip()
    if args.expect_claude_version and not claude_version.startswith(args.expect_claude_version):
        parser.error(f"claude CLI is {claude_version!r}, expected {args.expect_claude_version!r}")

    out_dir = (args.out or BENCH_DIR / "results" / datetime.now().strftime("%Y%m%d-%H%M%S")).resolve()
    for sub in ("transcripts", "patches"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    done = load_done(results_path) if args.resume else set()

    jobs: List[Tuple[Task, Arm, int]] = [(t, a, r) for t in tasks for a in arms for r in range(args.reps)
                                         if f"{t.id}__{a.name}__r{r}" not in done]
    random.Random(args.seed).shuffle(jobs)

    manifest = {"created_at": utc_now(), "model": args.model,
                "arms": [{"name": a.name, "claude_md": a.claude_md, "harness": a.harness, "plugin": a.plugin, "preamble": bool(a.preamble)} for a in arms],
                "tasks": [t.id for t in tasks], "reps": args.reps, "timeout": args.timeout,
                "max_budget_usd": args.max_budget_usd, "khoros_root": str(args.khoros_root),
                **khoros_state(args.khoros_root),
                "claude_version": claude_version, "prompt_version": PROMPT_VERSION}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    keep_awake()
    print(f"{len(jobs)} runs ({len(tasks)} tasks x {len(arms)} arms x {args.reps} reps, {len(done)} already done) -> {out_dir}")
    khoros_state_before = git_porcelain(args.khoros_root)
    work_root = Path(args.work_dir or tempfile.mkdtemp(prefix="khoros-bench-")).resolve()
    work_root.mkdir(parents=True, exist_ok=True)

    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        futures = {pool.submit(run_one, args, t, a, r, out_dir, work_root): (t, a, r) for t, a, r in jobs}
        for fut in as_completed(futures):
            t, a, r = futures[fut]
            try:
                rec = fut.result()
            except Exception as exc:
                rec = {"key": f"{t.id}__{a.name}__r{r}", "task": t.id, "tier": t.tier, "type": t.type, "arm": a.name,
                       "rep": r, "status": "runner_error", "error": repr(exc), "success": False}
            completed += 1
            if not args.dry_run:
                with _write_lock, open(results_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec) + "\n")
            cost = rec.get("cost_usd")
            print(f"[{completed}/{len(jobs)}] {rec['key']:<44} {rec['status']:<16} "
                  f"success={rec.get('success')} hidden={rec.get('hidden_pass_rate', '-')} "
                  f"cost={'-' if cost is None else f'${cost:.3f}'} wall={rec.get('wall_s', '-')}s", flush=True)
            if args.dry_run and completed == 1:
                print("  example command:", " ".join(rec.get("command", [])))

    if git_porcelain(args.khoros_root) != khoros_state_before:
        print(f"\nWARNING: the Khoros checkout at {args.khoros_root} changed during the run "
              "(an agent or khoros command wrote outside its workspace). Inspect `git status` there.")
    if args.dry_run:
        print(f"\nDry run: workspaces left in {work_root}")
    else:
        if not args.keep_workspaces:
            shutil.rmtree(work_root, ignore_errors=True)
        print(f"\nDone. Report: python3 {Path(__file__).parent / 'report.py'} {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
