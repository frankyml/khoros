#!/usr/bin/env python3
"""
Khoros fixed-overhead microbenchmark (no LLM calls).

1. CLI latency: wall-clock of the khoros commands an agent typically issues
   (init, triage, task create, claim, status, verify, verify --with-tests, lint), N iterations each,
   in a freshly provisioned khoros workspace. Reported as median / p95 / min.
2. Context tax: the static text Khoros adds to every agent session (CLAUDE.md, plugin agent and
   skill descriptions) and on demand (skill body), in bytes and approximate tokens (chars / 4).

Usage: python3 bench/overhead.py [--iterations 10] [--json out.json]
"""

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchlib import ARMS, REPO_ROOT, build_workspace, load_tasks


def timed(cmd: List[str], cwd: Path) -> float:
    start = time.perf_counter()
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} exited {res.returncode}:\n{res.stdout}\n{res.stderr}")
    return elapsed


def p95(xs: List[float]) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]


def cli_latency(khoros_root: Path, iterations: int) -> List[Dict[str, Any]]:
    task = load_tasks()[0]
    rows = []
    with tempfile.TemporaryDirectory(prefix="khoros-bench-overhead-") as tmp:
        tmp_path = Path(tmp)
        ws = tmp_path / "ws"
        build_workspace(task, ARMS["khoros"], ws, khoros_root=khoros_root)
        khoros = str(ws / "bin" / "khoros")

        init_samples = []
        for i in range(iterations):
            fresh = tmp_path / f"init-{i}"
            shutil.copytree(ws / "src", fresh / "src")
            init_samples.append(timed([khoros, "init", "--profile", "python"], fresh))
        rows.append(_row("init (fresh project)", init_samples))

        create_samples, claim_samples = [], []
        for i in range(iterations):
            create_samples.append(timed([khoros, "task", "create", f"bench-{i}", "Bench task", "--priority", "Q2",
                                         "--type", "feature", "--files", "src/shop/cart.py", "--criteria", "tests pass"], ws))
            claim_samples.append(timed([khoros, "claim", f"bench-{i}", "--worker", "@lead"], ws))
        rows.append(_row("task create", create_samples))
        rows.append(_row("claim", claim_samples))

        commands = {
            "triage": [khoros, "triage", "Add a percentage discount to pricing", "--files", "src/shop/pricing.py"],
            "status": [khoros, "status"],
            "verify": [khoros, "verify"],
            "verify --with-tests": [khoros, "verify", "--with-tests"],
            "lint": [khoros, "lint"],
        }
        for label, cmd in commands.items():
            rows.append(_row(label, [timed(cmd, ws) for _ in range(iterations)]))
    return rows


def _row(label: str, samples: List[float]) -> Dict[str, Any]:
    return {"command": label, "n": len(samples), "median_ms": statistics.median(samples) * 1000,
            "p95_ms": p95(samples) * 1000, "min_ms": min(samples) * 1000}


def frontmatter_description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return ""
    block = m.group(1)
    d = re.search(r"^description:\s*(?:>-?\s*\n((?:[ \t]+.*\n?)+)|(.*))", block, re.M)
    if not d:
        return ""
    return " ".join((d.group(1) or d.group(2) or "").split())


def context_tax(khoros_root: Path) -> List[Dict[str, Any]]:
    """Text Khoros injects into the agent's context. Tokens are approximate (chars/4); run_ab.py measures real usage."""
    rows = []

    def add(surface: str, when: str, text: str) -> None:
        rows.append({"surface": surface, "loaded": when, "bytes": len(text.encode("utf-8")), "approx_tokens": len(text) // 4})

    add("CLAUDE.md", "every turn (system prompt)", (khoros_root / "CLAUDE.md").read_text(encoding="utf-8"))
    agents = sorted((khoros_root / "plugin" / "agents").glob("*.md"))
    add(f"plugin agent descriptions ({len(agents)})", "every turn (Agent tool schema)",
        "\n".join(frontmatter_description(a) for a in agents))
    skills = sorted((khoros_root / "plugin" / "skills").glob("*/SKILL.md"))
    add(f"plugin skill descriptions ({len(skills)})", "every turn (Skill tool listing)",
        "\n".join(frontmatter_description(s) for s in skills))
    add("skill bodies", "when the skill is invoked", "\n".join(s.read_text(encoding="utf-8") for s in skills))
    add("agent bodies", "when a pdh-* subagent is spawned", "\n".join(a.read_text(encoding="utf-8") for a in agents))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--khoros-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", type=Path, help="Also write raw results to this JSON file")
    args = parser.parse_args()
    root = args.khoros_root.resolve()

    latency = cli_latency(root, args.iterations)
    tax = context_tax(root)

    print(f"## Khoros CLI latency ({args.iterations} iterations)\n")
    print(f"{'command':<22} {'median':>9} {'p95':>9} {'min':>9}")
    for r in latency:
        print(f"{r['command']:<22} {r['median_ms']:>7.0f}ms {r['p95_ms']:>7.0f}ms {r['min_ms']:>7.0f}ms")
    print("\n## Context tax (static text Khoros adds)\n")
    print(f"{'surface':<34} {'bytes':>7} {'~tokens':>8}  loaded")
    for r in tax:
        print(f"{r['surface']:<34} {r['bytes']:>7} {r['approx_tokens']:>8}  {r['loaded']}")
    always = sum(r["approx_tokens"] for r in tax if r["loaded"].startswith("every turn"))
    print(f"\n~{always} tokens ride along on every turn (cached after the first request).")
    if args.json:
        args.json.write_text(json.dumps({"latency": latency, "context_tax": tax}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
