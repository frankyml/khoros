#!/usr/bin/env python3
"""
Khoros v3.1 Host & Environment Auto-Adaptation Engine
Dynamically probes host OS, architecture, memory, filesystem CoW,
and AI agent environment (Claude Code vs Antigravity / Gemini).

Supports:
- Linux (x86_64 / aarch64, btrfs, bwrap/namespaces)
- macOS / Darwin (Apple Silicon M-series, e.g. M5 24GB, APFS CoW, Seatbelt / POSIX isolation)
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional


class HostEnvironment:
    @staticmethod
    def detect() -> Dict[str, Any]:
        """Probes the current execution environment and returns capability profile."""
        os_name = platform.system()  # 'Linux', 'Darwin', 'Windows'
        machine = platform.machine()  # 'x86_64', 'arm64'
        cpu_cores = os.cpu_count() or 4

        # Total Physical / Unified Memory (in GB)
        mem_gb = HostEnvironment._probe_memory_gb(os_name)

        # Filesystem Copy-on-Write (CoW) capability
        is_apfs = (os_name == "Darwin")
        has_btrfs = HostEnvironment._probe_btrfs() if os_name == "Linux" else False
        cow_supported = is_apfs or has_btrfs

        # Sandboxing mechanism available
        has_bwrap = bool(shutil.which("bwrap")) if os_name == "Linux" else False
        sandbox_mode = "bwrap" if has_bwrap else ("posix_seatbelt" if os_name == "Darwin" else "posix_process")

        # Active AI Agent Runtime
        active_agent_runtime = HostEnvironment._detect_agent_runtime()

        # Recommended concurrency ceiling based on available unified memory and cores
        # MacBook Air M5 24GB: 3-4 concurrent worktree workers; 8-16GB: 2 workers
        if mem_gb >= 24 and cpu_cores >= 8:
            recommended_max_workers = 4
        elif mem_gb >= 16:
            recommended_max_workers = 3
        else:
            recommended_max_workers = 2

        # Recommended cache prefix breakpoint for prompt caching:
        # Claude (Anthropic): 1,024 tokens breakpoint
        # Gemini (Google): 32,768 tokens (or 1,024 on Flash)
        is_claude = (active_agent_runtime == "claude_code")
        cache_prefix_tokens = 1024 if is_claude else 32768

        return {
            "os": os_name,
            "machine": machine,
            "cpu_cores": cpu_cores,
            "memory_gb": mem_gb,
            "cow_supported": cow_supported,
            "filesystem_cow": "APFS" if is_apfs else ("Btrfs" if has_btrfs else "standard"),
            "sandbox_mode": sandbox_mode,
            "active_agent_runtime": active_agent_runtime,
            "recommended_max_workers": recommended_max_workers,
            "cache_prefix_tokens": cache_prefix_tokens,
            "is_apple_silicon": (os_name == "Darwin" and machine in ("arm64", "aarch64")),
            "is_linux": (os_name == "Linux"),
            "display_name": f"{os_name} {machine} ({mem_gb:.0f}GB RAM | {active_agent_runtime})",
        }

    @staticmethod
    def _probe_memory_gb(os_name: str) -> float:
        """Determines total memory in gigabytes across Linux and macOS."""
        try:
            if os_name == "Darwin":
                # sysctl hw.memsize returns bytes
                out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
                return int(out) / (1024 ** 3)
            elif os_name == "Linux":
                if Path("/proc/meminfo").exists():
                    for line in Path("/proc/meminfo").read_text().splitlines():
                        if line.startswith("MemTotal:"):
                            parts = line.split()
                            kb = int(parts[1])
                            return kb / (1024 ** 2)
        except Exception:
            pass
        return 16.0  # safe fallback estimate

    @staticmethod
    def _probe_btrfs() -> bool:
        """Checks if current filesystem is btrfs."""
        try:
            p = subprocess.run(["stat", "-f", "-c", "%T", "."], capture_output=True, text=True)
            return "btrfs" in p.stdout.lower()
        except Exception:
            return False

    @staticmethod
    def _detect_agent_runtime() -> str:
        """Identifies if executing under Claude Code, Antigravity, or terminal."""
        if os.environ.get("CLAUDE_CODE") == "1" or os.environ.get("CLAUDE_PROJECT_DIR") or Path(".claude").exists():
            return "claude_code"
        if os.environ.get("GEMINI_API_KEY") or Path("/home/frankyml/.gemini").exists():
            return "antigravity"
        return "generic_cli"


def get_host_environment() -> Dict[str, Any]:
    """Helper function to get cached or fresh host environment."""
    return HostEnvironment.detect()
