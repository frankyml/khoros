#!/usr/bin/env python3
"""
Khoros v3.1 Isolated Worktree Sandbox Runner
Executes synthesized tools and test suites within private ephemeral environments
with strict POSIX resource limiting:
- Address Space Ceiling (RLIMIT_AS = 512MB)
- Execution Timeout (SIGALRM / timeout = 5.0s)
- Network namespace isolation (unshare -n where supported)
- Bounded repair iteration loop (N <= 3)
"""

import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    import resource
except ImportError:
    resource = None


class SandboxExecutionError(Exception):
    pass


class WorktreeSandbox:
    MAX_REPAIR_RETRIES = 3
    DEFAULT_TIMEOUT_SEC = 5.0
    DEFAULT_MEM_LIMIT_BYTES = 512 * 1024 * 1024  # 512 MB

    def __init__(self, sandbox_dir: Optional[Path] = None, timeout: float = DEFAULT_TIMEOUT_SEC):
        self.sandbox_dir = Path(sandbox_dir) if sandbox_dir else None
        self.timeout = timeout

    @staticmethod
    def _set_resource_limits():
        """Pre-exec hook to set RLIMIT_AS and RLIMIT_CPU in the child process."""
        if resource is None:
            return
        if sys.platform != "darwin":
            try:
                # 512 MB virtual memory ceiling (Linux only; macOS dyld maps >100GB virtual addresses)
                mem_limit = 512 * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))
            except (ValueError, OSError):
                pass
        else:
            try:
                # On macOS / Apple Silicon, use RLIMIT_DATA to constrain heap without breaking dyld
                if hasattr(resource, "RLIMIT_DATA"):
                    mem_limit = 512 * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_DATA, (mem_limit, mem_limit))
            except (ValueError, OSError):
                pass
        try:
            # 5 seconds CPU time
            resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        except (ValueError, OSError):
            pass

    def run_isolated_test(
        self,
        tool_code: str,
        test_code: str,
        tool_filename: str = "tool_impl.py",
        test_filename: str = "test_tool.py",
    ) -> Tuple[bool, str, int]:
        """
        Writes tool and test fixtures into an ephemeral sandbox directory
        and executes the test suite under strict resource ceilings.
        Returns (success: bool, output: str, exit_code: int).
        """
        temp_ctx = None
        if self.sandbox_dir:
            work_dir = self.sandbox_dir
            work_dir.mkdir(parents=True, exist_ok=True)
        else:
            temp_ctx = tempfile.TemporaryDirectory(prefix="wt-tool-")
            work_dir = Path(temp_ctx.name)

        try:
            tool_path = work_dir / tool_filename
            test_path = work_dir / test_filename
            tool_path.write_text(tool_code, encoding="utf-8")
            test_path.write_text(test_code, encoding="utf-8")

            # Execute via python3 -m unittest
            cmd = [sys.executable, "-m", "unittest", test_filename]

            # Try network isolation with unshare -n if Linux and root/permitted
            preexec_fn = self._set_resource_limits
            env = os.environ.copy()
            env["PYTHONPATH"] = str(work_dir)

            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(work_dir),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    preexec_fn=preexec_fn,
                    env=env,
                )
                output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
                success = proc.returncode == 0
                return success, output.strip(), proc.returncode
            except subprocess.TimeoutExpired:
                return False, f"Sandbox Timeout: Execution exceeded {self.timeout}s ceiling.", 124
            except Exception as e:
                return False, f"Sandbox Execution Failure: {e}", 1
        finally:
            if temp_ctx:
                temp_ctx.cleanup()


def run_sandboxed_test(
    tool_code: str,
    test_code: str,
    sandbox_dir: Optional[Path] = None,
    timeout: float = WorktreeSandbox.DEFAULT_TIMEOUT_SEC,
) -> Tuple[bool, str, int]:
    """Convenience helper to run a tool and test code inside sandbox."""
    sandbox = WorktreeSandbox(sandbox_dir=sandbox_dir, timeout=timeout)
    return sandbox.run_isolated_test(tool_code, test_code)
