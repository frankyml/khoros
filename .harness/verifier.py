#!/usr/bin/env python3
"""
Khoros v4 - Language-aware verification engine.

Runs a set of check plugins over the files in scope and (optionally) the project's own tests.
Every check that does not apply is reported as an explicit "skipped: <reason>"; failures carry a
"How to fix" hint and the tail of the failing command output.

Checks: secrets, python syntax, JS syntax (node --check), JSON/YAML/TOML parse, Mermaid in docs (WARN),
design tokens (only with .harness/design-tokens.json and UI files in scope), lint commands, tests.
"""

import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HARNESS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_DIR))

from linter import DesignTokenLinter
from prd_engine import PRDEngine

SKIP_DIRS = {".git", "build", ".gradle", "node_modules", "__pycache__", ".venv", "venv", ".worktrees", ".pytest_cache"}
UI_SUFFIXES = (".kt", ".dart", ".tsx", ".jsx", ".css")
BINARY_SUFFIXES = (".db", ".pyc", ".png", ".jpg", ".jar", ".apk", ".so")
TAIL_LINES = 60

DEFAULT_VERIFY_CONFIG: Dict[str, Any] = {
    "gate": "on",
    "test_command": "",
    "lint_commands": [],
    "test_timeout": 240,
    "max_stop_blocks": 3,
    "loop_edit_threshold": 8,
}

FIX_HINTS = {
    "HARDCODED_PRIVATE_KEY": "Remove the key from the file, load it from an environment variable or secret store, and rotate it.",
    "HARDCODED_API_SECRET": "Move the secret to an environment variable (or .env that is git-ignored) and rotate it.",
    "PYTHON_SYNTAX_ERROR": "Fix the syntax error at the given line; reproduce with: python3 -m py_compile <file>",
    "JS_SYNTAX_ERROR": "Fix the syntax error at the given line; reproduce with: node --check <file>",
    "CONFIG_PARSE_ERROR": "Fix the malformed config file; it must parse before anything can read it.",
    "MERMAID_SYNTAX": "Fix the Mermaid block so it renders (valid diagram header, balanced brackets).",
    "UNIT_TEST_FAILURE": "Reproduce with the command shown, fix the failing test or the code it covers, then re-run.",
    "TEST_TIMEOUT": "The test command exceeded its time budget; run it by hand, or raise verify.test_timeout in .harness/config.yaml.",
    "LINT_FAILURE": "Run the lint command shown and fix what it reports.",
}


# --------------------------------------------------------------------------- config

def _parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if " #" in raw and not raw.startswith(("'", '"')):
        raw = raw.split(" #", 1)[0].strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [_parse_scalar(p) for p in inner.split(",")] if inner else []
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    low = raw.lower()
    if low in ("on", "true", "yes"):
        return "on"
    if low in ("off", "false", "no"):
        return "off"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return raw


def load_verify_config(workspace_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Read the `verify:` section of .harness/config.yaml with a tiny stdlib YAML subset reader.

    Supports `key: scalar`, inline lists `[a, b]` and block lists (`- item`). Files without a
    verify section (v3.1) or unreadable files yield the defaults.
    """
    cfg = dict(DEFAULT_VERIFY_CONFIG)
    cfg["lint_commands"] = []
    ws = Path(workspace_dir) if workspace_dir else Path.cwd()
    try:
        text = (ws / ".harness" / "config.yaml").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return cfg

    in_section = False
    current_list: Optional[str] = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_section = bool(re.match(r"verify\s*:\s*(#.*)?$", line))
            current_list = None
            continue
        if not in_section:
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and current_list:
            item = _parse_scalar(stripped[2:])
            if not isinstance(cfg.get(current_list), list):
                cfg[current_list] = []
            cfg[current_list].append(item)
            continue
        m = re.match(r"([A-Za-z_][\w-]*)\s*:\s*(.*)$", stripped)
        if not m:
            continue
        key, rest = m.group(1), m.group(2)
        if key not in DEFAULT_VERIFY_CONFIG:
            current_list = None
            continue
        if rest == "" or rest.startswith("#"):
            current_list = key
            cfg[key] = []
            continue
        current_list = None
        value = _parse_scalar(rest)
        if isinstance(DEFAULT_VERIFY_CONFIG[key], int) and not isinstance(value, int):
            continue
        cfg[key] = value
    if not isinstance(cfg["lint_commands"], list):
        cfg["lint_commands"] = []
    return cfg


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


# --------------------------------------------------------------------------- git / files

def git_changed_files(workspace_dir: Path) -> Optional[List[Path]]:
    """Files changed vs HEAD plus untracked (non-ignored). None when not a git repo."""
    def git(*args: str) -> Optional[str]:
        try:
            proc = subprocess.run(["git", *args], cwd=str(workspace_dir), capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout if proc.returncode == 0 else None

    top = git("rev-parse", "--show-toplevel")
    if top is None:
        return None
    root = Path(top.strip())
    names = set()
    # `diff HEAD` fails in a repo without commits; fall back to the index
    tracked = git("diff", "--name-only", "HEAD")
    if tracked is None:
        tracked = git("diff", "--name-only", "--cached") or ""
        tracked += git("diff", "--name-only") or ""
    names.update(n for n in tracked.splitlines() if n)
    names.update(n for n in (git("ls-files", "--others", "--exclude-standard") or "").splitlines() if n)
    return sorted(p for p in (root / n for n in names) if p.is_file())


def expand_files(targets: List[Path]) -> List[Path]:
    files: List[Path] = []
    for target in targets:
        if not target.exists():
            continue
        candidates = [target] if target.is_file() else sorted(target.rglob("*"))
        for f in candidates:
            if f.is_file() and not any(p in SKIP_DIRS for p in f.parts) and f.suffix.lower() not in BINARY_SUFFIXES:
                files.append(f)
    return files


def _tail(text: str, lines: int = TAIL_LINES) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _run_command(cmd: Any, cwd: Path, timeout: float, shell: bool = False) -> Tuple[int, str, bool]:
    """Run a command in its own process group; kill the whole group on timeout. -> (rc, output, timed_out)."""
    env = dict(os.environ)
    env["KHOROS_VERIFY_DEPTH"] = str(int(env.get("KHOROS_VERIFY_DEPTH", "0") or 0) + 1)
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(cwd), shell=shell, env=env, text=True, errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        )
    except OSError as e:
        return 127, f"could not start command: {e}", False
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out or "", False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            proc.kill()
        out, _ = proc.communicate()
        return 124, out or "", True


# --------------------------------------------------------------------------- test detection

def _has_python_tests(ws: Path) -> Optional[Path]:
    """Return the preferred python test directory, or None."""
    for d in ("tests/unit", "tests", "test"):
        base = ws / d
        if base.is_dir() and (any(base.rglob("test_*.py")) or any(base.rglob("*_test.py"))):
            return base
    return None


def detect_test_command(ws: Path, cfg: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Any], str, bool, List[str]]:
    """-> (command, label, use_shell, skip_reasons). command is None when nothing can run."""
    cfg = cfg or load_verify_config(ws)
    configured = str(cfg.get("test_command") or "").strip()
    if configured:
        return configured, configured, True, []

    reasons: List[str] = []
    py_dir = _has_python_tests(ws)
    if py_dir is not None:
        rel = py_dir.relative_to(ws).as_posix()
        if importlib.util.find_spec("pytest") is not None:
            cmd = [sys.executable, "-m", "pytest", "-q", "-x"]
            if rel == "tests/unit":
                cmd.append(rel)
            return cmd, " ".join(["python3", *cmd[1:]]), False, reasons
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", rel]
        if (py_dir / "__init__.py").exists():
            cmd += ["-t", "."]
        return cmd, " ".join(["python3", *cmd[1:]]), False, reasons

    pkg = ws / "package.json"
    if pkg.exists():
        try:
            script = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}).get("test", "")
        except (OSError, ValueError):
            script = ""
        if script and "no test specified" not in script:
            if shutil.which("npm"):
                return ["npm", "test"], "npm test", False, reasons
            reasons.append("npm not installed")
        else:
            reasons.append("package.json has no test script")
    if (ws / "go.mod").exists():
        if shutil.which("go"):
            return ["go", "test", "./..."], "go test ./...", False, reasons
        reasons.append("go not installed")
    if (ws / "Cargo.toml").exists():
        if shutil.which("cargo"):
            return ["cargo", "test"], "cargo test", False, reasons
        reasons.append("cargo not installed")
    makefile = next((ws / n for n in ("Makefile", "makefile", "GNUmakefile") if (ws / n).exists()), None)
    if makefile is not None:
        try:
            has_target = re.search(r"^test\s*:", makefile.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
        except OSError:
            has_target = None
        if has_target:
            if shutil.which("make"):
                return ["make", "test"], "make test", False, reasons
            reasons.append("make not installed")
    if not reasons:
        reasons.append("no test command detected (set verify.test_command in .harness/config.yaml)")
    return None, "", False, reasons


# --------------------------------------------------------------------------- pipeline

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
        self.config = load_verify_config(self.workspace_dir)

    # -- individual checks (each takes the concrete files in scope)

    def scan_secrets(self, targets: List[Path]) -> List[Dict[str, Any]]:
        violations = []
        for fpath in expand_files(targets):
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
        for f in expand_files(targets):
            if f.suffix != ".py":
                continue
            try:
                compile(f.read_bytes(), str(f), "exec", dont_inherit=True)
            except SyntaxError as e:
                violations.append(
                    {
                        "file": str(f),
                        "line": e.lineno or 0,
                        "rule": "PYTHON_SYNTAX_ERROR",
                        "message": f"{e.msg}" + (f": {e.text.strip()}" if e.text else ""),
                        "severity": "ERROR",
                    }
                )
            except (ValueError, OSError) as e:
                violations.append(
                    {"file": str(f), "line": 0, "rule": "PYTHON_SYNTAX_ERROR", "message": str(e), "severity": "ERROR"}
                )
        return violations

    def verify_js_syntax(self, files: List[Path], node: str) -> List[Dict[str, Any]]:
        violations = []
        for f in files:
            rc, out, _ = _run_command([node, "--check", str(f)], self.workspace_dir, 20)
            if rc == 0:
                continue
            # .js files using ESM without "type": "module" are valid for the project's bundler
            if "Cannot use import statement" in out or "Unexpected token 'export'" in out:
                continue
            line = 0
            m = re.search(re.escape(f.name) + r":(\d+)", out)
            if m:
                line = int(m.group(1))
            msg = next((l.strip() for l in out.splitlines() if "Error" in l), out.strip()[:200])
            violations.append({"file": str(f), "line": line, "rule": "JS_SYNTAX_ERROR", "message": msg, "severity": "ERROR"})
        return violations

    def verify_config_files(self, files: List[Path]) -> Tuple[List[Dict[str, Any]], List[str]]:
        violations: List[Dict[str, Any]] = []
        skipped: List[str] = []
        yaml_mod = None
        toml_mod = None
        try:
            import yaml as yaml_mod  # type: ignore
        except ImportError:
            pass
        try:
            import tomllib as toml_mod  # type: ignore
        except ImportError:
            pass
        skipped_yaml = skipped_toml = False
        for f in files:
            suffix = f.suffix.lower()
            if suffix not in (".json", ".yaml", ".yml", ".toml"):
                continue
            if f.name.startswith(("tsconfig", "jsconfig")):  # JSON-with-comments
                continue
            try:
                if suffix == ".json":
                    json.loads(f.read_text(encoding="utf-8"))
                elif suffix == ".toml":
                    if toml_mod is None:
                        skipped_toml = True
                        continue
                    toml_mod.loads(f.read_text(encoding="utf-8"))
                else:
                    if yaml_mod is None:
                        skipped_yaml = True
                        continue
                    list(yaml_mod.safe_load_all(f.read_text(encoding="utf-8")))
            except Exception as e:
                violations.append(
                    {
                        "file": str(f),
                        "line": getattr(e, "lineno", 0) or 0,
                        "rule": "CONFIG_PARSE_ERROR",
                        "message": str(e).splitlines()[0][:200] if str(e) else type(e).__name__,
                        "severity": "ERROR",
                    }
                )
        if skipped_yaml:
            skipped.append("yaml-parse (skipped: PyYAML not installed)")
        if skipped_toml:
            skipped.append("toml-parse (skipped: needs Python 3.11+)")
        return violations, skipped

    def verify_mermaid_docs(self) -> List[Dict[str, Any]]:
        violations = []
        docs_dir = self.workspace_dir / "docs"
        if not docs_dir.exists():
            return violations
        engine = PRDEngine(prd_dir=docs_dir / "prd", flows_dir=docs_dir / "flows")
        block_re = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
        for md_file in docs_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for match in block_re.finditer(content):
                for err in engine.validate_mermaid(match.group(1)):
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

    def _lint_design_tokens(self, files: List[Path]) -> List[Dict[str, Any]]:
        linter = DesignTokenLinter(tokens_path=self.workspace_dir / ".harness" / "design-tokens.json")
        violations = []
        for f in files:
            if f.suffix.lower() in UI_SUFFIXES:
                for v in linter.lint_file(f):
                    violations.append({"file": str(f), **v})
        return violations

    # -- test / lint commands

    def run_tests(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """-> {status: passed|failed|timeout|skipped, command, reason, output_tail, duration}"""
        if int(os.environ.get("KHOROS_VERIFY_DEPTH", "0") or 0) >= 1:
            return {"status": "skipped", "reason": "nested verify run (avoids recursion)"}
        cmd, label, shell, reasons = detect_test_command(self.workspace_dir, self.config)
        if cmd is None:
            return {"status": "skipped", "reason": "; ".join(reasons)}
        limit = timeout if timeout is not None else self.config["test_timeout"]
        start = time.time()
        rc, out, timed_out = _run_command(cmd, self.workspace_dir, limit, shell=shell)
        result = {
            "command": label,
            "duration": round(time.time() - start, 1),
            "output_tail": _tail(out),
        }
        if timed_out:
            result.update(status="timeout", reason=f"exceeded {limit}s")
        elif rc == 5 and "pytest" in label:
            result.update(status="skipped", reason="no tests collected")
        elif rc == 0:
            result["status"] = "passed"
        else:
            result["status"] = "failed"
        return result

    def run_lint_commands(self, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        violations = []
        limit = timeout if timeout is not None else self.config["test_timeout"]
        for command in self.config["lint_commands"]:
            rc, out, timed_out = _run_command(str(command), self.workspace_dir, limit, shell=True)
            if rc != 0 or timed_out:
                violations.append(
                    {
                        "file": str(command),
                        "line": 0,
                        "rule": "LINT_FAILURE",
                        "message": ("timed out; " if timed_out else "") + _tail(out, 20),
                        "severity": "ERROR",
                    }
                )
        return violations

    # -- orchestration

    def default_targets(self) -> List[Path]:
        candidates = [
            self.workspace_dir / "shared" / "src",
            self.workspace_dir / "androidApp" / "src",
            self.workspace_dir / "src",
            self.workspace_dir / ".harness",
        ]
        targets = [p for p in candidates if p.exists()]
        return targets or [self.workspace_dir]

    def run(
        self,
        targets: Optional[List[Path]] = None,
        run_tests: bool = False,
        changed: bool = False,
        fast: bool = False,
        test_timeout: Optional[float] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        scope = "full"
        if targets:
            scope = "targets"
            files = expand_files([Path(t) for t in targets])
        elif changed:
            changed_files = git_changed_files(self.workspace_dir)
            if changed_files is None:
                files = expand_files(self.default_targets())
            else:
                scope = "changed"
                files = [f for f in changed_files if f.suffix.lower() not in BINARY_SUFFIXES]
        else:
            files = expand_files(self.default_targets())
        if fast:
            run_tests = False

        checks_run: List[str] = []
        skipped: List[str] = []
        violations: List[Dict[str, Any]] = []

        checks_run.append("secret-hygiene")
        violations.extend(self.scan_secrets(files))

        py_files = [f for f in files if f.suffix == ".py"]
        if py_files:
            checks_run.append("python-syntax")
            violations.extend(self.verify_python_syntax(py_files))
        else:
            skipped.append("python-syntax (skipped: no .py files in scope)")

        js_files = [f for f in files if f.suffix.lower() in (".js", ".mjs", ".cjs")]
        node = shutil.which("node")
        if not js_files:
            skipped.append("js-syntax (skipped: no .js files in scope)")
        elif not node:
            skipped.append("js-syntax (skipped: node not installed)")
        else:
            checks_run.append("js-syntax")
            violations.extend(self.verify_js_syntax(js_files, node))

        cfg_files = [f for f in files if f.suffix.lower() in (".json", ".yaml", ".yml", ".toml")]
        if cfg_files:
            checks_run.append("config-parse")
            cfg_violations, cfg_skips = self.verify_config_files(cfg_files)
            violations.extend(cfg_violations)
            skipped.extend(cfg_skips)
        else:
            skipped.append("config-parse (skipped: no JSON/YAML/TOML files in scope)")

        ui_files = [f for f in files if f.suffix.lower() in UI_SUFFIXES]
        if not (self.workspace_dir / ".harness" / "design-tokens.json").exists():
            skipped.append("design-tokens (skipped: no .harness/design-tokens.json)")
        elif not ui_files:
            skipped.append("design-tokens (skipped: no UI files in scope)")
        else:
            checks_run.append("design-tokens")
            violations.extend(self._lint_design_tokens(ui_files))

        if fast:
            skipped.append("spec-mermaid (skipped: --fast)")
        elif (self.workspace_dir / "docs").exists() and (
            scope != "changed" or any("docs" in f.parts and f.suffix == ".md" for f in files)
        ):
            checks_run.append("spec-mermaid")
            violations.extend(self.verify_mermaid_docs())
        else:
            skipped.append("spec-mermaid (skipped: no docs changes in scope)")

        test_result: Dict[str, Any] = {"status": "skipped", "reason": "not requested (--no-tests / --fast)"}
        if fast:
            skipped.append("lint-commands (skipped: --fast)")
        elif self.config["lint_commands"]:
            checks_run.append("lint-commands")
            violations.extend(self.run_lint_commands(test_timeout))
        else:
            skipped.append("lint-commands (skipped: no verify.lint_commands configured)")

        timed_out = False
        if run_tests:
            test_result = self.run_tests(test_timeout)
            status = test_result["status"]
            if status == "skipped":
                skipped.append(f"unit-tests (skipped: {test_result['reason']})")
            else:
                checks_run.append("unit-tests")
                if status == "timeout":
                    timed_out = True
                    violations.append(
                        {
                            "file": test_result["command"],
                            "line": 0,
                            "rule": "TEST_TIMEOUT",
                            "message": f"{test_result['command']} {test_result['reason']}",
                            "severity": "ERROR",
                        }
                    )
                elif status == "failed":
                    violations.append(
                        {
                            "file": test_result["command"],
                            "line": 0,
                            "rule": "UNIT_TEST_FAILURE",
                            "message": f"`{test_result['command']}` failed",
                            "severity": "ERROR",
                        }
                    )
        else:
            skipped.append(f"unit-tests (skipped: {test_result['reason']})")

        for v in violations:
            v.setdefault("fix", FIX_HINTS.get(v.get("rule"), ""))

        passed = not any(v.get("severity", "ERROR") == "ERROR" for v in violations)
        report = {
            "profile": self.profile,
            "scope": scope,
            "passed": passed,
            "checks_run": checks_run,
            "skipped": skipped,
            "violation_count": len(violations),
            "violations": violations,
            "tests": test_result,
            "timed_out": timed_out,
        }
        return passed, report


def format_report(report: Dict[str, Any], tail_lines: int = TAIL_LINES) -> str:
    """Concise, actionable human text for a verify report."""
    out: List[str] = []
    checks = ", ".join(report["checks_run"]) or "none"
    if report["passed"]:
        out.append(f"✓ Verification passed [scope: {report.get('scope', 'full')} | checks: {checks}]")
    else:
        out.append(f"✗ Verification failed: {report['violation_count']} issue(s) [scope: {report.get('scope', 'full')} | checks: {checks}]")
    for v in report["violations"]:
        loc = f"{v.get('file', '?')}:{v['line']}" if v.get("line") else str(v.get("file", "?"))
        out.append(f"  {loc} [{v.get('severity', 'ERROR')}] {v.get('rule')}: {v.get('message')}")
        if v.get("fix"):
            out.append(f"    How to fix: {v['fix']}")
    tests = report.get("tests") or {}
    if tests.get("status") in ("failed", "timeout") and tests.get("output_tail"):
        out.append(f"  Last output of `{tests.get('command')}` (tail):")
        out.extend("    " + l for l in tests["output_tail"].splitlines()[-tail_lines:])
    out.extend(f"  {s}" for s in report.get("skipped", []))
    return "\n".join(out)


if __name__ == "__main__":
    pipeline = VerificationPipeline()
    ok, result = pipeline.run(run_tests=True)
    print(json.dumps(result, indent=2))
    sys.exit(0 if ok else 1)
