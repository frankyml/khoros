#!/usr/bin/env python3
"""
Unit tests for the Khoros A/B benchmark suite (bench/):
- Oracle: every task's hidden tests fail before and pass with the reference solution
- Grader discriminates a plausible-but-wrong solution (hardcoded hex in the sale badge)
- Arm provisioning installs exactly the Khoros surfaces each arm declares
- stream-json transcript parsing and report statistics
"""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "bench"))

from benchlib import ARMS, PROMPT_SUFFIX, build_workspace, grade, load_tasks, parse_stream, soft_assert_counts
from report import adopted, min_detectable_effect, paired_bootstrap, pass_k, simulated_power, wilson
from validate_tasks import validate_task


class TestBenchOracle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="khoros-bench-test-")
        self.scratch = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_task_is_discriminating(self):
        for task in [t for t in load_tasks() if t.kind == "fixture"]:  # repo tasks: bench/validate_tasks.py
            with self.subTest(task=task.id):
                row = validate_task(task, self.scratch)
                self.assertEqual(row["problems"], [])

    @unittest.skipUnless((Path(__file__).resolve().parent.parent.parent / "bench" / "scenarios" / "cache" / "sqlglot" / ".git").exists(),
                         "sqlglot cache not cloned")
    def test_repo_task_grading(self):
        task = next(t for t in load_tasks(suite="repo-features") if t.id == "sqlglot-59a96d868a")
        before = grade(task, self._repo_ws(task, "before", solution=False))
        after = grade(task, self._repo_ws(task, "after", solution=True))
        self.assertFalse(before["success"])
        self.assertLess(before["hidden_pass_rate"], 0.5)
        self.assertTrue(after["success"])
        self.assertEqual(after["hidden_pass_rate"], 1.0)
        self.assertFalse((self.scratch / "before" / ".git" / "refs" / "remotes").exists())  # no upstream history

    def _repo_ws(self, task, name, solution):
        ws = self.scratch / name
        build_workspace(task, ARMS["vanilla"], ws, solution=solution)
        return ws

    def test_hardcoded_colour_badge_is_rejected(self):
        task = load_tasks(["t1-sale-badge"])[0]
        ws = self.scratch / "naive"
        build_workspace(task, ARMS["vanilla"], ws, solution=True)
        css = ws / "src" / "shop" / "web" / "static" / "cart.css"
        css.write_text(re.sub(r"var\(--color-error\)", "#BA1A1A", css.read_text(encoding="utf-8")), encoding="utf-8")
        result = grade(task, ws)
        self.assertFalse(result["success"])
        self.assertTrue(result["visible_ok"])

    def test_suites_partition_the_corpus(self):
        core, hard, repo = load_tasks(suite="core"), load_tasks(suite="hard"), load_tasks(suite="repo-features")
        self.assertTrue(core and hard)
        self.assertEqual(len(core) + len(hard) + len(repo), len(load_tasks()))
        self.assertTrue(all(t.kind == "repo" and t.meta["khoros_tier_with_files"][:2] in ("T2", "T3") for t in repo))
        self.assertTrue(all(t.suite == "hard" and t.id.startswith("h-") for t in hard))

    def test_bug_hunt_bugs_are_invisible_to_visible_tests(self):
        task = load_tasks(["h-bug-hunt"])[0]
        ws = self.scratch / "hunt"
        build_workspace(task, ARMS["vanilla"], ws)
        result = grade(task, ws)
        self.assertTrue(result["visible_ok"])
        self.assertFalse(result["success"])

    def test_fast_but_drifting_report_is_rejected(self):
        task = load_tasks(["h-report-perf"])[0]
        ws = self.scratch / "drift"
        build_workspace(task, ARMS["vanilla"], ws, solution=True)
        report = ws / "src" / "shop" / "reports.py"
        report.write_text(report.read_text(encoding="utf-8").replace("Decimal(100) - shown", "Decimal('100.0') - shown"), encoding="utf-8")
        result = grade(task, ws)
        self.assertFalse(result["success"])
        self.assertGreater(result["hidden_passed"], 0)

    def test_subtest_failures_count_once(self):
        task = load_tasks(["h-conventions"])[0]
        ws = self.scratch / "conv"
        build_workspace(task, ARMS["vanilla"], ws)
        result = grade(task, ws)
        self.assertEqual(result["hidden_passed"], 2)

    def test_arms_install_only_their_surfaces(self):
        task = load_tasks()[0]
        for arm in ARMS.values():
            with self.subTest(arm=arm.name):
                ws = self.scratch / arm.name
                info = build_workspace(task, arm, ws)
                self.assertEqual((ws / "CLAUDE.md").exists(), arm.claude_md)
                self.assertEqual((ws / ".harness" / "config.yaml").exists(), arm.harness)
                self.assertEqual("--plugin-dir" in info["extra_args"], arm.plugin)
                self.assertEqual("PATH" in info["env"], arm.harness)


class TestTranscriptParsing(unittest.TestCase):
    def test_parse_stream(self):
        events = [
            {"type": "system", "subtype": "init", "model": "claude-x", "plugins": [{"name": "plugin"}], "agents": [], "mcp_servers": []},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "bin/khoros triage 'x' && bin/khoros verify"}},
                {"type": "tool_use", "name": "Task", "input": {}},
                {"type": "text", "text": "hi"},
            ]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "python3 -m unittest"}}]}},
            {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.5, "duration_ms": 1000, "num_turns": 4,
             "modelUsage": {"m1": {"inputTokens": 10, "outputTokens": 20, "cacheReadInputTokens": 70, "cacheCreationInputTokens": 20},
                            "m2": {"inputTokens": 0, "outputTokens": 5, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0}}},
        ]
        m = parse_stream([json.dumps(e) for e in events] + ["not json"])
        self.assertEqual(m["tool_calls"], 3)
        self.assertEqual(m["subagents"], 1)
        self.assertEqual(m["khoros_cmds"], {"triage": 1, "verify": 1})
        self.assertEqual(m["output_tokens"], 25)
        self.assertEqual(m["prompt_tokens"], 100)
        self.assertEqual(m["cache_hit_ratio"], 0.7)
        self.assertEqual(m["init"]["plugins"], ["plugin"])

    def test_missing_result(self):
        self.assertFalse(parse_stream([])["has_result"])

    def test_adoption(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "bin/khoros triage 'x' --type feature"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "khoros task create t1 'T' && bin/khoros claim t1 --worker @lead"}},
            {"type": "tool_use", "name": "Task", "input": {"subagent_type": "plugin:pdh-critic", "prompt": "review"}},
            {"type": "tool_use", "name": "Skill", "input": {"skill": "plugin:development-harness"}},
        ]}}]
        m = parse_stream([json.dumps(e) for e in events])
        self.assertEqual({f for f, used in m["adoption"].items() if used},
                         {"triage", "task", "claim", "pdh_subagent", "harness_skill"})
        self.assertEqual(m["subagent_types"], {"plugin:pdh-critic": 1})

    def test_v4_adoption_and_gate_blocks(self):
        events = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "khoros:khoros-reviewer", "prompt": "review"}},
                {"type": "tool_use", "name": "Skill", "input": {"skill": "khoros:long-task"}},
            ]}},
            {"type": "user", "message": {"content": [{"type": "text", "text": (
                "Stop hook feedback:\n[bin/khoros-gate stop]: khoros gate: verification failed (attempt 1/3).")}]}},
            {"type": "user", "message": {"content": [{"type": "text", "text": "an unrelated message"}]}},
        ]
        m = parse_stream([json.dumps(e) for e in events])
        self.assertTrue(m["adoption"]["pdh_subagent"] and m["adoption"]["harness_skill"])
        self.assertEqual(m["behaviour"]["gate_blocks"], 1)

    def test_khoros_verify_counts_as_test_run_only_when_tests_ran(self):
        def run(output):
            events = [
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "id": "e", "input": {}}]}},
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "name": "Bash", "id": "v", "input": {"command": "bin/khoros verify"}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "v", "content": output}]}},
            ]
            return parse_stream([json.dumps(e) for e in events])["behaviour"]
        ran = run("✓ Verification passed [scope: full | checks: secret-hygiene, unit-tests]")
        self.assertEqual((ran["test_runs"], ran["ended_verified"]), (1, True))
        skipped = run("✓ Verification passed [scope: full | checks: secret-hygiene]\n  unit-tests (skipped: no tests)")
        self.assertEqual((skipped["test_runs"], skipped["ended_verified"]), (0, False))
        self.assertEqual(run('{"checks_run": ["secret-hygiene", "python-syntax"]}')["test_runs"], 0)  # v3.1, no tests

    def test_behaviour(self):
        def call(name, **inp):
            return {"type": "tool_use", "name": name, "input": inp}
        events = [{"type": "assistant", "message": {"content": [
            call("Bash", command="python3 -m unittest discover tests"),
            call("Edit", file_path="a.py"),
            call("Bash", command="sed -i 's/x/y/' b.py && python3 -m pytest -q"),
            call("Bash", command="cat > c.py <<'EOF'\nprint(1)\nEOF"),
        ]}}, {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "boom"}]}}]
        b = parse_stream([json.dumps(e) for e in events])["behaviour"]
        self.assertEqual((b["test_runs"], b["edits"], b["tool_errors"]), (2, 3, 1))
        self.assertTrue(b["ran_tests"])
        self.assertFalse(b["ended_verified"])  # the last action was an untested edit

    def test_adoption_from_old_records(self):
        old = {"khoros_cmds": {"verify": 2}, "skill_calls": 0}
        self.assertTrue(adopted(old, "verify"))
        self.assertFalse(adopted(old, "triage"))


class TestArmsAndPrompts(unittest.TestCase):
    def test_only_factory_arm_gets_the_workflow_preamble(self):
        task = load_tasks(["t0-line-rounding"])[0]
        for arm in ARMS.values():
            prompt = arm.prompt_for(task)
            self.assertTrue(prompt.endswith(PROMPT_SUFFIX))
            self.assertIn(task.prompt, prompt)
            self.assertEqual("bin/khoros triage" in prompt, arm.name == "khoros-factory", arm.name)

    def test_placebo_matches_khoros_context_length(self):
        root = Path(__file__).resolve().parent.parent.parent
        always_loaded = len((root / "CLAUDE.md").read_bytes())
        sys.path.insert(0, str(root / "bench"))
        from overhead import context_tax
        always_loaded = sum(r["bytes"] for r in context_tax(root) if r["loaded"].startswith("every turn"))
        placebo = len((root / "bench" / "placebo" / "CLAUDE.md").read_bytes())
        self.assertLess(abs(placebo - always_loaded) / always_loaded, 0.05)
        self.assertEqual(ARMS["placebo"].claude_md_source, "placebo/CLAUDE.md")

    def test_placebo_does_not_reveal_itself(self):
        text = (Path(__file__).resolve().parent.parent.parent / "bench" / "placebo" / "CLAUDE.md").read_text(encoding="utf-8")
        for word in ("khoros", "placebo", "benchmark", "harness", "experiment"):
            self.assertNotIn(word, text.lower())

    def test_suffix_is_neutral(self):
        self.assertNotIn("Do not ask", PROMPT_SUFFIX)


class TestSoftAssertCounting(unittest.TestCase):
    MODULE = """
import unittest

class T(unittest.TestCase):
    def validate_all(self, x):  # helper like sqlglot's: subTest + a nested assertion
        with self.subTest(x=x):
            self.assertEqual(x, 1)

    def test_m(self):
        self.validate_all(1)                       # pass
        self.validate_all(2)                       # fail, recorded by subTest instead of raised
        self.assertEqual(1, 1)                     # pass
        with self.assertRaises(ValueError):        # fail: nothing raised
            pass
        self.assertRaises(ValueError, int, "x")    # pass
"""

    def test_counts_top_level_assertions_including_hidden_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "soft_mod.py").write_text(self.MODULE, encoding="utf-8")
            counts = soft_assert_counts(Path(tmp), ["soft_mod.T.test_m"])
        self.assertEqual(counts["soft_mod.T.test_m"], [3, 2])


class TestReportStatistics(unittest.TestCase):
    def test_wilson(self):
        self.assertEqual(wilson(0, 0), (0.0, 0.0))
        lo, hi = wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3)
        self.assertAlmostEqual(hi, 0.7634, places=3)

    def test_paired_bootstrap(self):
        recs = []
        for task in ("a", "b"):
            for rep in range(4):
                recs.append({"task": task, "arm": "vanilla", "success": rep < 2, "cost_usd": 1.0, "wall_s": 10.0})
                recs.append({"task": task, "arm": "khoros", "success": True, "cost_usd": 2.0, "wall_s": 10.0})
        cmp = paired_bootstrap(recs, "khoros", "vanilla", iters=200)
        self.assertAlmostEqual(cmp["solve_delta"], 0.5)
        self.assertAlmostEqual(cmp["cost_ratio"], 2.0)
        self.assertAlmostEqual(cmp["wall_ratio"], 1.0)
        lo, hi = cmp["solve_delta_ci"]
        self.assertLessEqual(lo, 0.5)
        self.assertGreaterEqual(hi, 0.5)
        self.assertAlmostEqual(cmp["passk_delta"], 1.0)  # khoros: every task always solved; vanilla: none fully
        self.assertAlmostEqual(cmp["baseline_rate"], 0.5)

    def test_pass_k(self):
        recs = [{"task": "a", "success": True}, {"task": "a", "success": True},
                {"task": "b", "success": True}, {"task": "b", "success": False}]
        self.assertEqual(pass_k(recs), 0.5)

    def test_power_grows_with_tasks(self):
        small = simulated_power(9, 3, 15, 0.5, sims=200)
        large = simulated_power(50, 5, 15, 0.5, sims=200)
        self.assertLess(small, 0.35)
        self.assertGreater(large, 0.65)
        self.assertIsNone(min_detectable_effect(50, 5, 0.97))  # at the ceiling no gain is detectable


if __name__ == "__main__":
    unittest.main()
