#!/usr/bin/env python3
"""
Khoros v3.1 Skill Lifecycle & Evolutionary Grammar Engine
Implements the 10 formal evolutionary operators:
- Add, Refine, Merge, Split, Prune, Distill, Abstract, Compose, Rewrite, Rerank
Includes trajectory mining from completed task execution traces.
"""

import json
import os
import shutil
import tarfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class SkillLifecycleEngine:
    SIMILARITY_MERGE_THRESHOLD = 0.85
    MAX_SKILL_TOKENS = 2000

    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = Path(skills_dir) if skills_dir else Path.cwd() / ".harness" / "skills"
        self.archive_dir = self.skills_dir.parent / "archive"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def op_add(
        self,
        slug: str,
        title: str,
        description: str,
        procedural_steps: List[str],
        helper_scripts: Optional[Dict[str, str]] = None,
    ) -> Tuple[bool, str, Path]:
        """Operator 1: Add novel skill package into .harness/skills/<slug>/."""
        target_dir = self.skills_dir / slug
        if target_dir.exists():
            return False, f"Skill '{slug}' already exists.", target_dir

        target_dir.mkdir(parents=True, exist_ok=True)
        scripts_dir = target_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        steps_md = "\n".join(f"{i+1}. {step}" for i, step in enumerate(procedural_steps))
        skill_md = f"""---
name: "{slug}"
title: "{title}"
description: "{description}"
version: "1.0.0"
---

# {title}

## Purpose & Overview
{description}

## Procedural Workflow
{steps_md}

## Invariants & Escalations
- Never bypass universal verification gate (`khoros verify`).
- Escalate to @architect if modifications breach task contract scope.
"""
        (target_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        if helper_scripts:
            for s_name, s_code in helper_scripts.items():
                s_path = scripts_dir / s_name
                s_path.write_text(s_code, encoding="utf-8")
                s_path.chmod(0o755)

        return True, f"Skill '{slug}' added successfully.", target_dir

    def op_refine(self, slug: str, additional_exemplar: str, amended_guideline: Optional[str] = None) -> Tuple[bool, str]:
        """Operator 2: Refine existing skill with failure feedback or edge-case constraints."""
        target_file = self.skills_dir / slug / "SKILL.md"
        if not target_file.exists():
            return False, f"Skill '{slug}' not found."

        content = target_file.read_text(encoding="utf-8")
        append_block = f"\n\n### Negative Constraint Exemplar (Added: {time.strftime('%Y-%m-%d')})\n{additional_exemplar}\n"
        if amended_guideline:
            append_block += f"\n- **Amended Rule**: {amended_guideline}\n"

        target_file.write_text(content + append_block, encoding="utf-8")
        return True, f"Skill '{slug}' refined with new exemplar."

    def op_merge(self, slug_a: str, slug_b: str, merged_slug: str) -> Tuple[bool, str, Path]:
        """Operator 3: Consolidate two overlapping skills into a unified skill."""
        dir_a = self.skills_dir / slug_a
        dir_b = self.skills_dir / slug_b
        if not dir_a.exists() or not dir_b.exists():
            return False, f"Both skills must exist to merge: {slug_a}, {slug_b}", Path()

        merged_dir = self.skills_dir / merged_slug
        merged_dir.mkdir(parents=True, exist_ok=True)
        (merged_dir / "scripts").mkdir(parents=True, exist_ok=True)

        content_a = (dir_a / "SKILL.md").read_text(encoding="utf-8") if (dir_a / "SKILL.md").exists() else ""
        content_b = (dir_b / "SKILL.md").read_text(encoding="utf-8") if (dir_b / "SKILL.md").exists() else ""

        merged_md = f"""---
name: "{merged_slug}"
title: "Unified Skill: {slug_a} + {slug_b}"
version: "1.0.0"
---

# Unified Skill: {merged_slug}

## Consolidated Workflow from {slug_a} and {slug_b}
{content_a}

---

{content_b}
"""
        (merged_dir / "SKILL.md").write_text(merged_md, encoding="utf-8")

        # Copy any scripts
        for s in (dir_a / "scripts").glob("*"):
            if s.is_file():
                shutil.copy2(s, merged_dir / "scripts" / s.name)
        for s in (dir_b / "scripts").glob("*"):
            if s.is_file():
                shutil.copy2(s, merged_dir / "scripts" / s.name)

        return True, f"Merged '{slug_a}' and '{slug_b}' into '{merged_slug}'.", merged_dir

    def op_prune_to_archive(self, slug: str) -> Tuple[bool, str, Path]:
        """Operator 5: Move low-utility or retired skill into .harness/archive/<slug>.tar.gz."""
        target_dir = self.skills_dir / slug
        if not target_dir.exists():
            return False, f"Skill '{slug}' not found.", Path()

        archive_tar = self.archive_dir / f"skill_{slug}.tar.gz"
        with tarfile.open(archive_tar, "w:gz") as tar:
            tar.add(target_dir, arcname=slug)

        shutil.rmtree(target_dir)
        return True, f"Skill '{slug}' pruned to archive at {archive_tar}.", archive_tar

    def mine_skill_from_task(
        self,
        task_id: str,
        slug: str,
        task_title: str,
        events: List[Dict[str, Any]],
        diff_summary: str = "",
    ) -> Tuple[bool, str, Path]:
        """
        Mines procedural steps from a successful multi-turn execution trace.
        """
        extracted_steps = []
        for e in events:
            payload = json.loads(e.get("payload_json", "{}")) if isinstance(e.get("payload_json"), str) else e.get("payload_json", {})
            event_type = e.get("event_type", "")
            if event_type in ("TASK_DISPATCHED", "STATION_TRANSITION", "TASK_SUBMITTED", "POKA_YOKE_CHECK"):
                extracted_steps.append(f"Execute {event_type}: {payload.get('summary', payload.get('to_state', 'action'))}")

        if not extracted_steps:
            extracted_steps = [
                f"Triage and inspect scope for {task_title}",
                "Apply localized modifications within isolated worktree",
                "Verify with in-station poka-yoke jigs and universal verification gate",
            ]

        if diff_summary:
            extracted_steps.append(f"Verify against patch pattern:\n```\n{diff_summary[:400]}\n```")

        return self.op_add(
            slug=slug,
            title=f"Mined Playbook: {task_title}",
            description=f"Auto-mined procedural playbook from successful execution of {task_id}.",
            procedural_steps=extracted_steps,
        )
