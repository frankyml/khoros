---
name: development-harness
description: >-
  Autonomous Development Harness (PDH v2.0) with Player-Coach Lead Orchestrator (@lead)
  for generic software engineering, research, Python/CLI, web, and Android/KMP projects
  (Fluffi, Gainsmith, personal-development-harness, or any workspace with .harness/).
  Covers adaptive complexity triage, multi-archetype specs (PRD/RFC/RCA/Brief), SQLite WAL
  blackboard DAG orchestration, zero-loss subagent task contracts, universal multi-profile
  verification gates, design token linting, 60/120Hz frame pacing, and persona evaluation.
---

# Development Harness Skill (PDH v2.0 — Player-Coach Lead Orchestrator)

Activate this skill automatically whenever working in any workspace that contains a `.harness/` directory (`Fluffi`, `Gainsmith`, `personal-development-harness`, or any initialized project), even when the user does not explicitly mention "harness" in their prompt.

## 1. Operating as `@lead` (Player-Coach Orchestrator Topology)

When handling a user request in a `.harness/` workspace, you act as **`@lead` (Lead Orchestrator)** and route work by complexity tier so you never pay subagent latency/telephone-game costs on simple tasks, while protecting your strategic context window on large tasks:

- **Triage Complexity**:
  ```bash
  harness triage "<user request summary>" --files "file1,file2" [--type feature|bugfix|refactor|research|qa|ops]
  ```
  - **`T0_MICRO` / `T1_SCOPED` ($\le 3$ files, single domain)**: **Direct Fast Path.** Execute directly in the main agent loop, then run `harness verify`.
  - **`T2_ORCHESTRATED` / `T3_PARALLEL_DAG` (multi-file feature, architecture refactor, or broad research)**: **Subagent Fan-Out Path.**
    1. Create a domain-appropriate spec (`harness spec <prd|rfc|rca|brief> ...`).
    2. Register tasks with DAG dependencies (`--depends-on`), target files (`--files`), and acceptance criteria (`--criteria`) in `blackboard.db`.
    3. Generate a zero-telephone-game **Subagent Dispatch Packet** via `harness brief <task-id> --role <@explorer|@builder|@critic>` and pass it to `invoke_subagent` (use `Workspace="share"` for parallel `@builder` subagents; max 2 concurrent workers).
    4. Enforce **Generator–Verifier Separation**: verify completed subagent work with `harness verify` and an independent `@critic` review before `harness approve <task-id>`.

---

## 2. Domain Profiles & Multi-Archetype Specifications

PDH v2.0 decouples the core orchestration engine from domain-specific checks via profiles (`generic`, `python`, `mobile-kmp`, `web`, `research`):

- **Inspect or Switch Profile**:
  ```bash
  harness profile show
  harness profile set <generic|python|mobile-kmp|web|research>
  ```
- **Create Domain-Appropriate Specifications** (`docs/<type>/<slug>.md` with validated Mermaid diagrams):
  ```bash
  harness spec prd <slug> "<title>" --problem "<statement>"    # Product / UI Feature PRD with Personas
  harness spec rfc <slug> "<title>" --problem "<statement>"    # Technical / Architecture RFC
  harness spec rca <slug> "<title>" --problem "<statement>"    # Bug Root Cause Analysis & Fix Plan
  harness spec brief <slug> "<title>" --problem "<statement>"  # Research & Synthesis Brief
  ```
  *(Backwards-compatible alias: `harness prd <slug> "<title>" --problem "<statement>"`)*

---

## 3. Blackboard DAG Lifecycle & Zero-Loss Subagent Contracts

Tasks are tracked in `./.harness/blackboard.db` (SQLite in WAL mode, monotonic fencing tokens, 30-minute lease TTL, and DAG dependency barriers):

- **Check Status, Profile & DAG Dependencies**: `harness status` or `harness monitor`
- **Create Task with Contract & DAG Edges**:
  ```bash
  harness task create <task-id> "<title>" \
    --priority <Q0|Q1|Q2|Q3> \
    --type <feature|bugfix|refactor|research|qa|ops> \
    --depends-on "prereq-1,prereq-2" \
    --files "src/foo.py,tests/test_foo.py" \
    --criteria "Unit tests pass;Zero lint errors" \
    --spec "docs/rfc/my-spec.md"
  ```
- **Generate Subagent Prompt Packet (Eliminates Telephone Game)**:
  ```bash
  harness brief <task-id> --role @builder
  ```
- **Dispatch (Enforces DAG Barriers & 2-Worker Ceiling)**:
  ```bash
  harness dispatch [<task-id>] [--worker <name>]
  ```
- **Heartbeat / Submit / Review / Approve / Reject**:
  ```bash
  harness heartbeat <task-id>
  harness submit <task-id> --summary "<what changed and how it was verified>"
  harness review <task-id>
  harness approve <task-id>
  harness reject <task-id> --feedback "<actionable reason>"
  harness compact  # Compacts sprint state into CURRENT_SPRINT_STATE.md
  ```

---

## 4. Universal Verification Gate & Profile Tooling

- **Run Universal Verification Pipeline** (automatically runs secret hygiene scan, UI design token linter when UI files exist, Python syntax validation, Mermaid spec checks, and optional unit tests):
  ```bash
  harness verify [--with-tests] [targets...]
  ```
- **UI Design System Linter** (`mobile-kmp` & `web` profiles):
  - Always reference `.harness/design-tokens.json` and project theme tokens (`FluffiTheme` / `GainsmithTheme`). Never write raw hex colors (`#...` or `Color(0x...)`) outside theme/token files, and align spacing (`padding`, `spacedBy`, `contentPadding`) to the 2dp/4dp grid.
  ```bash
  harness lint [shared/src androidApp/src]
  ```
- **Native Android Crash Sentinel & 60/120 Hz Assertion** (`mobile-kmp` profile):
  ```bash
  crash-sentinel --check
  frame-pacing-assert
  ```
- **Synthetic Persona Evaluation**:
  ```bash
  harness personas
  ```
