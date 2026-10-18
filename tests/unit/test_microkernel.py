#!/usr/bin/env python3
"""
Unit Tests for PDH v3.0 Microkernel Architecture & Kaizen Engine
Validates KernelEventStore, ExecutionGraph, InStationJigRunner, AgentCapsule, and Credit Attribution.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT_HARNESS_DIR = Path(__file__).resolve().parent.parent.parent / ".harness"
sys.path.insert(0, str(ROOT_HARNESS_DIR))

from kernel.event_store import KernelEventStore
from kernel.graph import ExecutionGraph, StateNode, TransitionGuard
from kernel.jigs import InStationJigRunner
from capsules.loader import AgentCapsule, CapsuleLoader
from kaizen.attribution import assign_credit_attribution


class TestMicrokernel(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.db_path = self.tmp_path / "kernel.db"
        self.event_store = KernelEventStore(db_path=self.db_path)
        self.graph = ExecutionGraph(event_store=self.event_store)
        self.jigs = InStationJigRunner(event_store=self.event_store)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_event_store_and_projections(self):
        # 1. Upsert projection
        contract = {"task_id": "T-100", "hard_constraints": [{"id": "INV-01", "rule": "No raw hex"}]}
        self.event_store.upsert_projection(
            task_id="T-100",
            status="PENDING",
            archetype="feature",
            contract=contract,
            owner="lead",
        )
        proj = self.event_store.get_projection("T-100")
        self.assertIsNotNone(proj)
        self.assertEqual(proj["status"], "PENDING")
        self.assertEqual(proj["current_epoch"], 1)

        # 2. Emit event
        ev_id = self.event_store.emit_event(
            event_type="TASK_DISPATCHED",
            task_id="T-100",
            payload={"station": "STATION_1_CAD"},
            emitted_by="lead-orchestrator",
        )
        self.assertGreater(ev_id, 0)
        events = self.event_store.get_events(task_id="T-100")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "TASK_DISPATCHED")

    def test_file_lease_fencing_and_conflicts(self):
        files = ["src/ui/Screen.kt", "src/ui/Theme.kt"]
        # Claim lease
        ok, conflicts = self.event_store.acquire_file_leases(
            files=files,
            task_id="T-101",
            holder_capsule="worker-alpha",
            fencing_token=1,
            ttl_seconds=300,
        )
        self.assertTrue(ok)
        self.assertEqual(conflicts, [])

        # Conflicting claim by another worker
        ok2, conflicts2 = self.event_store.acquire_file_leases(
            files=["src/ui/Screen.kt", "src/domain/Model.kt"],
            task_id="T-102",
            holder_capsule="worker-beta",
            fencing_token=1,
            ttl_seconds=300,
        )
        self.assertFalse(ok2)
        self.assertEqual(conflicts2, ["src/ui/Screen.kt"])

        # Release lease
        released = self.event_store.release_file_leases("T-101")
        self.assertEqual(released, 2)

        # Now worker-beta can claim
        ok3, conflicts3 = self.event_store.acquire_file_leases(
            files=["src/ui/Screen.kt"],
            task_id="T-102",
            holder_capsule="worker-beta",
            fencing_token=1,
            ttl_seconds=300,
        )
        self.assertTrue(ok3)

    def test_execution_graph_and_anti_deadlock_circuit_breaker(self):
        task_id = "T-200"
        self.event_store.upsert_projection(
            task_id=task_id,
            status="PENDING",
            archetype="feature",
            contract={"task_id": task_id},
        )

        # Transition PENDING -> STATION_1_CAD
        ok, msg, p1 = self.graph.transition(task_id, "dispatch", "lead")
        self.assertTrue(ok)
        self.assertEqual(p1["status"], "STATION_1_CAD")

        # STATION_1_CAD -> STATION_2_SUB_ASSEMBLY
        ok, _, p2 = self.graph.transition(task_id, "contract_ready", "cad-lead")
        self.assertTrue(ok)
        self.assertEqual(p2["status"], "STATION_2_SUB_ASSEMBLY")

        # STATION_2_SUB_ASSEMBLY -> STATION_3_AUDIT
        ok, _, p3 = self.graph.transition(task_id, "poka_yoke_pass", "builder")
        self.assertTrue(ok)
        self.assertEqual(p3["status"], "STATION_3_AUDIT")

        # Iteration 1: Reject -> loops back to STATION_2_SUB_ASSEMBLY (epoch 2)
        ok, _, p4 = self.graph.transition(task_id, "audit_rejected", "critic", {"reason": "missing test"})
        self.assertTrue(ok)
        self.assertEqual(p4["status"], "STATION_2_SUB_ASSEMBLY")
        self.assertEqual(p4["current_epoch"], 2)

        # Re-submit to audit
        self.graph.transition(task_id, "poka_yoke_pass", "builder")

        # Iteration 2: Reject -> loops back to STATION_2_SUB_ASSEMBLY (epoch 3)
        ok, _, p5 = self.graph.transition(task_id, "audit_rejected", "critic", {"reason": "flaky timeout"})
        self.assertTrue(ok)
        self.assertEqual(p5["status"], "STATION_2_SUB_ASSEMBLY")
        self.assertEqual(p5["current_epoch"], 3)

        # Re-submit to audit
        self.graph.transition(task_id, "poka_yoke_pass", "builder")

        # Iteration 3: Reject again -> Exceeds max 3 iterations -> Trips Circuit Breaker!
        ok, msg_deadlock, p6 = self.graph.transition(task_id, "audit_rejected", "critic", {"reason": "still failing"})
        self.assertFalse(ok)
        self.assertIn("Anti-deadlock circuit breaker tripped", msg_deadlock)

        # Task escalated to DEADLOCK_ESCALATED
        proj_final = self.event_store.get_projection(task_id)
        self.assertEqual(proj_final["status"], "DEADLOCK_ESCALATED")

    def test_in_station_poka_yoke_jigs(self):
        # 1. Broken Python syntax
        bad_python = "def broken_func(:\n    return 42"
        passed, viols = self.jigs.validate_content("src/calc.py", bad_python)
        self.assertFalse(passed)
        self.assertEqual(viols[0]["rule"], "AST_SYNTAX_ERROR")

        # 2. Hardcoded Secret
        leaked_secret = 'api_key = "synthetic_mock_credential_123456789012345678"'
        passed_s, viols_s = self.jigs.validate_content("src/config.py", leaked_secret)
        self.assertFalse(passed_s)
        self.assertEqual(viols_s[0]["rule"], "HARDCODED_API_SECRET")

        # 3. Hardcoded Hex Color in UI file
        bad_ui = "val textColor = #FF5722\nText('Hello')"
        passed_u, viols_u = self.jigs.validate_content("src/ui/Card.kt", bad_ui)
        self.assertFalse(passed_u)
        self.assertEqual(viols_u[0]["rule"], "DESIGN_TOKEN_VIOLATION")

        # 4. Clean code
        clean_code = "def calc():\n    return 42\n"
        passed_c, viols_c = self.jigs.validate_content("src/calc.py", clean_code)
        self.assertTrue(passed_c)
        self.assertEqual(len(viols_c), 0)

    def test_agent_capsule_and_pareto_rule_budget(self):
        loader = CapsuleLoader()
        capsule = loader.load_capsule("mobile-builder")
        self.assertIsNotNone(capsule)
        self.assertEqual(capsule.id, "mobile-builder")

        # 4-Tier token allocations
        alloc = capsule.calculate_token_allocations(total_context_tokens=100000)
        self.assertEqual(alloc["system_charter_tokens"], 15000)
        self.assertEqual(alloc["working_scratchpad_tokens"], 35000)
        self.assertEqual(alloc["generation_headroom_tokens"], 20000)

        # Test Pareto rule budget cap (K <= 12)
        # Mobile builder already has 1 rule (INV-01)
        for i in range(2, 13):
            ok, _ = capsule.add_rule(f"INV-{i:02d}", f"Sample rule {i}")
            self.assertTrue(ok)

        # 13th rule must exceed budget
        ok_exceeded, msg = capsule.add_rule("INV-13", "Excessive rule")
        self.assertFalse(ok_exceeded)
        self.assertIn("Pareto Rule Budget exceeded", msg)

    def test_causal_credit_attribution(self):
        # 1. Poka-yoke breach with rule declared in contract
        task_id = "T-301"
        self.event_store.upsert_projection(
            task_id=task_id,
            status="STATION_2_SUB_ASSEMBLY",
            archetype="feature",
            contract={"hard_constraints": [{"id": "DESIGN_TOKEN_VIOLATION"}]},
        )
        fail_ev = {
            "event_type": "POKA_YOKE_VIOLATION",
            "payload": {"violations": [{"rule": "DESIGN_TOKEN_VIOLATION"}]},
        }
        vec = assign_credit_attribution(self.event_store, task_id, fail_ev)
        self.assertEqual(vec["impl"], 0.85)
        self.assertEqual(vec["eval"], 0.15)

        # 2. Infrastructure Crash
        crash_ev = {"event_type": "TOOL_CRASH", "payload": {}}
        vec_crash = assign_credit_attribution(self.event_store, task_id, crash_ev)
        self.assertEqual(vec_crash["tool"], 1.0)


if __name__ == "__main__":
    unittest.main()
