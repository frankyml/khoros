#!/usr/bin/env python3
"""
Unit tests for Khoros v3.1 Phase 3:
- 4-Tier Context Allocation math & Static Prefix Preamble
- Working Memory Compactor: Mask, Fold, Prune
- Dual-Watermark Context Pressure Controller
- Pareto Rule Cap (K <= 12) & Semantic Merging
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Add .harness to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / ".harness"))

from capsules.compactor import (
    ContextPressureController,
    fold_long_output,
    mask_compiler_trace,
    prune_speculative_trajectory,
)
from capsules.loader import AgentCapsule


class TestPhase3ContextAllocation(unittest.TestCase):
    def test_token_allocations_64k(self):
        capsule = AgentCapsule(
            capsule_id="test-capsule",
            version="3.1.0",
            charter={"role": "Mobile Engineer", "goal": "Deliver fluid UI"},
        )
        alloc = capsule.calculate_token_allocations(64000)
        self.assertEqual(alloc["system_charter_tokens"], 9600)      # 15%
        self.assertEqual(alloc["tool_schema_tokens"], 9600)         # 15%
        self.assertEqual(alloc["distilled_memory_tokens"], 9600)    # 15%
        self.assertEqual(alloc["working_scratchpad_tokens"], 22400) # 35%
        self.assertEqual(alloc["generation_headroom_tokens"], 12800)# 20%
        self.assertEqual(sum(alloc.values()), 64000)

    def test_static_prefix_preamble_building(self):
        capsule = AgentCapsule(
            capsule_id="test-capsule",
            version="3.1.0",
            charter={
                "role": "Staff Systems Architect",
                "goal": "Enforce clean boundaries",
                "escalation_conditions": ["Cross-domain boundary violation"],
            },
            capabilities={"skills": ["a11y-debugging"], "jigs": ["no-raw-hex"]},
            rules_and_invariants={
                "pareto_budget_cap": 12,
                "hard_constraints": [
                    {"id": "INV-01", "rule": "No raw hex colors outside tokens", "enforcement": "AST_LINTER"}
                ],
            },
        )
        preamble = capsule.build_static_prefix_preamble()
        self.assertIn("SYSTEM CHARTER: Staff Systems Architect", preamble)
        self.assertIn("Active Skills: a11y-debugging", preamble)
        self.assertIn("INV-01", preamble)
        self.assertIn("Cross-domain boundary violation", preamble)


class TestPhase3ParetoBudget(unittest.TestCase):
    def test_pareto_cap_enforcement_and_semantic_merge(self):
        capsule = AgentCapsule(
            capsule_id="test-capsule",
            version="3.1.0",
            charter={"role": "Engineer", "goal": "Build robust code"},
            rules_and_invariants={"pareto_budget_cap": 2, "hard_constraints": []},
        )

        # Add Rule 1
        ok, msg = capsule.add_rule("R1", "Never use raw hex colors in UI")
        self.assertTrue(ok)
        self.assertEqual(len(capsule.get_hard_constraints()), 1)

        # Add Rule 2
        ok, msg = capsule.add_rule("R2", "Ensure all touch targets measure at least 48dp")
        self.assertTrue(ok)
        self.assertEqual(len(capsule.get_hard_constraints()), 2)

        # Semantic Merge attempt: adding nearly identical rule to R1
        overlapping_rule = "Never use raw hex colors in UI components"
        ok_merge, msg_merge = capsule.add_rule("R3", overlapping_rule)
        self.assertTrue(ok_merge, "Should merge overlapping rule")
        self.assertIn("Merged", msg_merge)
        self.assertEqual(len(capsule.get_hard_constraints()), 2, "Cap must remain at 2 after merge")

        # Exceed cap without auto-subsume
        ok_exceed, msg_exceed = capsule.add_rule("R4", "Always sanitize SQL queries with parameters")
        self.assertFalse(ok_exceed, "Should block rule beyond cap")
        self.assertIn("Pareto Rule Budget exceeded", msg_exceed)

        # Auto-subsume evicts oldest
        ok_subsume, msg_subsume = capsule.add_rule("R4", "Always sanitize SQL queries with parameters", auto_subsume=True)
        self.assertTrue(ok_subsume)
        self.assertIn("Evicted", msg_subsume)
        self.assertEqual(len(capsule.get_hard_constraints()), 2)
        rule_ids = [r["id"] for r in capsule.get_hard_constraints()]
        self.assertNotIn("R1", rule_ids, "R1 should have been evicted")
        self.assertIn("R4", rule_ids, "R4 should be admitted")


class TestPhase3Compactor(unittest.TestCase):
    def test_mask_compiler_trace(self):
        raw_error = "\n".join([f"warning: unused variable var_{i}" for i in range(100)])
        raw_error += "\nsrc/core/Session.kt:42: error: Unresolved reference 'ColorPrimary'\n"
        raw_error += "\n".join([f"info: processing step {i}" for i in range(50)])

        masked = mask_compiler_trace(raw_error, tool_name="kotlinc")
        self.assertIn("COMPILER_MASK: kotlinc", masked)
        self.assertIn("Unresolved reference 'ColorPrimary'", masked)
        self.assertLess(len(masked), 250, "Masked trace should be dramatically compressed")

    def test_fold_long_output(self):
        long_output = "Line item trace data\n" * 100  # ~2100 chars
        with tempfile.TemporaryDirectory() as tmp_dir:
            folded = fold_long_output(long_output, max_chars=400, log_dir=Path(tmp_dir), label="test_output")
            self.assertIn("FOLDED_OUTPUT: test_output", folded)
            self.assertIn("Head", folded)
            self.assertIn("Tail", folded)
            self.assertIn("folded to", folded)
            self.assertLess(len(folded), 700)

    def test_prune_speculative_trajectory(self):
        history = [
            {"turn": 1, "status": "VERIFIED", "content": "Initial code"},
            {"turn": 2, "status": "ROLLED_BACK", "content": "Speculative failed diff"},
            {"turn": 3, "status": "VERIFIED", "content": "Final working code"},
        ]
        pruned = prune_speculative_trajectory(history)
        self.assertEqual(len(pruned), 2)
        self.assertEqual(pruned[0]["turn"], 1)
        self.assertEqual(pruned[1]["turn"], 3)

    def test_context_pressure_controller(self):
        controller = ContextPressureController(high_watermark=0.85, low_watermark=0.60)

        # 50% capacity -> Normal pressure
        tripped, ratio, msg = controller.evaluate(50000, 100000)
        self.assertFalse(tripped)
        self.assertIn("NORMAL_PRESSURE", msg)

        # 90% capacity -> High pressure trips compaction
        tripped, ratio, msg = controller.evaluate(90000, 100000)
        self.assertTrue(tripped)
        self.assertIn("HIGH_PRESSURE", msg)

        # 70% capacity -> Stays under pressure until drops below 60%
        tripped, ratio, msg = controller.evaluate(70000, 100000)
        self.assertTrue(tripped)

        # 55% capacity -> Resets to normal
        tripped, ratio, msg = controller.evaluate(55000, 100000)
        self.assertFalse(tripped)


if __name__ == "__main__":
    unittest.main()
