# Chapter 01: Evolution & Iterations

**Khoros** represents an architectural journey from simple local developer automations to an industrial-grade, self-improving AI software factory.

```
┌─────────────────┐      ┌─────────────────────────────┐      ┌──────────────────────────────────┐
│    PDH v1.0     │      │          PDH v2.0           │      │        Khoros (PDH v3.0)         │
│ (Mobile Scripts)│ ──►  │ (Player-Coach Blackboard DAG)│ ──► │(Self-Improving Software Factory) │
└─────────────────┘      └─────────────────────────────┘      └──────────────────────────────────┘
  • Bash scripts           • Adaptive Triage (T0-T3)            • Microkernel Decoupling
  • framestats parsing     • SQLite WAL Blackboard DAG          • Declarative Agent Capsules
  • Hardcoded linting      • Subagent Task Contracts            • In-Station Poka-Yoke AST Jigs
  • Mobile KMP focus       • Generator-Verifier Separation      • Bounded Kaizen Loop (Causal DAG)
```

---

## 1. PDH v1.0: Mobile / KMP Bash Script Automations

### Context & Motivations
PDH originated in the context of high-performance mobile applications (such as *Fluffi* and *Gainsmith*) targeting Android and Kotlin Multiplatform (KMP). Delivering fluid 60/120 Hz experiences required strict adherence to non-functional quality gates: zero dropped VSYNC frames, sub-1% jank, zero hardcoded hex colors, and a strict 4dp design grid.

### Key Features
- **`bin/crash-sentinel`**: Bash script monitoring Android `logcat` for ANR (Application Not Responding) traces and unhandled exceptions.
- **`bin/frame-pacing-assert`**: Automated parsing of Android `dumpsys gfxinfo framestats` to evaluate 95th-percentile frame durations and jank percentages.
- **`bin/harness` (v1.0)**: Initial command-line wrapper invoking linters and test suites.

### Architectural Limitations
1. **Domain Over-Specialization**: Tightly coupled to Android ADB and Kotlin Compose; unusable for generic Python, web, or backend projects.
2. **Brittle Script Chaining**: Lacked formal state persistence, dependency graphs, or concurrency control.
3. **High Human Cognitive Overhead**: The human developer had to manually orchestrate every step and interpret raw terminal logs.

---

## 2. PDH v2.0: Player-Coach Lead Orchestrator with SQLite Blackboard DAG

### Context & Motivations
As tasks expanded from micro-fixes to multi-file features and architecture refactors, LLM agents suffered from **the telephone game**: losing requirements across subagent handoffs, hallucinating file boundaries, and getting stuck in unguided loops.

PDH v2.0 introduced the **Player-Coach pattern** backed by a transactional blackboard.

### Key Milestones
1. **Adaptive Complexity Routing (`LeadRouter`)**:
   - **T0/T1 (Fast Path)**: Single-domain micro-tasks ($\le 3$ files) executed directly by the Lead in the main loop with zero delegation latency.
   - **T2/T3 (Orchestrated Path)**: Multi-file features decomposed into formal specifications (`prd`, `rfc`, `rca`, `brief`) and orchestrated across isolated specialist subagents.
2. **SQLite WAL Blackboard (`blackboard.db`)**:
   - Transactional task ledger with monotonic fencing tokens and atomic Compare-And-Swap (CAS) leases.
   - Full Directed Acyclic Graph (DAG) dependency barriers (`--depends-on`).
3. **Zero-Loss Subagent Task Contracts**:
   - Explicit inputs, outputs, and acceptance criteria synthesized into typed briefs, eliminating ambiguity between Lead and Workers.
4. **Generator-Verifier Separation (`@critic`)**:
   - Implementation workers (`@builder`) were barred from self-approving changes. An independent adversarial critic audited diffs with zero confirmation bias.
5. **Universal Multi-Profile Verification Gate (`verifier.py`)**:
   - Auto-detected project profiles (`mobile-kmp`, `python`, `web`, `generic`) and enforced unified secret scanning, syntax checks, token linters, and Mermaid diagram validation.

### Architectural Limitations of v2.0
- **Domain Leakage in Core Schema**: `.harness/blackboard.py` hardcoded statuses and task types; `dispatcher.py` hardcoded Android keywords (`"anr"`).
- **Filesystem Collisions**: Concurrent subagents sharing the workspace directory risked Git index locks and conflicting edits.
- **Prompt Bloat & Rule Dilution**: Guidelines were appended as growing markdown prompt checklists, causing attention dispersion ("lost in the middle").
- **Open-Loop Execution**: The system did not learn from failures or user corrections.

---

## 3. PDH v3.0: The Self-Improving Agentic Software Factory

### Context & Motivations
PDH v3.0 bridges modern **Agentic Graph Engineering**, **Microkernel OS Design**, and **Lean Software Manufacturing (Toyota Production System)** into an autonomous, self-improving software factory.

### Key Innovations
1. **Microkernel Decoupling (Mechanism vs. Policy)**:
   - Strips the kernel down to an append-only event store (`kernel_events`), state graph runner, worktree sandbox manager, and token governor.
   - Domain knowledge is completely encapsulated into modular **Agent Capsules** (`capsule.yaml`).
2. **Dual-Graph Execution Engine**:
   - Resolves the cycle paradox: logical graphs are cyclical (allowing Builder $\leftrightarrow$ Critic review loops), while physical execution unrolls into an immutable sequence of epoch attempts (`task:attempt:N`).
   - Hard circuit breaker ($N \le 3$) trips the Andon Cord if rework loops fail to converge.
3. **Hybrid Git Worktrees with Cache Symlinking**:
   - Each task executes in an isolated private worktree (`.harness/worktrees/wt-<task-id>`) checked out to branch `squad/<task-id>`.
   - Heavy build caches (`.venv`, `.gradle`, `node_modules`) are symlinked from the host, eliminating cold-start build penalties.
4. **Lean Manufacturing & In-Station Poka-Yoke Jigs (*Jidoka*)**:
   - Quality at the source: AST linters and design token validators run directly on file write hooks in Station 2 (Sub-Assembly). Defects cannot touch disk.
   - Multi-tiered Andon Cord: distinguishes between Tier 0 self-healing formatting, Tier 1 blast-radius local squad halts, and Tier 2 global trunk freezes.
5. **Bounded Kaizen Self-Improvement Engine**:
   - Decoupled from the critical production line (runs asynchronously in background Queue Q3).
   - **Causal Credit Attribution DAG ($\vec{\alpha}$)**: Mathematically partitions fault between Specification, Implementation, Verification, and Tooling.
   - **The Determinism Invariant (Code > Prompt)**: Synthesizes recurring failure patterns into deterministic AST regex linters or unit tests rather than polluting system prompts.
   - **Pareto Rule Budget ($K \le 12$)**: Strictly caps rules to prevent prompt bloat and attention dispersion.
   - **Cryptographic Quarantine Ledger**: Automated Kaizen proposals are isolated in `kaizen_proposals` until approved via `harness kaizen approve`.

---

## Iteration Summary Matrix

| Metric / Dimension | PDH v1.0 | PDH v2.0 | PDH v3.0 |
|---|---|---|---|
| **Domain Scope** | Android / KMP only | Multi-profile (configurable) | Task-Agnostic Microkernel |
| **State Persistence** | None (ephemeral bash) | SQLite WAL Task CRUD | Event-Sourced WAL + Projections |
| **Execution Topology** | Linear pipeline | Player-Coach DAG | Cellular Dynamic Squads |
| **Concurrency Isolation** | Single-threaded | Token/lease tracking (shared dir) | Hybrid Git Worktrees + Cache Symlinks |
| **Quality Control** | Post-hoc CLI assertion | Downstream Critic audit | In-Station Poka-Yoke Jigs (*Jidoka*) |
| **Anti-Deadlock Guards** | Manual human break | Lease timeout only | $N \le 3$ Circuit Breaker + Oscillation Watchdog |
| **Self-Improvement** | None | Manual PRD/RCA docs | Automated Causal DAG + Kaizen Quarantine |
| **Rule Budgeting** | Unbounded markdown | Growing prompt files | Bounded Pareto Budget ($K \le 12$) |

---

*Proceed to [02. Core Architecture: The Microkernel](02-Core-Architecture-The-Microkernel.md) to inspect the microkernel runtime and event store.*
