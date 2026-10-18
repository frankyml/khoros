#!/usr/bin/env python3
"""
Personal Development Harness (PDH) v2.0 - Specification & Product Definition Engine
Supports multi-archetype specifications across generic and mobile domains:
- prd: Product Requirement Document (User Flows, State Machines, Personas)
- rfc: Technical Architecture / Engineering RFC (Boundaries, Sequence Flows, Trade-offs)
- rca: Root Cause Analysis & Bug Resolution Spec (Fault Tree, Hypothesis Matrix, Regression Plan)
- brief: Research & Synthesis Brief (Questions, Methodology, Evidence Matrix)
"""

import json
import re
import sys
from pathlib import Path
from typing import List, Optional


class PRDEngine:
    VALID_SPEC_TYPES = ("prd", "rfc", "rca", "brief")

    def __init__(
        self,
        prd_dir: Optional[Path] = None,
        flows_dir: Optional[Path] = None,
        workspace_dir: Optional[Path] = None,
    ):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()
        self.prd_dir = Path(prd_dir) if prd_dir else (self.workspace_dir / "docs" / "prd")
        self.flows_dir = Path(flows_dir) if flows_dir else (self.workspace_dir / "docs" / "flows")
        self.prd_dir.mkdir(parents=True, exist_ok=True)
        self.flows_dir.mkdir(parents=True, exist_ok=True)

    def _detect_profile(self, explicit_profile: Optional[str] = None) -> str:
        if explicit_profile:
            return explicit_profile.lower()
        cfg = self.workspace_dir / ".harness" / "config.yaml"
        if cfg.exists():
            text = cfg.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^\s*profile:\s*[\"']?([a-zA-Z0-9_-]+)[\"']?", text, re.MULTILINE)
            if m:
                return m.group(1).lower()
        if (self.workspace_dir / "shared" / "src").exists() or (self.workspace_dir / "androidApp" / "src").exists():
            return "mobile-kmp"
        if (self.workspace_dir / "pyproject.toml").exists() or (self.workspace_dir / "tests" / "unit").exists():
            return "python"
        if (self.workspace_dir / "package.json").exists():
            return "web"
        return "generic"

    def _load_project_personas(self) -> List[str]:
        personas_dir = self.workspace_dir / ".harness" / "personas"
        loaded = []
        if personas_dir.exists():
            for p_file in sorted(personas_dir.glob("*.json")):
                try:
                    data = json.loads(p_file.read_text(encoding="utf-8"))
                    name = data.get("name", p_file.stem)
                    arch = data.get("archetype", "User Persona")
                    prios = ", ".join(data.get("priorities", [])[:2])
                    loaded.append(f"{name} ({arch} — {prios})" if prios else f"{name} ({arch})")
                except Exception:
                    continue
        if loaded:
            return loaded
        return [
            "Alex (Impatient Power User - wants zero-latency, keyboard/gesture efficiency)",
            "Sam (Non-Technical Novice - needs intuitive affordances, zero jargon)",
            "Jordan (A11y & Screen-Reader User - requires 48dp tap targets, dynamic text scaling)",
        ]

    def validate_mermaid(self, mermaid_content: str) -> List[str]:
        errors = []
        valid_headers = [
            "flowchart TD", "flowchart TB", "flowchart LR",
            "graph TD", "graph TB", "graph LR",
            "stateDiagram-v2", "stateDiagram", "sequenceDiagram", "classDiagram", "erDiagram"
        ]
        lines = [line.strip() for line in mermaid_content.strip().split("\n") if line.strip()]
        if not lines:
            return ["Mermaid diagram is empty."]

        first_line = lines[0]
        if not any(first_line.startswith(h) for h in valid_headers):
            errors.append(f"Invalid or unsupported Mermaid header '{first_line}'. Must start with one of {valid_headers}")

        for idx, line in enumerate(lines, 1):
            if "-->" in line or "-->|" in line or ":" in line:
                if re.search(r"\[[^\"\]]*\([^\"\]]*\)[^\"\]]*\]", line):
                    errors.append(f"Line {idx}: Unquoted parentheses in node label. Quote label: id[\"Label (Info)\"]")

        return errors

    def create_prd(
        self,
        slug: str,
        title: str,
        problem_statement: str,
        target_personas: Optional[List[str]] = None,
        key_flows: Optional[List[str]] = None,
        profile: Optional[str] = None,
    ) -> Path:
        active_profile = self._detect_profile(profile)
        personas = target_personas or self._load_project_personas()
        flows = key_flows or [
            "Primary User Flow & Ergonomics",
            "Local Persistence & State Integrity",
            "Offline Recovery & Guardrails",
        ]

        if active_profile == "mobile-kmp":
            platform_line = "Native Mobile (Kotlin Multiplatform / Compose) & Web Companion"
            nfr_block = """- **60/120 Hz Native Fluidity**: Zero dropped VSYNC frames, Jank Frame Rate $< 1.0\\%$ verified via `frame-pacing-assert`.
- **Offline-First Durability**: Local persistence backed by deterministic state repositories.
- **Cybersecurity & Hardening**: STRIDE threat modeling passed, zero plaintext secrets, `allowBackup=false`.
- **Design System Enforcement**: Must pass `harness verify` / `harness lint` with zero raw hex color codes and clean 2dp/4dp spacing alignment."""
        else:
            platform_line = f"Cross-Domain ({active_profile.upper()} Profile)"
            nfr_block = """- **Deterministic Verification**: Must pass `harness verify` (syntax, unit tests, lint, and secret hygiene gates).
- **State & Concurrency Integrity**: Idempotent operations with clear error recovery and atomic persistence.
- **Security & Secret Hygiene**: STRIDE threat modeling passed, zero hardcoded credentials or plaintext secrets.
- **Ergonomics & Observability**: Structured telemetry, actionable error messages, and clean modularity."""

        target_file = self.prd_dir / f"{slug}.md"
        content = f"""# Product Requirement Document (PRD): {title}
**Status**: Draft / In-Review  
**Architecture Spec**: Clean / Hexagonal Architecture  
**Target Platforms**: {platform_line}  

---

## 1. Executive Summary & Problem Statement
{problem_statement}

---

## 2. Target Personas & Jobs-To-Be-Done (JTBD)
"""
        for p in personas:
            content += f"- **{p}**\n"

        content += """
---

## 3. User Flows & State Machine Specifications

### Primary Execution Flow
```mermaid
flowchart TD
    Start([Trigger Action]) --> Validate{Input & Context Valid?}
    Validate -- Yes --> Execute[Execute Core Domain Logic]
    Validate -- No --> Fault[Structured Validation Error]
    Execute --> PersistState[Commit State & Audit Event]
    PersistState --> Completed([Output Verified])
```

### State Machine Lifecycle
```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Loading : User Triggered Action
    Loading --> Success : State Committed & Verified
    Loading --> Error : Validation or Guardrail Fault
    Error --> Idle : User Retry or Dismiss
    Success --> Idle : Reset
```

---

## 4. Key Functional Requirements
"""
        for idx, f in enumerate(flows, 1):
            content += f"{idx}. **{f}**: Deterministic implementation adhering to project architecture and `.harness/config.yaml`.\n"

        content += f"""
---

## 5. Non-Functional & Quality Requirements
{nfr_block}
"""
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(content)

        return target_file

    def create_spec(
        self,
        spec_type: str,
        slug: str,
        title: str,
        problem_statement: str,
        profile: Optional[str] = None,
    ) -> Path:
        stype = spec_type.lower().strip()
        if stype not in self.VALID_SPEC_TYPES:
            raise ValueError(f"Unsupported spec type '{spec_type}'. Must be one of {self.VALID_SPEC_TYPES}")

        if stype == "prd":
            return self.create_prd(slug, title, problem_statement, profile=profile)

        active_profile = self._detect_profile(profile)
        spec_dir = self.workspace_dir / "docs" / stype
        spec_dir.mkdir(parents=True, exist_ok=True)
        target_file = spec_dir / f"{slug}.md"

        if stype == "rfc":
            content = f"""# Technical RFC: {title}
**Status**: Proposed  
**Profile**: `{active_profile}`  
**Orchestration Tier**: Tier 2 (Multi-Step Architecture & Implementation)  

---

## 1. Context & Problem Statement
{problem_statement}

---

## 2. Proposed Architecture & Boundaries
```mermaid
flowchart LR
    Input([Caller / CLI / API]) --> Core["Core Domain Logic"]
    Core --> Adapter["Persistence / External Adapter"]
    Core --> Verify["Verification Gate (harness verify)"]
```

### Key Design Decisions
1. **Separation of Concerns**: Core domain logic remains decoupled from I/O and presentation adapters.
2. **Backwards Compatibility**: Existing interfaces and schemas migrate cleanly without breaking callers.
3. **Failure Modes & Rollback**: All state mutations are atomic or guarded by fencing tokens.

---

## 3. Task Breakdown & Verification Plan
- [ ] Define interfaces and data contracts.
- [ ] Implement core logic and unit tests.
- [ ] Run `harness verify` and independent `@critic` review.
"""
        elif stype == "rca":
            content = f"""# Root Cause Analysis (RCA): {title}
**Status**: Investigating  
**Profile**: `{active_profile}`  

---

## 1. Symptom & Reproduction Steps
{problem_statement}

---

## 2. Fault Tree & Causal Chain
```mermaid
flowchart TD
    Symptom["Observed Symptom / Failure"] --> H1["Hypothesis 1: State / Concurrency Race"]
    Symptom --> H2["Hypothesis 2: Boundary / Input Validation Fault"]
    H1 --> RootCause["Verified Root Cause"]
    RootCause --> Fix["Targeted Fix + Regression Test"]
```

---

## 3. Fix Strategy & Regression Guardrails
1. **Minimal Reproducer**: Add a failing test reproducing the exact fault before applying the fix.
2. **Remediation**: Fix the underlying cause rather than masking symptoms.
3. **Verification Gate**: Confirm `harness verify` passes with zero regressions.
"""
        else:  # brief (Research & Synthesis Brief)
            content = f"""# Research & Synthesis Brief: {title}
**Status**: Active Research  
**Profile**: `{active_profile}`  

---

## 1. Objective & Core Questions
{problem_statement}

---

## 2. Research Methodology & Synthesis Pipeline
```mermaid
flowchart LR
    Query["Research Questions"] --> Gather["Primary Sources & Codebase Audit (@explorer)"]
    Gather --> Compare["Trade-off & Evidence Matrix"]
    Compare --> Synthesis["Actionable Recommendations (@lead)"]
```

---

## 3. Evaluation Matrix & Deliverables
| Option / Hypothesis | Primary Strengths | Failure Modes / Risks | Verdict |
| :--- | :--- | :--- | :--- |
| Baseline Approach | Low complexity | Limited scalability | Reference |
| Proposed Iteration | High leverage, SOTA aligned | Requires migration step | Recommended |
"""

        with open(target_file, "w", encoding="utf-8") as f:
            f.write(content)
        return target_file


if __name__ == "__main__":
    engine = PRDEngine()
    slug = sys.argv[1] if len(sys.argv) > 1 else "sample-feature"
    title = sys.argv[2] if len(sys.argv) > 2 else "Core App Foundation"
    path = engine.create_prd(slug, title, "Provide a seamless offline-first native experience.")
    print(f"PRD generated at: {path}")
