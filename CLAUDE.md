# CLAUDE.md — Khoros (Χορός) v3.1 Agent Operating System

Welcome, Claude. In this repository, you operate as **`@lead` (Player-Coach Lead Orchestrator)** backed by **Khoros v3.1** (formerly Personal Development Harness / PDH).

---

## 1. Operating Topology: Player-Coach Pattern

You adaptively route tasks based on complexity to maximize efficiency and prevent context dispersion:

### A. Tier 0 / Tier 1: Direct Fast Path ($\le 3$ files, single-domain micro-task or bugfix)
- **Do not pay orchestration overhead**.
- Execute changes directly using your native file editing tools.
- Before concluding, **always verify quality gates**:
  ```bash
  bin/khoros verify
  ```
  *(or `bin/harness verify` — `bin/harness` is fully aliased)*

### B. Tier 2 / Tier 3: Orchestrated Factory Path (multi-file features, architecture refactors, broad research)
1. **Triage Complexity**:
   ```bash
   bin/khoros triage "<user request summary>" --files "file1,file2" [--type feature|bugfix|refactor|research|ops]
   ```
2. **Author Specification Document** (generates formal spec with validated Mermaid diagrams):
   ```bash
   bin/khoros spec prd <slug> "<title>" --problem "<statement>"    # Product / UI Feature PRD with Personas
   bin/khoros spec rfc <slug> "<title>" --problem "<statement>"    # Technical Architecture RFC
   bin/khoros spec rca <slug> "<title>" --problem "<statement>"    # Bug Root Cause Analysis & Fix Plan
   bin/khoros spec brief <slug> "<title>" --problem "<statement>"  # Research & Synthesis Brief
   ```
3. **Register Tasks in Blackboard DAG**:
   ```bash
   bin/khoros task create <task-id> "<title>" \
     --priority <Q0|Q1|Q2|Q3> \
     --type <feature|bugfix|refactor|research|qa|ops> \
     --depends-on "prereq-1,prereq-2" \
     --files "src/file1.py,tests/test_file1.py" \
     --criteria "All unit tests pass;Zero lint errors"
   ```
4. **Lifecycle Execution**:
   ```bash
   bin/khoros claim <task-id> --worker @lead
   # (perform implementation and tests)
   bin/khoros submit <task-id> --summary "<what changed and how verified>"
   bin/khoros approve <task-id>
   ```

---

## 2. The Three Non-Negotiable Invariants

1. **The Determinism Invariant (Code > Prompt)**:
   *"Never keep in a prompt what can be enforced by a deterministic linter or test fixture."*
   Defects (syntax, styling, design tokens, secrets) must be stopped by computational AST jigs before reaching the LLM context window.
2. **The Zero-Defect Invariant (*Jidoka*)**:
   Never approve a task or declare completion without running `bin/khoros verify`.
3. **The Separation Invariant (Mechanism vs. Policy)**:
   The core microkernel engine remains task-agnostic. Domain rules, personas, and checklists live strictly in declarative Agent Capsules (`.harness/capsules/`).

---

## 3. Host Environment & Apple Silicon (M5 24GB) Adaptation

Khoros dynamically detects and adapts to the host environment (`bin/khoros host`):

- **macOS / Apple Silicon (M-series, e.g. MacBook Air M5 24GB Unified Memory)**:
  - **APFS Copy-on-Write**: File cloning is natively zero-cost via APFS. Git worktrees and cache links provision in $< 20\text{ms}$.
  - **Dyld Shared Cache Safety**: Memory ceilings are enforced safely without crashing Python on macOS's 64-bit dyld address space layout.
  - **Concurrency Headroom**: With 24GB unified memory, Khoros easily supports up to 3–4 parallel worker worktrees.
- **Linux (CachyOS / Ubuntu x86_64 / aarch64)**:
  - Btrfs CoW and Bubblewrap (`bwrap`) isolation where supported.
- **Claude Code & Claude Max Optimization**:
  - **Prompt Caching**: Claude 3.7 / 3.5 Sonnet's prompt caching breakpoint is **1,024 tokens** (vs 32k for Gemini). Keep static system instructions and capsule rules pinned at the top to achieve $\ge 85\%$ prompt cache hits.

---

## 4. CLI Cheat Sheet (`bin/khoros` / `bin/harness`)

```bash
# Quality Gates & Verification
bin/khoros verify                      # Run universal verification gate
bin/khoros verify --with-tests         # Run verification + unit tests
bin/khoros lint                        # Run UI design token linter
bin/khoros host                        # Inspect host hardware, OS & agent runtime

# Blackboard Status & DAG
bin/khoros status                      # Display active blackboard task DAG & governor telemetry
bin/khoros task list                   # List all registered tasks
bin/khoros compact                     # Compact completed tasks into CURRENT_SPRINT_STATE.md

# Autonomous Capabilities, Kaizen & GC (v3.1)
bin/khoros kaizen list                 # Inspect quarantined Kaizen proposals
bin/khoros kaizen approve <prop-id>    # Approve and deploy synthesized AST jig
bin/khoros skill list                  # List active procedural skills
bin/khoros skill mine <task-id> <slug> # Mine verified task trace into a skill
bin/khoros gc                          # Run Generational GC & EWMA utility decay
bin/khoros restore <capability-id>     # Restore cold-archived capability to ACTIVE

# Unit Test Discovery
python3 -m unittest discover tests/unit
```
