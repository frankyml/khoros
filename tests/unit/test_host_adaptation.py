#!/usr/bin/env python3
"""
Unit tests for Khoros v3.1 Host & Environment Auto-Adaptation:
- Linux vs Darwin / macOS Apple Silicon detection
- APFS vs Btrfs CoW detection
- Claude Code runtime & 1024 token prompt cache adaptation
- Unified memory probing & safe resource limit handling
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Add .harness to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / ".harness"))

from kernel.host import HostEnvironment, get_host_environment
from kernel.sandbox import WorktreeSandbox


class TestHostEnvironmentAdaptation(unittest.TestCase):
    def test_detect_current_environment(self):
        env = get_host_environment()
        self.assertIn("os", env)
        self.assertIn("machine", env)
        self.assertIn("memory_gb", env)
        self.assertGreater(env["memory_gb"], 0)
        self.assertIn("cow_supported", env)
        self.assertIn("cache_prefix_tokens", env)
        self.assertIn("display_name", env)

    @patch("platform.system", return_value="Darwin")
    @patch("platform.machine", return_value="arm64")
    @patch("os.cpu_count", return_value=10)
    @patch.object(HostEnvironment, "_probe_memory_gb", return_value=24.0)
    def test_macbook_air_m5_adaptation(self, mock_mem, mock_cpus, mock_machine, mock_system):
        with patch.dict(os.environ, {"CLAUDE_CODE": "1"}):
            env = HostEnvironment.detect()
            self.assertEqual(env["os"], "Darwin")
            self.assertEqual(env["machine"], "arm64")
            self.assertTrue(env["is_apple_silicon"])
            self.assertEqual(env["memory_gb"], 24.0)
            self.assertTrue(env["cow_supported"])
            self.assertEqual(env["filesystem_cow"], "APFS")
            self.assertEqual(env["active_agent_runtime"], "claude_code")
            self.assertEqual(env["cache_prefix_tokens"], 1024)
            self.assertEqual(env["recommended_max_workers"], 4)
            self.assertEqual(env["sandbox_mode"], "posix_seatbelt")

    def test_sandbox_darwin_safety_hook(self):
        # Verify that _set_resource_limits does not crash
        WorktreeSandbox._set_resource_limits()


if __name__ == "__main__":
    unittest.main()
