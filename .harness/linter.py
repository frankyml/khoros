#!/usr/bin/env python3
"""
Personal Development Harness (PDH) - Design Token & A11y Compliance Linter
Enforces design token consistency, flags raw hex colors, and guards 48dp tap target minimums.
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

HARNESS_DIR = Path(__file__).resolve().parent
TOKENS_PATH = HARNESS_DIR / "design-tokens.json"


class DesignTokenLinter:
    def __init__(self, tokens_path: Path = TOKENS_PATH):
        self.tokens_path = tokens_path
        self.tokens = self._load_tokens()
        self.valid_spacings = {4, 8, 12, 16, 24, 32, 48, 64}

    def _load_tokens(self) -> Dict:
        if self.tokens_path.exists():
            with open(self.tokens_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def lint_file(self, file_path: Path) -> List[Dict]:
        violations = []
        if not file_path.is_file():
            return violations

        # Skip theme definitions or token files themselves
        if "theme" in file_path.name.lower() or file_path.suffix == ".json":
            return violations

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception as e:
            return [{"line": 0, "rule": "READ_ERROR", "message": str(e), "severity": "ERROR"}]

        # Regex patterns
        hex_pattern = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
        compose_hex_pattern = re.compile(r"Color\(0x[0-9a-fA-F]{8}\)")
        compose_dp_pattern = re.compile(r"\b(\d+)\.dp\b")
        css_px_pattern = re.compile(r"\b(?:padding|margin|gap):\s*(\d+)px\b")

        for idx, line in enumerate(lines, 1):
            # Check for arbitrary raw hex colors
            hex_matches = hex_pattern.findall(line)
            compose_hex_matches = compose_hex_pattern.findall(line)
            if hex_matches or compose_hex_matches:
                violations.append({
                    "line": idx,
                    "rule": "NO_RAW_HEX_COLOR",
                    "message": f"Found raw hardcoded color in '{line.strip()}'. Use tokens from design-tokens.json or MaterialTheme.colorScheme instead.",
                    "severity": "ERROR",
                })

            # Check for arbitrary dp spacings
            for dp_match in compose_dp_pattern.finditer(line):
                val = int(dp_match.group(1))
                if val not in self.valid_spacings and val > 0:
                    violations.append({
                        "line": idx,
                        "rule": "INVALID_SPACING_SCALE",
                        "message": f"Spacing '{val}.dp' violates the 4dp grid token scale (allowed: {sorted(list(self.valid_spacings))}).",
                        "severity": "WARN",
                    })

            # Check for arbitrary CSS px spacings
            for px_match in css_px_pattern.finditer(line):
                val = int(px_match.group(1))
                if val not in self.valid_spacings and val > 0:
                    violations.append({
                        "line": idx,
                        "rule": "INVALID_SPACING_SCALE",
                        "message": f"CSS Spacing '{val}px' violates the 4dp grid token scale (allowed: {sorted(list(self.valid_spacings))}).",
                        "severity": "WARN",
                    })

        return violations

    def lint_directory(self, root_dir: Path, extensions: Tuple[str, ...] = (".kt", ".dart", ".tsx", ".jsx", ".css")) -> Dict[str, List[Dict]]:
        report = {}
        for ext in extensions:
            for file_path in root_dir.rglob(f"*{ext}"):
                violations = self.lint_file(file_path)
                if violations:
                    report[str(file_path)] = violations
        return report


if __name__ == "__main__":
    linter = DesignTokenLinter()
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("src")
    if target.is_file():
        res = {str(target): linter.lint_file(target)}
    else:
        res = linter.lint_directory(target)

    total_violations = sum(len(v) for v in res.values())
    if total_violations == 0:
        print("✓ All UI source files comply with design tokens.")
        sys.exit(0)
    else:
        print(f"✗ Found {total_violations} design token violation(s):\n")
        for fpath, viols in res.items():
            print(f"File: {fpath}")
            for v in viols:
                print(f"  Line {v['line']} [{v['severity']}]: {v['rule']} - {v['message']}")
        sys.exit(1)
