#!/usr/bin/env python3
"""
Unit tests for the v4 verify engine (.harness/verifier.py) and the `bin/khoros verify` CLI:
- test-command detection (pytest/unittest/npm/go/cargo/make, config override, every ecosystem, project interpreter)
- syntax checks (python, js, JSON with comments), --changed scoping, --fast, explicit skips, config reader
- command running: zero tests is a skip, timeouts never hang, one shared deadline
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / ".harness"))

import verifier
from verifier import VerificationPipeline, detect_test_commands, load_verify_config, parse_failing_ids

KHOROS = ROOT / "bin" / "khoros"
FAILING = "import unittest\n\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.assertTrue(False)\n"


def git(ws, *args):
    subprocess.run(["git", *args], cwd=str(ws), check=True, capture_output=True)


class VerifyEngineBase(unittest.TestCase):
    def setUp(self):
        # inner verify runs must execute their temp project's tests even when this suite runs under `khoros verify`
        patcher = mock.patch.dict("os.environ")
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("KHOROS_VERIFY_DEPTH", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text=""):
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class TestDetectTestCommand(VerifyEngineBase):
    def detect(self):
        return detect_test_commands(self.ws)

    def first(self):
        runs, reasons = self.detect()
        return (runs[0] if runs else None), reasons

    def no_pytest(self):
        return mock.patch("verifier._python_has_pytest", return_value=False)

    def test_unittest_fallback_without_pytest(self):
        self.write("tests/test_a.py", FAILING)
        with self.no_pytest():
            run, _ = self.first()
        self.assertEqual(run["cmd"][1:4], ["-m", "unittest", "discover"])
        self.assertIn("tests", run["cmd"])

    def test_unittest_package_sets_top_level(self):
        self.write("tests/__init__.py")
        self.write("tests/test_a.py", FAILING)
        with self.no_pytest():
            run, _ = self.first()
        self.assertEqual(run["cmd"][-2:], ["-t", "."])

    def test_pytest_when_installed(self):
        self.write("tests/test_a.py", FAILING)
        with mock.patch("verifier._python_has_pytest", return_value=True):
            run, _ = self.first()
        self.assertEqual(run["cmd"][1:4], ["-m", "pytest", "-q"])
        self.assertNotIn("-x", run["cmd"])  # the gate compares the whole failure set with the baseline
        self.assertTrue(run["label"].startswith("python3 -m pytest"))

    def test_project_venv_interpreter_wins_over_path(self):  # D4
        venv_python = self.write(".venv/bin/python", "#!/bin/sh\n")
        os.chmod(venv_python, 0o755)
        self.write("tests/test_a.py", FAILING)
        with self.no_pytest():
            run, _ = self.first()
        self.assertEqual(run["cmd"][0], str(venv_python))
        self.assertTrue(run["label"].startswith(".venv/bin/python -m unittest"))

    def test_hook_interpreter_is_not_used(self):  # D4
        self.write("tests/test_a.py", FAILING)
        with self.no_pytest(), mock.patch("verifier.shutil.which", return_value="/opt/proj/python3"):
            run, _ = self.first()
        self.assertEqual(run["cmd"][0], "/opt/proj/python3")

    def test_every_python_test_location_is_discovered(self):  # D6: no tests/unit narrowing
        self.write("tests/unit/test_a.py", FAILING)
        self.write("tests/integration/test_b.py", FAILING)
        with self.no_pytest():
            runs, _ = self.detect()
        started = sorted(r["cmd"][r["cmd"].index("-s") + 1] for r in runs)
        self.assertEqual(started, ["tests/integration", "tests/unit"])

    def test_pytest_style_suffix_gets_its_own_pattern(self):
        self.write("tests/m_test.py", FAILING)
        with self.no_pytest():
            run, _ = self.first()
        self.assertEqual(run["cmd"][-2:], ["-p", "*_test.py"])

    def test_every_ecosystem_runs_not_the_first_match(self):  # D6
        self.write("tests/unit/test_a.py", FAILING)
        self.write("package.json", json.dumps({"scripts": {"test": "jest"}}))
        self.write("go.mod", "module x\n")
        self.write("Makefile", "test:\n\t@echo ok\n")
        with self.no_pytest(), mock.patch("verifier.shutil.which", side_effect=lambda n: f"/usr/bin/{n}"):
            runs, _ = self.detect()
        labels = [r["label"] for r in runs]
        self.assertEqual(len(runs), 3, labels)
        self.assertTrue(labels[0].endswith("discover -s tests/unit"))
        self.assertEqual(labels[1:], ["npm test", "go test ./..."])  # make only when nothing else was detected

    def test_npm_with_real_test_script(self):
        self.write("package.json", json.dumps({"scripts": {"test": "jest"}}))
        with mock.patch("verifier.shutil.which", return_value="/usr/bin/npm"):
            run, _ = self.first()
        self.assertEqual(run["cmd"], ["npm", "test"])

    def test_npm_default_script_is_not_a_test(self):
        self.write("package.json", json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}))
        with mock.patch("verifier.shutil.which", return_value="/usr/bin/npm"):
            run, reasons = self.first()
        self.assertIsNone(run)
        self.assertTrue(any("no test script" in r for r in reasons))

    def test_go_and_cargo(self):
        self.write("go.mod", "module x\n")
        with mock.patch("verifier.shutil.which", return_value="/usr/bin/go"):
            self.assertEqual(self.first()[0]["cmd"], ["go", "test", "./..."])
        (self.ws / "go.mod").unlink()
        self.write("Cargo.toml", "[package]\nname='x'\n")
        with mock.patch("verifier.shutil.which", return_value="/usr/bin/cargo"):
            self.assertEqual(self.first()[0]["cmd"], ["cargo", "test"])

    def test_make_test_target(self):
        self.write("Makefile", "test:\n\t@echo ok\n")
        with mock.patch("verifier.shutil.which", return_value="/usr/bin/make"):
            self.assertEqual(self.first()[0]["cmd"], ["make", "test"])

    def test_missing_toolchain_is_reported(self):
        self.write("go.mod", "module x\n")
        with mock.patch("verifier.shutil.which", return_value=None):
            run, reasons = self.first()
        self.assertIsNone(run)
        self.assertIn("go not installed", reasons)

    def test_config_override_wins(self):
        self.write("tests/test_a.py", FAILING)
        self.write(".harness/config.yaml", 'verify:\n  test_command: "echo hi"\n')
        runs, _ = self.detect()
        self.assertEqual([(r["cmd"], r["shell"]) for r in runs], [("echo hi", True)])

    def test_nothing_detected(self):
        run, reasons = self.first()
        self.assertIsNone(run)
        self.assertTrue(reasons)


class TestFailingIds(unittest.TestCase):
    def test_unittest_and_pytest_ids(self):
        out = "FAIL: test_a (m.T)\nERROR: test_b (m.T)\nFAILED (failures=1, errors=1)\n"
        self.assertEqual(parse_failing_ids(out), ["test_a (m.T)", "test_b (m.T)"])
        out = "FAILED tests/test_x.py::test_a - AssertionError: x\nERROR tests/test_y.py - ImportError\n"
        self.assertEqual(parse_failing_ids(out), ["tests/test_x.py::test_a", "tests/test_y.py"])

    def test_unparsable_is_none(self):
        self.assertIsNone(parse_failing_ids("npm ERR! Test failed\n"))


class TestConfigReader(VerifyEngineBase):
    def test_v31_config_without_verify_section_gives_defaults(self):
        self.write(".harness/config.yaml", 'version: "3.1"\nprofile: "python"\nmodels:\n  claude:\n    fast:\n      id: "x"\n')
        self.assertEqual(load_verify_config(self.ws), verifier.DEFAULT_VERIFY_CONFIG)

    def test_missing_file_gives_defaults(self):
        self.assertEqual(load_verify_config(self.ws)["max_stop_blocks"], 3)

    def test_verify_section_values(self):
        self.write(
            ".harness/config.yaml",
            'version: "4.0"\nverify:\n  gate: off   # disabled\n  test_command: "make check"\n'
            "  lint_commands:\n    - ruff check .\n    - 'mypy src'\n  test_timeout: 30\n  max_stop_blocks: 5\nother:\n  gate: on\n",
        )
        cfg = load_verify_config(self.ws)
        self.assertEqual(cfg["gate"], "off")
        self.assertEqual(cfg["test_command"], "make check")
        self.assertEqual(cfg["lint_commands"], ["ruff check .", "mypy src"])
        self.assertEqual((cfg["test_timeout"], cfg["max_stop_blocks"]), (30, 5))
        self.assertEqual(cfg["loop_edit_threshold"], 8)

    def test_inline_empty_list(self):
        self.write(".harness/config.yaml", "verify:\n  lint_commands: []\n  gate: on\n")
        cfg = load_verify_config(self.ws)
        self.assertEqual((cfg["lint_commands"], cfg["gate"]), ([], "on"))

    def test_quoted_value_followed_by_comment(self):
        self.write(".harness/config.yaml", 'verify:\n  test_command: ""    # empty = auto-detect\n  gate: "on"  # x\n')
        cfg = load_verify_config(self.ws)
        self.assertEqual((cfg["test_command"], cfg["gate"]), ("", "on"))

    def test_shipped_config_parses_to_defaults(self):
        shipped = Path(__file__).resolve().parents[2] / ".harness" / "config.yaml"
        self.write(".harness/config.yaml", shipped.read_text(encoding="utf-8"))
        self.assertEqual(load_verify_config(self.ws)["test_command"], "")


class TestStaticChecks(VerifyEngineBase):
    def run_pipeline(self, **kw):
        return VerificationPipeline(workspace_dir=self.ws).run(targets=[self.ws], **kw)

    def test_broken_python_fails_with_line_and_fix(self):
        self.write("bad.py", "x = 1\ndef f(:\n    pass\n")
        ok, report = self.run_pipeline()
        self.assertFalse(ok)
        v = report["violations"][0]
        self.assertEqual((v["rule"], v["line"]), ("PYTHON_SYNTAX_ERROR", 2))
        self.assertTrue(v["fix"])

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_broken_js_fails(self):
        self.write("bad.js", "function f( {\n")
        ok, report = self.run_pipeline()
        self.assertFalse(ok)
        self.assertEqual(report["violations"][0]["rule"], "JS_SYNTAX_ERROR")

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_valid_js_passes(self):
        self.write("ok.js", "const a = 1;\nconsole.log(a);\n")
        ok, report = self.run_pipeline()
        self.assertTrue(ok)
        self.assertIn("js-syntax", report["checks_run"])

    def test_js_skipped_when_node_missing(self):
        self.write("bad.js", "function f( {\n")
        with mock.patch("verifier.shutil.which", return_value=None):
            ok, report = self.run_pipeline()
        self.assertTrue(ok)
        self.assertIn("js-syntax (skipped: node not installed)", report["skipped"])

    def test_broken_json_fails(self):
        self.write("cfg.json", "{not json")
        ok, report = self.run_pipeline()
        self.assertFalse(ok)
        self.assertEqual(report["violations"][0]["rule"], "CONFIG_PARSE_ERROR")

    def test_skips_are_explicit(self):
        ok, report = self.run_pipeline()
        self.assertTrue(ok)
        joined = " | ".join(report["skipped"])
        self.assertIn("python-syntax (skipped: no .py files", joined)
        self.assertIn("design-tokens (skipped: no .harness/design-tokens.json", joined)
        self.assertIn("unit-tests (skipped", joined)

    def test_design_tokens_need_file_and_ui_files(self):
        self.write("Screen.tsx", "const s = { padding: 13 };\n")
        _, report = self.run_pipeline()
        self.assertNotIn("design-tokens", report["checks_run"])
        self.write(".harness/design-tokens.json", json.dumps({}))
        _, report = self.run_pipeline()
        self.assertIn("design-tokens", report["checks_run"])

    def test_fast_never_runs_tests(self):
        self.write("tests/test_x.py", FAILING)
        ok, report = self.run_pipeline(run_tests=True, fast=True)
        self.assertTrue(ok)
        self.assertNotIn("unit-tests", report["checks_run"])

    def test_failing_tests_report_tail_and_hint(self):
        self.write("tests/test_x.py", FAILING)
        ok, report = self.run_pipeline(run_tests=True)
        self.assertFalse(ok)
        self.assertEqual(report["tests"]["status"], "failed")
        self.assertIn("AssertionError", report["tests"]["output_tail"])
        text = verifier.format_report(report)
        self.assertIn("How to fix", text)
        self.assertIn("AssertionError", text)

    def test_test_timeout_is_reported(self):
        self.write(".harness/config.yaml", 'verify:\n  test_command: "sleep 5"\n')
        ok, report = self.run_pipeline(run_tests=True, test_timeout=0.5)
        self.assertFalse(ok)
        self.assertTrue(report["timed_out"])
        self.assertEqual(report["violations"][0]["rule"], "TEST_TIMEOUT")

    def test_nested_verify_skips_tests(self):
        self.write("tests/test_x.py", FAILING)
        with mock.patch.dict("os.environ", {"KHOROS_VERIFY_DEPTH": "1"}):
            ok, report = self.run_pipeline(run_tests=True)
        self.assertTrue(ok)

    def fake_python(self, body):
        py = self.write(".venv/bin/python", "#!/bin/sh\nif [ \"$1\" = -c ]; then exit 1; fi\n" + body)
        os.chmod(py, 0o755)
        self.write("tests/test_x.py", "def test_x():\n    assert False\n")  # pytest-style: unittest sees nothing

    def test_zero_tests_ran_is_skipped_not_passed_or_failed(self):  # D4
        self.fake_python("echo 'Ran 0 tests in 0.000s'; echo OK\nexit 0\n")
        ok, report = self.run_pipeline(run_tests=True)
        self.assertTrue(ok)
        self.assertNotIn("unit-tests", report["checks_run"])
        self.assertTrue(any("unit-tests (skipped" in s and "no tests collected" in s for s in report["skipped"]))

    def test_zero_tests_with_nonzero_exit_is_skipped_too(self):  # D4: Python 3.12+ exits 5
        self.fake_python("echo 'Ran 0 tests in 0.000s'; echo NO TESTS RAN; exit 5\n")
        ok, report = self.run_pipeline(run_tests=True)
        self.assertTrue(ok, report)
        self.assertEqual(report["tests"]["status"], "skipped")

    def test_pytest_exit_5_is_skipped(self):
        self.write(".harness/config.yaml", 'verify:\n  test_command: "echo pytest; exit 5"\n')
        ok, report = self.run_pipeline(run_tests=True)
        self.assertTrue(ok, report)

    def test_every_detected_runner_is_run_and_reported(self):  # D6
        self.write("package.json", json.dumps({"scripts": {"test": "exit 1"}}))
        self.write("tests/unit/test_a.py", "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): pass\n")
        self.write("tests/integration/test_b.py", FAILING)
        ok, report = self.run_pipeline(run_tests=True)
        self.assertFalse(ok)
        runs = {r["command"]: r["status"] for r in report["tests"]["runs"]}
        self.assertEqual(sorted(runs.values()), sorted(["failed", "passed"] + (["failed"] if shutil.which("npm") else [])))
        self.assertEqual(runs["python3 -m unittest discover -s tests/integration"], "failed")

    def test_jsonc_files_are_not_flagged(self):  # D7
        self.write(".vscode/settings.json", '{\n  // editor\n  "a": 1, /* x */\n  "b": [1, 2,],\n}\n')
        self.write(".devcontainer/devcontainer.json", '{\n  "name": "x", // c\n}\n')
        self.write("tsconfig.build.json", '{"compilerOptions": {/* c */},}\n')
        self.write("x.jsonc", "// c\n{}\n")
        ok, report = self.run_pipeline()
        self.assertTrue(ok, report["violations"])

    def test_jsonc_strip_keeps_comment_markers_inside_strings(self):  # D7
        self.write(".vscode/settings.json", '{"url": "http://x/*not a comment*/", "n": 1,}\n')
        self.assertTrue(self.run_pipeline()[0])
        self.write(".vscode/settings.json", '{"url": "x",, }\n')  # still broken JSON
        self.assertFalse(self.run_pipeline()[0])

    def test_plain_json_with_comments_is_still_flagged(self):  # D7: the exemption is not blanket
        self.write("package.json", '{\n  // nope\n  "a": 1\n}\n')
        self.assertFalse(self.run_pipeline()[0])

    def test_changed_files_under_a_skip_named_parent_dir_are_checked(self):
        sub = self.write("build/proj/bad.py", "def f(:\n").parent.parent
        ok, _ = VerificationPipeline(workspace_dir=sub).run(targets=[sub / "proj" / "bad.py"])
        self.assertFalse(ok)


class TestRunCommand(VerifyEngineBase):
    def test_daemonized_child_does_not_extend_the_timeout(self):  # D8a
        script = self.write("spawn.py", (
            "import os, time\nif os.fork() == 0:\n    os.setsid(); time.sleep(25); os._exit(0)\ntime.sleep(1000)\n"))
        t0 = time.time()
        rc, _, timed_out = verifier._run_command([sys.executable, str(script)], self.ws, 2)
        self.assertTrue(timed_out)
        self.assertLess(time.time() - t0, 10)

    def test_timeout_kills_the_whole_process_group(self):  # D8
        pidfile = self.ws / "pid"
        rc, _, timed_out = verifier._run_command(f"sh -c 'echo $$ > {pidfile}; sleep 60' & wait", self.ws, 1, shell=True)
        self.assertTrue(timed_out)
        pid = int(pidfile.read_text())
        time.sleep(0.3)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_output_is_captured_and_capped(self):
        rc, out, timed_out = verifier._run_command(f"{sys.executable} -c \"print('x' * 50)\"; exit 3", self.ws, 10, shell=True)
        self.assertEqual((rc, timed_out, out.strip()), (3, False, "x" * 50))

    def test_tail_caps_line_length(self):
        self.assertEqual(len(verifier._tail("y" * 100000)), 400)

    def test_one_deadline_is_shared_by_lint_and_tests(self):  # D8c
        self.write(".harness/config.yaml", 'verify:\n  lint_commands:\n    - sleep 30\n  test_command: "sleep 30"\n')
        pipeline = VerificationPipeline(workspace_dir=self.ws, deadline=time.monotonic() + 2)
        t0 = time.time()
        ok, report = pipeline.run(targets=[self.ws], run_tests=True, test_timeout=30)
        self.assertLess(time.time() - t0, 10)
        self.assertFalse(ok)
        self.assertTrue(report["timed_out"])
        self.assertEqual({v["rule"] for v in report["violations"]}, {"LINT_FAILURE", "TEST_TIMEOUT"})


class TestChangedScope(VerifyEngineBase):
    def test_changed_only_checks_changed_files(self):
        git(self.ws, "init", "-q")
        git(self.ws, "config", "user.email", "t@t")
        git(self.ws, "config", "user.name", "t")
        self.write("old_bad.py", "def f(:\n")
        git(self.ws, "add", "-A")
        git(self.ws, "commit", "-qm", "init")
        self.write("new_ok.py", "x = 1\n")
        ok, report = VerificationPipeline(workspace_dir=self.ws).run(changed=True)
        self.assertTrue(ok)
        self.write("new_bad.py", "def g(:\n")
        ok, report = VerificationPipeline(workspace_dir=self.ws).run(changed=True)
        self.assertFalse(ok)
        self.assertEqual(report["scope"], "changed")
        self.assertTrue(all("new_bad.py" in v["file"] for v in report["violations"]))

    def test_changed_outside_git_falls_back_to_full(self):
        self.write("bad.py", "def f(:\n")
        ok, report = VerificationPipeline(workspace_dir=self.ws).run(changed=True)
        self.assertFalse(ok)
        self.assertEqual(report["scope"], "full")


class TestVerifyCli(VerifyEngineBase):
    def verify(self, *args):
        return subprocess.run(
            [sys.executable, str(KHOROS), "verify", *args], cwd=str(self.ws), capture_output=True, text=True, timeout=120
        )

    def test_json_and_no_tests(self):
        self.write("tests/test_x.py", FAILING)
        proc = self.verify("--no-tests", "--json", str(self.ws))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["passed"])

    def test_default_runs_tests_and_exits_1(self):
        self.write("tests/test_x.py", FAILING)
        proc = self.verify(str(self.ws))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("unit-tests", proc.stdout)

    def test_with_tests_alias_accepted(self):
        proc = self.verify("--with-tests", str(self.ws))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
