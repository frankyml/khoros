#!/usr/bin/env python3
"""
Unit tests for the verification gate's test discovery (`khoros verify --with-tests`):
- runs tests/unit when present, otherwise tests/, otherwise test/
- fails on a failing test in a flat tests/ layout
- reports, instead of silently passing, when no test directory exists
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / ".harness"))

from verifier import VerificationPipeline

PASSING = "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
FAILING = "import unittest\n\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.assertTrue(False)\n"


class TestVerifierTestGate(unittest.TestCase):
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

    def run_gate(self):
        return VerificationPipeline(workspace_dir=self.ws, profile="generic").run(targets=[self.ws], run_tests=True)

    def write(self, rel, text):
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_flat_tests_layout_runs(self):
        self.write("tests/test_x.py", FAILING)
        ok, report = self.run_gate()
        self.assertFalse(ok)
        self.assertIn("unit-tests", report["checks_run"])

    def test_tests_unit_preferred(self):
        self.write("tests/unit/test_x.py", PASSING)
        self.write("tests/test_y.py", FAILING)
        ok, _ = self.run_gate()
        self.assertTrue(ok)

    def test_no_tests_is_reported(self):
        ok, report = self.run_gate()
        self.assertTrue(ok)
        self.assertTrue(any(c.startswith("unit-tests (skipped") for c in report["skipped"]))


if __name__ == "__main__":
    unittest.main()
