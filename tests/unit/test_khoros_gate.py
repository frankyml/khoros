#!/usr/bin/env python3
"""
Unit tests for bin/khoros-gate (Claude Code hook entrypoint):
- stop: no changes, failing tests, retry cap, escape hatch, stop_hook_active, timeout, pass resets counter
- post-edit: syntax error blocks, loop nudge fires once per threshold, garbage stdin is harmless
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parent.parent.parent / "bin" / "khoros-gate"
FAILING = "import unittest\n\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.assertTrue(False)\n"
PASSING = "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"


class GateBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name).resolve()
        self.git("init", "-q")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        self.write("README.md", "# t\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", *args], cwd=str(self.ws), check=True, capture_output=True)

    def write(self, rel, text=""):
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def gate(self, sub, payload=None, raw=None, env=None):
        data = raw if raw is not None else json.dumps({"session_id": "s1", "cwd": str(self.ws), **(payload or {})})
        full_env = {k: v for k, v in os.environ.items() if k not in ("KHOROS_GATE", "KHOROS_VERIFY_DEPTH")}
        full_env.update(env or {})
        return subprocess.run(
            [sys.executable, str(GATE), sub], input=data, capture_output=True, text=True, timeout=120, env=full_env,
            cwd=str(self.ws),
        )


class TestGateStop(GateBase):
    def test_no_changes_allows(self):
        proc = self.gate("stop")
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))

    def test_docs_only_changes_allow(self):
        self.write("README.md", "# changed\n")
        self.write("docs/x.md", "x\n")
        self.assertEqual(self.gate("stop").returncode, 0)

    def test_not_a_git_repo_allows(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tests").mkdir()
            (Path(d) / "tests" / "test_x.py").write_text(FAILING)
            proc = subprocess.run(
                [sys.executable, str(GATE), "stop"], input=json.dumps({"cwd": d}), capture_output=True, text=True,
                timeout=60, cwd=d,
            )
        self.assertEqual(proc.returncode, 0)

    def test_failing_tests_block_with_actionable_stderr(self):
        self.write("tests/test_x.py", FAILING)
        proc = self.gate("stop")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("verification failed", proc.stderr)
        self.assertIn("How to fix", proc.stderr)
        self.assertIn("AssertionError", proc.stderr)

    def test_passing_tests_allow(self):
        self.write("tests/test_x.py", PASSING)
        self.assertEqual(self.gate("stop").returncode, 0)

    def test_retry_cap_releases_after_n_blocks(self):
        self.write("tests/test_x.py", FAILING)
        self.write(".harness/config.yaml", "verify:\n  max_stop_blocks: 2\n")
        self.assertEqual(self.gate("stop").returncode, 2)
        self.assertEqual(self.gate("stop", {"stop_hook_active": True}).returncode, 2)
        proc = self.gate("stop", {"stop_hook_active": True})
        self.assertEqual(proc.returncode, 0)
        self.assertIn("gave up after 2 attempts", proc.stderr)

    def test_pass_resets_counter(self):
        self.write("tests/test_x.py", FAILING)
        self.assertEqual(self.gate("stop").returncode, 2)
        state = list((self.ws / ".harness" / "state").glob("gate-*.json"))
        self.assertEqual(json.loads(state[0].read_text())["blocks"], 1)
        self.write("tests/test_x.py", PASSING)
        self.assertEqual(self.gate("stop").returncode, 0)
        self.assertEqual(list((self.ws / ".harness" / "state").glob("gate-*.json")), [])

    def test_env_escape_hatch(self):
        self.write("tests/test_x.py", FAILING)
        self.assertEqual(self.gate("stop", env={"KHOROS_GATE": "off"}).returncode, 0)

    def test_config_escape_hatch(self):
        self.write("tests/test_x.py", FAILING)
        self.write(".harness/config.yaml", "verify:\n  gate: off\n")
        self.assertEqual(self.gate("stop").returncode, 0)

    def test_timeout_allows_stop(self):
        self.write("tests/test_x.py", FAILING)
        self.write(".harness/config.yaml", 'verify:\n  test_command: "sleep 10"\n  test_timeout: 1\n')
        proc = self.gate("stop")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("exceeded 1s", proc.stderr)

    def test_garbage_stdin_does_not_crash(self):
        self.assertEqual(self.gate("stop", raw="not json{").returncode, 0)


class TestGatePostEdit(GateBase):
    def edit(self, path, session="s1"):
        return self.gate("post-edit", {"session_id": session, "tool_input": {"file_path": str(path)}})

    def test_syntax_error_blocks(self):
        bad = self.write("bad.py", "def f(:\n")
        proc = self.edit(bad)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("PYTHON_SYNTAX_ERROR", proc.stderr)
        self.assertIn("bad.py:1", proc.stderr)

    def test_clean_file_passes(self):
        self.assertEqual(self.edit(self.write("ok.py", "x = 1\n")).returncode, 0)

    def test_loop_nudge_fires_once_per_threshold(self):
        self.write(".harness/config.yaml", "verify:\n  loop_edit_threshold: 3\n")
        ok = self.write("ok.py", "x = 1\n")
        codes = [self.edit(ok).returncode for _ in range(5)]
        self.assertEqual(codes, [0, 0, 2, 0, 0])
        proc = self.edit(ok)  # 6th edit -> second threshold
        self.assertEqual(proc.returncode, 2)
        self.assertIn("edited 6 times", proc.stderr)

    def test_loop_counts_are_per_session(self):
        self.write(".harness/config.yaml", "verify:\n  loop_edit_threshold: 2\n")
        ok = self.write("ok.py", "x = 1\n")
        self.assertEqual(self.edit(ok, "a").returncode, 0)
        self.assertEqual(self.edit(ok, "b").returncode, 0)

    def test_garbage_stdin_allows(self):
        self.assertEqual(self.gate("post-edit", raw="\x00garbage").returncode, 0)

    def test_missing_file_path_allows(self):
        self.assertEqual(self.gate("post-edit", {"tool_input": {}}).returncode, 0)

    def test_escape_hatch(self):
        bad = self.write("bad.py", "def f(:\n")
        proc = self.gate("post-edit", {"tool_input": {"file_path": str(bad)}}, env={"KHOROS_GATE": "off"})
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
