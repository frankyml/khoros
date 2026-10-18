# Chapter 08: Autonomous Capabilities & Library Hygiene

Khoros v3.1 introduces an end-to-end evolutionary subsystem enabling autonomous capability synthesis, closed-loop skill refinement, and self-maintaining library hygiene. This ensures that agent skills and deterministic jigs continuously adapt and evolve from real-world execution traces while rigorously avoiding context bloat, security regressions, or library rot.

---

## 1. Dynamic Tool Synthesis & Tiered Risk Classification

When recurrent execution defects or missing capabilities are detected, Khoros synthesizes tools dynamically under an immutable security hierarchy. Tools are classified via an AST security visitor before execution or staging:

| Tier | Classification | Permitted Operations | Isolation & Verification Boundary | Admission Gate |
|---|---|---|---|---|
| **Tier 1** | Pure AST & Read-Only Logic | In-memory AST analysis, deterministic regex, non-mutating file reads | Pure Python AST sandbox; zero subprocess or network capability | Automated admission upon Clean-Trunk Canary pass ($\text{FP}=0$) |
| **Tier 2** | Worktree File Utilities | Ephemeral file transforms, workspace formatting, build artifact extraction | Isolated ephemeral Git worktree; POSIX resource bounds (`RLIMIT_AS` 512MB, timeout $\le 5$s) | Shadow Canary run; staged in `generation=1` |
| **Tier 3** | Mutating Shell & Subprocess | Bash scripts, network calls, external compiler invocations, git operations | Strictly quarantined; non-privileged namespaces where permitted | **Quarantined Proposal Ledger** requiring explicit Human-in-the-Loop (`khoros kaizen approve`) |

---

## 2. Clean-Trunk Canary Verification ($\text{FP} = 0$)

Before any synthesized tool or AST jig can be admitted into production:
1. **Canary Baseline**: The synthesized jig is evaluated against the clean production codebase (excluding ephemeral worktrees and `.harness/`).
2. **Zero False Positives Invariant**: The canary verifies that the new jig produces exactly zero false positives on known-clean trunk code:
   $$\text{FP}_{\text{trunk}} = 0$$
3. **Defect Catch Verification**: The jig must successfully trigger a positive violation against the specific defect fixture that motivated its creation.

If any clean trunk file triggers a false positive, the synthesis is rejected and discarded.

---

## 3. The "Rule of Two" ($N=2$) Pareto Distillation Engine

To prevent synthesizing one-off jigs for transient anomalies:
- Execution failures are normalized into AST signatures (stripping variable identifiers, literals, and formatting).
- Failure signatures are logged in `failure_signatures`.
- When a failure signature reaches a frequency of $N \ge 2$, the **Rule of Two** triggers autonomous AST jig distillation:
  $$\text{Frequency}(\text{Sig}) \ge 2 \implies \text{Synthesize In-Station Poka-Yoke Jig}$$
- Deterministic jigs are generated in `.harness/jigs/` and registered in `capability_registry` under the principle: **Code > Prompt**.

---

## 4. 4-Tier Cognitive Context Allocation & Dynamic Compaction

To ensure predictable KV-cache prefix hits ($\ge 85\%$) and protect reasoning capacity, context windows are partitioned into strict deterministic tiers:

$$\mathcal{C}_{\text{total}} = \mathcal{P}_{\text{charter}} (15\%) + \mathcal{T}_{\text{tools}} (15\%) + \mathcal{M}_{\text{memory}} (15\%) + \mathcal{S}_{\text{scratchpad}} (35\%) + \mathcal{H}_{\text{headroom}} (20\%)$$

```
┌───────────────────────────────┬───────────────────────────────┬───────────────────────────────┐
│ Charter & Invariants (15%)    │ Active Tools / Jigs (15%)     │ Distilled Kaizen Rules (15%)  │
├───────────────────────────────┴───────────────────────────────┴───────────────────────────────┤
│ [Pinned Static Prefix: >= 85% KV-Cache Reuse]                                                 │
├───────────────────────────────────────────────────────────────┬───────────────────────────────┤
│ Dynamic Working Scratchpad (35%)                              │ Reserved Output Headroom (20%)│
└───────────────────────────────────────────────────────────────┴───────────────────────────────┘
```

### Context Compaction Primitives
When scratchpad pressure crosses the **85% High Watermark**, the `ContextPressureController` invokes deterministic compaction primitives until usage drops below the **60% Low Watermark**:
- **Masking (`mask_compiler_trace`)**: Compiler and stack traces are compressed by $\ge 98.5\%$, retaining only the root exception line and the top/bottom stack frames.
- **Folding (`fold_long_output`)**: Tool outputs exceeding 2,000 characters are persisted to `.harness/worktrees/logs/` and replaced by a disk anchor URI.
- **Pruning (`prune_speculative_trajectory`)**: Subagent exploration logs and aborted trial steps are stripped from the trajectory once a verified solution is discovered.

---

## 5. 10-Operator Evolutionary Skill Grammar

Skills in `.harness/skills/` evolve through a closed-loop genetic grammar:

1. **`op_add`**: Ingests new verified patterns from external task solutions.
2. **`op_refine`**: Updates existing steps with observed workarounds and precise flags.
3. **`op_merge`**: Combines overlapping skills ($\ge 0.85$ semantic Jaccard overlap) into a cohesive procedure.
4. **`op_split`**: Decomposes bloated skills exceeding instruction limits into focused sub-skills.
5. **`op_prune_to_archive`**: Retires skills that have decayed in utility to compressed cold storage archives.
6. **`op_distill`**: Compresses multi-step natural language instructions into deterministic AST checks or CLI commands.
7. **`op_abstract`**: Replaces project-specific identifiers with parameterizable template variables.
8. **`op_compose`**: Links dependent skills into composite pipeline playbooks.
9. **`op_rewrite`**: Restructures complex prose into concise imperative checklists.
10. **`op_rerank`**: Prioritizes skill recommendations based on EWMA success telemetry.

### Trajectory Mining (`khoros skill mine`)
Completed tasks with clean verification traces can be mined directly:
```bash
khoros skill mine <task-id> <slug> --title "<Descriptive Title>"
```
The mining engine extracts the task's event sequence, tools invoked, and diff summaries, generating a standardized `SKILL.md` template.

---

## 6. Generational Garbage Collection & Safe Eviction

Khoros prevents library bloat and stale capability rot through a dual-cadence GC engine:

### Station 4 Micro-GC
- **Trigger**: Executed synchronously upon task merge or termination.
- **Latency**: Sub-millisecond execution.
- **Actions**:
  1. Decommissions ephemeral Git worktrees (`.harness/worktrees/wt-<task-id>`).
  2. Purges unpromoted Gen-0 scratch scripts.
  3. Releases atomic CAS file leases in `file_leases`.

### Macro-GC & 3-Phase Safe Eviction
- **Trigger**: Sprint boundaries or `khoros gc`.
- **Decay Scoring**: Evaluates capabilities using an Exponentially Weighted Moving Average (EWMA):
  $$U_t = \lambda U_{t-1} + (1 - \lambda)\mathbb{I}_{\text{invoked}} \quad (\lambda = 0.95)$$
- **3-Phase Eviction Lifecycle**:
  1. **Phase 1: Soft Deprecation** ($U_t < 0.15$): Capability is flagged `SOFT_DEPRECATED` and suppressed from active agent prompts.
  2. **Phase 2: Cold Storage Archive** (Inactive $\ge 14$ days): Files are compressed into `.harness/archive/<cap_id>_<timestamp>.tar.gz` and removed from disk.
  3. **Phase 3: Permanent Purge** (Archived $\ge 90$ days): Record removed from registry.

### Capability Restoration
Any archived or soft-deprecated capability can be instantly resurrected:
```bash
khoros restore <capability-id>
```
The archive is uncompressed back into its original workspace location, and its status is reset to `ACTIVE`.

---

*Return to [Wiki Home](Home.md)*
