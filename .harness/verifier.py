#!/usr/bin/env python3
"""
Khoros v4 - Language-aware verification engine.

Runs a set of check plugins over the files in scope and (optionally) the project's own tests.
Every check that does not apply is reported as an explicit "skipped: <reason>"; failures carry a
"How to fix" hint and the tail of the failing command output.

Checks: secrets, python syntax, JS syntax (node --check), JSON/YAML/TOML parse, Mermaid in docs (WARN),
design tokens (only with .harness/design-tokens.json and UI files in scope), lint commands, tests.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
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
    "gate_budget": 270,  # seconds for the whole Stop gate (lint + tests + baseline); hook timeout is 300
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
    quoted = re.match(r"""("[^"]*"|'[^']*')\s*(#.*)?$""", raw)
    if quoted:  # a quoted value may be followed by a comment: `""  # empty = auto-detect`
        return quoted.group(1)[1:-1]
    if " #" in raw:
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
            # skip-dirs apply below a directory target only: a checkout living under `.worktrees/` or `build/`
            # must not have all its files skipped because of where it sits
            below = f.relative_to(target).parts if target.is_dir() else ()
            if f.is_file() and not any(p in SKIP_DIRS for p in below) and f.suffix.lower() not in BINARY_SUFFIXES:
                files.append(f)
    return files


def _tail(text: str, lines: int = TAIL_LINES) -> str:
    # a minified bundle can put megabytes on one line: cap line length as well as line count
    return "\n".join(l[:400] for l in text.strip().splitlines()[-lines:])


MAX_OUTPUT_BYTES = 4_000_000
_ACTIVE_GROUPS: set = set()


_LAUNCH = {"busy": False, "pending": False}


def kill_active_children() -> None:
    """SIGKILL every command process group still running."""
    for pid in list(_ACTIVE_GROUPS):
        try:
            os.killpg(pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass


def terminate_requested() -> None:
    """The gate's SIGTERM handler: take every running command down and exit. A signal that lands while a command
    is being spawned (started but not yet registered) is deferred until it is registered, so it is not missed."""
    if _LAUNCH["busy"]:
        _LAUNCH["pending"] = True
        return
    kill_active_children()
    raise SystemExit(0)


def _run_command(cmd: Any, cwd: Path, timeout: float, shell: bool = False) -> Tuple[int, str, bool]:
    """Run a command in its own process group; kill the whole group on timeout. -> (rc, output, timed_out).

    Output goes to a temp file, not a pipe: a daemonized grandchild that inherits the descriptor
    cannot keep us waiting after the timeout.
    """
    env = dict(os.environ)
    env["KHOROS_VERIFY_DEPTH"] = str(int(env.get("KHOROS_VERIFY_DEPTH", "0") or 0) + 1)
    with tempfile.TemporaryFile() as sink:
        _LAUNCH["busy"] = True
        try:
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(cwd), shell=shell, env=env, stdin=subprocess.DEVNULL,
                    stdout=sink, stderr=subprocess.STDOUT, start_new_session=True,
                )
            except OSError as e:
                return 127, f"could not start command: {e}", False
            _ACTIVE_GROUPS.add(proc.pid)
        finally:
            _LAUNCH["busy"] = False
        if _LAUNCH["pending"]:
            terminate_requested()
        timed_out = False
        try:
            proc.wait(timeout=max(timeout, 0))
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        finally:
            _ACTIVE_GROUPS.discard(proc.pid)
        size = sink.seek(0, os.SEEK_END)
        sink.seek(max(0, size - MAX_OUTPUT_BYTES))
        out = sink.read().decode("utf-8", errors="replace")
    return (124 if timed_out or proc.returncode is None else proc.returncode), out, timed_out


# --------------------------------------------------------------------------- test detection

def find_project_python(ws: Path) -> Tuple[str, str]:
    """The interpreter the project's tests should run with -> (executable, display name).

    The project's own venv wins; otherwise `python3` on PATH. Never the interpreter running the hook.
    """
    for rel in (".venv/bin/python", "venv/bin/python", ".venv/Scripts/python.exe", "venv/Scripts/python.exe"):
        candidate = ws / rel
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate), rel
    found = shutil.which("python3") or shutil.which("python")
    return (found, "python3") if found else (sys.executable, "python3")


def _python_has_pytest(py: str, ws: Path) -> bool:
    try:
        return subprocess.run([py, "-c", "import pytest"], cwd=str(ws), capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _has_pytest_config(ws: Path) -> bool:
    if (ws / "pytest.ini").exists():
        return True
    for name, marker in (("pyproject.toml", "[tool.pytest"), ("setup.cfg", "[tool:pytest]"), ("tox.ini", "[pytest]")):
        try:
            if marker in (ws / name).read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            pass
    return False


def _python_test_dirs(ws: Path) -> Dict[Path, List[str]]:
    """Directories under tests/ or test/ that directly hold test files -> unittest patterns they need."""
    found: Dict[Path, List[str]] = {}
    for top in ("tests", "test"):
        base = ws / top
        if not base.is_dir():
            continue
        for d in [base, *sorted(p for p in base.rglob("*") if p.is_dir())]:
            if any(part in SKIP_DIRS for part in d.relative_to(ws).parts):
                continue
            patterns = [pat for pat in ("test*.py", "*_test.py") if any(d.glob(pat))]
            if patterns:
                found[d] = patterns
    return found


def _unittest_commands(py: str, label_py: str, ws: Path, dirs: Dict[Path, List[str]]) -> List[Dict[str, Any]]:
    """One `unittest discover` per test location: discovery only recurses through packages."""
    def rel(p: Path) -> str:
        return p.relative_to(ws).as_posix() or "."

    seen = set()
    runs = []
    for d, patterns in dirs.items():
        top = d
        if (d / "__init__.py").exists():
            while top.parent != ws and (top.parent / "__init__.py").exists():
                top = top.parent
        for pat in patterns:
            key = (top, pat)
            if key in seen:
                continue
            seen.add(key)
            args = ["-m", "unittest", "discover", "-s", rel(top)]
            if (top / "__init__.py").exists():
                args += ["-t", rel(top.parent)]
            if pat != "test*.py":
                args += ["-p", pat]
            runs.append({"cmd": [py, *args], "label": " ".join([label_py, *args]), "shell": False})
    return runs


def detect_test_commands(
    ws: Path, cfg: Optional[Dict[str, Any]] = None, python_root: Optional[Path] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """-> (runs, skip_reasons). Every detected ecosystem contributes its test command(s).

    Each run is {cmd, label, shell}. `python_root` is where the project interpreter is looked up
    (defaults to `ws`; the baseline worktree passes the real checkout, which owns the venv).
    """
    cfg = cfg or load_verify_config(ws)
    configured = str(cfg.get("test_command") or "").strip()
    if configured:
        return [{"cmd": configured, "label": configured, "shell": True}], []

    reasons: List[str] = []
    runs: List[Dict[str, Any]] = []
    py_dirs = _python_test_dirs(ws)
    if py_dirs:
        py, label_py = find_project_python(python_root or ws)
        if _python_has_pytest(py, ws):
            args = ["-m", "pytest", "-q"]  # no -x: the gate compares the full failure set with the baseline
            if not _has_pytest_config(ws):
                args.extend(sorted({d.relative_to(ws).parts[0] for d in py_dirs}))
            runs.append({"cmd": [py, *args], "label": " ".join([label_py, *args]), "shell": False})
        else:
            runs.extend(_unittest_commands(py, label_py, ws, py_dirs))

    pkg = ws / "package.json"
    if pkg.exists():
        try:
            script = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}).get("test", "")
        except (OSError, ValueError):
            script = ""
        if script and "no test specified" not in script:
            if shutil.which("npm"):
                runs.append({"cmd": ["npm", "test"], "label": "npm test", "shell": False})
            else:
                reasons.append("npm not installed")
        else:
            reasons.append("package.json has no test script")
    if (ws / "go.mod").exists():
        if shutil.which("go"):
            runs.append({"cmd": ["go", "test", "./..."], "label": "go test ./...", "shell": False})
        else:
            reasons.append("go not installed")
    if (ws / "Cargo.toml").exists():
        if shutil.which("cargo"):
            runs.append({"cmd": ["cargo", "test"], "label": "cargo test", "shell": False})
        else:
            reasons.append("cargo not installed")
    makefile = next((ws / n for n in ("Makefile", "makefile", "GNUmakefile") if (ws / n).exists()), None)
    if makefile is not None and not runs:  # make is the fallback, not one more runner
        try:
            has_target = re.search(r"^test\s*:", makefile.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
        except OSError:
            has_target = None
        if has_target:
            if shutil.which("make"):
                runs.append({"cmd": ["make", "test"], "label": "make test", "shell": False})
            else:
                reasons.append("make not installed")
    if not runs and not reasons:
        reasons.append("no test command detected (set verify.test_command in .harness/config.yaml)")
    return runs, reasons


_UNITTEST_FAILED = re.compile(r"^(?:FAIL|ERROR): (.+?)\s*$", re.MULTILINE)
_PYTEST_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+\.py(?:::\S+)?)(?: - .*)?$", re.MULTILINE)


def parse_failing_ids(output: str) -> Optional[List[str]]:
    """Failing test ids from unittest (`FAIL: test_x (mod.Class)`) or pytest (`FAILED path::name`) output."""
    ids = {m.group(1) for m in _UNITTEST_FAILED.finditer(output)} | {m.group(1) for m in _PYTEST_FAILED.finditer(output)}
    return sorted(ids) or None


# --------------------------------------------------------------------------- pipeline

def _is_jsonc(f: Path) -> bool:
    """JSON files that editors and tools read with comments and trailing commas allowed."""
    name = f.name.lower()
    return (
        name.endswith(".jsonc")
        or name.startswith(("tsconfig", "jsconfig"))
        or name == "devcontainer.json"
        or ".vscode" in f.parts
        or ".devcontainer" in f.parts
    )


def _strip_jsonc(text: str) -> str:
    """Drop // and /* */ comments (outside strings) and trailing commas so json.loads can check the rest."""
    out: List[str] = []
    i, n, in_str = 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            in_str = c != '"'
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


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

    def __init__(
        self,
        workspace_dir: Optional[Path] = None,
        profile: Optional[str] = None,
        deadline: Optional[float] = None,
        python_root: Optional[Path] = None,
    ):
        """`deadline` is an absolute time.monotonic() value shared by every command of this pipeline."""
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()
        self.profile = (profile or detect_project_profile(self.workspace_dir)).lower()
        self.config = load_verify_config(self.workspace_dir)
        self.deadline = deadline
        self.python_root = python_root

    def remaining(self, limit: float) -> float:
        """`limit` clipped to what is left of the shared deadline (never negative)."""
        if self.deadline is None:
            return limit
        return max(0.0, min(limit, self.deadline - time.monotonic()))

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
            budget = self.remaining(20)
            if budget <= 0:  # out of time: the rest of the files stay unchecked, not failed
                break
            rc, out, timed_out = _run_command([node, "--check", str(f)], self.workspace_dir, budget)
            if rc == 0 or timed_out:
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
            try:
                if suffix == ".json":
                    text = f.read_text(encoding="utf-8-sig")
                    json.loads(_strip_jsonc(text) if _is_jsonc(f) else text)
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

    def _run_one_test(self, run: Dict[str, Any], limit: float) -> Dict[str, Any]:
        label = run["label"]
        start = time.time()
        if limit <= 0:
            return {"command": label, "status": "timeout", "reason": "time budget exhausted", "duration": 0.0,
                    "output_tail": "", "failing_ids": None}
        rc, out, timed_out = _run_command(run["cmd"], self.workspace_dir, limit, shell=run["shell"])
        result: Dict[str, Any] = {
            "command": label,
            "duration": round(time.time() - start, 1),
            "output_tail": _tail(out),
            "failing_ids": None,
        }
        if timed_out:
            result.update(status="timeout", reason=f"exceeded {round(limit)}s")
        elif (rc == 5 and "pytest" in label) or re.search(r"^Ran 0 tests", out, re.MULTILINE):
            reason = "no tests collected"
            if "unittest" in label:
                reason += " (unittest found none; pytest-style tests need pytest installed for this interpreter)"
            result.update(status="skipped", reason=reason)
        elif rc == 0:
            result["status"] = "passed"
        else:
            result.update(status="failed", failing_ids=parse_failing_ids(out))
        return result

    def run_tests(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Run the test command of every detected ecosystem.

        -> {status: passed|failed|timeout|skipped, command, reason, output_tail, duration, runs: [...]}
        where each run has {command, status, reason, output_tail, duration, failing_ids}.
        """
        if int(os.environ.get("KHOROS_VERIFY_DEPTH", "0") or 0) >= 1:
            return {"status": "skipped", "reason": "nested verify run (avoids recursion)", "runs": []}
        runs, reasons = detect_test_commands(self.workspace_dir, self.config, self.python_root)
        if not runs:
            return {"status": "skipped", "reason": "; ".join(reasons), "runs": []}
        limit = timeout if timeout is not None else self.config["test_timeout"]
        results = [self._run_one_test(run, self.remaining(limit)) for run in runs]
        statuses = [r["status"] for r in results]
        status = next((st for st in ("failed", "timeout", "passed") if st in statuses), "skipped")
        shown = [r for r in results if r["status"] == status] if status != "passed" else results
        return {
            "status": status,
            "command": ", ".join(r["command"] for r in shown),
            "reason": "; ".join(f"{r['command']}: {r['reason']}" for r in results if r.get("reason")),
            "duration": round(sum(r["duration"] for r in results), 1),
            "output_tail": "\n".join(r["output_tail"] for r in shown if r["status"] in ("failed", "timeout")),
            "runs": results,
        }

    def run_lint_commands(self, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        violations = []
        limit = timeout if timeout is not None else self.config["test_timeout"]
        for command in self.config["lint_commands"]:
            budget = self.remaining(limit)
            if budget <= 0:
                violations.append(
                    {"file": str(command), "line": 0, "rule": "LINT_FAILURE", "severity": "WARN",
                     "message": "not run: gate time budget exhausted"}
                )
                continue
            rc, out, timed_out = _run_command(str(command), self.workspace_dir, budget, shell=True)
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
        scope_label: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        scope = "full"
        if targets:
            scope = scope_label or "targets"
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
            if not test_result.get("runs"):
                skipped.append(f"unit-tests (skipped: {test_result['reason']})")
            else:
                if any(r["status"] != "skipped" for r in test_result["runs"]):
                    checks_run.append("unit-tests")
                for r in test_result["runs"]:
                    if r["status"] == "skipped":
                        skipped.append(f"unit-tests (skipped: {r['command']}: {r['reason']})")
                    elif r["status"] == "timeout":
                        timed_out = True
                        violations.append(
                            {
                                "file": r["command"],
                                "line": 0,
                                "rule": "TEST_TIMEOUT",
                                "message": f"{r['command']} {r['reason']}",
                                "severity": "ERROR",
                            }
                        )
                    elif r["status"] == "failed":
                        violations.append(
                            {
                                "file": r["command"],
                                "line": 0,
                                "rule": "UNIT_TEST_FAILURE",
                                "message": f"`{r['command']}` failed",
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
    runs = [r for r in tests.get("runs") or [] if r.get("status") in ("failed", "timeout") and r.get("output_tail")]
    if not runs and tests.get("status") in ("failed", "timeout") and tests.get("output_tail"):
        runs = [{"command": tests.get("command"), "output_tail": tests["output_tail"]}]
    for r in runs:
        out.append(f"  Last output of `{r.get('command')}` (tail):")
        out.extend("    " + l for l in r["output_tail"].splitlines()[-max(tail_lines // len(runs), 10):])
    out.extend(f"  {s}" for s in report.get("skipped", []))
    return "\n".join(out)


if __name__ == "__main__":
    pipeline = VerificationPipeline()
    ok, result = pipeline.run(run_tests=True)
    print(json.dumps(result, indent=2))
    sys.exit(0 if ok else 1)
