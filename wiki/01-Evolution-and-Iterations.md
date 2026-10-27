# Chapter 01: Evolution & Iterations

> **Status: historical record, not current behaviour.** This chapter describes the v1 to v3.1 designs as intended. Several v3 features (jigs at write time, causal attribution, bwrap sandbox, cache-hit targets, kaizen, capsules) are experimental and not wired into the runtime; v4 is described in [chapter 09](09-Khoros-v4-Evidence-Driven-Harness.md).** See [`.harness/EXPERIMENTAL.md`](../.harness/EXPERIMENTAL.md) and the [v4 RFC](../docs/rfc/khoros-v4.md).

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

## 4. Khoros v3.1: Autonomous Capabilities & Library Hygiene

### Context & Motivations
While v3.0 established the software factory microkernel and offline Kaizen loop, capabilities (tools and skills) still required manual authoring or human-in-the-loop intervention for every addition. As agents operate continuously, they risk accumulating stale tools, context-polluting prompt guides, and experiencing prompt injection or runaway synthesis. 

Khoros v3.1 completes the vision with **autonomous capability synthesis, closed-loop evolutionary refinement, and generational garbage collection**. Furthermore, the primary CLI executable was promoted from `harness` to `khoros` (retaining `harness` as a backwards-compatible alias).

### Key Milestones
1. **CLI Migration & Backwards Compatibility**:
   - `bin/khoros` established as the primary executable; `bin/harness` maintained as an aliased symlink.
2. **Tiered Risk-Gated Tool Synthesis**:
   - Synthesized tools are classified via AST analysis into Tier 1 (AST / read-only), Tier 2 (worktree file utilities), and Tier 3 (mutating shell/subprocess).
3. **Clean-Trunk Canary Verification ($\text{FP} = 0$)**:
   - Enforces a zero false positive invariant on clean trunk production code before admitting any synthesized AST jig.
4. **"Rule of Two" ($N=2$) Pareto Distillation**:
   - Normalized AST failure signatures trigger automated Poka-Yoke AST jig creation upon recurring at frequency $N \ge 2$, mechanically enforcing **Code > Prompt**.
5. **Static Prefix Pinning & Dynamic Compaction**:
   - Design target of a pinned 45% static prefix for high KV-cache reuse (not measured).
   - Fold, Mask, and Prune algorithms reduce compiler dumps by $\ge 98.5\%$ when working memory exceeds 85% high watermark.
6. **10-Operator Evolutionary Skill Grammar & Trajectory Mining**:
   - Skills evolve through a 10-operator grammar (`op_add`, `op_refine`, `op_merge`, `op_split`, etc.).
   - `khoros skill mine` distills completed task trajectories into permanent reusable skills.
7. **Generational Garbage Collection & 3-Phase Safe Eviction**:
   - **Station 4 Micro-GC**: Sub-millisecond teardown of worktrees, ephemeral scratch scripts, and CAS file leases.
   - **Macro-GC**: EWMA utility decay ($U_t = 0.95 U_{t-1} + 0.05 \mathbb{I}$) with 3-phase lifecycle (Active $\to$ Soft Deprecated $\to$ Cold Storage Archive $\to$ Permanent Purge) and instant restoration (`khoros restore`).

---

## Iteration Summary Matrix

| Metric / Dimension | PDH v1.0 | PDH v2.0 | PDH v3.0 | Khoros v3.1 |
|---|---|---|---|---|
| **CLI Binary** | `harness` (bash) | `harness` (python) | `harness` (python) | `khoros` (primary) / `harness` (alias) |
| **Domain Scope** | Android / KMP only | Multi-profile | Task-Agnostic Microkernel | Agnostic + Self-Synthesizing |
| **Tool Synthesis** | Manual only | Manual jigs | Offline Kaizen Proposals | Tiered AST Synthesis + Clean-Trunk Canary |
| **Distillation Threshold** | None | Ad-hoc PRDs | Manual Kaizen review | Rule of Two ($N \ge 2$) AST Automation |
| **Cognitive Memory** | Unbounded prompt | Growing markdown | Pareto Cap ($K \le 12$) | Pinned Prefix ($\ge 85\%$ KV hit) + Fold/Mask/Prune |
| **Skill Evolution** | None | Static docs | Rule updates | 10-Operator Evolutionary Grammar + Mining |
| **Library Hygiene** | Manual purge | Manual cleanup | None | Generational GC (Micro-GC + EWMA Macro-GC) |

---

*Proceed to [02. Core Architecture: The Microkernel](02-Core-Architecture-The-Microkernel.md) to inspect the microkernel runtime and event store.*

