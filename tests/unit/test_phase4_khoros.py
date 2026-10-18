#!/usr/bin/env python3
"""
Unit tests for Khoros v3.1 Phase 4:
- Skill Lifecycle Engine & 10-Operator Evolutionary Grammar
- Skill Trajectory Mining from completed tasks
- Station 4 Micro-GC (rapid teardown of ephemeral state)
- Macro-GC with EWMA utility decay and 3-Phase Safe Eviction
- Capability Restoration from Cold Storage
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add .harness to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / ".harness"))

from blackboard import Blackboard
from kernel.gc import GenerationalGC, run_macro_gc, run_micro_gc
from skills.lifecycle import SkillLifecycleEngine


class TestPhase4SkillLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.skills_dir = Path(self.temp_dir.name) / "skills"
        self.engine = SkillLifecycleEngine(skills_dir=self.skills_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_op_add_and_refine(self):
        # 1. Add skill
        ok, msg, p = self.engine.op_add(
            slug="kmp-compose-a11y",
            title="Compose A11y Guidelines",
            description="Enforces 48dp touch targets and content descriptions.",
            procedural_steps=[
                "Inspect clickable modifier",
                "Ensure minimum interactive component size >= 48.dp",
            ],
        )
        self.assertTrue(ok)
        self.assertTrue((p / "SKILL.md").exists())
        content = (p / "SKILL.md").read_text()
        self.assertIn("Compose A11y Guidelines", content)

        # 2. Refine skill
        ok_ref, msg_ref = self.engine.op_refine(
            slug="kmp-compose-a11y",
            additional_exemplar="- Modifier.clickable { ... }\n+ Modifier.requiredSizeIn(min=48.dp).clickable { ... }",
            amended_guideline="Always wrap custom button icons in Box with minimum touch boundary.",
        )
        self.assertTrue(ok_ref)
        content_refined = (p / "SKILL.md").read_text()
        self.assertIn("Negative Constraint Exemplar", content_refined)
        self.assertIn("Amended Rule", content_refined)

    def test_op_merge(self):
        # Add Skill A and Skill B
        self.engine.op_add("layout-fix", "Layout Fix", "Fix layout bugs", ["Step 1"])
        self.engine.op_add("responsive-layout", "Responsive Layout", "Build responsive layout", ["Step 2"])

        # Merge them
        ok, msg, merged_dir = self.engine.op_merge("layout-fix", "responsive-layout", "unified-layout")
        self.assertTrue(ok)
        self.assertTrue((merged_dir / "SKILL.md").exists())
        content = (merged_dir / "SKILL.md").read_text()
        self.assertIn("Unified Skill: layout-fix + responsive-layout", content)

    def test_op_prune_to_archive(self):
        self.engine.op_add("deprecated-skill", "Deprecated", "Old skill", ["Step 1"])
        self.assertTrue((self.skills_dir / "deprecated-skill").exists())

        ok, msg, archive_tar = self.engine.op_prune_to_archive("deprecated-skill")
        self.assertTrue(ok)
        self.assertFalse((self.skills_dir / "deprecated-skill").exists())
        self.assertTrue(archive_tar.exists())

    def test_mine_skill_from_task(self):
        events = [
            {"event_type": "TASK_DISPATCHED", "payload_json": json.dumps({"summary": "Task claimed by @builder"})},
            {"event_type": "POKA_YOKE_CHECK", "payload_json": json.dumps({"summary": "Design tokens verified"})},
            {"event_type": "TASK_SUBMITTED", "payload_json": json.dumps({"summary": "Submitted for audit"})},
        ]
        ok, msg, p = self.engine.mine_skill_from_task(
            task_id="task-042",
            slug="mined-token-workflow",
            task_title="Token Normalization Walkthrough",
            events=events,
            diff_summary="- Color(0x123456)\n+ Theme.colors.primary",
        )
        self.assertTrue(ok)
        content = (p / "SKILL.md").read_text()
        self.assertIn("Token Normalization Walkthrough", content)
        self.assertIn("POKA_YOKE_CHECK", content)


class TestPhase4GenerationalGC(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.harness_dir = self.root_dir / ".harness"
        self.harness_dir.mkdir(parents=True)
        self.db_path = self.harness_dir / "blackboard.db"
        self.bb = Blackboard(db_path=self.db_path)
        self.gc = GenerationalGC(bb=self.bb, root_dir=self.root_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_micro_gc_releases_leases_and_sweeps_worktree(self):
        # Create dummy worktree and file lease
        wt_dir = self.harness_dir / "worktrees" / "wt-task-test"
        wt_dir.mkdir(parents=True)
        (wt_dir / "dummy.txt").write_text("scratch")

        # Lease in db
        with self.bb._get_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO tasks (id, title, status, created_at, updated_at) VALUES ('task-test', 'Test', 'CLAIMED', 0, 0);")
            conn.execute("INSERT INTO file_leases (file_path, task_id, holder_capsule, lease_expires_at, fencing_token) VALUES ('src/File.kt', 'task-test', '@builder', 9999999999, 1);")

        res = self.gc.run_micro_gc("task-test", worktree_dir=wt_dir)
        self.assertEqual(res["task_id"], "task-test")
        self.assertEqual(res["leases_released"], 1)
        self.assertTrue(res["worktree_removed"])
        self.assertFalse(wt_dir.exists())

    def test_macro_gc_and_safe_eviction_lifecycle(self):
        # Register dummy capability with low utility score
        dummy_tool = self.harness_dir / "jigs" / "dummy_decayed_jig.py"
        dummy_tool.parent.mkdir(parents=True, exist_ok=True)
        dummy_tool.write_text("def check(): pass")

        self.bb.register_capability(
            capability_id="jig:dummy_decayed",
            cap_type="JIG",
            file_path=str(dummy_tool),
            content_hash="abc",
            semantic_description="Decayed tool test",
            risk_tier=1,
            generation=1,
            status="ACTIVE",
        )

        # Decay utility score below 0.15
        with self.bb._get_connection() as conn:
            conn.execute(
                "UPDATE capability_telemetry SET utility_score = 0.05, last_invoked_at = ? WHERE capability_id = 'jig:dummy_decayed';",
                (time.time() - 20 * 86400,), # 20 days ago
            )

        # 1. Run Macro-GC: moves ACTIVE -> SOFT_DEPRECATED
        res1 = self.gc.run_macro_gc(decay_threshold=0.15)
        self.assertIn("jig:dummy_decayed", res1["soft_deprecated"])
        cap1 = self.bb.get_capability("jig:dummy_decayed")
        self.assertEqual(cap1["status"], "SOFT_DEPRECATED")

        # 2. Run Macro-GC again: moves SOFT_DEPRECATED -> COLD_ARCHIVE
        res2 = self.gc.run_macro_gc(archive_days=14)
        self.assertIn("jig:dummy_decayed", res2["cold_archived"])
        cap2 = self.bb.get_capability("jig:dummy_decayed")
        self.assertEqual(cap2["status"], "COLD_ARCHIVE")
        self.assertFalse(dummy_tool.exists(), "File should be archived")

        # 3. Test Restoration
        ok_res, msg_res = self.gc.restore_capability("jig:dummy_decayed")
        self.assertTrue(ok_res)
        cap_restored = self.bb.get_capability("jig:dummy_decayed")
        self.assertEqual(cap_restored["status"], "ACTIVE")
        self.assertTrue(dummy_tool.exists(), "Restored file should be re-extracted")


if __name__ == "__main__":
    import json
    unittest.main()
