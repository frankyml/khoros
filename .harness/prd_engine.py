#!/usr/bin/env python3
"""
Personal Development Harness (PDH) - Product & Flow Definition Engine
Generates formal PRDs with validated Mermaid state machines and user journeys.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
DOCS_PRD_DIR = WORKSPACE_DIR / "docs" / "prd"
DOCS_FLOWS_DIR = WORKSPACE_DIR / "docs" / "flows"


class PRDEngine:
    def __init__(self, prd_dir: Path = DOCS_PRD_DIR, flows_dir: Path = DOCS_FLOWS_DIR):
        self.prd_dir = prd_dir
        self.flows_dir = flows_dir
        self.prd_dir.mkdir(parents=True, exist_ok=True)
        self.flows_dir.mkdir(parents=True, exist_ok=True)

    def validate_mermaid(self, mermaid_content: str) -> List[str]:
        errors = []
        valid_headers = [
            "flowchart TD", "flowchart LR", "graph TD", "graph LR",
            "stateDiagram-v2", "stateDiagram", "sequenceDiagram", "classDiagram", "erDiagram"
        ]
        lines = [line.strip() for line in mermaid_content.strip().split("\n") if line.strip()]
        if not lines:
            return ["Mermaid diagram is empty."]
        
        first_line = lines[0]
        if not any(first_line.startswith(h) for h in valid_headers):
            errors.append(f"Invalid or unsupported Mermaid header '{first_line}'. Must start with one of {valid_headers}")

        # Check for unquoted parenthesis or brackets in labels
        for idx, line in enumerate(lines, 1):
            if "-->" in line or "-->|" in line or ":" in line:
                # Check for suspicious unquoted labels with parentheses
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
    ) -> Path:
        personas = target_personas or [
            "Alex (Impatient Power User - wants zero-latency, keyboard/gesture efficiency)",
            "Sam (Non-Technical Novice - needs intuitive affordances, zero jargon)",
            "Jordan (A11y & Screen-Reader User - requires 48dp tap targets, dynamic text scaling)"
        ]
        flows = key_flows or ["Authentication & Session Bootstrap", "Core Feature Walkthrough", "Offline Mutate & Auto-Sync"]

        target_file = self.prd_dir / f"{slug}.md"
        content = f"""# Product Requirement Document (PRD): {title}
**Status**: Draft / In-Review  
**Architecture Spec**: Clean / Hexagonal Architecture  
**Target Platforms**: Native Mobile (Kotlin Multiplatform / Compose) & Web Companion  

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

### Primary Navigation Flow
```mermaid
flowchart TD
    Start([Launch App]) --> AuthCheck{Active Session?}
    AuthCheck -- Yes --> Dashboard[Home Dashboard]
    AuthCheck -- No --> AuthScreen[Login / Register]
    AuthScreen --> BiometricPrompt[Biometric / Keystore Auth]
    BiometricPrompt --> Dashboard
    Dashboard --> OfflineAction[Perform Local Mutation]
    OfflineAction --> SyncWorker[WorkManager Background OCC Sync]
    SyncWorker --> SyncSuccess([State Synchronized])
```

### State Machine Lifecycle
```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Loading : User Triggered Action
    Loading --> Success : 200 OK or Local Cache Hit
    Loading --> Error : Validation or Network Fault
    Error --> Idle : User Retry or Dismiss
    Success --> Idle : Reset
```

---

## 4. Key Functional Requirements
"""
        for idx, f in enumerate(flows, 1):
            content += f"{idx}. **{f}**: High-fidelity native implementation adhering to `.harness/design-tokens.json`.\n"

        content += """
---

## 5. Non-Functional & Native Quality Requirements
- **60/120 Hz Native Fluidity**: Zero dropped VSYNC frames, Jank Frame Rate $< 1.0\\%$ verified via Android `dumpsys gfxinfo framestats`.
- **Offline-First Synchronization**: Local persistence backed by Field-Level Optimistic Concurrency Control (OCC) and mutation journals.
- **Cybersecurity & Hardening**: STRIDE threat modeling passed, zero plaintext secrets, Android Keystore biometrics.
- **Design System Enforcement**: Must pass `.harness/linter.py` with zero raw hex color codes and strict 4dp grid alignment.
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
