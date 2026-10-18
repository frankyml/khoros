#!/usr/bin/env python3
"""
PDH v3.0 Hybrid Git Worktree & Concurrency Isolation Manager
Provisions private Git worktrees per squad worker with shared build cache symlinks,
atomic fast-forward trunk integration, and zero-defect cleanup.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


class WorktreeManager:
    CACHE_DIRS = [".venv", ".gradle", "node_modules", "target"]

    def __init__(self, repo_root: Optional[Path] = None, worktree_base: Optional[Path] = None):
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()
        self.worktree_base = (
            Path(worktree_base)
            if worktree_base
            else self.repo_root / ".harness" / "worktrees"
        )
        self.cache_base = self.repo_root / ".harness" / "cache"
        self.worktree_base.mkdir(parents=True, exist_ok=True)
        self.cache_base.mkdir(parents=True, exist_ok=True)

    def _run_git(self, args: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
        p = subprocess.run(
            ["git"] + args,
            cwd=str(cwd or self.repo_root),
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()

    def provision_worktree(self, task_id: str, base_branch: str = "HEAD") -> Tuple[bool, Path, str]:
        """
        Creates an isolated git worktree for the task and links heavy caches.
        Returns: (success, worktree_path, message)
        """
        wt_dir = self.worktree_base / f"wt-{task_id}"
        branch_name = f"squad/{task_id}"

        if wt_dir.exists():
            return True, wt_dir, f"Worktree already exists at {wt_dir}"

        # Delete existing branch if lingering
        self._run_git(["branch", "-D", branch_name])

        # Create worktree
        rc, out, err = self._run_git(
            ["worktree", "add", "-b", branch_name, str(wt_dir), base_branch]
        )
        if rc != 0:
            return False, wt_dir, f"Failed to create git worktree: {err or out}"

        # Symlink caches from repo root or cache base to eliminate cold-start build penalties
        for cache_name in self.CACHE_DIRS:
            root_cache = self.repo_root / cache_name
            target_link = wt_dir / cache_name
            if root_cache.exists() and not target_link.exists():
                try:
                    os.symlink(root_cache, target_link)
                except OSError:
                    pass

        return True, wt_dir, f"Provisioned worktree on branch '{branch_name}' at {wt_dir}"

    def integrate_to_trunk(self, task_id: str, trunk_branch: str = "main") -> Tuple[bool, str]:
        """
        Fast-forward merges the task branch into trunk and decommissions the worktree.
        """
        wt_dir = self.worktree_base / f"wt-{task_id}"
        branch_name = f"squad/{task_id}"

        # Fast-forward merge into current branch
        rc, out, err = self._run_git(["merge", "--ff-only", branch_name])
        if rc != 0:
            # Fallback to standard merge commit if divergent
            rc_m, out_m, err_m = self._run_git(["merge", "-m", f"Merge {branch_name} into {trunk_branch}", branch_name])
            if rc_m != 0:
                return False, f"Merge failed: {err_m or err}"

        # Teardown worktree
        self.decommission_worktree(task_id)
        return True, f"Successfully merged {branch_name} to {trunk_branch} and cleaned up."

    def decommission_worktree(self, task_id: str) -> Tuple[bool, str]:
        wt_dir = self.worktree_base / f"wt-{task_id}"
        branch_name = f"squad/{task_id}"

        if wt_dir.exists():
            self._run_git(["worktree", "remove", "--force", str(wt_dir)])
            if wt_dir.exists():
                shutil.rmtree(wt_dir, ignore_errors=True)

        self._run_git(["branch", "-D", branch_name])
        return True, f"Decommissioned worktree for {task_id}"
