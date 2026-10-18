#!/usr/bin/env python3
"""
Khoros v3.1 Static AST Capability Risk Classifier
Analyzes synthesized Python tool/jig code via AST parsing and classifies its security risk tier:
- Tier 1: Pure AST / Regex Linters (Read-only diagnostics, zero side-effects, instant auto-admit)
- Tier 2: Worktree File Utilities (Local reads/writes confined to current worktree, shadow canary)
- Tier 3: High-Risk Mutating / Shell / Network (Shell exec, network sockets, requires HITL approval)
"""

import ast
from enum import IntEnum
from typing import List, Set, Tuple


class RiskTier(IntEnum):
    TIER_1_READONLY_JIG = 1
    TIER_2_WORKTREE_UTIL = 2
    TIER_3_MUTATING_SHELL_NET = 3


class CapabilityRiskClassifier(ast.NodeVisitor):
    # Prohibited modules that immediately escalate to Tier 3
    TIER_3_MODULES: Set[str] = {
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "http",
        "http.client",
        "urllib.request",
        "ctypes",
        "pty",
        "paramiko",
        "ftplib",
        "smtplib",
        "telnetlib",
    }

    # Risky os/sys functions that escalate to Tier 3
    TIER_3_CALLS: Set[str] = {
        "system",
        "popen",
        "exec",
        "eval",
        "execfile",
        "spawn",
        "spawnl",
        "spawnv",
        "fork",
        "kill",
        "chmod",
        "chown",
    }

    # Write calls that escalate Tier 1 -> Tier 2
    WRITE_CALLS: Set[str] = {
        "write",
        "writelines",
        "write_text",
        "write_bytes",
        "unlink",
        "remove",
        "rmdir",
        "mkdir",
        "makedirs",
        "rename",
        "replace",
        "copy",
        "copy2",
        "copytree",
    }

    def __init__(self):
        self.risk_tier = RiskTier.TIER_1_READONLY_JIG
        self.flagged_reasons: List[str] = []
        self.imported_modules: Set[str] = set()

    def classify_code(self, source_code: str) -> Tuple[RiskTier, List[str]]:
        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            return RiskTier.TIER_3_MUTATING_SHELL_NET, [f"SyntaxError in code: {e}"]

        self.risk_tier = RiskTier.TIER_1_READONLY_JIG
        self.flagged_reasons = []
        self.imported_modules = set()
        self.visit(tree)
        return self.risk_tier, self.flagged_reasons

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            mod = alias.name.split(".")[0]
            self.imported_modules.add(alias.name)
            if alias.name in self.TIER_3_MODULES or mod in self.TIER_3_MODULES:
                self._escalate(
                    RiskTier.TIER_3_MUTATING_SHELL_NET,
                    f"Import of high-risk network/process module '{alias.name}'",
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            mod = node.module.split(".")[0]
            self.imported_modules.add(node.module)
            if node.module in self.TIER_3_MODULES or mod in self.TIER_3_MODULES:
                self._escalate(
                    RiskTier.TIER_3_MUTATING_SHELL_NET,
                    f"Import from high-risk network/process module '{node.module}'",
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in ("exec", "eval", "compile"):
                self._escalate(
                    RiskTier.TIER_3_MUTATING_SHELL_NET,
                    f"Dynamic code execution call '{func_name}()'",
                )
            elif func_name == "open":
                # Check if opening for write/append
                for arg in node.args[1:]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if any(m in arg.value for m in ("w", "a", "+", "x")):
                            self._escalate(
                                RiskTier.TIER_2_WORKTREE_UTIL,
                                f"File write access via open(..., mode='{arg.value}')",
                            )
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        if any(m in kw.value.value for m in ("w", "a", "+", "x")):
                            self._escalate(
                                RiskTier.TIER_2_WORKTREE_UTIL,
                                f"File write access via open(..., mode='{kw.value.value}')",
                            )

        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
            if func_name in self.TIER_3_CALLS:
                self._escalate(
                    RiskTier.TIER_3_MUTATING_SHELL_NET,
                    f"Process/shell invocation call '{func_name}()'",
                )
            elif func_name in self.WRITE_CALLS:
                self._escalate(
                    RiskTier.TIER_2_WORKTREE_UTIL,
                    f"File system modification call '{func_name}()'",
                )

        self.generic_visit(node)

    def _escalate(self, tier: RiskTier, reason: str):
        if tier > self.risk_tier:
            self.risk_tier = tier
        self.flagged_reasons.append(reason)


def classify_capability_code(source_code: str) -> Tuple[RiskTier, List[str]]:
    """Convenience helper to classify source code."""
    classifier = CapabilityRiskClassifier()
    return classifier.classify_code(source_code)
