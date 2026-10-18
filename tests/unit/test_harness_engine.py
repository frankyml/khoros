#!/usr/bin/env python3
"""
Unit & Integration Tests for the Personal Development Harness (PDH v2.0) Engine
"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT_HARNESS_DIR = Path(__file__).resolve().parent.parent.parent / ".harness"
sys.path.insert(0, str(ROOT_HARNESS_DIR))

from blackboard import Blackboard
from dispatcher import LeadRouter, TaskDispatcher
from governor import PriorityTier, TokenGovernor
from linter import DesignTokenLinter
from prd_engine import PRDEngine
from verifier import VerificationPipeline


class TestHarnessEngine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.db_path = self.tmp_path / "blackboard.db"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_blackboard_lifecycle_and_optional_token_submit(self):
        bb = Blackboard(db_path=self.db_path, lease_ttl_seconds=1800)
        bb.create_task("task-101", "Verify Blackboard Lifecycle", {"priority": "Q0"})
        ok, token = bb.claim_task("task-101", "worker-1")
        self.assertTrue(ok)
        self.assertEqual(token, 1)

        # Heartbeat without explicit token
        self.assertTrue(bb.heartbeat("task-101"))

        # Complete without explicit token
        self.assertTrue(bb.complete_task("task-101", result={"summary": "Done"}))
        tasks = {t["id"]: t for t in bb.list_tasks()}
        self.assertEqual(tasks["task-101"]["status"], "REVIEW_REQUESTED")

    def test_blackboard_dag_dependencies_and_task_contract(self):
        bb = Blackboard(db_path=self.db_path, lease_ttl_seconds=1800)
        bb.create_task(
            "task-arch",
            "Design RFC Architecture",
            payload={"priority": "Q1", "scope_files": ["docs/rfc/arch.md"]},
            task_type="spec",
        )
        bb.create_task(
            "task-impl",
            "Implement Core Engine",
            payload={
                "priority": "Q2",
                "scope_files": ["src/engine.py"],
                "acceptance_criteria": ["Pass unit tests", "Zero lint errors"],
            },
            task_type="feature",
            depends_on=["task-arch"],
        )

        # Cannot claim task-impl while task-arch is PENDING
        met, unmet = bb.are_dependencies_met("task-impl")
        self.assertFalse(met)
        self.assertEqual(unmet, ["task-arch"])
        ok, _ = bb.claim_task("task-impl", "worker-impl")
        self.assertFalse(ok)

        # Dispatcher skips blocked task-impl and dispatches task-arch instead
        dispatcher = TaskDispatcher(db_path=self.db_path)
        dispatched_ok, msg = dispatcher.dispatch_next()
        self.assertTrue(dispatched_ok)
        self.assertIn("task-arch", msg)

        # Complete and approve task-arch
        bb.complete_task("task-arch", result={"summary": "RFC approved"})
        with bb._get_connection() as conn:
            conn.execute("UPDATE tasks SET status = 'COMPLETED', updated_at = ? WHERE id = 'task-arch';", (time.time(),))

        # Now task-impl dependencies are met and contract includes prerequisite outputs
        met_after, unmet_after = bb.are_dependencies_met("task-impl")
        self.assertTrue(met_after)
        self.assertEqual(unmet_after, [])

        contract = bb.get_task_contract("task-impl")
        self.assertEqual(contract["task_type"], "feature")
        self.assertIn("task-arch", contract["dependency_outputs"])
        self.assertEqual(contract["dependency_outputs"]["task-arch"]["summary"], "RFC approved")

        packet = dispatcher.generate_subagent_packet("task-impl", role="@builder")
        self.assertIn("src/engine.py", packet)
        self.assertIn("RFC approved", packet)

    def test_lead_router_player_coach_triage(self):
        router = LeadRouter()

        # T0 Micro task
        t0 = router.triage("Fix typo in README", scope_files=["README.md"])
        self.assertEqual(t0["tier"], "T0_MICRO")
        self.assertEqual(t0["execution_mode"], "DIRECT_FAST_PATH")

        # T2 Research task
        t_res = router.triage("Analyse the state of the art for coding agent harnesses and compare architectures")
        self.assertEqual(t_res["task_type"], "research")
        self.assertEqual(t_res["recommended_spec"], "brief")
        self.assertIn("@explorer", t_res["recommended_roles"])

        # T2/T3 Architecture refactor
        t_arch = router.triage(
            "Iterate architecture of multi-agent orchestrator across all engine modules",
            scope_files=["a.py", "b.py", "c.py", "d.py"],
        )
        self.assertIn(t_arch["tier"], ("T2_ORCHESTRATED", "T3_PARALLEL_DAG"))
        self.assertEqual(t_arch["execution_mode"], "SUBAGENT_FAN_OUT")
        self.assertEqual(t_arch["workspace_isolation"], "share")

    def test_governor_sqlite_persistence(self):
        gov1 = TokenGovernor(db_path=self.db_path)
        gov1.record_usage(PriorityTier.Q1_REASONING, input_tokens=40000, cached_tokens=36000, output_tokens=2000)

        # Instantiate a second TokenGovernor pointing to the same SQLite DB
        gov2 = TokenGovernor(db_path=self.db_path)
        telemetry = gov2.get_telemetry()
        self.assertEqual(telemetry["current_rpm"], 1)
        self.assertEqual(telemetry["total_input_tokens"], 40000)
        self.assertEqual(telemetry["total_cached_tokens"], 36000)
        self.assertEqual(telemetry["cache_hit_rate_percent"], 90.0)

    def test_design_token_linter_precision(self):
        linter = DesignTokenLinter()

        # 1. Valid UI file with KDoc hex comment, 20.dp icon size, 56.dp height, and 16.dp/20.dp padding
        valid_ui = self.tmp_path / "SampleScreen.kt"
        valid_ui.write_text(
            """
            /**
             * Uses #161719 background in dark theme.
             */
            @Composable
            fun SampleScreen() {
                // Inline comment with #FF0000
                Box(
                    modifier = Modifier
                        .size(20.dp)
                        .height(56.dp)
                        .padding(horizontal = 20.dp, vertical = 10.dp)
                )
            }
            """,
            encoding="utf-8",
        )
        self.assertEqual(linter.lint_file(valid_ui), [])

        # 2. Invalid UI file with raw Color(0x...) and off-grid 9.dp padding
        invalid_ui = self.tmp_path / "BrokenScreen.kt"
        invalid_ui.write_text(
            """
            @Composable
            fun BrokenScreen() {
                Box(
                    modifier = Modifier
                        .background(Color(0xFFFF0000))
                        .padding(vertical = 9.dp)
                )
            }
            """,
            encoding="utf-8",
        )
        viols = linter.lint_file(invalid_ui)
        rules = [v["rule"] for v in viols]
        self.assertIn("NO_RAW_HEX_COLOR", rules)
        self.assertIn("INVALID_SPACING_SCALE", rules)

    def test_prd_and_multi_archetype_spec_engine(self):
        prd_dir = self.tmp_path / "docs" / "prd"
        flows_dir = self.tmp_path / "docs" / "flows"
        engine = PRDEngine(prd_dir=prd_dir, flows_dir=flows_dir, workspace_dir=self.tmp_path)

        # Backwards-compatible create_prd
        out_prd = engine.create_prd("test-feature", "Test Feature", "Test problem statement")
        self.assertTrue(out_prd.exists())
        text = out_prd.read_text(encoding="utf-8")
        self.assertIn("flowchart TD", text)
        self.assertIn("stateDiagram-v2", text)

        # Multi-archetype specs (rfc, rca, brief)
        for stype in ("rfc", "rca", "brief"):
            spec_path = engine.create_spec(stype, f"sample-{stype}", f"Title {stype}", "Detailed problem", profile="python")
            self.assertTrue(spec_path.exists())
            self.assertIn("```mermaid", spec_path.read_text(encoding="utf-8"))

    def test_universal_verification_pipeline(self):
        pipeline = VerificationPipeline(workspace_dir=self.tmp_path, profile="python")
        clean_py = self.tmp_path / "clean_mod.py"
        clean_py.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

        ok, report = pipeline.run(targets=[clean_py])
        self.assertTrue(ok)
        self.assertEqual(report["violation_count"], 0)

        # Secret detection test
        leaky_py = self.tmp_path / "leaky_mod.py"
        leaky_py.write_text('api_key = "synthetic_mock_credential_9876543210abcdef"\n', encoding="utf-8")
        ok2, report2 = pipeline.run(targets=[leaky_py])
        self.assertFalse(ok2)
        self.assertEqual(report2["violations"][0]["rule"], "HARDCODED_API_SECRET")


if __name__ == "__main__":
    unittest.main()
