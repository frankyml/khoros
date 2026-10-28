#!/usr/bin/env python3
"""
Mine Phase 2 "multi-file feature" tasks from a real repository's history (scenario 1, H1).

Each task rewinds the repo to the parent of a real feature commit and asks for that feature; the grader runs the
test methods the real commit changed. A commit becomes a task only if all of these hold:
  * it is a feature commit touching >= 2 source files and >= 1 test file, 4+ files in total, 30-400 added
    source lines
  * at the commit, every test method in its changed test files passes
  * at the parent, with the commit's test files applied, at least one of them fails (fail-to-pass ids);
    the ones that pass in both are kept as regression (pass-to-pass) ids
  * Khoros's own triage, given the real file list, rates it T2 or T3 (pre-registered entry gate)

Prompts alternate between a terse ticket (the commit subject) and a full ticket (subject + commit description),
in commit order, so the spec-writing question gets both conditions. The tier from the prompt alone is recorded too.

Usage:
  python3 bench/scenarios/mine_repo_features.py --repo sqlglot --since 2025-06-01 --max 20
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

BENCH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH_DIR))

from benchlib import REPO_ROOT, SCENARIO_CACHE, TASKS_DIR, export_repo, run_test_ids, soft_assert_counts  # noqa: E402

FEATURE_SUBJECT = re.compile(r"^feat(\([^)]*\))?!?:", re.IGNORECASE)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def candidates(repo: Path, package: str, since: str) -> List[Dict]:
    out = []
    log = git(repo, "log", f"--since={since}", "--no-merges", "--format=%H%x09%s")
    for line in log.splitlines():
        sha, subject = line.split("\t", 1)
        if not FEATURE_SUBJECT.match(subject):
            continue
        files = git(repo, "diff", "--name-only", f"{sha}^", sha).split()
        src = [f for f in files if f.startswith(f"{package}/") and f.endswith(".py")]
        tests = [f for f in files if f.startswith("tests/") and f.endswith(".py")]
        added = sum(int(n) for n, *_ in (row.split("\t") for row in git(repo, "diff", "--numstat", f"{sha}^", sha, "--", package).splitlines()) if n.isdigit())
        if len(src) >= 2 and tests and len(src) + len(tests) >= 4 and 30 <= added <= 400 and len(files) == len(src) + len(tests):
            out.append({"sha": sha, "subject": subject, "src": src, "tests": tests, "added": added})
    return out


def test_ids(ws: Path, test_files: List[str]) -> List[str]:
    """Every test method id in the given files, as unittest dotted names."""
    script = (
        "import json, sys, unittest\n"
        "ids = []\n"
        "def walk(s):\n"
        "    for t in s:\n"
        "        walk(t) if isinstance(t, unittest.TestSuite) else ids.append(t.id())\n"
        "for name in sys.argv[1:]:\n"
        "    walk(unittest.defaultTestLoader.loadTestsFromName(name))\n"
        "print(json.dumps(ids))\n"
    )
    modules = [f[:-3].replace("/", ".") for f in test_files]
    res = subprocess.run([sys.executable, "-c", script, *modules], cwd=ws, capture_output=True, text=True, timeout=300)
    try:
        return [i for i in json.loads(res.stdout.strip().splitlines()[-1]) if "_FailedTest" not in i and "LoadTest" not in i]
    except (IndexError, ValueError):
        return []


def khoros_tier(request: str, files: Optional[List[str]] = None) -> str:
    cmd = [str(REPO_ROOT / "bin" / "khoros"), "triage", request]
    if files:
        cmd += ["--files", ",".join(files)]
    with tempfile.TemporaryDirectory() as scratch:
        out = subprocess.run(cmd, capture_output=True, text=True, cwd=scratch).stdout
    match = re.search(r"Complexity Tier\s*:\s*(\S+)", out)
    return match.group(1) if match else "unknown"


def ticket(subject: str, body: str, full: bool) -> str:
    title = re.sub(r"\s*\(#\d+\)\s*$", "", subject)
    title = re.sub(r"\s*\[[A-Z]+\]", "", title).strip()
    scope = FEATURE_SUBJECT.match(title)
    area = (scope.group(1) or "").strip("()") if scope else ""
    what = FEATURE_SUBJECT.sub("", title).strip()
    head = f"{area}: {what}" if area else what
    text = f"Feature request for this repository: {head[:1].upper() + head[1:]}."
    if full and body.strip():
        text += "\n\nDetails from the requester:\n\n" + body.strip()
    return text


def count_assertions(task_dir: Path) -> Dict:
    """Per fail-to-pass method: assertions at the real commit (denominator) and how many already pass before it."""
    meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="assert-") as tmp:
        after, before = Path(tmp) / "after", Path(tmp) / "before"
        for ws, rev in ((after, meta["commit"]), (before, meta["base"])):
            ws.mkdir()
            export_repo(meta["repo"], rev, ws)
        for path in (task_dir / "hidden").rglob("*.py"):
            rel = path.relative_to(task_dir / "hidden")
            shutil.copy2(path, before / rel)
        at_commit = soft_assert_counts(after, meta["f2p"])
        at_parent = soft_assert_counts(before, meta["f2p"])
    meta["f2p_assertions"] = {i: at_commit[i][0] for i in meta["f2p"]}
    meta["f2p_assertions_passing_before"] = {i: min(at_parent[i][0], at_commit[i][0]) for i in meta["f2p"]}
    (task_dir / "task.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def mine(args) -> int:
    repo = SCENARIO_CACHE / args.repo
    pool = candidates(repo, args.package, args.since)
    print(f"{len(pool)} candidate commits")
    made = 0
    for index, cand in enumerate(pool):
        if made >= args.max:
            break
        sha, parent = cand["sha"], git(repo, "rev-parse", f"{cand['sha']}^").strip()
        task_id = f"{args.repo}-{sha[:10]}"
        if (TASKS_DIR / task_id).exists():
            made += 1
            continue
        all_files = cand["src"] + cand["tests"]
        tier = khoros_tier(cand["subject"], all_files)
        if tier not in ("T2_ORCHESTRATED", "T3_PARALLEL_DAG"):
            print(f"  skip {sha[:10]}: Khoros tier {tier}")
            continue
        with tempfile.TemporaryDirectory(prefix="mine-") as tmp:
            after, before = Path(tmp) / "after", Path(tmp) / "before"
            for ws, rev in ((after, sha), (before, parent)):
                ws.mkdir()
                export_repo(args.repo, rev, ws)
            for test in cand["tests"]:  # the commit's tests applied on the parent
                (before / test).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(after / test, before / test)
            ids = test_ids(after, cand["tests"])
            if not ids:
                print(f"  skip {sha[:10]}: no test ids")
                continue
            status_after = run_test_ids(after, ids)
            if not all(status_after.values()):
                print(f"  skip {sha[:10]}: {sum(not v for v in status_after.values())} test(s) fail even at the commit")
                continue
            status_before = run_test_ids(before, ids)
            f2p = [i for i in ids if not status_before.get(i, False)]
            p2p = [i for i in ids if status_before.get(i, False)]
            if not f2p:
                print(f"  skip {sha[:10]}: no fail-to-pass tests")
                continue

            body = git(repo, "log", "-1", "--format=%b", sha)
            full = index % 2 == 1
            prompt = ticket(cand["subject"], body, full)
            task_dir = TASKS_DIR / task_id
            (task_dir / "hidden").mkdir(parents=True)
            for test in cand["tests"]:
                (task_dir / "hidden" / test).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(after / test, task_dir / "hidden" / test)
            for src in cand["src"]:  # the real change, used only by the oracle check
                (task_dir / "solution" / src).parent.mkdir(parents=True, exist_ok=True)
                if (after / src).exists():
                    shutil.copy2(after / src, task_dir / "solution" / src)
        meta = {
            "title": cand["subject"][:120], "tier": "T3" if tier.startswith("T3") else "T2", "type": "feature",
            "suite": "repo-features", "kind": "repo", "repo": args.repo, "base": parent, "commit": sha,
            "f2p": f2p, "p2p": p2p, "files_changed": all_files, "added_lines": cand["added"],
            "prompt_variant": "full" if full and body.strip() else "terse",
            "khoros_tier_with_files": tier, "khoros_tier_prompt_only": khoros_tier(prompt),
        }
        (task_dir / "task.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        (task_dir / "prompt.md").write_text(prompt + "\n", encoding="utf-8")
        count_assertions(task_dir)
        made += 1
        print(f"  task {task_id}: {len(f2p)} fail-to-pass, {len(p2p)} pass-to-pass, {meta['prompt_variant']} ticket")
    print(f"{made} task(s) in {TASKS_DIR}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="Repo name under bench/scenarios/cache/")
    parser.add_argument("--package", help="Source package directory (default: the repo name)")
    parser.add_argument("--since", default="2025-06-01")
    parser.add_argument("--max", type=int, default=20)
    parser.add_argument("--backfill-assertions", action="store_true", help="Only (re)count assertions of existing tasks")
    args = parser.parse_args()
    args.package = args.package or args.repo
    if args.backfill_assertions:
        for task_dir in sorted(TASKS_DIR.glob(f"{args.repo}-*")):
            meta = count_assertions(task_dir)
            total = sum(meta["f2p_assertions"].values())
            before = sum(meta["f2p_assertions_passing_before"].values())
            print(f"{task_dir.name}: {total} assertions in fail-to-pass methods, {before} already pass before the feature")
        return 0
    return mine(args)


if __name__ == "__main__":
    sys.exit(main())
