#!/usr/bin/env python3
"""
Unit tests for the v4 verify engine (.harness/verifier.py) and the `bin/khoros verify` CLI:
- test-command detection (pytest/unittest/npm/go/cargo/make, config override)
- syntax checks (python, js), --changed scoping, --fast, explicit skips, config reader
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / ".harness"))

import verifier
from verifier import VerificationPipeline, detect_test_command, load_verify_config

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
        return detect_test_command(self.ws)

    def test_unittest_fallback_without_pytest(self):
        self.write("tests/test_a.py", FAILING)
        with mock.patch("verifier.importlib.util.find_spec", return_value=None):
            cmd, label, _, _ = self.detect()
        self.assertEqual(cmd[1:4], ["-m", "unittest", "discover"])
        self.assertIn("tests", cmd)

    def test_unittest_package_sets_top_level(self):
        self.write("tests/__init__.py")
        self.write("tests/test_a.py", FAILING)
        with mock.patch("verifier.importlib.util.find_spec", return_value=None):
            cmd, _, _, _ = self.detect()
        self.assertEqual(cmd[-2:], ["-t", "."])

    def test_pytest_when_installed(self):
        self.write("tests/test_a.py", FAILING)
        with mock.patch("verifier.importlib.util.find_spec", return_value=object()):
            cmd, label, _, _ = self.detect()
        self.assertEqual(cmd[1:5], ["-m", "pytest", "-q", "-x"])
        self.assertTrue(label.startswith("python3 -m pytest"))

    def test_npm_with_real_test_script(self):
        self.write("package.json", json.dumps({"scripts": {"test": "jest"}}))
        with mock.patch("verifier.shutil.which", return_value="/usr/bin/npm"):
            cmd, label, _, _ = self.detect()
        self.assertEqual(cmd, ["npm", "test"])

    def test_npm_default_script_is_not_a_test(self):
        self.write("package.json", json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}))
        with mock.patch("verifier.shutil.which", return_value="/usr/bin/npm"):
            cmd, _, _, reasons = self.detect()
        self.assertIsNone(cmd)
        self.assertTrue(any("no test script" in r for r in reasons))

    def test_go_and_cargo(self):
        self.write("go.mod", "module x\n")
        with mock.patch("verifier.shutil.which", return_value="/usr/bin/go"):
            self.assertEqual(self.detect()[0], ["go", "test", "./..."])
        (self.ws / "go.mod").unlink()
        self.write("Cargo.toml", "[package]\nname='x'\n")
        with mock.patch("verifier.shutil.which", return_value="/usr/bin/cargo"):
            self.assertEqual(self.detect()[0], ["cargo", "test"])

    def test_make_test_target(self):
        self.write("Makefile", "test:\n\t@echo ok\n")
        with mock.patch("verifier.shutil.which", return_value="/usr/bin/make"):
            self.assertEqual(self.detect()[0], ["make", "test"])

    def test_missing_toolchain_is_reported(self):
        self.write("go.mod", "module x\n")
        with mock.patch("verifier.shutil.which", return_value=None):
            cmd, _, _, reasons = self.detect()
        self.assertIsNone(cmd)
        self.assertIn("go not installed", reasons)

    def test_config_override_wins(self):
        self.write("tests/test_a.py", FAILING)
        self.write(".harness/config.yaml", 'verify:\n  test_command: "echo hi"\n')
        cmd, label, shell, _ = self.detect()
        self.assertEqual((cmd, shell), ("echo hi", True))

    def test_nothing_detected(self):
        cmd, _, _, reasons = self.detect()
        self.assertIsNone(cmd)
        self.assertTrue(reasons)


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
