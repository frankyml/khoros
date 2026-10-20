#!/usr/bin/env python3
"""
Phase 1 runner: Claude Code with vs. without Khoros on external Harbor datasets (Terminal-Bench 2.0, ...).

Each arm is one Harbor job over the same tasks, with the same model, attempts and timeouts; the arms run side by
side so time-of-day noise hits them equally. Results are converted to bench's results.jsonl schema, so
`python3 bench/report.py <out>` analyses them exactly like the local suites.

Arms: vanilla (Harbor's stock claude-code agent), khoros and khoros-factory (khoros_agent.py). Khoros arms get
only Khoros's runtime files mounted read-only at /opt/khoros, never the repo (it holds benchmark solutions).

Needs Docker, Harbor (`uv tool install harbor`) and Claude credentials for the containers in an env file
(CLAUDE_CODE_OAUTH_TOKEN + CLAUDE_FORCE_OAUTH=1 from `claude setup-token`, or ANTHROPIC_API_KEY).
Behind a TLS-inspecting proxy, put the proxy's root CA in certs/corporate-ca.pem and run with --corporate-ca.

Usage:
  python3 bench/harbor/run_harbor.py --tasks fix-git,prove-plus-comm --agent oracle --dry-run
  python3 bench/harbor/run_harbor.py --task-list pilot.txt --arms vanilla --model haiku --reps 2 --out ...
  python3 bench/harbor/run_harbor.py --task-list selected.txt --model sonnet --reps 5 --env-file certs/claude.env
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HARBOR_DIR = Path(__file__).resolve().parent
BENCH_DIR = HARBOR_DIR.parent
REPO_ROOT = BENCH_DIR.parent
sys.path.insert(0, str(BENCH_DIR))

from benchlib import khoros_state, parse_stream  # noqa: E402

AGENTS = {
    "vanilla": "claude-code",
    "khoros": "khoros_agent:KhorosClaudeCode",
    "khoros-factory": "khoros_agent:KhorosFactoryClaudeCode",
}
# x86-only images on Apple Silicon (e.g. SWE-rebench): Claude Code from npm for every arm, see khoros_agent.py
NPM_AGENTS = {
    "vanilla": "khoros_agent:NpmClaudeCode",
    "khoros": "khoros_agent:NpmKhorosClaudeCode",
    "khoros-factory": "khoros_agent:NpmKhorosFactoryClaudeCode",
}
KHOROS_SURFACES = ("bin", ".harness", "plugin", "CLAUDE.md")


def khoros_mounts(khoros_root: Path) -> str:
    return json.dumps([{"type": "bind", "source": str(khoros_root / name), "target": f"/opt/khoros/{name}", "read_only": True}
                       for name in KHOROS_SURFACES])


def write_ca_overlay() -> Path:
    certs = HARBOR_DIR / "certs"
    for name in ("ca-bundle.pem", "corporate-ca.pem"):
        if not (certs / name).exists():
            raise SystemExit(f"--corporate-ca needs {certs / name} (see the header of corporate-ca.compose.template.yaml)")
    template = (HARBOR_DIR / "corporate-ca.compose.template.yaml").read_text(encoding="utf-8")
    body = "\n".join(line for line in template.splitlines() if not line.startswith("#"))
    overlay = certs / "corporate-ca.compose.yaml"
    overlay.write_text(body.replace("{CERTS_DIR}", str(certs)) + "\n", encoding="utf-8")
    return overlay


def task_view(dataset: Path, tasks: List[str], out: Path) -> Path:
    """A dataset folder holding only the selected tasks (symlinks), so Harbor needs no per-task -i flags."""
    view = out / "tasks"
    shutil.rmtree(view, ignore_errors=True)
    view.mkdir(parents=True)
    for task in tasks:
        (view / task).symlink_to((dataset / task).resolve(), target_is_directory=True)
    return view


def harbor_command(args, arm: str, agent: str, job_name: str, view: Path, overlay: Optional[Path]) -> List[str]:
    cmd = [args.harbor_bin, "run", "-p", str(view), "-a", agent, "-k", str(args.reps),
           "-n", str(args.concurrency), "-o", str(args.jobs_dir), "--job-name", job_name, "-y", "-q",
           "--timeout-multiplier", str(args.timeout_multiplier)]
    if args.force_build:
        cmd += ["--force-build"]
    if args.model and agent != "oracle":
        cmd += ["-m", args.model]
    if overlay:
        cmd += ["--extra-docker-compose", str(overlay)]
    if arm != "vanilla" and agent != "oracle":
        cmd += ["--mounts", khoros_mounts(args.khoros_root)]
    if args.env_file:
        cmd += ["--env-file", str(args.env_file)]
    return cmd


def task_meta(dataset: Path, task: str) -> Dict[str, Any]:
    toml = dataset / task / "task.toml"
    text = toml.read_text(encoding="utf-8") if toml.exists() else ""
    difficulty = re.search(r'^difficulty\s*=\s*"([^"]+)"', text, re.M)
    expert = re.search(r"^expert_time_estimate_min\s*=\s*([\d.]+)", text, re.M)
    return {"difficulty": difficulty.group(1) if difficulty else "unknown",
            "expert_min": float(expert.group(1)) if expert else None}


def convert_job(job_dir: Path, arm: str, suite: str, dataset: Path, model: str) -> List[Dict[str, Any]]:
    """Turn a Harbor job directory into bench results records (one per trial)."""
    records, seen = [], {}
    for result_path in sorted(job_dir.glob("*/result.json")):
        res = json.loads(result_path.read_text(encoding="utf-8"))
        task = res["task_name"]
        rep = seen.get(task, 0)
        seen[task] = rep + 1
        reward = ((res.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        exception = res.get("exception_info")
        meta = task_meta(dataset, task)
        record: Dict[str, Any] = {
            "key": f"{task}__{arm}__r{rep}", "task": task, "arm": arm, "rep": rep, "suite": suite, "model": model,
            "tier": meta["difficulty"], "type": "terminal", "expert_min": meta["expert_min"],
            "success": reward is not None and float(reward) >= 1.0,
            "hidden_pass_rate": float(reward) if reward is not None else 0.0,
            "visible_ok": True,
            "status": "ok" if not exception else _exception_status(exception),
            "harbor_trial": res.get("trial_name"),
            "started_at": res.get("started_at"), "finished_at": res.get("finished_at"),
        }
        partial = test_pass_fraction(result_path.parent / "verifier" / "ctrf.json")
        if partial is not None:
            # Share of the task's tests that passed: partial credit, far more sensitive than the binary reward
            record["hidden_pass_rate"] = partial
        execution = res.get("agent_execution") or {}
        if execution.get("started_at") and execution.get("finished_at"):
            record["wall_s"] = round((_ts(execution["finished_at"]) - _ts(execution["started_at"])), 2)
        transcript = result_path.parent / "agent" / "claude-code.txt"
        if transcript.exists():
            metrics = parse_stream(transcript.read_text(encoding="utf-8", errors="replace").splitlines())
            metrics.pop("duration_ms", None)
            record.update(metrics)
        agent_result = res.get("agent_result") or {}
        if record.get("cost_usd") is None and agent_result.get("cost_usd") is not None:
            record["cost_usd"] = agent_result["cost_usd"]
        records.append(record)
    return records


def test_pass_fraction(ctrf_path: Path) -> Optional[float]:
    """Passed / total from a CTRF test report (written by most Terminal-Bench verifiers); None if absent."""
    if not ctrf_path.exists():
        return None
    try:
        summary = json.loads(ctrf_path.read_text(encoding="utf-8"))["results"]["summary"]
        total = int(summary.get("tests", 0))
        return round(int(summary.get("passed", 0)) / total, 4) if total else None
    except (ValueError, KeyError, TypeError):
        return None


def _exception_status(exception: Dict[str, Any]) -> str:
    kind = str(exception.get("exception_type") or exception.get("type") or "error")
    return "timeout" if "Timeout" in kind else f"error:{kind}"


def _ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def keep_awake() -> None:
    """Hold the Mac awake while this process runs: on sleep, runs pause and their timeouts stop counting."""
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-ims", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=HARBOR_DIR / "datasets" / "terminal-bench")
    parser.add_argument("--suite", default="terminal-bench", help="Suite label stored on every record")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--tasks", help="Comma-separated task names")
    selection.add_argument("--task-list", type=Path, help="File with one task name per line")
    parser.add_argument("--arms", default="vanilla,khoros,khoros-factory")
    parser.add_argument("--agent", help="Override the agent for every arm (e.g. oracle, to test the setup)")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--reps", type=int, default=1, help="Attempts per task and arm")
    parser.add_argument("--concurrency", type=int, default=2, help="Concurrent trials per arm")
    parser.add_argument("--timeout-multiplier", type=float, default=1.0)
    parser.add_argument("--env-file", type=Path, help="Env file with Claude credentials for the containers")
    parser.add_argument("--corporate-ca", action="store_true", help="Mount certs/ca-bundle.pem into every container")
    parser.add_argument("--npm-install", action="store_true",
                        help="Install Claude Code from npm in every arm (needed for x86-only images under Rosetta)")
    parser.add_argument("--force-build", action="store_true",
                        help="Build task images from their Dockerfiles (native ARM on Apple Silicon; see prepare_dataset.py)")
    parser.add_argument("--khoros-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--harbor-bin", default=shutil.which("harbor") or str(Path.home() / ".local/bin/harbor"))
    parser.add_argument("--jobs-dir", type=Path, default=HARBOR_DIR / "jobs")
    parser.add_argument("--out", type=Path, help="bench results dir (default bench/results/harbor-<timestamp>)")
    parser.add_argument("--convert-only", action="store_true", help="Skip running; convert the jobs of an earlier --out")
    parser.add_argument("--dry-run", action="store_true", help="Print the Harbor commands only")
    args = parser.parse_args()

    tasks = [t.strip() for t in (args.tasks.split(",") if args.tasks else args.task_list.read_text().splitlines()) if t.strip()]
    missing = [t for t in tasks if not (args.dataset / t).is_dir()]
    if missing:
        parser.error(f"tasks not in {args.dataset}: {', '.join(missing)}")
    arms = args.arms.split(",")
    if any(a not in AGENTS for a in arms):
        parser.error(f"arms must be among {', '.join(AGENTS)}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = (args.out or BENCH_DIR / "results" / f"harbor-{stamp}").resolve()
    out.mkdir(parents=True, exist_ok=True)
    overlay = write_ca_overlay() if args.corporate_ca else None

    env = dict(os.environ)
    env["PYTHONPATH"] = f"{HARBOR_DIR}{os.pathsep}{env.get('PYTHONPATH', '')}"
    if args.corporate_ca:
        bundle = str(HARBOR_DIR / "certs" / "ca-bundle.pem")
        env.update(SSL_CERT_FILE=bundle, REQUESTS_CA_BUNDLE=bundle)

    keep_awake()
    jobs = {arm: f"{out.name}-{arm}" for arm in arms}
    if not args.convert_only:
        view = task_view(args.dataset, tasks, out)
        procs = []
        for arm in arms:
            agent = args.agent or (NPM_AGENTS if args.npm_install else AGENTS)[arm]
            cmd = harbor_command(args, arm, agent, jobs[arm], view, overlay)
            print("$ " + " ".join(cmd), flush=True)
            if not args.dry_run:
                log = open(out / f"harbor-{arm}.log", "w", encoding="utf-8")
                procs.append((arm, subprocess.Popen(cmd, cwd=HARBOR_DIR, env=env, stdout=log, stderr=subprocess.STDOUT), log))
        for arm, proc, log in procs:
            proc.wait()
            log.close()
            print(f"{arm}: harbor exited {proc.returncode}", flush=True)
    if args.dry_run:
        return 0

    manifest = {"created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "model": args.model,
                "arms": [{"name": a} for a in arms], "tasks": tasks, "reps": args.reps, "suite": args.suite,
                "dataset": str(args.dataset), "harbor_jobs": {a: str(args.jobs_dir / j) for a, j in jobs.items()},
                **khoros_state(args.khoros_root), "runner": "harbor"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    records = [r for arm in arms for r in convert_job(args.jobs_dir / jobs[arm], arm, args.suite, args.dataset, args.model)]
    with open(out / "results.jsonl", "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    solved = {a: sum(r["success"] for r in records if r["arm"] == a) for a in arms}
    print(f"{len(records)} trials converted -> {out / 'results.jsonl'}; solved per arm: {solved}")
    print(f"Report: python3 {BENCH_DIR / 'report.py'} {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
