# Khoros (Χορός) Wiki

Welcome to the official documentation and knowledge base for **Khoros (Χορός)** *(formerly Personal Development Harness / PDH)*.

Named after the synchronized classical Greek ensemble led by the *Coryphaeus* (our Player-Coach Lead Orchestrator), **Khoros** is an autonomous software engineering operating system and microkernel designed to orchestrate single-agent and multi-agent squads with quality controls borrowed from industrial manufacturing. Parts of that design are implemented and parts are experimental; the status of each is stated in its chapter.

---

## Wiki Table of Contents

| Chapter | Document | Description |
|---|---|---|
| **01** | [Evolution & Iterations](01-Evolution-and-Iterations.md) | Architectural lineage from v1.0 bash scripts to v2.0 Player-Coach DAG to v3.0 Self-Improving Factory. |
| **02** | [Core Architecture: The Microkernel](02-Core-Architecture-The-Microkernel.md) | Mechanism vs. Policy decoupling, SQLite WAL event store, dual-graph execution, and worktrees. |
| **03** | [Agent Capsules & Cognitive Memory](03-Agent-Capsules-and-Cognitive-Memory.md) | Declarative `capsule.yaml` manifests, 4-tier context budgeting, and Pareto rule bounds ($K \le 12$). |
| **04** | [The Lean Software Factory](04-The-Lean-Software-Factory.md) | Toyota Production System (TPS) applied to AI: 4 assembly stations, Poka-Yoke jigs, and Andon cords. |
| **05** | [Team Organization & Squad Dynamics](05-Team-Organization-and-Squad-Dynamics.md) | Cellular squad assembly, 3-tier squad protocol, and anti-deadlock circuit breakers. |
| **06** | [The Kaizen Self-Improvement Engine](06-The-Kaizen-Self-Improvement-Engine.md) | Causal credit attribution ($\vec{\alpha}$), Code > Prompt invariant, and quarantined proposal ledgers. |
| **07** | [Developer Guide & CLI Reference](07-Developer-Guide-and-CLI-Reference.md) | CLI commands, running verification gates, authoring capsules, and development workflows. |
| **08** | [Autonomous Capabilities & Library Hygiene](08-Autonomous-Capabilities-and-Library-Hygiene.md) | Dynamic tool synthesis, AST risk classification, clean-trunk canaries, evolutionary skill grammar, and generational GC. |
| **09** | [Khoros v4: Evidence-Driven Harness](09-Khoros-v4-Evidence-Driven-Harness.md) | Current design: Stop-hook gate, minimal context, opt-in long-task skill, single reviewer, and benchmark status. |

> Chapters 01-08 describe the v3 design. Each opens with a status note saying what is experimental or not wired into the runtime.

---

## Architectural Philosophy: The Three Invariants

**Khoros** is governed by three non-negotiable architectural invariants:

1. **The Separation Invariant (Mechanism vs. Policy)**:  
   The core engine (Kernel) must contain zero domain knowledge. It provides distributed OS mechanics (state machines, transactions, sandboxes). The intent is that domain logic and verification criteria live in declarative Agent Capsules; in practice no capsule files exist yet and domain checks are opt-in configuration (for example design tokens only when `.harness/design-tokens.json` is present).

2. **The Determinism Invariant (Code > Prompt)**:  
   *"Never keep in a prompt what can be enforced by a deterministic linter or test fixture."* Mechanical violations (syntax, design tokens, secrets) should be stopped by deterministic checks rather than prose. In v4 these are the `verify` checks run by the Stop-hook gate and the per-edit hook; the write-time "AST jig" runner is experimental and not hooked to any write.

3. **The Zero-Defect Invariant (Quality at the Source / *Jidoka*)**:  
   Defects should be caught as early as practical. In v4 that means per-edit static checks and a gate that blocks the agent from stopping while tests fail, with a retry cap and an escape hatch. It is not a guarantee: `verify` only checks what it can detect.

---

## System Topology Map

*The diagram below is the v3 design intent, not the v4 runtime (see [chapter 09](09-Khoros-v4-Evidence-Driven-Harness.md) for that).*

```mermaid
flowchart TD
    UserReq([Developer Request / Epic]) --> KernelCAD[Station 1: CAD Blueprinting]
    KernelCAD --> TaskContract[Signed Task Contract Fixture]
    
    subgraph SquadCell["Station 2: Sub-Assembly Squad Cell"]
        WorkerCapsule["Worker Capsule (Builder)"]
        Worktree["Private Git Worktree (Symlinked Caches)"]
        Jigs["In-Station Poka-Yoke Jigs (AST Linters)"]
        WorkerCapsule --> Worktree
        Worktree --> Jigs
        Jigs -- Fail (Tier 1 Local Andon) --> WorkerCapsule
    end
    
    TaskContract --> SquadCell
    Jigs -- Pass --> StationAudit["Station 3: Adversarial Critic & Personas"]
    
    StationAudit -- Reject (N <= 3) --> SquadCell
    StationAudit -- Pass --> StationPacemaker["Station 4: Pacemaker Trunk Integration"]
    
    StationPacemaker --> MainTrunk([Main Trunk Released])
    StationPacemaker -.-> OffLineKaizen["Off-Line Kaizen Cell (Decoupled Background Loop)"]
    
    subgraph Kaizen["Kaizen Engine (Queue Q3)"]
        OffLineKaizen --> Attribution["Causal Credit Attribution DAG"]
        Attribution --> QuarantinedLedger["Quarantined Proposal Ledger"]
        QuarantinedLedger --> HITL["Human-in-the-Loop Promotion Gate"]
    end
```

---

*Proceed to [01. Evolution & Iterations](01-Evolution-and-Iterations.md) to explore the full history and technical transitions of the harness.*
