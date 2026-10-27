#!/usr/bin/env python3
"""
Khoros A/B benchmark library: task corpus loading, per-arm workspace provisioning,
hidden-test grading and Claude Code stream-json transcript parsing.

Shared by run_ab.py (agent runs), validate_tasks.py (oracle checks), overhead.py
(CLI latency) and report.py (statistics). Standard library only, Python >= 3.9.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent
FIXTURE_DIR = BENCH_DIR / "fixture"
TASKS_DIR = BENCH_DIR / "tasks"

HIDDEN_DIR_NAME = ".bench_hidden"
VISIBLE_DIR_NAME = ".bench_visible"
# Bench internals and Khoros runtime state never count as agent output.
GIT_EXCLUDES = [
    "__pycache__/",
    "*.pyc",
    f"{HIDDEN_DIR_NAME}/",
    f"{VISIBLE_DIR_NAME}/",
    ".harness/*.db*",
    ".harness/*.log",
    ".harness/worktrees/",
    ".harness/cache/",
    ".harness/state/",
    ".harness/archives/",
]

# Bump when the prompt wrapper changes: runs with different versions are not comparable.
PROMPT_VERSION = 2
# Neutral facts only. v1 ended with "Do not ask questions; complete the task end to end", which pushed
# agents toward one-shot execution and may have suppressed planning workflows.
PROMPT_SUFFIX = (
    "\n\n---\nThe repository is in the current working directory. "
    "Nobody is available to answer questions during this session."
)
FACTORY_PREAMBLE = (
    "Work through this repository's Khoros workflow as described in CLAUDE.md: start by triaging the request "
    "with `bin/khoros triage`, and if it is T2 or T3, write the recommended spec, register the work as tasks "
    "on the blackboard, and claim, submit and approve them. Run `bin/khoros verify --with-tests` before "
    "finishing.\n\n"
)


@dataclass(frozen=True)
class Arm:
    """One experimental condition. Every Khoros surface can be toggled independently for ablations."""

    name: str
    claude_md: bool = False  # copy Khoros CLAUDE.md into the workspace
    harness: bool = False  # `khoros init` + bin/khoros on PATH
    plugin: bool = False  # --plugin-dir <khoros>/plugin (v4: verify gate hooks, khoros-reviewer agent, long-task skill)
    preamble: str = ""  # prepended to the task prompt; only the factory arm uses it
    claude_md_source: str = ""  # CLAUDE.md to install instead of Khoros's (path relative to bench/)

    def prompt_for(self, task: "Task") -> str:
        return self.preamble + task.prompt + PROMPT_SUFFIX


ARMS: Dict[str, Arm] = {
    "vanilla": Arm("vanilla"),
    "khoros": Arm("khoros", claude_md=True, harness=True, plugin=True),
    "khoros-noplugin": Arm("khoros-noplugin", claude_md=True, harness=True, plugin=False),
    "khoros-cli-only": Arm("khoros-cli-only", claude_md=False, harness=True, plugin=False),
    # Cost track: Khoros with a trimmed CLAUDE.md (same behavioural rules, no cheat sheet or host notes)
    "khoros-lean": Arm("khoros-lean", claude_md=True, harness=True, plugin=True, claude_md_source="variants/khoros-lean/CLAUDE.md"),
    # Control for prompt length: a CLAUDE.md as long as Khoros's always-loaded context, with no instructions
    "placebo": Arm("placebo", claude_md=True, claude_md_source="placebo/CLAUDE.md"),
    # Same install as `khoros`, but the prompt asks for the full workflow, so the factory itself is tested
    "khoros-factory": Arm("khoros-factory", claude_md=True, harness=True, plugin=True, preamble=FACTORY_PREAMBLE),
}

# Khoros features whose use is tracked per run (see parse_stream)
ADOPTION_FEATURES = ("triage", "spec", "task", "claim", "submit", "approve", "brief", "verify", "pdh_subagent", "harness_skill")


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    tier: str
    type: str
    prompt: str
    dir: Path
    suite: str = "core"
    kind: str = "fixture"  # "fixture": bench/fixture + overlays; "repo": an open-source repo at a base commit
    meta: Dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    @property
    def setup_dir(self) -> Path:
        return self.dir / "setup"

    @property
    def solution_dir(self) -> Path:
        return self.dir / "solution"

    @property
    def hidden_dir(self) -> Path:
        return self.dir / "hidden"

    def expected_hidden_tests(self) -> int:
        if self.kind == "repo":
            return len(self.meta.get("f2p", []))
        return sum(len(re.findall(r"^\s+def test_", p.read_text(encoding="utf-8"), re.M)) for p in self.hidden_dir.glob("test_*.py"))


def load_tasks(ids: Optional[Iterable[str]] = None, suite: Optional[str] = None) -> List[Task]:
    """Load tasks by id and/or suite ("core", "hard"); no filter loads every task."""
    wanted = set(ids) if ids else None
    tasks = []
    for task_dir in sorted(p for p in TASKS_DIR.iterdir() if (p / "task.json").exists()):
        if wanted is not None and task_dir.name not in wanted:
            continue
        meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        if suite is not None and meta.get("suite", "core") != suite:
            continue
        prompt = (task_dir / "prompt.md").read_text(encoding="utf-8").strip()
        tasks.append(Task(task_dir.name, meta["title"], meta["tier"], meta["type"], prompt, task_dir,
                          meta.get("suite", "core"), meta.get("kind", "fixture"), meta))
    if wanted is not None:
        missing = wanted - {t.id for t in tasks}
        if missing:
            raise SystemExit(f"Unknown task id(s): {', '.join(sorted(missing))}")
    return tasks


def overlay(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    for path in src.rglob("*"):
        if path.is_file():
            target = dst / path.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _git(ws: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="bench", GIT_AUTHOR_EMAIL="bench@localhost",
               GIT_COMMITTER_NAME="bench", GIT_COMMITTER_EMAIL="bench@localhost")
    res = subprocess.run(["git", *args], cwd=ws, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {ws}: {res.stderr.strip()}")
    return res.stdout


def build_workspace(task: Task, arm: Arm, ws: Path, khoros_root: Path = REPO_ROOT, solution: bool = False) -> Dict[str, Any]:
    """
    Materialise fixture + task setup (+ reference solution for oracle runs) + arm-specific Khoros
    install into `ws`, then commit a baseline so the agent's diff can be measured.
    Returns the extra CLI args and env the agent process needs for this arm.
    """
    ws.mkdir(parents=True, exist_ok=False)
    if task.kind == "repo":
        export_repo(task.meta["repo"], task.meta["base"], ws)
    else:
        shutil.copytree(FIXTURE_DIR, ws, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    overlay(task.setup_dir, ws)
    if solution:
        overlay(task.solution_dir, ws)

    extra_args: List[str] = []
    env: Dict[str, str] = {}
    if arm.claude_md:
        source = BENCH_DIR / arm.claude_md_source if arm.claude_md_source else khoros_root / "CLAUDE.md"
        target = ws / "CLAUDE.md"
        if target.exists():
            # A real project's own instructions stay; the arm's text is appended, as installing Khoros would
            target.write_text(target.read_text(encoding="utf-8").rstrip() + "\n\n" + source.read_text(encoding="utf-8"),
                              encoding="utf-8")
        else:
            shutil.copy2(source, target)
    if arm.harness:
        (ws / "bin").mkdir(exist_ok=True)
        for name in ("khoros", "harness"):
            os.symlink(khoros_root / "bin" / "khoros", ws / "bin" / name)
        res = subprocess.run([str(ws / "bin" / "khoros"), "init", "--profile", "python"], cwd=ws, capture_output=True, text=True)
        if res.returncode != 0 or not (ws / ".harness" / "config.yaml").exists():
            raise RuntimeError(f"khoros init failed in {ws}:\n{res.stdout}\n{res.stderr}")
        env["PATH"] = f"{ws / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"
    if arm.plugin:
        extra_args += ["--plugin-dir", str(khoros_root / "plugin")]

    _git(ws, "init", "-q")
    (ws / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (ws / ".git" / "info" / "exclude").write_text("\n".join(GIT_EXCLUDES) + "\n", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "baseline")
    return {"extra_args": extra_args, "env": env}


KHOROS_RUNTIME_PATHS = ("bin", ".harness", "plugin", "CLAUDE.md")


def khoros_state(khoros_root: Path) -> Dict[str, Any]:
    """
    The Khoros version a run actually used: the commit plus a hash of uncommitted changes (tracked and untracked)
    to its runtime files, so results with the same commit but different working trees can be told apart.
    """
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=khoros_root, capture_output=True, text=True).stdout

    digest = hashlib.sha256(git("diff", "HEAD", "--", *KHOROS_RUNTIME_PATHS).encode("utf-8"))
    untracked = sorted(git("ls-files", "--others", "--exclude-standard", "--", *KHOROS_RUNTIME_PATHS).split())
    for rel in untracked:
        digest.update(rel.encode("utf-8"))
        digest.update((khoros_root / rel).read_bytes())
    dirty = sorted(set(git("diff", "HEAD", "--name-only", "--", *KHOROS_RUNTIME_PATHS).split()) | set(untracked))
    return {"khoros_commit": git("rev-parse", "HEAD").strip(), "khoros_dirty": bool(dirty),
            "khoros_dirty_files": dirty, "khoros_dirty_hash": digest.hexdigest()[:16] if dirty else None}


# --------------------------------------------------------------------------- grading

_UNITTEST_JSON_RUNNER = """
import json, os, sys, unittest
start = sys.argv[1]
suite = unittest.defaultTestLoader.discover(start, pattern="test_*.py", top_level_dir=start)
with open(os.devnull, "w") as devnull:
    res = unittest.TextTestRunner(stream=devnull, verbosity=0).run(suite)
failed = res.failures + res.errors
# a failing subTest reports once per sub-case; count each test method once
failed_tests = {getattr(t, "test_case", t).id() for t, _ in failed}
print(json.dumps({"run": res.testsRun, "failures": len(res.failures), "errors": len(res.errors),
                  "failed_tests": len(failed_tests), "skipped": len(res.skipped), "ok": res.wasSuccessful(),
                  "failed_ids": [t.id() for t, _ in failed][:20]}))
"""


def run_unittests(ws: Path, test_dir: Path, timeout: int = 180) -> Dict[str, Any]:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        res = subprocess.run([sys.executable, "-c", _UNITTEST_JSON_RUNNER, str(test_dir)], cwd=ws,
                             capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"run": 0, "failures": 0, "errors": 1, "skipped": 0, "ok": False, "failed_ids": ["<timeout>"]}
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"run": 0, "failures": 0, "errors": 1, "skipped": 0, "ok": False,
                "failed_ids": [f"<runner crashed: {res.stderr.strip()[-300:]}>"]}


# Files a harness writes for its own process (instructions, state, specs), never product code
HARNESS_ARTEFACT = re.compile(r"^(?:CLAUDE\.md|AGENTS\.md|CURRENT_SPRINT_STATE\.md|\.harness/|bin/(?:khoros|harness)$|"
                              r"docs/(?:prd|rfc|rca|brief|flows)/)")


def diff_stats(ws: Path) -> Dict[str, Any]:
    """Agent changes against the baseline commit, split into product code vs. everything else."""
    _git(ws, "add", "-A")
    numstat = _git(ws, "diff", "--cached", "--numstat", "HEAD")
    code_files, other_files = [], []
    added = removed = 0
    for line in numstat.splitlines():
        a, r, path = line.split("\t", 2)
        if not HARNESS_ARTEFACT.match(path):
            code_files.append(path)
            added += int(a) if a.isdigit() else 0
            removed += int(r) if r.isdigit() else 0
        else:
            other_files.append(path)
    return {"code_files_changed": len(code_files), "lines_added": added, "lines_removed": removed,
            "other_files_changed": len(other_files), "other_files": other_files[:30]}


def grade(task: Task, ws: Path) -> Dict[str, Any]:
    """Score a finished workspace: hidden tests + pristine visible tests (regressions) + agent's own suite."""
    if task.kind == "repo":
        return grade_repo(task, ws)
    stats = diff_stats(ws)
    patch = _git(ws, "diff", "--cached", "HEAD", "--", "src", "tests")

    hidden_dir, visible_dir = ws / HIDDEN_DIR_NAME, ws / VISIBLE_DIR_NAME
    for d in (hidden_dir, visible_dir):
        shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(task.hidden_dir, hidden_dir)
    shutil.copytree(FIXTURE_DIR / "tests", visible_dir, ignore=shutil.ignore_patterns("__pycache__"))

    hidden = run_unittests(ws, hidden_dir)
    visible = run_unittests(ws, visible_dir)
    own = run_unittests(ws, ws / "tests") if (ws / "tests").exists() else {"run": 0, "ok": False}

    expected = task.expected_hidden_tests()
    hidden_passed = max(hidden["run"] - hidden.get("failed_tests", hidden["failures"] + hidden["errors"]), 0)
    baseline_visible = len(list((FIXTURE_DIR / "tests").glob("test_*.py")))
    return {
        "success": bool(hidden["ok"] and visible["ok"] and hidden["run"] >= expected),
        "hidden_passed": hidden_passed,
        "hidden_expected": expected,
        "hidden_pass_rate": round(hidden_passed / expected, 4) if expected else 0.0,
        "hidden_failed_ids": hidden.get("failed_ids", []),
        "visible_ok": visible["ok"],
        "visible_failed_ids": visible.get("failed_ids", []),
        "agent_suite_ok": own.get("ok", False),
        "agent_suite_tests": own.get("run", 0),
        "agent_test_files_added": max(len(list((ws / "tests").glob("test_*.py"))) - baseline_visible, 0),
        **stats,
        "_patch": patch,
    }


# --------------------------------------------------------------------------- transcripts

KHOROS_CMD = re.compile(r"(?:^|[\s;&|/])(?:khoros|harness)\s+([a-z-]+)")
# Harness-neutral behaviour signals, measured the same way in every arm
TEST_CMD = re.compile(r"\b(?:pytest|unittest|tox|nox|go test|cargo test|npm (?:run )?test|yarn test|jest|mvn test|"
                      r"gradle test|make (?:test|check)|ctest|rspec|phpunit|khoros verify --with-tests|bash tests?/)")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Heuristic: file writes through the shell (redirects, sed -i, patch, Python write calls)
SHELL_EDIT = re.compile(r"\bsed\s+-i|\bpatch\b|\bgit apply\b|\btee\s+\S+\.\w+|"
                        r">>?\s*\S+\.(?:py|js|ts|go|rs|c|h|java|rb|sh|toml|ya?ml|json|md|txt|cfg|ini|css|html)\b|"
                        r"\.write_text\(|\bopen\([^)]*['\"][wa]\+?['\"]")


def parse_stream(lines: Iterable[str]) -> Dict[str, Any]:
    """Extract cost, token, turn and tool-usage metrics from `claude -p --output-format stream-json` output."""
    tools: Dict[str, int] = {}
    khoros_cmds: Dict[str, int] = {}
    subagent_types: Dict[str, int] = {}
    skills: Dict[str, int] = {}
    timeline: List[str] = []  # "edit" / "test" in call order, to tell whether work ended verified
    tool_errors = 0
    gate_blocks = 0  # times the Khoros v4 Stop gate sent the agent back to work
    init: Dict[str, Any] = {}
    result: Optional[Dict[str, Any]] = None
    for raw in lines:
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        etype = event.get("type")
        if etype == "system" and event.get("subtype") == "init" and not init:
            init = {"model": event.get("model"), "plugins": [p.get("name") for p in event.get("plugins", [])],
                    "agents": event.get("agents", []), "mcp_servers": event.get("mcp_servers", [])}
        elif etype == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if block.get("type") != "tool_use":
                    continue
                name = block.get("name", "?")
                tools[name] = tools.get(name, 0) + 1
                args = block.get("input") or {}
                if name in EDIT_TOOLS:
                    timeline.append("edit")
                if name == "Bash":
                    command = str(args.get("command", ""))
                    for sub in KHOROS_CMD.findall(command):
                        khoros_cmds[sub] = khoros_cmds.get(sub, 0) + 1
                    # A command can edit and then test (`sed -i ...; pytest`): record both, edit first
                    if SHELL_EDIT.search(command):
                        timeline.append("edit")
                    if TEST_CMD.search(command):
                        timeline.append("test")
                elif name in ("Task", "Agent"):
                    kind = str(args.get("subagent_type", "general-purpose"))
                    subagent_types[kind] = subagent_types.get(kind, 0) + 1
                elif name == "Skill":
                    skill = str(args.get("skill", args.get("command", "?")))
                    skills[skill] = skills.get(skill, 0) + 1
        elif etype == "user":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    tool_errors += 1
                elif isinstance(block, dict) and block.get("type") == "text" and "khoros gate" in block.get("text", ""):
                    text = block["text"]
                    if "Stop hook" in text and "verification failed" in text:
                        gate_blocks += 1
        elif etype == "result":
            result = event

    metrics: Dict[str, Any] = {
        "tool_calls": sum(tools.values()),
        "tools": tools,
        "subagents": tools.get("Task", 0) + tools.get("Agent", 0),
        "skill_calls": tools.get("Skill", 0),
        "khoros_calls": sum(khoros_cmds.values()),
        "khoros_cmds": khoros_cmds,
        "subagent_types": subagent_types,
        "skills": skills,
        "adoption": {
            **{f: khoros_cmds.get(f, 0) > 0 for f in ("triage", "spec", "task", "claim", "submit", "approve", "brief", "verify")},
            # v3.1 personas (pdh-*) and the v4 reviewer share one column so versions stay comparable
            "pdh_subagent": any("pdh-" in kind or "khoros-reviewer" in kind for kind in subagent_types),
            "harness_skill": any("development-harness" in s or "long-task" in s for s in skills),
        },
        "init": init,
        "has_result": result is not None,
        "behaviour": {
            "ran_tests": "test" in timeline,
            # verified finish: a test run after the last edit (or tests run and nothing edited)
            "ended_verified": "test" in timeline and ("edit" not in timeline or
                                                      max(i for i, e in enumerate(timeline) if e == "test")
                                                      > max(i for i, e in enumerate(timeline) if e == "edit")),
            "test_runs": timeline.count("test"),
            "edits": timeline.count("edit"),
            "tool_errors": tool_errors,
            "used_todos": tools.get("TodoWrite", 0) > 0,
            "gate_blocks": gate_blocks,
        },
    }
    if result is None:
        return metrics

    tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    model_usage = result.get("modelUsage") or {}
    if model_usage:  # includes subagent/side-model usage
        for usage in model_usage.values():
            tokens["input"] += usage.get("inputTokens", 0)
            tokens["output"] += usage.get("outputTokens", 0)
            tokens["cache_read"] += usage.get("cacheReadInputTokens", 0)
            tokens["cache_write"] += usage.get("cacheCreationInputTokens", 0)
    else:
        usage = result.get("usage") or {}
        tokens = {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0),
                  "cache_read": usage.get("cache_read_input_tokens", 0),
                  "cache_write": usage.get("cache_creation_input_tokens", 0)}
    prompt_tokens = tokens["input"] + tokens["cache_read"] + tokens["cache_write"]
    metrics.update({
        "result_subtype": result.get("subtype"),
        "is_error": bool(result.get("is_error")),
        "cost_usd": result.get("total_cost_usd"),
        "duration_ms": result.get("duration_ms"),
        "duration_api_ms": result.get("duration_api_ms"),
        "turns": result.get("num_turns"),
        "input_tokens": tokens["input"],
        "output_tokens": tokens["output"],
        "cache_read_tokens": tokens["cache_read"],
        "cache_write_tokens": tokens["cache_write"],
        "prompt_tokens": prompt_tokens,
        "cache_hit_ratio": round(tokens["cache_read"] / prompt_tokens, 4) if prompt_tokens else None,
        "models": sorted(model_usage) if model_usage else [],
        # Claude Code prices tokens at list price per model; on a subscription this is an estimate, not a bill
        "cost_by_model": {m: round(u.get("costUSD", 0.0), 6) for m, u in model_usage.items()},
    })
    return metrics


# --------------------------------------------------------------------------- repository tasks (Phase 2)

SCENARIO_CACHE = BENCH_DIR / "scenarios" / "cache"

_TEST_ID_RUNNER = """
import json, os, sys, unittest
ids = json.load(open(sys.argv[1]))
status = {}
for test_id in ids:
    try:
        suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
        with open(os.devnull, "w") as devnull:
            res = unittest.TextTestRunner(stream=devnull, verbosity=0).run(suite)
        status[test_id] = res.wasSuccessful() and res.testsRun > 0
    except Exception:
        status[test_id] = False
print(json.dumps(status))
"""


# Assertion-level scoring: every assert*/validate* call in a test method is wrapped so a failure is recorded and
# the method carries on. Gives partial credit inside the (often single) fail-to-pass method; denominators come from
# the real commit, so assertions a crashed run never reached count as failed.
_SOFT_ASSERT_RUNNER = """
import json, os, sys, unittest
ids = json.load(open(sys.argv[1]))
counts = {}
class SoftContext:
    # assertRaises used as a context manager: a missing exception is counted as a failure instead of raised
    def __init__(self, inner, tally, depth):
        self.inner, self.tally, self.depth = inner, tally, depth
    def __enter__(self):
        self.depth[0] += 1
        return self.inner.__enter__()
    def __exit__(self, et, ev, tb):
        self.depth[0] -= 1
        try:
            suppressed = self.inner.__exit__(et, ev, tb)
            self.tally[0] += 1
            return suppressed
        except Exception:
            self.tally[1] += 1
            return True
def recorded_failures(test):
    # failures caught by self.subTest() are recorded on the outcome instead of raised (3.9: outcome.errors;
    # 3.11+: outcome.result.failures/errors)
    outcome = getattr(test, "_outcome", None)
    if outcome is None:
        return 0
    if getattr(outcome, "errors", None) is not None:
        return sum(1 for _, exc in outcome.errors if exc is not None)
    result = getattr(outcome, "result", None)
    return len(getattr(result, "failures", [])) + len(getattr(result, "errors", [])) if result else 0
def soften(test, tally):
    depth = [0]  # only top-level assertion calls are counted; nested ones (validate_all -> assertEqual) run as-is
    for name in dir(type(test)):
        if not name.startswith(("assert", "validate")) or name == "assertWarns":
            continue
        original = getattr(test, name, None)
        if not callable(original):
            continue
        if name.startswith("assertRaises"):
            def raises(*a, _orig=original, **k):
                if depth[0]:
                    return _orig(*a, **k)
                if len(a) <= 1 and "callable" not in k:
                    return SoftContext(_orig(*a, **k), tally, depth)
                depth[0] += 1
                try:
                    out = _orig(*a, **k)
                    tally[0] += 1
                    return out
                except Exception:
                    tally[1] += 1
                    return None
                finally:
                    depth[0] -= 1
            setattr(test, name, raises)
            continue
        def wrapper(*a, _orig=original, **k):
            if depth[0]:
                return _orig(*a, **k)
            depth[0] += 1
            seen = recorded_failures(test)
            try:
                out = _orig(*a, **k)
                tally[0 if recorded_failures(test) == seen else 1] += 1
                return out
            except Exception:
                tally[1] += 1
                return None
            finally:
                depth[0] -= 1
        setattr(test, name, wrapper)
def walk(suite):
    for t in suite:
        yield from walk(t) if isinstance(t, unittest.TestSuite) else [t]
for test_id in ids:
    tally = [0, 0]
    try:
        for test in walk(unittest.defaultTestLoader.loadTestsFromName(test_id)):
            soften(test, tally)
            with open(os.devnull, "w") as devnull:
                unittest.TextTestRunner(stream=devnull, verbosity=0).run(test)
    except Exception:
        pass
    counts[test_id] = tally
print(json.dumps(counts))
"""


def soft_assert_counts(ws: Path, ids: List[str], timeout: int = 600) -> Dict[str, List[int]]:
    """[passed, failed] assertion calls per test id, with failing assertions not stopping the test."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    ids_file = ws / ".bench_soft_ids.json"
    ids_file.write_text(json.dumps(ids), encoding="utf-8")
    try:
        res = subprocess.run([sys.executable, "-c", _SOFT_ASSERT_RUNNER, str(ids_file)], cwd=ws, capture_output=True,
                             text=True, timeout=timeout, env=env)
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (subprocess.TimeoutExpired, IndexError, ValueError):
        return {test_id: [0, 0] for test_id in ids}
    finally:
        ids_file.unlink(missing_ok=True)


def export_repo(repo: str, commit: str, dest: Path) -> None:
    """Export a commit's tree with no git history, so an agent cannot read the answer from later commits."""
    source = SCENARIO_CACHE / repo
    if not (source / ".git").exists():
        raise RuntimeError(f"missing repo cache {source}; clone it first (see bench/scenarios/README.md)")
    archive = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", commit], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True)


def run_test_ids(ws: Path, ids: List[str], timeout: int = 600) -> Dict[str, bool]:
    """Pass/fail per unittest id, run from the workspace root; a module that fails to import fails all its ids."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    ids_file = ws / ".bench_test_ids.json"
    ids_file.write_text(json.dumps(ids), encoding="utf-8")
    try:
        res = subprocess.run([sys.executable, "-c", _TEST_ID_RUNNER, str(ids_file)], cwd=ws, capture_output=True,
                             text=True, timeout=timeout, env=env)
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (subprocess.TimeoutExpired, IndexError, ValueError):
        return {test_id: False for test_id in ids}
    finally:
        ids_file.unlink(missing_ok=True)


def grade_repo(task: Task, ws: Path) -> Dict[str, Any]:
    """
    SWE-bench-style grading: restore the real commit's test files (the agent's edits to them are discarded),
    then run fail-to-pass ids (the feature) and pass-to-pass ids (regressions in the touched test files).
    """
    stats = diff_stats(ws)
    patch = _git(ws, "diff", "--cached", "HEAD")
    overlay(task.hidden_dir, ws)
    f2p, p2p = task.meta["f2p"], task.meta["p2p"]
    status = run_test_ids(ws, f2p + p2p)
    f2p_passed = sum(status.get(i, False) for i in f2p)
    p2p_failed = [i for i in p2p if not status.get(i, False)]
    # Partial credit: share of the assertions the feature has to flip, i.e. (passing now - passing before) /
    # (total - passing before), with totals from the real commit. Breaking old assertions counts against it.
    # Falls back to the share of fail-to-pass methods when no assertion flips (the failure is outside an assertion).
    totals = task.meta.get("f2p_assertions") or {}
    before = task.meta.get("f2p_assertions_passing_before") or {}
    to_flip = sum(totals.get(i, 0) - before.get(i, 0) for i in f2p)
    if totals and to_flip > 0:
        counts = soft_assert_counts(ws, f2p)
        gained = sum(min(counts.get(i, [0, 0])[0], totals[i]) - before.get(i, 0) for i in f2p)
        partial = min(max(gained / to_flip, 0.0), 1.0)
    else:
        partial = f2p_passed / len(f2p) if f2p else 0.0
    return {
        "success": f2p_passed == len(f2p) and not p2p_failed,
        "hidden_passed": f2p_passed,
        "hidden_expected": len(f2p),
        "hidden_pass_rate": round(partial, 4),
        "f2p_methods_passed": f2p_passed,
        "hidden_failed_ids": [i for i in f2p if not status.get(i, False)][:20],
        "visible_ok": not p2p_failed,
        "visible_failed_ids": p2p_failed[:20],
        "agent_suite_ok": None,
        "agent_suite_tests": 0,
        "agent_test_files_added": 0,
        **stats,
        "_patch": patch,
    }
