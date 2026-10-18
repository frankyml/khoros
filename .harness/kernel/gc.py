#!/usr/bin/env python3
"""
Khoros v3.1 Generational Garbage Collection & Safe Eviction Engine
Implements:
1. Station 4 Micro-GC: Rapid cleanup (<2ms) of Gen-0 ephemeral scratch scripts,
   worktree teardown, and CAS file lease release upon TASK_MERGED.
2. Macro-GC: Sprint boundary hygiene with EWMA utility decay scoring,
   differential dead-tool elimination, and 3-Phase Safe Eviction:
   Active -> Soft Deprecated -> Cold Storage Archive -> Permanent Purge.
3. Capability Restoration from archive.
"""

import os
import shutil
import tarfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blackboard import Blackboard


class GenerationalGC:
    DEFAULT_DECAY_THRESHOLD = 0.15
    DEFAULT_ARCHIVE_INACTIVE_DAYS = 14

    def __init__(self, bb: Optional[Blackboard] = None, root_dir: Optional[Path] = None):
        self.bb = bb or Blackboard()
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()
        self.archive_dir = self.root_dir / ".harness" / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def run_micro_gc(self, task_id: str, worktree_dir: Optional[Path] = None) -> Dict[str, Any]:
        """
        Station 4 Micro-GC: Executed immediately upon task merge or abort.
        Decommissions worktree, purges Gen-0 ephemeral files, and releases CAS file leases.
        """
        start_time = time.time()
        purged_files = 0
        wt_removed = False

        # 1. Release file leases
        with self.bb._get_connection() as conn:
            cur = conn.execute("DELETE FROM file_leases WHERE task_id = ?;", (task_id,))
            leases_released = cur.rowcount

        # 2. Decommission private worktree if present
        wt_path = worktree_dir or (self.root_dir / ".harness" / "worktrees" / f"wt-{task_id}")
        if wt_path and wt_path.exists():
            try:
                shutil.rmtree(wt_path, ignore_errors=True)
                wt_removed = True
            except Exception:
                pass

        # 3. Clean up unpromoted Gen-0 ephemeral scratch scripts
        scratch_dir = self.root_dir / ".harness" / "worktrees" / "scratch"
        if scratch_dir.exists():
            for f in scratch_dir.glob(f"*{task_id}*"):
                try:
                    f.unlink()
                    purged_files += 1
                except Exception:
                    pass

        elapsed_ms = (time.time() - start_time) * 1000.0
        return {
            "task_id": task_id,
            "leases_released": leases_released,
            "worktree_removed": wt_removed,
            "ephemeral_files_purged": purged_files,
            "elapsed_ms": round(elapsed_ms, 2),
        }

    def run_macro_gc(
        self,
        dry_run: bool = False,
        decay_threshold: float = DEFAULT_DECAY_THRESHOLD,
        archive_days: int = DEFAULT_ARCHIVE_INACTIVE_DAYS,
    ) -> Dict[str, Any]:
        """
        Macro-GC: Evaluates capability utility decay across all active capabilities.
        Executes 3-phase safe eviction:
        - Active -> Soft Deprecated (low utility score Ut < threshold)
        - Soft Deprecated -> Cold Storage Archive (inactive > archive_days)
        """
        now = time.time()
        cutoff_sec = archive_days * 86400.0
        caps = self.bb.list_capabilities(status=None)

        soft_deprecated = []
        cold_archived = []
        retained = []

        for c in caps:
            cap_id = c["capability_id"]
            status = c["status"]
            gen = c.get("generation", 1)
            u_score = c.get("utility_score", 1.0)
            last_invoked = c.get("last_invoked_at", now)
            file_path = Path(c["file_path"])

            # Canonical (Gen 2) capabilities are pinned and protected from auto-eviction
            if gen == 2:
                retained.append(cap_id)
                continue

            # Phase 1 -> Phase 2: Active to Soft Deprecated
            if status == "ACTIVE" and u_score < decay_threshold:
                if not dry_run:
                    with self.bb._get_connection() as conn:
                        conn.execute(
                            "UPDATE capability_registry SET status = 'SOFT_DEPRECATED', updated_at = ? WHERE capability_id = ?;",
                            (now, cap_id),
                        )
                soft_deprecated.append(cap_id)

            # Phase 2 -> Phase 3: Soft Deprecated to Cold Storage Archive
            elif status == "SOFT_DEPRECATED" and (now - last_invoked) >= cutoff_sec:
                if not dry_run:
                    # Archive file
                    if file_path.exists():
                        archive_tar = self.archive_dir / f"{cap_id.replace(':', '_')}.tar.gz"
                        with tarfile.open(archive_tar, "w:gz") as tar:
                            tar.add(file_path, arcname=file_path.name)
                        if file_path.is_file():
                            file_path.unlink()
                        elif file_path.is_dir():
                            shutil.rmtree(file_path)

                    with self.bb._get_connection() as conn:
                        conn.execute(
                            "UPDATE capability_registry SET status = 'COLD_ARCHIVE', updated_at = ? WHERE capability_id = ?;",
                            (now, cap_id),
                        )
                cold_archived.append(cap_id)
            else:
                retained.append(cap_id)

        return {
            "dry_run": dry_run,
            "soft_deprecated": soft_deprecated,
            "cold_archived": cold_archived,
            "retained": retained,
        }

    def restore_capability(self, capability_id: str) -> Tuple[bool, str]:
        """Restores a cold-archived capability back to ACTIVE status."""
        cap = self.bb.get_capability(capability_id)
        if not cap:
            return False, f"Capability '{capability_id}' not found."

        archive_tar = self.archive_dir / f"{capability_id.replace(':', '_')}.tar.gz"
        target_path = Path(cap["file_path"])

        if archive_tar.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive_tar, "r:gz") as tar:
                tar.extractall(path=target_path.parent)
            archive_tar.unlink()

        now = time.time()
        with self.bb._get_connection() as conn:
            conn.execute(
                "UPDATE capability_registry SET status = 'ACTIVE', updated_at = ? WHERE capability_id = ?;",
                (now, capability_id),
            )
            conn.execute(
                "UPDATE capability_telemetry SET utility_score = 1.0, last_invoked_at = ? WHERE capability_id = ?;",
                (now, capability_id),
            )
        return True, f"Capability '{capability_id}' successfully restored to ACTIVE."

    def purge_archived(self, confirm: bool = False) -> int:
        """Permanent purge: Deletes archived artifacts from disk. Requires confirm=True."""
        if not confirm:
            return 0
        purged_count = 0
        for tar_file in self.archive_dir.glob("*.tar.gz"):
            tar_file.unlink()
            purged_count += 1
        with self.bb._get_connection() as conn:
            conn.execute("UPDATE capability_registry SET status = 'PURGED' WHERE status = 'COLD_ARCHIVE';")
        return purged_count


def run_micro_gc(task_id: str, worktree_dir: Optional[Path] = None, bb: Optional[Blackboard] = None) -> Dict[str, Any]:
    gc = GenerationalGC(bb=bb)
    return gc.run_micro_gc(task_id, worktree_dir=worktree_dir)


def run_macro_gc(bb: Optional[Blackboard] = None, dry_run: bool = False) -> Dict[str, Any]:
    gc = GenerationalGC(bb=bb)
    return gc.run_macro_gc(dry_run=dry_run)
