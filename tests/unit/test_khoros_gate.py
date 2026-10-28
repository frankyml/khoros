#!/usr/bin/env python3
"""
Unit tests for bin/khoros-gate (Claude Code hook entrypoint):
- stop: no changes, failing tests, retry cap, escape hatch, timeout, pass resets counter; blocks via JSON, exit 0
- session scope: only what this session changed is verified (Q&A turns, pre-existing red tests, commits, subdirectories)
- fail-safe: unwritable state fails open, a given-up failure stays given up, nothing hangs, no orphans
- post-edit: syntax error blocks, loop nudge fires once per threshold, garbage stdin is harmless
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parent.parent.parent / "bin" / "khoros-gate"
FAILING = "import unittest\n\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.assertTrue(False)\n"
PASSING = "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
APP_RED = "def add(a, b):\n    return a + b\n\ndef mul(a, b):\n    return a + b  # broken\n"
APP_TEST = (
    "import unittest, app\n\nclass T(unittest.TestCase):\n"
    "    def test_add(self):\n        self.assertEqual(app.add(1, 2), 3)\n"
    "    def test_mul(self):\n        self.assertEqual(app.mul(2, 3), 6)\n"
)


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

    def commit_all(self, msg="c"):
        self.git("add", "-A")
        self.git("commit", "-qm", msg)

    def gate(self, sub, payload=None, raw=None, env=None):
        data = raw if raw is not None else json.dumps({"session_id": "s1", "cwd": str(self.ws), **(payload or {})})
        full_env = {k: v for k, v in os.environ.items() if k not in ("KHOROS_GATE", "KHOROS_VERIFY_DEPTH")}
        full_env.update(env or {})
        return subprocess.run(
            [sys.executable, str(GATE), sub], input=data, capture_output=True, text=True, timeout=120, env=full_env,
            cwd=str(self.ws),
        )

    def start(self, payload=None):
        proc = self.gate("session-start", payload)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""), proc.stderr)

    def stop(self, payload=None, **kw):
        """-> (returncode, parsed stdout JSON or {}, raw proc)"""
        proc = self.gate("stop", payload, **kw)
        return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else {}), proc

    def khoros_dir(self):
        return self.ws / ".git" / "khoros"


class TestGateStop(GateBase):
    def test_no_changes_allows(self):
        self.start()
        proc = self.gate("stop")
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))

    def test_docs_only_changes_allow(self):
        self.start()
        self.write("README.md", "# changed\n")
        self.write("docs/x.md", "x\n")
        self.assertEqual(self.gate("stop").stdout, "")

    def test_not_a_git_repo_allows(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tests").mkdir()
            (Path(d) / "tests" / "test_x.py").write_text(FAILING)
            proc = subprocess.run(
                [sys.executable, str(GATE), "stop"], input=json.dumps({"cwd": d}), capture_output=True, text=True,
                timeout=60, cwd=d,
            )
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_failing_tests_block_via_json_with_actionable_reason(self):
        self.start()
        self.write("tests/test_x.py", FAILING)
        rc, out, proc = self.stop()
        self.assertEqual(rc, 0, proc.stderr)  # exit 2 would show "Stop hook error" in Claude Code
        self.assertEqual(out["decision"], "block")
        self.assertIn("khoros gate: verification failed (attempt 1/3)", out["reason"])
        self.assertIn("How to fix", out["reason"])
        self.assertIn("AssertionError", out["reason"])
        self.assertLessEqual(len(out["reason"].splitlines()), 60)

    def test_passing_tests_allow(self):
        self.start()
        self.write("tests/test_x.py", PASSING)
        rc, out, _ = self.stop()
        self.assertEqual((rc, out), (0, {}))

    def test_retry_cap_releases_after_n_blocks(self):
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.write(".harness/config.yaml", "verify:\n  max_stop_blocks: 2\n")
        self.assertEqual(self.stop()[1]["decision"], "block")
        self.write("app.py", "x = 1\n")  # the agent keeps working, so the gate is not stalled
        self.assertEqual(self.stop({"stop_hook_active": True})[1]["decision"], "block")
        self.write("app.py", "x = 2\n")
        rc, out, _ = self.stop({"stop_hook_active": True})
        self.assertEqual(rc, 0)
        self.assertNotIn("decision", out)
        self.assertIn("gave up after 2 attempts", out["systemMessage"])

    def test_stall_releases_when_nothing_changed_since_the_block(self):
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.assertEqual(self.stop()[1]["decision"], "block")
        rc, out, _ = self.stop({"stop_hook_active": True})  # the agent stopped again without touching anything
        self.assertEqual(rc, 0)
        self.assertNotIn("decision", out)
        self.assertIn("no changes since the last failed verification", out["systemMessage"])
        self.write("tests/test_x.py", FAILING + "\n# edited\n")  # new work on the same failure: verify again
        self.assertEqual(self.stop()[1], {})  # same failure signature, already given up
        self.write("tests/test_y.py", FAILING.replace("test_bad", "test_other"))
        self.assertEqual(self.stop()[1]["decision"], "block")

    def test_give_up_sticks_until_the_failure_changes(self):
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.write(".harness/config.yaml", "verify:\n  max_stop_blocks: 1\n")
        self.assertEqual(self.stop()[1]["decision"], "block")
        self.assertIn("no changes since the last failed verification", self.stop()[1]["systemMessage"])
        for _ in range(3):  # D1: the old gate reset its counter on give-up and blocked again forever
            self.assertEqual(self.stop()[1], {})
        self.write("tests/test_y.py", FAILING.replace("test_bad", "test_other"))  # a different failure
        self.assertEqual(self.stop()[1]["decision"], "block")

    def test_pass_resets_counter(self):
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.assertEqual(self.stop()[1]["decision"], "block")
        state = list(self.khoros_dir().glob("gate-*.json"))
        self.assertEqual(json.loads(state[0].read_text())["blocks"], 1)
        self.write("tests/test_x.py", PASSING)
        self.assertEqual(self.stop()[1], {})
        self.assertEqual(list(self.khoros_dir().glob("gate-*.json")), [])

    def test_env_escape_hatch(self):
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.assertEqual(self.stop(env={"KHOROS_GATE": "off"})[1], {})

    def test_config_escape_hatch(self):
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.write(".harness/config.yaml", "verify:\n  gate: off\n")
        self.assertEqual(self.stop()[1], {})

    def test_timeout_allows_stop(self):
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.write(".harness/config.yaml", 'verify:\n  test_command: "sleep 10"\n  test_timeout: 1\n')
        rc, out, _ = self.stop()
        self.assertEqual(rc, 0)
        self.assertNotIn("decision", out)
        self.assertIn("time budget", out["systemMessage"])

    def test_garbage_stdin_does_not_crash(self):
        self.assertEqual(self.gate("stop", raw="not json{").returncode, 0)

    def test_state_lives_in_git_dir_not_in_the_work_tree(self):  # D11
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.stop()
        self.gate("post-edit", {"tool_input": {"file_path": str(self.ws / "tests" / "test_x.py")}})
        self.assertTrue(list(self.khoros_dir().glob("*.json")))
        self.assertFalse((self.ws / ".harness" / "state").exists())
        status = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=str(self.ws), capture_output=True,
                                text=True).stdout
        self.assertNotIn("khoros", status)
        self.assertNotIn(".harness", status)


class TestSessionScope(GateBase):
    def red_repo(self):
        self.write("app.py", APP_RED)
        self.write("tests/test_app.py", APP_TEST)
        self.commit_all("red")

    def test_question_turn_in_a_red_repo_is_silent(self):  # D1
        self.red_repo()
        self.start()
        rc, out, proc = self.stop()
        self.assertEqual((rc, out, proc.stderr), (0, {}, ""))

    def test_dirty_files_from_before_the_session_do_not_count(self):  # D1
        self.red_repo()
        self.write("wip.py", "x = 1\n")  # dirty before the session started
        self.start()
        self.assertEqual(self.stop()[1], {})

    def test_preexisting_failure_does_not_block_but_a_new_one_does(self):  # D1, live case
        self.red_repo()
        self.start()
        self.write("util.py", "def greet():\n    return 'hi'\n")
        rc, out, proc = self.stop()
        self.assertEqual(rc, 0, proc.stderr)
        self.assertNotIn("decision", out)
        self.assertIn("pre-date this session", out["systemMessage"])
        self.assertIn("test_mul", out["systemMessage"])
        self.assertEqual(len(self.worktrees()), 1, "baseline worktree must be cleaned up")

        self.write("tests/test_new.py", FAILING)
        out = self.stop()[1]
        self.assertEqual(out["decision"], "block")
        self.assertIn("New failures since this session started", out["reason"])
        self.assertIn("test_bad", out["reason"])
        self.assertIn("pre-date this session", out["reason"])
        self.assertNotIn("test_mul (", out["reason"].split("New failures")[1].split("\n")[0])

    def test_baseline_is_cached_per_commit_and_command(self):  # D1
        self.red_repo()
        self.start()
        self.write("util.py", "x = 1\n")
        self.stop()
        self.assertEqual(len(list(self.khoros_dir().glob("baseline-*.json"))), 1)
        self.stop()
        self.assertEqual(len(list(self.khoros_dir().glob("baseline-*.json"))), 1)

    def test_unparsable_failure_blocks_only_if_the_baseline_passed(self):  # D1
        self.write(".harness/config.yaml", 'verify:\n  test_command: "test -f marker"\n')
        self.write("marker", "")
        self.commit_all("with marker")
        self.start()
        self.write("a.py", "x = 1\n")
        (self.ws / "marker").unlink()  # baseline passed, now fails with no parsable ids
        self.assertEqual(self.stop()[1]["decision"], "block")

        self.git("rm", "-q", "--cached", "marker")
        self.commit_all("marker removed")
        self.write("b.py", "y = 1\n")
        self.start({"session_id": "s2"})  # baseline now red: the same failure is not new
        self.write("c.py", "z = 1\n")
        rc, out, _ = self.stop({"session_id": "s2"})
        self.assertEqual(rc, 0)
        self.assertNotIn("decision", out)

    def test_commit_then_stop_still_verifies(self):  # D3
        self.start()
        self.write("calc.py", "def add(a, b) return a + b\n")  # syntax error
        self.commit_all("broken")
        out = self.stop()[1]
        self.assertEqual(out["decision"], "block")
        self.assertIn("PYTHON_SYNTAX_ERROR", out["reason"])

    def test_committed_failing_test_still_blocks(self):  # D3
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.commit_all("failing")
        self.assertEqual(self.stop()[1]["decision"], "block")

    def test_no_baseline_falls_back_to_post_edit_records(self):  # no SessionStart ran
        self.write("tests/test_x.py", FAILING)
        self.assertEqual(self.stop()[1], {}, "nothing recorded: silent")
        self.gate("post-edit", {"tool_input": {"file_path": str(self.ws / "tests" / "test_x.py")}})
        self.assertEqual(self.stop()[1]["decision"], "block")

    def test_subdirectory_cwd_uses_the_repo_root(self):  # D5
        self.write("calc.py", "def add(a, b):\n    return a + b\n")
        self.write("tests/test_calc.py", "import unittest, calc\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(calc.add(1, 2), 3)\n")
        self.commit_all("calc")
        (self.ws / "pkg").mkdir()
        self.start({"cwd": str(self.ws / "pkg")})
        self.write("calc.py", "def add(a, b):\n    return a - b\n")
        out = self.stop({"cwd": str(self.ws / "pkg")})[1]
        self.assertEqual(out["decision"], "block")
        self.assertIn("test_add", out["reason"])

    def test_root_config_is_read_from_a_subdirectory(self):  # D5
        self.write(".harness/config.yaml", "verify:\n  gate: off\n")
        (self.ws / "pkg").mkdir()
        self.start({"cwd": str(self.ws / "pkg")})
        self.write("tests/test_x.py", FAILING)
        self.assertEqual(self.stop({"cwd": str(self.ws / "pkg")})[1], {})

    def test_subagent_stop_payload_is_ignored(self):  # D9
        self.start()
        self.write("tests/test_x.py", FAILING)
        rc, out, _ = self.stop({"agent_id": "a1", "agent_type": "Explore"})
        self.assertEqual((rc, out), (0, {}))

    def test_hooks_json_wires_session_start_and_not_subagent_stop(self):  # D9
        hooks = json.loads((GATE.parent.parent / "plugin" / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertNotIn("SubagentStop", hooks)
        self.assertEqual(set(hooks), {"SessionStart", "Stop", "PostToolUse"})
        self.assertIn("khoros-gate\" session-start", hooks["SessionStart"][0]["hooks"][0]["command"])
        for event in hooks.values():
            self.assertLess(event[0]["hooks"][0]["timeout"], 301)

    def worktrees(self):
        out = subprocess.run(["git", "worktree", "list"], cwd=str(self.ws), capture_output=True, text=True).stdout
        return out.splitlines()


class TestGateFailSafe(GateBase):
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores directory permissions")
    def test_unwritable_state_fails_open(self):  # D2
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.gate("post-edit", {"tool_input": {"file_path": str(self.ws / "tests" / "test_x.py")}})
        kdir = self.khoros_dir()
        os.chmod(kdir, 0o555)
        try:
            for _ in range(3):
                rc, out, _ = self.stop({"stop_hook_active": True})
                self.assertEqual(rc, 0)
                self.assertNotIn("decision", out)
                self.assertIn("cannot write", out["systemMessage"])
        finally:
            os.chmod(kdir, 0o755)

    def test_state_path_that_is_a_file_falls_back_to_temp_dir(self):  # D2
        (self.ws / ".git" / "khoros").write_text("not a dir")
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.assertEqual(self.stop()[1]["decision"], "block")
        self.write("app.py", "x = 1\n")  # keep working so the second stop is not a stall
        self.assertEqual(self.stop()[1]["decision"], "block")  # the counter persisted in the fallback dir

    def test_test_timeout_does_not_wait_for_daemonized_children(self):  # D8a
        self.start()
        script = self.write("spawn.py", (
            "import os, sys, time\n"
            "if os.fork() == 0:\n    os.setsid(); time.sleep(30); os._exit(0)\n"
            "print('running', flush=True); time.sleep(1000)\n"))
        self.write(".harness/config.yaml", f'verify:\n  test_command: "{sys.executable} {script}"\n  test_timeout: 2\n')
        self.write("a.py", "x = 1\n")
        t0 = time.time()
        rc, out, _ = self.stop()
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(rc, 0)
        self.assertIn("time budget", out["systemMessage"])

    def test_sigterm_kills_the_running_tests(self):  # D8b
        self.start()
        pidfile = self.ws / "test.pid"
        self.write(".harness/config.yaml", f'verify:\n  test_command: "echo $$ > {pidfile}; exec sleep 120"\n')
        self.write("a.py", "x = 1\n")
        env = {k: v for k, v in os.environ.items() if k not in ("KHOROS_GATE", "KHOROS_VERIFY_DEPTH")}
        proc = subprocess.Popen(
            [sys.executable, str(GATE), "stop"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(self.ws), env=env,
        )
        proc.stdin.write(json.dumps({"session_id": "s1", "cwd": str(self.ws)}))
        proc.stdin.close()
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            time.sleep(0.1)
        pid = int(pidfile.read_text().strip())
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=20)
        proc.stdout.close()
        proc.stderr.close()
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        os.kill(pid, signal.SIGKILL)
        self.fail("the test process outlived the gate")

    def test_shared_budget_bounds_lint_plus_tests_and_keeps_static_findings(self):  # D8c, D12
        self.start()
        self.write(
            ".harness/config.yaml",
            'verify:\n  lint_commands:\n    - sleep 30\n  test_command: "sleep 30"\n  test_timeout: 30\n  gate_budget: 4\n',
        )
        self.write("bad.py", "def f(:\n")
        t0 = time.time()
        rc, out, _ = self.stop()
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(out["decision"], "block")
        self.assertIn("PYTHON_SYNTAX_ERROR", out["reason"])  # found in the same run as the timeout

    def test_project_interpreter_runs_the_tests(self):  # D4
        fake = self.write(".venv/bin/python", "#!/bin/sh\n"
                          "if [ \"$1\" = -c ]; then exit 1; fi\n"
                          "echo 'FAIL: test_from_venv (m.T)'; echo 'Ran 1 test'; exit 1\n")
        os.chmod(fake, 0o755)
        self.start()
        self.write("tests/test_x.py", PASSING)
        out = self.stop()[1]
        self.assertEqual(out["decision"], "block")
        self.assertIn("test_from_venv", out["reason"])
        self.assertIn(".venv/bin/python -m unittest", out["reason"])


class TestGateViewerState(GateBase):
    """What the khoros-view mod reads (runs-<session>.json) and writes (off-<session>.json)."""

    def runs(self, session="s1"):
        path = self.khoros_dir() / f"runs-{session}.json"
        return json.loads(path.read_text())["runs"] if path.exists() else []

    def test_block_then_pass_are_recorded_with_their_tests(self):
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.assertEqual(self.stop()[1]["decision"], "block")
        self.write("tests/test_x.py", PASSING)
        self.assertEqual(self.stop({"stop_hook_active": True})[1], {})
        block, ok = self.runs()
        self.assertEqual((block["outcome"], block["attempt"], block["max"]), ("block", 1, 3))
        self.assertTrue(block["new"])
        self.assertIn("failed", [t["status"] for t in block["tests"]])
        self.assertEqual(ok["outcome"], "pass")
        self.assertEqual({t["status"] for t in ok["tests"]}, {"passed"})
        self.assertLessEqual(block["at"], ok["at"])

    def test_preexisting_failures_are_recorded(self):
        self.write("app.py", APP_RED)
        self.write("tests/test_app.py", APP_TEST)
        self.commit_all()
        self.start()
        self.write("notes.py", "x = 1\n")  # unrelated change: the red test pre-dates the session
        self.stop()
        (run,) = self.runs()
        self.assertEqual(run["outcome"], "pass")
        self.assertTrue(run["preexisting"])

    def test_stall_is_recorded(self):
        self.start()
        self.write("tests/test_x.py", FAILING)
        self.stop()
        self.stop({"stop_hook_active": True})
        self.assertEqual([r["outcome"] for r in self.runs()], ["block", "stall"])

    def test_run_log_is_capped(self):
        self.start()
        self.write("tests/test_x.py", PASSING)
        self.khoros_dir().mkdir(parents=True, exist_ok=True)
        old = [{"at": i, "outcome": "pass"} for i in range(60)]
        (self.khoros_dir() / "runs-s1.json").write_text(json.dumps({"runs": old}))
        self.stop()
        runs = self.runs()
        self.assertEqual(len(runs), 50)
        self.assertEqual(runs[0]["at"], 11)

    def test_session_off_flag_disables_stop_and_post_edit_for_that_session_only(self):
        self.start()
        self.start({"session_id": "s2"})
        self.write("tests/test_x.py", FAILING)
        flag = self.khoros_dir() / "off-s1.json"
        flag.write_text('{"off": true}')
        self.assertEqual(self.stop()[1], {})
        self.assertEqual(self.runs(), [])
        proc = self.gate("post-edit", {"tool_input": {"file_path": str(self.write("bad.py", "def f(:\n"))}})
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.stop({"session_id": "s2"})[1]["decision"], "block")
        flag.write_text('{"off": false}')  # the mod turns the gate back on by rewriting the flag
        self.assertEqual(self.stop()[1]["decision"], "block")


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
