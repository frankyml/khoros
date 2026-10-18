#!/usr/bin/env python3
"""
Unit tests for Khoros v3.1 Phase 2:
- WorktreeSandbox isolation and resource limit handling
- CleanTrunkCanary regression scanning (FP = 0 invariant)
- Kaizen Rule of Two (N=2) Pareto Distillation Engine
- Quarantined Proposal Ledger
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Add .harness to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / ".harness"))

from blackboard import Blackboard
from kaizen.distillation import KaizenDistillationEngine, normalize_ast_signature
from kernel.canary import CleanTrunkCanary, run_canary_check
from kernel.sandbox import WorktreeSandbox, run_sandboxed_test


class TestPhase2Sandbox(unittest.TestCase):
    def test_sandbox_passing_test(self):
        tool_code = """
def add(a, b):
    return a + b
"""
        test_code = """
import unittest
from tool_impl import add

class TestAdd(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

if __name__ == '__main__':
    unittest.main()
"""
        ok, output, exit_code = run_sandboxed_test(tool_code, test_code)
        self.assertTrue(ok, f"Sandbox test should pass: {output}")
        self.assertEqual(exit_code, 0)

    def test_sandbox_failing_test(self):
        tool_code = """
def add(a, b):
    return a - b
"""
        test_code = """
import unittest
from tool_impl import add

class TestAdd(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

if __name__ == '__main__':
    unittest.main()
"""
        ok, output, exit_code = run_sandboxed_test(tool_code, test_code)
        self.assertFalse(ok, "Sandbox test should fail")
        self.assertNotEqual(exit_code, 0)


class TestPhase2Canary(unittest.TestCase):
    def test_canary_passes_on_compliant_code(self):
        root = Path(__file__).resolve().parent.parent.parent
        target_token = "ABSURD" + "_NON_EXISTENT" + "_CANARY_TEST_TOKEN"
        # Jig checker that checks for a non-existent token
        def clean_checker(path: Path, content: str):
            if target_token in content:
                return ["Found absurd token"]
            return []

        res = run_canary_check(clean_checker, root_dir=root / "tests")
        self.assertTrue(res.passed)
        self.assertEqual(res.false_positives, 0)
        self.assertGreater(res.scanned_files, 0)

    def test_canary_flags_false_positives_on_over_restrictive_jig(self):
        root = Path(__file__).resolve().parent.parent.parent
        # Over-restrictive jig flagging common 'import' statement
        def bad_checker(path: Path, content: str):
            if "import" in content:
                return ["Flagged import"]
            return []

        res = run_canary_check(bad_checker, root_dir=root / "tests")
        self.assertFalse(res.passed)
        self.assertGreater(res.false_positives, 0)


class TestPhase2Distillation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_blackboard.db"
        self.bb = Blackboard(db_path=self.db_path)
        self.engine = KaizenDistillationEngine(bb=self.bb)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_normalize_ast_signature(self):
        code1 = "color = '#FF0000'"
        code2 = "theme_color = '#00FF00'"
        sig1 = normalize_ast_signature(code1)
        sig2 = normalize_ast_signature(code2)
        # Structural AST hashes should be identical despite different var names and colors
        self.assertEqual(sig1, sig2)

    def test_rule_of_two_trips_distillation(self):
        diff1 = "- Color('#FF0000')\n+ Theme.colors.primary"
        sig_id1, count1, tripped1 = self.engine.record_failure_and_evaluate("HARDCODED_HEX", diff1)
        self.assertEqual(count1, 1)
        self.assertFalse(tripped1)

        diff2 = "- Color('#00FF00')\n+ Theme.colors.secondary"
        sig_id2, count2, tripped2 = self.engine.record_failure_and_evaluate("HARDCODED_HEX", diff2)
        self.assertEqual(sig_id1, sig_id2)
        self.assertEqual(count2, 2)
        self.assertTrue(tripped2, "N=2 must trip distillation engine")

        # Synthesize in-station jig
        ok, msg, details = self.engine.synthesize_jig_for_signature(sig_id1)
        self.assertTrue(ok, f"Synthesis should succeed: {msg}")
        self.assertIn("AUTO_ADMITTED", details["status"])


if __name__ == "__main__":
    unittest.main()
