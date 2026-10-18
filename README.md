# Khoros (Χορός)

> **The Self-Improving Agentic Software Factory & Ensemble Microkernel**  
> *Formerly known as Personal Development Harness (PDH)*  
> Backed by a task-agnostic microkernel, declarative agent capsules, cellular squad dynamics, and a bounded Kaizen self-improvement loop.

[![Khoros Verify](https://img.shields.io/badge/Khoros%20Verify-Passing-brightgreen.svg)](#)
[![Architecture](https://img.shields.io/badge/Architecture-Khoros%20v3.0%20Microkernel-blue.svg)](wiki/02-Core-Architecture-The-Microkernel.md)
[![CLI](https://img.shields.io/badge/CLI-khoros%20%7C%20harness-purple.svg)](#)
[![Design Tokens](https://img.shields.io/badge/Design%20Tokens-4dp%20%2F%20Zero%20Raw%20Hex-orange.svg)](#)

---

## The Khoros Paradigm

In classical Greek drama, the **Khoros** (Χορός) was the coordinated ensemble that observed the action, provided critical reflection, and acted in harmony—guided by the **Coryphaeus** (the Chorus Leader, our *Player-Coach Lead Orchestrator*).

**Khoros** applies this concept to autonomous software engineering: an agnostic microkernel orchestrating specialized agent capsules in dynamic, self-organizing squads with the mathematical discipline and quality controls of an industrial software factory.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        KHOROS AGENTIC SOFTWARE FACTORY                 │
├────────────────────────────────────────────────────────────────────────┤
│  LAYER 3: OFFLINE KAIZEN CELL (Continuous Learning & Attribution)      │
│  [Traces] ──► [Causal Elimination DAG] ──► [Quarantined AST Jigs]      │
├────────────────────────────────────────────────────────────────────────┤
│  LAYER 2: CELLULAR PRODUCTION LINE (Dynamic Squads & Capsules)         │
│  [CAD Blueprint] ──► [Sub-Assembly + Jigs] ──► [Critic] ──► [Trunk FF] │
├────────────────────────────────────────────────────────────────────────┤
│  LAYER 1: TASK-AGNOSTIC KHOROS MICROKERNEL                             │
│  • Event-Sourced SQLite WAL Ledger     • Dual-Graph Execution Engine   │
│  • Hybrid Git Worktrees & Cache Links  • Multi-Tiered Andon Cord       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Navigation

- 📖 **[Project Wiki](wiki/Home.md)** — Full architectural guides, design principles, and operational specifications.
  - [01. Evolution & Iterations](wiki/01-Evolution-and-Iterations.md)
  - [02. Core Architecture: The Microkernel](wiki/02-Core-Architecture-The-Microkernel.md)
  - [03. Agent Capsules & Cognitive Memory](wiki/03-Agent-Capsules-and-Cognitive-Memory.md)
  - [04. The Lean Software Factory](wiki/04-The-Lean-Software-Factory.md)
  - [05. Team Organization & Squad Dynamics](wiki/05-Team-Organization-and-Squad-Dynamics.md)
  - [06. The Kaizen Self-Improvement Engine](wiki/06-The-Kaizen-Self-Improvement-Engine.md)
  - [07. Developer Guide & CLI Reference](wiki/07-Developer-Guide-and-CLI-Reference.md)

---

## Key Features

1. **Task-Agnostic Microkernel**: The core engine contains zero domain knowledge (no Android, Python, Web, or Bio specifics). It provides distributed OS primitives: atomic transactions, state machines, worktree sandboxes, and file leases.
2. **Declarative Agent Capsules**: Domain intelligence, charters, skills, and hard invariants are encapsulated in modular `capsule.yaml` manifests.
3. **Poka-Yoke Jigs (*Jidoka*)**: Quality at the source. Write-time AST linters and design token validators catch defects before code is saved or shared.
4. **Anti-Deadlock Squad Engine**: Prevents infinite renegotiation between Builders and Critics using a hard iteration cap ($N \le 3$), signed SHA-256 criteria, and an oscillation distance watchdog.
5. **Bounded Kaizen Self-Improvement**: Post-task retrospectives use a 3-stage causal elimination DAG ($\vec{\alpha}$) to apportion credit, enforce the **Code > Prompt** invariant, and cap rules at a Pareto budget ($K \le 12$).

---

## Quick Start

```bash
# Verify the health of Khoros and all quality gates
bin/khoros verify
# (or bin/harness verify)

# Run the complete test suite
python3 -m unittest discover tests/unit

# View current tasks on the blackboard
bin/khoros task list
```

Explore the **[Wiki Home](wiki/Home.md)** for in-depth architectural guides and developer documentation.
