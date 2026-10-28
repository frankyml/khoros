#!/usr/bin/env python3
"""
Unit tests for Khoros v3.1 Phase 1:
- CLI rename & backwards-compatible symlinks
- Blackboard capability/telemetry schemas and APIs
- Static AST Capability Risk Classifier
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Add .harness to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / ".harness"))

from blackboard import Blackboard
from kernel.classifier import CapabilityRiskClassifier, RiskTier, classify_capability_code
from kernel.event_store import CapabilityEventType, KernelEventStore


class TestPhase1CLI(unittest.TestCase):
    def test_khoros_binary_exists_and_runs(self):
        root = Path(__file__).resolve().parent.parent.parent
        khoros_bin = root / "bin" / "khoros"
        self.assertTrue(khoros_bin.exists(), "bin/khoros must exist")
        self.assertTrue(os.access(khoros_bin, os.X_OK), "bin/khoros must be executable")

        res = subprocess.run([str(khoros_bin), "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("khoros", res.stdout)
        self.assertIn("Khoros v4", res.stdout)

    def test_harness_symlink_points_to_khoros(self):
        root = Path(__file__).resolve().parent.parent.parent
        harness_bin = root / "bin" / "harness"
        self.assertTrue(harness_bin.exists(), "bin/harness must exist")
        self.assertTrue(harness_bin.is_symlink(), "bin/harness must be a symlink")
        self.assertEqual(os.readlink(harness_bin), "khoros")

        res = subprocess.run([str(harness_bin), "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("Khoros v4", res.stdout)


class TestPhase1Blackboard(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_blackboard.db"
        self.bb = Blackboard(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_capability_registry_and_telemetry(self):
        self.bb.register_capability(
            capability_id="jig:no_raw_hex",
            cap_type="JIG",
            file_path=".harness/kernel/jigs.py",
            content_hash="abc123hash",
            semantic_description="Detects raw hex color literals",
            risk_tier=1,
            version="1.0.0",
        )
        cap = self.bb.get_capability("jig:no_raw_hex")
        self.assertIsNotNone(cap)
        self.assertEqual(cap["type"], "JIG")
        self.assertEqual(cap["risk_tier"], 1)
        self.assertEqual(cap["utility_score"], 1.0)
        self.assertEqual(cap["invocations_total"], 0)

        # Record invocations and decay
        new_score = self.bb.record_capability_invocation("jig:no_raw_hex", success=True)
        self.assertGreaterEqual(new_score, 0.95)

        cap_updated = self.bb.get_capability("jig:no_raw_hex")
        self.assertEqual(cap_updated["invocations_total"], 1)
        self.assertEqual(cap_updated["invocations_success"], 1)

    def test_failure_signatures_rule_of_two(self):
        sig_id, count1 = self.bb.log_failure_signature(
            ast_structural_hash="sha256_ast_test_hash",
            error_type="RAW_COLOR_LITERAL",
            exemplar_diff="- Color(0xFF0000)\n+ Theme.colors.primary",
        )
        self.assertEqual(count1, 1)

        # Second occurrence trips recurrence
        sig_id_2, count2 = self.bb.log_failure_signature(
            ast_structural_hash="sha256_ast_test_hash",
            error_type="RAW_COLOR_LITERAL",
            exemplar_diff="- Color(0x00FF00)\n+ Theme.colors.secondary",
        )
        self.assertEqual(sig_id, sig_id_2)
        self.assertEqual(count2, 2)

    def test_kaizen_proposals(self):
        self.bb.create_kaizen_proposal(
            proposal_id="prop-001",
            target_type="JIG",
            slug="jig_test_check",
            source_code="def check(): pass",
            test_code="def test_check(): pass",
            risk_tier=1,
        )
        props = self.bb.list_kaizen_proposals(status="QUARANTINED")
        self.assertEqual(len(props), 1)
        self.assertEqual(props[0]["slug"], "jig_test_check")

        ok = self.bb.update_kaizen_proposal_status("prop-001", "APPROVED")
        self.assertTrue(ok)
        approved = self.bb.list_kaizen_proposals(status="APPROVED")
        self.assertEqual(len(approved), 1)


class TestPhase1Classifier(unittest.TestCase):
    def test_tier1_pure_ast_jig(self):
        code = """
import ast

class HexColorLinter(ast.NodeVisitor):
    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value.startswith("#"):
            return False
        return True
"""
        tier, reasons = classify_capability_code(code)
        self.assertEqual(tier, RiskTier.TIER_1_READONLY_JIG)
        self.assertEqual(len(reasons), 0)

    def test_tier2_worktree_file_write(self):
        code = """
from pathlib import Path

def format_tokens(file_path):
    p = Path(file_path)
    content = p.read_text()
    p.write_text(content.strip())
"""
        tier, reasons = classify_capability_code(code)
        self.assertEqual(tier, RiskTier.TIER_2_WORKTREE_UTIL)
        self.assertTrue(any("write_text" in r for r in reasons))

    def test_tier3_subprocess_shell_invocation(self):
        code = """
import subprocess

def run_git():
    subprocess.run(["git", "status"])
"""
        tier, reasons = classify_capability_code(code)
        self.assertEqual(tier, RiskTier.TIER_3_MUTATING_SHELL_NET)
        self.assertTrue(any("subprocess" in r for r in reasons))

    def test_tier3_network_socket_import(self):
        code = """
import socket

def check_port():
    s = socket.socket()
    s.connect(("127.0.0.1", 8080))
"""
        tier, reasons = classify_capability_code(code)
        self.assertEqual(tier, RiskTier.TIER_3_MUTATING_SHELL_NET)
        self.assertTrue(any("socket" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
