---
name: development-harness
description: >-
  Khoros (formerly Personal Development Harness) v3.1 with Player-Coach Lead Orchestrator (@lead)
  for generic software engineering, research, Python/CLI, web, and Android/KMP projects
  (Fluffi, Gainsmith, personal-development-harness, or any workspace with .harness/).
  Covers adaptive complexity triage, multi-archetype specs (PRD/RFC/RCA/Brief), SQLite WAL
  blackboard DAG orchestration, zero-loss subagent task contracts, universal multi-profile
  verification gates, autonomous capability synthesis, evolutionary skill grammar, and generational GC.
---

# Development Harness Skill (Khoros v3.1 — Player-Coach Lead Orchestrator)

Activate this skill automatically whenever working in any workspace that contains a `.harness/` directory (`Fluffi`, `Gainsmith`, `personal-development-harness`, or any initialized project), even when the user does not explicitly mention "harness" or "khoros" in their prompt. Primary CLI is `khoros` (with `harness` aliased for full backwards compatibility).

## 1. Operating as `@lead` (Player-Coach Orchestrator Topology)

When handling a user request in a `.harness/` workspace, you act as **`@lead` (Lead Orchestrator)** and route work by complexity tier so you never pay subagent latency/telephone-game costs on simple tasks, while protecting your strategic context window on large tasks:

- **Triage Complexity**:
  ```bash
  khoros triage "<user request summary>" --files "file1,file2" [--type feature|bugfix|refactor|research|qa|ops]
  ```
  - **`T0_MICRO` / `T1_SCOPED` ($\le 3$ files, single domain)**: **Direct Fast Path.** Execute directly in the main agent loop, then run `khoros verify`.
  - **`T2_ORCHESTRATED` / `T3_PARALLEL_DAG` (multi-file feature, architecture refactor, or broad research)**: **Subagent Fan-Out Path.**
    1. Create a domain-appropriate spec (`khoros spec <prd|rfc|rca|brief> ...`).
    2. Register tasks with DAG dependencies (`--depends-on`), target files (`--files`), and acceptance criteria (`--criteria`) in `blackboard.db`.
    3. Generate a zero-telephone-game **Subagent Dispatch Packet** via `khoros brief <task-id> --role <@explorer|@builder|@critic>` and pass it to `invoke_subagent` (use `Workspace="share"` for parallel `@builder` subagents; max 2 concurrent workers).
    4. Enforce **Generator–Verifier Separation**: verify completed subagent work with `khoros verify` and an independent `@critic` review before `khoros approve <task-id>`.

---

## 2. Domain Profiles & Multi-Archetype Specifications

Khoros decouples the core orchestration engine from domain-specific checks via profiles (`generic`, `python`, `mobile-kmp`, `web`, `research`):

- **Inspect or Switch Profile**:
  ```bash
  khoros profile show
  khoros profile set <generic|python|mobile-kmp|web|research>
  ```
- **Create Domain-Appropriate Specifications** (`docs/<type>/<slug>.md` with validated Mermaid diagrams):
  ```bash
  khoros spec prd <slug> "<title>" --problem "<statement>"    # Product / UI Feature PRD with Personas
  khoros spec rfc <slug> "<title>" --problem "<statement>"    # Technical / Architecture RFC
  khoros spec rca <slug> "<title>" --problem "<statement>"    # Bug Root Cause Analysis & Fix Plan
  khoros spec brief <slug> "<title>" --problem "<statement>"  # Research & Synthesis Brief
  ```
  *(Backwards-compatible alias: `khoros prd <slug> "<title>" --problem "<statement>"`)*

---

## 3. Blackboard DAG Lifecycle & Zero-Loss Subagent Contracts

Tasks are tracked in `./.harness/blackboard.db` (SQLite in WAL mode, monotonic fencing tokens, 30-minute lease TTL, and DAG dependency barriers):

- **Check Status, Profile & DAG Dependencies**: `khoros status` or `khoros monitor`
- **Create Task with Contract & DAG Edges**:
  ```bash
  khoros task create <task-id> "<title>" \
    --priority <Q0|Q1|Q2|Q3> \
    --type <feature|bugfix|refactor|research|qa|ops> \
    --depends-on "prereq-1,prereq-2" \
    --files "src/foo.py,tests/test_foo.py" \
    --criteria "Unit tests pass;Zero lint errors" \
    --spec "docs/rfc/my-spec.md"
  ```
- **Generate Subagent Prompt Packet (Eliminates Telephone Game)**:
  ```bash
  khoros brief <task-id> --role @builder
  ```
- **Dispatch (Enforces DAG Barriers & 2-Worker Ceiling)**:
  ```bash
  khoros dispatch [<task-id>] [--worker <name>]
  ```
- **Heartbeat / Submit / Review / Approve / Reject**:
  ```bash
  khoros heartbeat <task-id>
  khoros submit <task-id> --summary "<what changed and how it was verified>"
  khoros review <task-id>
  khoros approve <task-id>
  khoros reject <task-id> --feedback "<actionable reason>"
  khoros compact  # Compacts sprint state into CURRENT_SPRINT_STATE.md
  ```

---

## 4. Universal Verification Gate & Profile Tooling

- **Run Universal Verification Pipeline** (automatically runs secret hygiene scan, UI design token linter when UI files exist, Python syntax validation, Mermaid spec checks, and optional unit tests):
  ```bash
  khoros verify [--with-tests] [targets...]
  ```
- **UI Design System Linter** (`mobile-kmp` & `web` profiles):
  - Always reference `.harness/design-tokens.json` and project theme tokens (`FluffiTheme` / `GainsmithTheme`). Never write raw hex colors (`#...` or `Color(0x...)`) outside theme/token files, and align spacing (`padding`, `spacedBy`, `contentPadding`) to the 2dp/4dp grid.
  ```bash
  khoros lint [shared/src androidApp/src]
  ```
- **Native Android Crash Sentinel & 60/120 Hz Assertion** (`mobile-kmp` profile):
  ```bash
  crash-sentinel --check
  frame-pacing-assert
  ```
- **Synthetic Persona Evaluation**:
  ```bash
  khoros personas
  ```

---

## 5. Autonomous Capability Synthesis, Evolution & Generational GC (v3.1)

- **Kaizen Distillation & Proposal Management**:
  ```bash
  khoros kaizen list                # Inspect quarantined Kaizen proposals
  khoros kaizen inspect <prop-id>   # View AST diff, canary verification & attribution
  khoros kaizen approve <prop-id>   # Promote proposal to canonical jigs / rules
  khoros kaizen reject <prop-id>    # Reject proposal
  ```
- **Skill Lifecycle & Trajectory Mining**:
  ```bash
  khoros skill list                 # List active local skills
  khoros skill inspect <slug>       # View skill instructions and metadata
  khoros skill mine <task-id> <slug> # Mine verified execution trace into a reusable skill
  ```
- **Generational GC & Capability Restoration**:
  ```bash
  khoros gc                         # Run Macro-GC (EWMA utility decay & 3-phase safe eviction)
  khoros restore <capability-id>    # Restore soft-deprecated or cold-archived capability
  ```
