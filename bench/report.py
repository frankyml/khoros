#!/usr/bin/env python3
"""
Statistical report for an A/B results directory produced by run_ab.py.

Outputs (stdout + <results>/report.md + <results>/summary.csv):
  * per-arm headline: solve rate (Wilson 95% CI), hidden-test pass rate, cost, latency, turns, tokens,
    cost per solved task, Khoros CLI / subagent / skill usage, harness artefacts written
  * per-tier and per-task breakdowns
  * paired comparison of every arm against the baseline arm (default: vanilla), task-stratified
    bootstrap 95% CIs for the solve-rate delta and the cost / latency ratios

Usage: python3 bench/report.py bench/results/<dir> [--baseline vanilla] [--bootstrap 5000]
       python3 bench/report.py --power --tasks 50 --trials 5 --rate 0.5   # size a design before running it
"""

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchlib import parse_stream  # noqa: E402

Record = Dict[str, Any]
ADOPTION_FEATURES = (
    "triage", "spec", "task", "claim", "submit", "approve", "brief", "verify", "pdh_subagent", "harness_skill",
    "status_tool",
)


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def values(recs: Sequence[Record], field: str) -> List[float]:
    return [float(r[field]) for r in recs if isinstance(r.get(field), (int, float)) and not isinstance(r.get(field), bool)]


def median(xs: Sequence[float]) -> Optional[float]:
    return statistics.median(xs) if xs else None


def mean(xs: Sequence[float]) -> Optional[float]:
    return statistics.fmean(xs) if xs else None


def load(results_dir: Path) -> List[Record]:
    path = results_dir / "results.jsonl"
    if not path.exists():
        raise SystemExit(f"No results.jsonl in {results_dir}")
    recs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    recs = [r for r in recs if r.get("status") not in ("dry_run", "provision_error", "runner_error")]
    for r in recs:  # records from before behaviour tracking: recompute it from the saved transcript
        transcript = results_dir / "transcripts" / f"{r['key']}.jsonl"
        if "behaviour" not in r and transcript.exists():
            r["behaviour"] = parse_stream(transcript.read_text(encoding="utf-8").splitlines())["behaviour"]
    return recs


def arm_summary(recs: Sequence[Record]) -> Dict[str, Any]:
    n = len(recs)
    k = sum(1 for r in recs if r.get("success"))
    lo, hi = wilson(k, n)
    costs = values(recs, "cost_usd")
    return {
        "runs": n,
        "solved": k,
        "solve_rate": k / n if n else 0.0,
        "solve_ci": (lo, hi),
        "hidden_pass": mean(values(recs, "hidden_pass_rate")),
        "regressions": sum(1 for r in recs if r.get("visible_ok") is False),
        "cost_total": sum(costs),
        "cost_median": median(costs),
        "cost_mean": mean(costs),
        "cost_per_solve": (sum(costs) / k) if k else None,
        "wall_median": median(values(recs, "wall_s")),
        "turns_median": median(values(recs, "turns")),
        "tool_calls_median": median(values(recs, "tool_calls")),
        "output_tokens_median": median(values(recs, "output_tokens")),
        "prompt_tokens_median": median(values(recs, "prompt_tokens")),
        "cache_hit_median": median(values(recs, "cache_hit_ratio")),
        "lines_changed_median": median([float(r.get("lines_added", 0) + r.get("lines_removed", 0)) for r in recs]),
        "tests_added_runs": sum(1 for r in recs if r.get("agent_test_files_added", 0) > 0),
        "khoros_calls_mean": mean(values(recs, "khoros_calls")),
        "subagents_mean": mean(values(recs, "subagents")),
        "skills_mean": mean(values(recs, "skill_calls")),
        "artefacts_mean": mean(values(recs, "other_files_changed")),
        "non_ok": sum(1 for r in recs if r.get("status") != "ok"),
        "pass_k": pass_k(recs),
        "timeout_solved": sum(1 for r in recs if r.get("status") == "timeout" and r.get("success")),
    }


def by(recs: Sequence[Record], *keys: str) -> Dict[Tuple, List[Record]]:
    groups: Dict[Tuple, List[Record]] = defaultdict(list)
    for r in recs:
        groups[tuple(r.get(k) for k in keys)].append(r)
    return groups


def success_rate(recs: Sequence[Record]) -> float:
    return sum(bool(r.get("success")) for r in recs) / len(recs)


def pass_k(recs: Sequence[Record]) -> Optional[float]:
    """pass^k: share of tasks where every trial succeeded (k = trials of that task). Reliability, not best case."""
    tasks = by(recs, "task")
    if not tasks:
        return None
    return sum(all(r.get("success") for r in rs) for rs in tasks.values()) / len(tasks)


def paired_bootstrap(recs: Sequence[Record], arm: str, base: str, iters: int, seed: int = 7) -> Dict[str, Any]:
    """
    Two-stage clustered bootstrap over tasks present in both arms: resample tasks with replacement, then
    resample each task's trials per arm. Tasks are the unit of generalisation, so intervals cover both
    task-to-task and trial-to-trial variation. Every task weighs the same (macro-average).
    """
    groups = by(recs, "task", "arm")
    tasks = sorted({t for (t, a) in groups if (t, arm) in groups and (t, base) in groups})
    if not tasks:
        return {}

    def stat(task_list: List[str], sample: Callable[[List[Record]], List[Record]]) -> Tuple[Optional[float], ...]:
        solve, hidden, reliable, cost_logs, wall_logs = [], [], [], [], []
        for t in task_list:
            a, b = sample(groups[(t, arm)]), sample(groups[(t, base)])
            solve.append(success_rate(a) - success_rate(b))
            ha, hb = mean(values(a, "hidden_pass_rate")), mean(values(b, "hidden_pass_rate"))
            if ha is not None and hb is not None:
                hidden.append(ha - hb)
            reliable.append(float(all(r.get("success") for r in a)) - float(all(r.get("success") for r in b)))
            ca, cb = mean(values(a, "cost_usd")), mean(values(b, "cost_usd"))
            if ca and cb:
                cost_logs.append(math.log(ca / cb))
            wa, wb = mean(values(a, "wall_s")), mean(values(b, "wall_s"))
            if wa and wb:
                wall_logs.append(math.log(wa / wb))
        geo = lambda logs: math.exp(statistics.fmean(logs)) if logs else None  # noqa: E731
        avg = lambda xs: statistics.fmean(xs) if xs else None  # noqa: E731
        return avg(solve), avg(hidden), avg(reliable), geo(cost_logs), geo(wall_logs)

    rng = random.Random(seed)
    point = stat(tasks, lambda rs: rs)
    draws = [stat([rng.choice(tasks) for _ in tasks], lambda rs: [rng.choice(rs) for _ in rs]) for _ in range(iters)]

    def ci(i: int) -> Optional[Tuple[float, float]]:
        xs = sorted(d[i] for d in draws if d[i] is not None)
        if not xs:
            return None
        return (xs[int(0.025 * (len(xs) - 1))], xs[int(0.975 * (len(xs) - 1))])

    min_runs = min(len(groups[(t, a)]) for t in tasks for a in (arm, base))
    base_recs = [r for t in tasks for r in groups[(t, base)]]
    return {"tasks": len(tasks), "min_runs": min_runs, "baseline_rate": success_rate(base_recs),
            "solve_delta": point[0], "solve_delta_ci": ci(0),
            "hidden_delta": point[1], "hidden_delta_ci": ci(1),
            "passk_delta": point[2], "passk_delta_ci": ci(2),
            "cost_ratio": point[3], "cost_ratio_ci": ci(3), "wall_ratio": point[4], "wall_ratio_ci": ci(4)}


def simulated_power(n_tasks: int, trials: int, effect_pp: float, baseline: float, sims: int = 300, seed: int = 11) -> float:
    """
    Power of this design (task-paired t-test, binary success) by simulation. Task difficulty varies on the
    logit scale (sd 1.5, typical of agent benchmarks); the harness shifts every task by the same logit amount.
    """
    rng = random.Random(seed)
    logit = lambda p: math.log(p / (1 - p))  # noqa: E731
    inv = lambda x: 1 / (1 + math.exp(-x))  # noqa: E731
    shift = logit(min(baseline + effect_pp / 100, 0.995)) - logit(baseline)
    hits = 0
    for _ in range(sims):
        diffs = []
        for _ in range(n_tasks):
            d = rng.gauss(logit(baseline), 1.5)
            pa, pb = inv(d), inv(d + shift)
            diffs.append((sum(rng.random() < pb for _ in range(trials)) - sum(rng.random() < pa for _ in range(trials))) / trials)
        sd = statistics.stdev(diffs) if n_tasks > 1 else 0.0
        if sd > 0 and statistics.fmean(diffs) / (sd / math.sqrt(n_tasks)) > 2.0:
            hits += 1
    return hits / sims


def min_detectable_effect(n_tasks: int, trials: int, baseline: float, power: float = 0.8) -> Optional[int]:
    """Smallest solve-rate gain (percentage points, step 5) detected with `power`; None if above 50 or at the ceiling."""
    baseline = min(max(baseline, 0.05), 0.95)
    for effect in range(5, 55, 5):
        if baseline + effect / 100 >= 0.995:
            return None
        if simulated_power(n_tasks, trials, effect, baseline) >= power:
            return effect
    return None


def adopted(r: Record, feature: str) -> bool:
    """Feature use for one run; older records without an `adoption` field are derived from raw counters."""
    if "adoption" in r:
        return bool(r["adoption"].get(feature))
    if feature in ("pdh_subagent", "status_tool"):
        return False
    if feature == "harness_skill":
        return r.get("skill_calls", 0) > 0
    return r.get("khoros_cmds", {}).get(feature, 0) > 0


# --------------------------------------------------------------------------- formatting

def pct(x: Optional[float]) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def usd(x: Optional[float]) -> str:
    return "–" if x is None else f"${x:.3f}"


def num(x: Optional[float], digits: int = 0) -> str:
    if x is None:
        return "–"
    return f"{x:,.{digits}f}"


def table(headers: List[str], rows: List[List[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(out)


def verdict(cmp: Dict[str, Any], arm: str, base: str) -> str:
    if cmp["min_runs"] < 2:
        return f"{arm} vs {base}: not enough data for significance (need >= 2 runs per task and arm; use --reps 3+)"
    lo, hi = cmp["solve_delta_ci"]
    if lo > 0:
        quality = f"**{arm} solves more tasks** than {base} (CI excludes 0)"
    elif hi < 0:
        quality = f"**{arm} solves fewer tasks** than {base} (CI excludes 0)"
    elif cmp["baseline_rate"] >= 0.9:
        quality = (f"solve rate is **inconclusive**: {base} already solves {cmp['baseline_rate']:.0%}, "
                   "so these tasks can show harm but not help")
    else:
        mde = min_detectable_effect(cmp["tasks"], cmp["min_runs"], cmp["baseline_rate"])
        reach = f"about {mde} points" if mde else "more than 50 points"
        quality = (f"solve rate is **inconclusive**, not equal: with {cmp['tasks']} tasks × {cmp['min_runs']} trials "
                   f"this design only reliably detects gains of {reach}")
    parts = [quality]
    if cmp.get("cost_ratio_ci"):
        clo, chi = cmp["cost_ratio_ci"]
        if clo > 1:
            parts.append(f"{arm} costs **{cmp['cost_ratio']:.2f}x** as much (significant)")
        elif chi < 1:
            parts.append(f"{arm} costs **{cmp['cost_ratio']:.2f}x** as much, i.e. cheaper (significant)")
        else:
            parts.append(f"cost difference not significant ({cmp['cost_ratio']:.2f}x)")
    return "; ".join(parts) + "."


def render(recs: List[Record], manifest: Dict[str, Any], baseline: str, iters: int) -> Tuple[str, List[Dict[str, Any]]]:
    arms = [a["name"] for a in manifest.get("arms", [])] or sorted({r["arm"] for r in recs})
    by_arm = by(recs, "arm")
    lines = [
        "# Khoros A/B benchmark report",
        "",
        f"Model `{manifest.get('model')}` · {manifest.get('claude_version', '')} · Khoros commit "
        f"`{(manifest.get('khoros_commit') or '')[:10]}`"
        + (f" + uncommitted changes `{manifest['khoros_dirty_hash']}`" if manifest.get("khoros_dirty") else
           " (uncommitted state not recorded)" if "khoros_dirty" not in manifest else "")
        + f" · {len(recs)} graded runs · {manifest.get('created_at', '')}",
        "",
        "**Solved** = every hidden test passes *and* the pristine visible suite still passes.",
        "",
        "## Headline",
        "",
    ]
    csv_rows: List[Dict[str, Any]] = []
    rows = []
    for arm in arms:
        s = arm_summary(by_arm.get((arm,), []))
        csv_rows.append({"arm": arm, **{k: v for k, v in s.items() if k != "solve_ci"},
                         "solve_ci_lo": s["solve_ci"][0], "solve_ci_hi": s["solve_ci"][1]})
        rows.append([
            f"`{arm}`", f"{s['solved']}/{s['runs']}", f"{pct(s['solve_rate'])} ({pct(s['solve_ci'][0])}–{pct(s['solve_ci'][1])})",
            pct(s["pass_k"]), pct(s["hidden_pass"]), str(s["regressions"]), usd(s["cost_median"]), usd(s["cost_per_solve"]), usd(s["cost_total"]),
            num(s["wall_median"]) + "s", num(s["turns_median"]), num(s["output_tokens_median"]),
            num(s["prompt_tokens_median"]), pct(s["cache_hit_median"]), str(s["non_ok"]),
        ])
    lines.append(table(["arm", "solved", "solve rate (95% CI)", "pass^k", "hidden tests", "regressions", "median cost",
                        "cost / solve", "total cost", "median wall", "median turns", "median out tok",
                        "median prompt tok", "cache hit", "non-ok runs"], rows))
    lines += ["", "pass^k = share of tasks where *every* trial succeeded (reliability). Costs are Claude Code's "
              "list-price estimates from token usage, not a bill."]
    timeouts = sum(arm_summary(by_arm.get((a,), []))["timeout_solved"] for a in arms)
    if timeouts:
        lines.append(f"{timeouts} run(s) hit the time limit but had already produced a passing solution; they count as solved.")

    lines += ["", "## Harness behaviour", "",
              "What the agent did, measured the same way in every arm (shell edits detected heuristically). "
              "A harness should change behaviour even where it cannot change the outcome.", ""]
    rows = []
    for arm in arms:
        group = [r for r in by_arm.get((arm,), []) if r.get("behaviour")]
        share = lambda key: pct(sum(bool(r["behaviour"].get(key)) for r in group) / len(group)) if group else "–"  # noqa: E731
        med = lambda key: num(median([float(r["behaviour"].get(key, 0)) for r in group])) if group else "–"  # noqa: E731
        rows.append([f"`{arm}`", share("ran_tests"), share("ended_verified"), med("test_runs"), med("edits"),
                     med("tool_errors"), share("used_todos"), share("gate_blocks")])
    lines.append(table(["arm", "ran tests", "ended on verified code", "median test runs", "median edits",
                        "median tool errors", "used to-do planning", "blocked by gate"], rows))

    lines += ["", "## Khoros feature adoption", "",
              "Share of runs that used each feature at least once. A feature nobody uses cannot be what helps or hurts.", ""]
    rows = []
    for arm in arms:
        group = by_arm.get((arm,), [])
        rows.append([f"`{arm}`"] + [pct(sum(adopted(r, f) for r in group) / len(group)) if group else "–" for f in ADOPTION_FEATURES])
    lines.append(table(["arm"] + list(ADOPTION_FEATURES), rows))

    lines += ["", "## Process footprint", ""]
    rows = []
    for arm in arms:
        s = arm_summary(by_arm.get((arm,), []))
        rows.append([f"`{arm}`", num(s["tool_calls_median"]), num(s["khoros_calls_mean"], 1), num(s["subagents_mean"], 1),
                     num(s["skills_mean"], 1), num(s["artefacts_mean"], 1), num(s["lines_changed_median"]),
                     f"{s['tests_added_runs']}/{s['runs']}"])
    lines.append(table(["arm", "median tool calls", "khoros CLI calls / run", "subagents / run", "skills / run",
                        "non-code files written / run", "median lines changed", "runs adding test files"], rows))

    comparisons = [a for a in arms if a != baseline and (a,) in by_arm]
    if (baseline,) in by_arm and comparisons:
        lines += ["", f"## Paired comparison vs `{baseline}`", "",
                  f"Two-stage clustered bootstrap ({iters} resamples: tasks, then trials within each task); "
                  "ratios are geometric means of per-task mean ratios.", ""]
        rows, verdicts = [], []
        suites = sorted({r.get("suite", "core") for r in recs})
        scopes = [("all", recs)] + ([(s, [r for r in recs if r.get("suite", "core") == s]) for s in suites] if len(suites) > 1 else [])
        for arm, (scope, scoped) in [(a, sc) for a in comparisons for sc in scopes]:
            cmp = paired_bootstrap(scoped, arm, baseline, iters)
            if not cmp:
                continue
            label = arm if scope == "all" else f"{arm} · {scope} suite"
            fmt_ci = lambda c, f: "–" if not c else f"{f(c[0])} … {f(c[1])}"  # noqa: E731
            signed = lambda x: f"{x * 100:+.0f} pp"  # noqa: E731
            ratio = lambda x: f"{x:.2f}x"  # noqa: E731
            maybe = lambda x, f: "–" if x is None else f(x)  # noqa: E731
            rows.append([f"`{label}`", str(cmp["tasks"]), signed(cmp["solve_delta"]), fmt_ci(cmp["solve_delta_ci"], signed),
                         maybe(cmp["passk_delta"], signed), fmt_ci(cmp["passk_delta_ci"], signed),
                         maybe(cmp["hidden_delta"], signed), fmt_ci(cmp["hidden_delta_ci"], signed),
                         "–" if cmp["cost_ratio"] is None else ratio(cmp["cost_ratio"]), fmt_ci(cmp["cost_ratio_ci"], ratio),
                         "–" if cmp["wall_ratio"] is None else ratio(cmp["wall_ratio"]), fmt_ci(cmp["wall_ratio_ci"], ratio)])
            verdicts.append(f"- {'' if scope == 'all' else f'*{scope} suite:* '}{verdict(cmp, arm, baseline)}")
        lines.append(table(["arm", "tasks", "Δ solve rate", "95% CI", "Δ pass^k", "95% CI", "Δ hidden tests", "95% CI",
                            "cost ratio", "95% CI", "latency ratio", "95% CI"], rows))
        lines += [""] + verdicts

    suites = sorted({r.get("suite", "core") for r in recs})
    if len(suites) > 1:
        lines += ["", "## By suite", ""]
        rows = []
        for suite in suites:
            row = [suite]
            for arm in arms:
                group = [r for r in recs if r.get("suite", "core") == suite and r["arm"] == arm]
                s = arm_summary(group)
                row += [f"{s['solved']}/{s['runs']}", pct(s["hidden_pass"]), usd(s["cost_median"])]
            rows.append(row)
        lines.append(table(["suite"] + [f"{a} {m}" for a in arms for m in ("solved", "hidden", "cost")], rows))

    lines += ["", "## By tier", ""]
    tiers = sorted({r["tier"] for r in recs})
    rows = []
    for tier in tiers:
        row = [tier]
        for arm in arms:
            s = arm_summary(by(recs, "tier", "arm").get((tier, arm), []))
            row += [f"{s['solved']}/{s['runs']}", usd(s["cost_median"]), num(s["wall_median"]) + "s"]
        rows.append(row)
    lines.append(table(["tier"] + [f"{a} {m}" for a in arms for m in ("solved", "cost", "wall")], rows))

    lines += ["", "## By task", ""]
    rows = []
    for task in sorted({r["task"] for r in recs}):
        tier = next(r["tier"] for r in recs if r["task"] == task)
        row = [f"`{task}`", tier]
        for arm in arms:
            group = by(recs, "task", "arm").get((task, arm), [])
            s = arm_summary(group)
            row += [f"{s['solved']}/{s['runs']}", pct(s["hidden_pass"]), usd(s["cost_median"]), num(s["turns_median"])]
        rows.append(row)
    lines.append(table(["task", "tier"] + [f"{a} {m}" for a in arms for m in ("solved", "hidden", "cost", "turns")], rows))

    failures = [r for r in recs if not r.get("success")]
    if failures:
        lines += ["", "## Failed runs", ""]
        rows = [[f"`{r['key']}`", r.get("status", "?"), pct(r.get("hidden_pass_rate")), str(r.get("visible_ok")),
                 ", ".join(i.split(".")[-1] for i in (r.get("hidden_failed_ids") or [])[:3]) or "–"] for r in failures]
        lines.append(table(["run", "status", "hidden", "visible ok", "first failing hidden tests"], rows))

    return "\n".join(lines) + "\n", csv_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results_dir", type=Path, nargs="?")
    parser.add_argument("--baseline", default="vanilla")
    parser.add_argument("--bootstrap", type=int, default=5000, help="Bootstrap resamples (default 5000)")
    plan = parser.add_argument_group("design planning (no results needed)")
    plan.add_argument("--power", action="store_true", help="Print power for a planned design instead of a report")
    plan.add_argument("--tasks", type=int, default=50, help="Planned tasks (with --power)")
    plan.add_argument("--trials", type=int, default=5, help="Planned trials per task and arm (with --power)")
    plan.add_argument("--rate", type=float, default=0.5, help="Expected vanilla solve rate (with --power)")
    args = parser.parse_args()

    if args.power:
        print(f"Design: {args.tasks} tasks x {args.trials} trials per arm, vanilla solve rate {args.rate:.0%}")
        for effect in (5, 10, 15, 20, 30):
            if args.rate + effect / 100 < 1:
                print(f"  +{effect:>2} pp gain -> power {simulated_power(args.tasks, args.trials, effect, args.rate):.0%}")
        mde = min_detectable_effect(args.tasks, args.trials, args.rate)
        print(f"Smallest gain detected 80% of the time: {f'about {mde} pp' if mde else 'more than 50 pp (or at the ceiling)'}")
        return 0
    if args.results_dir is None:
        parser.error("results_dir is required unless --power is given")

    recs = load(args.results_dir)
    if not recs:
        raise SystemExit("No graded runs yet.")
    manifest_path = args.results_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    md, csv_rows = render(recs, manifest, args.baseline, args.bootstrap)
    (args.results_dir / "report.md").write_text(md, encoding="utf-8")
    with open(args.results_dir / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
