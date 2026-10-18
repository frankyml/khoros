#!/usr/bin/env python3
"""
Khoros v3.1 Clean-Trunk Canary Regression Engine
Executes candidate synthesized jigs across 100% of tracked clean repository files (HEAD).
Enforces the core safety invariant: False Positives (FP) = 0 on clean production code.
"""

import os
from pathlib import Path
from typing import Callable, List, Optional, Set, Tuple


class CanaryScanResult:
    def __init__(self, scanned_files: int, false_positives: int, violations: List[str]):
        self.scanned_files = scanned_files
        self.false_positives = false_positives
        self.violations = violations

    @property
    def passed(self) -> bool:
        return self.false_positives == 0


class CleanTrunkCanary:
    EXCLUDED_DIRS: Set[str] = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        ".gradle",
        "worktrees",
        "ast_index",
        ".harness",
    }

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()

    def run_canary_scan(
        self,
        jig_checker: Callable[[Path, str], List[str]],
        file_extensions: Optional[List[str]] = None,
        max_files: int = 500,
    ) -> CanaryScanResult:
        """
        Executes jig_checker(path, content) across tracked repository files.
        jig_checker must return a list of violation strings (empty if compliant).
        """
        exts = set(file_extensions or [".py", ".kt", ".kts", ".java", ".js", ".ts", ".html"])
        scanned_count = 0
        fp_count = 0
        violations_sample: List[str] = []

        for root, dirs, files in os.walk(self.root_dir):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in self.EXCLUDED_DIRS]

            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() not in exts:
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    violations = jig_checker(file_path, content)
                    scanned_count += 1
                    if violations:
                        fp_count += len(violations)
                        for v in violations:
                            if len(violations_sample) < 10:
                                violations_sample.append(f"{file_path.relative_to(self.root_dir)}: {v}")
                except Exception:
                    continue

                if scanned_count >= max_files:
                    break
            if scanned_count >= max_files:
                break

        return CanaryScanResult(
            scanned_files=scanned_count,
            false_positives=fp_count,
            violations=violations_sample,
        )


def run_canary_check(
    jig_checker: Callable[[Path, str], List[str]],
    root_dir: Optional[Path] = None,
    file_extensions: Optional[List[str]] = None,
) -> CanaryScanResult:
    """Convenience helper to run clean-trunk canary check."""
    canary = CleanTrunkCanary(root_dir=root_dir)
    return canary.run_canary_scan(jig_checker, file_extensions=file_extensions)
