#!/usr/bin/env python3
"""
Personal Development Harness (PDH) - Design Token & A11y Compliance Linter
Enforces design token consistency, flags raw hex colors outside theme/token files,
and checks spacing calls against the 2dp/4dp design token grid without false-positiving
component sizes, corner radii, or doc comments.
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def resolve_tokens_path() -> Path:
    cwd_tokens = Path.cwd() / ".harness" / "design-tokens.json"
    if cwd_tokens.exists():
        return cwd_tokens
    return Path(__file__).resolve().parent / "design-tokens.json"


class DesignTokenLinter:
    def __init__(self, tokens_path: Optional[Path] = None):
        self.tokens_path = Path(tokens_path) if tokens_path else resolve_tokens_path()
        self.tokens = self._load_tokens()
        self.valid_spacings = {2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 64, 72, 80, 96}

    def _load_tokens(self) -> Dict:
        if self.tokens_path.exists():
            with open(self.tokens_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def lint_file(self, file_path: Path) -> List[Dict]:
        violations = []
        if not file_path.is_file():
            return violations

        if file_path.suffix == ".json":
            return violations

        # Skip build/generated/report directories
        if any(ignored in file_path.parts for ignored in ("build", ".gradle", "node_modules", ".git", "reports", ".agents")):
            return violations

        # Skip theme definitions, design token catalogs, or data models
        path_parts_lower = [p.lower() for p in file_path.parts]
        name_lower = file_path.name.lower()
        if any(part in ("theme", "tokens", "token", "model", "models", "catalog") for part in path_parts_lower):
            return violations
        if any(kw in name_lower for kw in ("theme", "color", "colors", "token", "tokens", "liquidglass", "spacing", "shape", "shapes")):
            return violations

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception as e:
            return [{"line": 0, "rule": "READ_ERROR", "message": str(e), "severity": "ERROR"}]

        hex_pattern = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
        compose_hex_pattern = re.compile(r"Color\(0x[0-9a-fA-F]{8}\)")
        spacing_call_pattern = re.compile(r"\b(?:padding|spacedBy|contentPadding)\s*(?:\(|=)\s*([^)\n]+)")
        compose_dp_pattern = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\.dp\b")
        css_px_pattern = re.compile(r"\b(?:padding|margin|gap):\s*(\d+)px\b")

        in_block_comment = False
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()

            # Track multiline /* ... */ comments
            if "/*" in stripped:
                in_block_comment = True
            if in_block_comment:
                if "*/" in stripped:
                    in_block_comment = False
                continue
            if stripped.startswith("//") or stripped.startswith("*"):
                continue

            code_only = line.split("//")[0]

            # 1. Check for arbitrary raw hex colors in active code
            hex_matches = hex_pattern.findall(code_only)
            compose_hex_matches = compose_hex_pattern.findall(code_only)
            if hex_matches or compose_hex_matches:
                violations.append({
                    "line": idx,
                    "rule": "NO_RAW_HEX_COLOR",
                    "message": f"Found raw hardcoded color in '{stripped}'. Use tokens from design-tokens.json or MaterialTheme/Theme tokens instead.",
                    "severity": "ERROR",
                })

            # 2. Check spacing/padding calls for off-grid dp values
            for sm in spacing_call_pattern.finditer(code_only):
                arg_segment = sm.group(1)
                for dp_match in compose_dp_pattern.finditer(arg_segment):
                    raw_str = dp_match.group(1)
                    val = float(raw_str)
                    if val <= 2.0:
                        continue
                    if val % 2 != 0:
                        violations.append({
                            "line": idx,
                            "rule": "INVALID_SPACING_SCALE",
                            "message": f"Spacing '{raw_str}.dp' in '{stripped}' is off-grid (must align to 2dp/4dp token scale).",
                            "severity": "WARN",
                        })

            # 3. Check CSS padding/margin/gap px spacings
            for px_match in css_px_pattern.finditer(code_only):
                val = int(px_match.group(1))
                if val > 2 and val % 2 != 0:
                    violations.append({
                        "line": idx,
                        "rule": "INVALID_SPACING_SCALE",
                        "message": f"CSS Spacing '{val}px' is off-grid (must align to 2px/4px token scale).",
                        "severity": "WARN",
                    })

        return violations

    def lint_directory(self, root_dir: Path, extensions: Tuple[str, ...] = (".kt", ".dart", ".tsx", ".jsx", ".css")) -> Dict[str, List[Dict]]:
        report = {}
        if not root_dir.exists():
            return report
        for ext in extensions:
            for file_path in root_dir.rglob(f"*{ext}"):
                if any(part in ("build", ".gradle", "node_modules", ".git", "reports", ".agents") for part in file_path.parts):
                    continue
                violations = self.lint_file(file_path)
                if violations:
                    report[str(file_path)] = violations
        return report


if __name__ == "__main__":
    linter = DesignTokenLinter()
    targets = [Path(arg) for arg in sys.argv[1:]] if len(sys.argv) > 1 else [Path("src")]
    res: Dict[str, List[Dict]] = {}
    for target in targets:
        if target.is_file():
            v = linter.lint_file(target)
            if v:
                res[str(target)] = v
        else:
            res.update(linter.lint_directory(target))

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
