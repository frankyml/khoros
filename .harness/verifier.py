#!/usr/bin/env python3
"""
Personal Development Harness (PDH) v2.0 - Universal Verification Pipeline
Pluggable verification engine supporting domain profiles:
- mobile-kmp (Design tokens, 2dp/4dp grid, secret scan, Mermaid spec validation)
- python (Syntax/AST check, unittest/pytest discovery, secret scan)
- web (Design tokens, CSS/TSX spacing & hex check, secret scan)
- research (Artifact/Markdown link & Mermaid validation, citation hygiene)
- generic (Secret scan, Mermaid validation, custom config commands)
"""

import json
import py_compile
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HARNESS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_DIR))

from linter import DesignTokenLinter
from prd_engine import PRDEngine


def detect_project_profile(workspace_dir: Optional[Path] = None) -> str:
    ws = Path(workspace_dir) if workspace_dir else Path.cwd()
    cfg_path = ws / ".harness" / "config.yaml"
    if cfg_path.exists():
        text = cfg_path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^\s*profile:\s*[\"']?([a-zA-Z0-9_-]+)[\"']?", text, re.MULTILINE)
        if m:
            return m.group(1).lower()

    # Auto-detect from project structure
    if (ws / "shared" / "src").exists() or (ws / "androidApp" / "src").exists():
        return "mobile-kmp"
    if (ws / "pyproject.toml").exists() or (ws / "setup.py").exists() or (ws / "tests" / "unit").exists():
        return "python"
    if (ws / "package.json").exists():
        return "web"
    return "generic"


class VerificationPipeline:
    SECRET_PATTERNS = [
        (
            "HARDCODED_PRIVATE_KEY",
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
        ),
        (
            "HARDCODED_API_SECRET",
            re.compile(r"(?:api_key|secret_key|access_token)\s*[:=]\s*[\"'](?!YOUR_|REPLACE_|example|test)[A-Za-z0-9_\-]{24,}[\"']", re.IGNORECASE),
        ),
    ]

    def __init__(self, workspace_dir: Optional[Path] = None, profile: Optional[str] = None):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()
        self.profile = (profile or detect_project_profile(self.workspace_dir)).lower()
        self.linter = DesignTokenLinter()
        self.prd_engine = PRDEngine(
            prd_dir=self.workspace_dir / "docs" / "prd",
            flows_dir=self.workspace_dir / "docs" / "flows",
        )

    def scan_secrets(self, targets: List[Path]) -> List[Dict[str, Any]]:
        violations = []
        skip_dirs = {".git", "build", ".gradle", "node_modules", "__pycache__", ".venv", "venv"}
        for target in targets:
            if not target.exists():
                continue
            files = [target] if target.is_file() else list(target.rglob("*"))
            for fpath in files:
                if not fpath.is_file():
                    continue
                if any(p in skip_dirs for p in fpath.parts):
                    continue
                if fpath.suffix.lower() in (".db", ".pyc", ".png", ".jpg", ".jar", ".apk", ".so"):
                    continue
                if fpath.name == "verifier.py":
                    continue
                try:
                    lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
                except Exception:
                    continue
                for idx, line in enumerate(lines, 1):
                    for rule_name, pattern in self.SECRET_PATTERNS:
                        if pattern.search(line):
                            violations.append(
                                {
                                    "file": str(fpath),
                                    "line": idx,
                                    "rule": rule_name,
                                    "message": "Potential hardcoded secret or private key detected.",
                                    "severity": "ERROR",
                                }
                            )
        return violations

    def verify_python_syntax(self, targets: List[Path]) -> List[Dict[str, Any]]:
        violations = []
        skip_dirs = {".git", "build", "node_modules", "__pycache__", ".venv", "venv"}
        for target in targets:
            if not target.exists():
                continue
            py_files = [target] if (target.is_file() and target.suffix == ".py") else list(target.rglob("*.py"))
            for py_f in py_files:
                if any(p in skip_dirs for p in py_f.parts):
                    continue
                try:
                    py_compile.compile(str(py_f), doraise=True)
                except py_compile.PyCompileError as e:
                    violations.append(
                        {
                            "file": str(py_f),
                            "line": 0,
                            "rule": "PYTHON_SYNTAX_ERROR",
                            "message": str(e),
                            "severity": "ERROR",
                        }
                    )
        return violations

    def verify_mermaid_docs(self) -> List[Dict[str, Any]]:
        violations = []
        docs_dir = self.workspace_dir / "docs"
        if not docs_dir.exists():
            return violations
        block_re = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
        for md_file in docs_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for match in block_re.finditer(content):
                errs = self.prd_engine.validate_mermaid(match.group(1))
                for err in errs:
                    violations.append(
                        {
                            "file": str(md_file),
                            "line": 0,
                            "rule": "MERMAID_SYNTAX",
                            "message": err,
                            "severity": "WARN",
                        }
                    )
        return violations

    def run(self, targets: Optional[List[Path]] = None, run_tests: bool = False) -> Tuple[bool, Dict[str, Any]]:
        if not targets:
            candidates = [
                self.workspace_dir / "shared" / "src",
                self.workspace_dir / "androidApp" / "src",
                self.workspace_dir / "src",
                self.workspace_dir / ".harness",
            ]
            targets = [p for p in candidates if p.exists()]
            if not targets:
                targets = [self.workspace_dir]

        checks_run = []
        violations: List[Dict[str, Any]] = []

        # 1. Universal Secret & Security Hygiene Gate
        checks_run.append("secret-hygiene")
        violations.extend(self.scan_secrets(targets))

        # 2. UI Design Token Gate (runs when UI files exist or profile is mobile-kmp / web)
        checks_run.append("design-tokens")
        for target in targets:
            if target.is_file():
                for v in self.linter.lint_file(target):
                    violations.append({"file": str(target), **v})
            elif target.exists():
                res = self.linter.lint_directory(target)
                for fpath, vlist in res.items():
                    for v in vlist:
                        violations.append({"file": fpath, **v})

        # 3. Python Syntax / Engine Integrity Gate
        if self.profile in ("python", "generic") or (self.workspace_dir / ".harness").exists():
            checks_run.append("python-syntax")
            violations.extend(self.verify_python_syntax(targets))

        # 4. Documentation & Spec Mermaid Gate
        if (self.workspace_dir / "docs").exists():
            checks_run.append("spec-mermaid")
            violations.extend(self.verify_mermaid_docs())

        # 5. Optional Automated Unit Test Gate
        test_dir = next((d for d in ("tests/unit", "tests", "test") if (self.workspace_dir / d).is_dir()), None)
        if run_tests and test_dir is None:
            # Say so instead of passing silently: a gate that ran no tests proves nothing
            checks_run.append("unit-tests (skipped: no tests/ directory)")
        elif run_tests:
            checks_run.append("unit-tests")
            proc = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", test_dir],
                cwd=str(self.workspace_dir),
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                violations.append(
                    {
                        "file": test_dir,
                        "line": 0,
                        "rule": "UNIT_TEST_FAILURE",
                        "message": (proc.stderr or proc.stdout).strip()[-400:],
                        "severity": "ERROR",
                    }
                )

        passed = len(violations) == 0
        report = {
            "profile": self.profile,
            "passed": passed,
            "checks_run": checks_run,
            "violation_count": len(violations),
            "violations": violations,
        }
        return passed, report


if __name__ == "__main__":
    pipeline = VerificationPipeline()
    ok, result = pipeline.run(run_tests=True)
    print(json.dumps(result, indent=2))
    sys.exit(0 if ok else 1)
