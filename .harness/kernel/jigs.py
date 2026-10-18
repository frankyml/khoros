#!/usr/bin/env python3
"""
PDH v3.0 In-Station Poka-Yoke Jigs (Jidoka Quality at the Source)
Enforces write-time AST validation, token invariants, and secret scanning directly
in Station 2 (Sub-Assembly) before code is committed or propagated downstream.
"""

import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from .event_store import KernelEventStore


class InStationJigRunner:
    SECRET_PATTERNS = [
        (
            "HARDCODED_PRIVATE_KEY",
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
        ),
        (
            "HARDCODED_API_SECRET",
            re.compile(
                r"(?:api_key|secret_key|access_token)\s*[:=]\s*[\"'](?!YOUR_|REPLACE_|example|test)[A-Za-z0-9_\-]{24,}[\"']",
                re.IGNORECASE,
            ),
        ),
    ]

    HEX_COLOR_PATTERN = re.compile(r"(?<!&)(#[0-9a-fA-F]{6,8}|Color\(0x[0-9a-fA-F]{8}\))")

    def __init__(self, event_store: Optional[KernelEventStore] = None):
        self.event_store = event_store

    def validate_content(
        self,
        file_path: str,
        content: str,
        task_id: str = "adhoc",
        capsule_id: str = "worker",
        epoch: int = 1,
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Executes in-station quality checks on proposed code modifications.
        Returns: (passed, violations)
        """
        violations = []
        path = Path(file_path)

        # 1. AST Syntax Check for Python files
        if path.suffix == ".py":
            try:
                ast.parse(content, filename=file_path)
            except SyntaxError as e:
                violations.append({
                    "rule": "AST_SYNTAX_ERROR",
                    "severity": "CRITICAL",
                    "line": e.lineno,
                    "message": f"Syntax error: {e.msg}",
                })

        # 2. Secret Scanning (Zero Hardcoded Secrets)
        for rule_name, pattern in self.SECRET_PATTERNS:
            for match in pattern.finditer(content):
                line_no = content.count("\n", 0, match.start()) + 1
                violations.append({
                    "rule": rule_name,
                    "severity": "CRITICAL",
                    "line": line_no,
                    "message": "Potential hardcoded cryptographic credential or API secret.",
                })

        # 3. Design Token Invariant (No raw hex colors outside theme/token files)
        is_ui_file = path.suffix in [".kt", ".dart", ".tsx", ".jsx", ".swift"]
        is_token_def = any(t in path.name.lower() for t in ["theme", "token", "color"])
        if is_ui_file and not is_token_def:
            for match in self.HEX_COLOR_PATTERN.finditer(content):
                line_no = content.count("\n", 0, match.start()) + 1
                violations.append({
                    "rule": "DESIGN_TOKEN_VIOLATION",
                    "severity": "ERROR",
                    "line": line_no,
                    "message": f"Raw color literal '{match.group(0)}' detected. Reference design-tokens.json instead.",
                })

        passed = len(violations) == 0

        # Emit Andon Cord event if critical violations detected
        if not passed and self.event_store:
            self.event_store.emit_event(
                event_type="POKA_YOKE_VIOLATION",
                task_id=task_id,
                payload={
                    "file": file_path,
                    "violation_count": len(violations),
                    "violations": violations,
                },
                emitted_by=capsule_id,
                epoch=epoch,
            )

        return passed, violations
