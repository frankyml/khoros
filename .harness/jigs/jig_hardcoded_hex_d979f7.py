#!/usr/bin/env python3
"""
Kaizen Synthesized AST Jig: jig_hardcoded_hex_d979f7
Enforces deterministic mechanical check for error type: HARDCODED_HEX
"""

import ast
from pathlib import Path
from typing import List


class HardcodedHexChecker(ast.NodeVisitor):
    def __init__(self):
        self.violations: List[str] = []

    def visit_Constant(self, node: ast.Constant):
        # Mechanical detection of pattern
        if isinstance(node.value, str) and "#hardcoded_hex" in node.value.lower():
            self.violations.append(f"Disallowed pattern found: {node.value}")
        self.generic_visit(node)


def check_file(file_path: Path, content: str) -> List[str]:
    try:
        tree = ast.parse(content)
        checker = HardcodedHexChecker()
        checker.visit(tree)
        return checker.violations
    except SyntaxError:
        return []
