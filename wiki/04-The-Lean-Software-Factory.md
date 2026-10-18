# Chapter 04: The Lean Software Factory

**Khoros** adapts the principles of the **Toyota Production System (TPS)** and modern Lean Manufacturing to multi-agent software engineering.

```
[Raw Demand] ──► [Station 1: CAD] ──► [Station 2: Sub-Assembly] ──► [Station 3: Audit] ──► [Station 4: Pacemaker Merge]
                      (90s)                 (240s - BOTTLENECK)           (60s)                    (30s)
                                                     │
                                                     ▼ (Async Edge Cell)
                                           [Off-Line Kaizen Cell]
```

---

## 1. The 4 Assembly Line Stations

Traditional software engineering allows large batches of unverified code to accumulate across branches before massive merge reviews. Khoros enforces **One-Piece Flow** and strict work-in-progress (CONWIP) limits:

### Station 1: CAD Blueprinting & Contract Tooling
- **Takt Time ($T_{\text{takt}}$)**: 90 seconds.
- **WIP Limit**: $\le 3$ active specifications.
- **Functions**:
  - Classifies task archetype (`feature`, `refactor`, `bugfix`, `research`).
  - Synthesizes formal `contract.json` fixture with declared `--files` and acceptance criteria.
  - Runs **Selective Micro-LATS** ($k=3, d=2$) evaluated via deterministic structural heuristics.

### Station 2: Cell Sub-Assembly (The Factory Bottleneck)
- **Takt Time ($T_{\text{takt}}$)**: 240 seconds.
- **WIP Limit**: $\le 2$ concurrent workers (Strict CONWIP Bottleneck).
- **Functions**:
  - Executes implementation inside an isolated Git worktree (`wt-<task-id>`).
  - Embeds **In-Station Poka-Yoke Jigs** directly on write hooks.

### Station 3: Independent Adversarial Audit (QA)
- **Takt Time ($T_{\text{takt}}$)**: 60 seconds.
- **WIP Limit**: $\le 1$ item in review.
- **Functions**:
  - Independent Adversarial Critic audits the diff against the signed contract with zero confirmation bias.
  - Evaluates user personas (Alex, Sam, Jordan) and runs regression suites.

### Station 4: Pacemaker Trunk Integration
- **Takt Time ($T_{\text{takt}}$)**: 30 seconds.
- **WIP Limit**: $\le 1$ item.
- **Functions**:
  - Fast-forward merge (`git merge --ff-only`) into `main`.
  - Evicts the worktree and releases file leases.
  - Seals the event record and dispatches telemetry to the off-line Kaizen cell.

---

## 2. In-Station Poka-Yoke Jigs (*Jidoka*)

In classical manufacturing, catching defects downstream at final inspection causes costly scrap and rework (*Muda of Inspection*).

Khoros implements **Quality at the Source (*Jidoka*)** via [`kernel/jigs.py`](../.harness/kernel/jigs.py):

```
      Traditional Multi-Agent Pipeline                     Khoros In-Station Jigs
┌──────────────────────────────────────────┐    ┌──────────────────────────────────────────┐
│ Worker writes code with raw #hex color   │    │ Worker attempts to write raw #hex color  │
│ 15 min later: CI or Critic rejects patch │ VS │ In-Station Jig immediately blocks write  │
│ Entire sub-assembly scrapped & redone    │    │ Worker corrects within current turn      │
└──────────────────────────────────────────┘    └──────────────────────────────────────────┘
```

### Active In-Station Checks:
1. **AST Syntax Jig**: Automatically validates Python/TSX/Dart AST syntax before files hit disk.
2. **Secret Hygiene Jig**: Rejects private keys and API tokens at tool execution time.
3. **Design Token Jig**: Rejects raw `#hex` color literals and unmapped dp values in presentation files.

---

## 3. The Multi-Tiered Andon Cord

In the Toyota Production System, any worker can pull the **Andon Cord** to halt the line when a defect occurs. However, in an AI factory, halting everything for minor whitespace or format nits causes **factory starvation**.

Khoros establishes a **Three-Tiered Andon System**:

| Tier | Severity | Trigger | Assembly Action |
|---|---|---|---|
| **Tier 0: Self-Healing** | Format / Style | Whitespace, import sorting, lint formatting (`ruff format`, `ktlint`) | **Do not halt.** Kernel auto-executes deterministic formatter on worktree. |
| **Tier 1: Blast-Radius Halt** | Deterministic Bug | AST syntax error, local test failure in touched files, token violation | **Halt worker only.** Cord pulled locally for that worktree. Other squads continue. |
| **Tier 2: Global Factory Halt** | Systemic Breach | Trunk merge conflict, DB corruption, kernel invariant violation | **Halt entire line.** Freeze trunk, alert Squad Lead & Human. |

### Flaky Test Quarantine Protocol
If a test fails on modified code in a worktree, the kernel automatically verifies the test against unpatched `main`:
- If the test **also fails on `main`**, it is flagged as `FLAKY_QUARANTINED`.
- It creates an asynchronous issue ticket and does **not** pull the Andon Cord for the current task.

---

## 4. Factory Quality & Yield Metrics

The Factory Manager tracks three quantifiable lean metrics:

### 1. Rolled First-Pass Yield (RFPY)
Measures the probability that a task will pass through all 4 stations without any rework:
$$\text{RFPY} = \prod_{i=1}^4 \text{FPY}_i = \text{FPY}_{\text{CAD}} \times \text{FPY}_{\text{SubAssembly}} \times \text{FPY}_{\text{Audit}} \times \text{FPY}_{\text{Integration}}$$
*Target*: $\text{RFPY} \ge 75\%$ on multi-file features; $\ge 90\%$ on micro-fixes.

### 2. Defect Parts Per Million (PPM)
$$\text{PPM} = \left( \frac{\text{Total Detected Violations}}{\text{Total Verification Opportunities}} \right) \times 10^6$$
*World-Class Target*: $< 1,000\text{ PPM}$.

### 3. Rework Ratio ($R_{\%}$)
$$\text{Rework Ratio} = \left( \frac{\text{Total Inner Retries}}{\text{Total Dispatched Tasks}} \right) \times 100$$
*Threshold*: If $R_{\%} > 15\%$, triggers an automatic review of the Capsule Charter and Jigs.

---

*Proceed to [05. Team Organization & Squad Dynamics](05-Team-Organization-and-Squad-Dynamics.md) to explore cellular squad assembly and peer protocols.*
