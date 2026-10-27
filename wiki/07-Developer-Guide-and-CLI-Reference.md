# Chapter 07: Developer Guide & CLI Reference

> **Status: mixed.** The `verify`, `task` and `status` commands are current (v4 adds `--fast`, `--changed` and a test run by default; see chapter 09). The capsule authoring section and the kaizen, gc and skill commands are experimental.** See [`.harness/EXPERIMENTAL.md`](../.harness/EXPERIMENTAL.md) and the [v4 RFC](../docs/rfc/khoros-v4.md).

This guide provides practical instructions for operating the **Khoros** CLI (`bin/khoros` or `bin/harness`), authoring custom Agent Capsules, adding In-Station Jigs, and running verification suites.

---

## 1. CLI Command Reference (`bin/khoros` / `bin/harness`)

### Core Verification & Quality Control
```bash
# Run universal verification gate (detects profile: python, mobile-kmp, web, generic)
bin/khoros verify
# (or bin/harness verify)

# Run verification with unit and integration test discovery
bin/harness verify --test

# Run design token linter specifically
bin/harness lint

# Assert native frame pacing (Android/Compose)
bin/harness frame-pacing --fps 120 --max-jank 1.0
```

---

### Task & Factory Lifecycle Commands
```bash
# Triage a user request (Player-Coach complexity routing)
bin/harness triage "Implement dark mode support for profile settings screen"

# Author a formal specification document (auto-initializes .harness/ if needed)
bin/harness spec prd dark-mode "Dark Mode Presentation Support" --problem "High battery consumption in low-light"

# Create a task contract on the blackboard
bin/harness task create \
  --title "Implement Dark Mode Theme Tokens" \
  --type feature \
  --priority Q1 \
  --files "core/designsystem/Theme.kt" "core/designsystem/Colors.kt" \
  --criteria "Conforms to 4dp grid" "Zero raw hex colors" \
  --depends-on "task-spec-dark-mode"

# List active tasks and status projections
bin/harness task list

# Claim a task lease (monotonically increments fencing token)
bin/harness task claim task-001 --worker "worker-dark-mode"

# Send a lease heartbeat
bin/harness task heartbeat task-001

# Submit task completion (moves task to REVIEW_REQUESTED)
bin/harness task complete task-001 --summary "Theme tokens implemented and verified"
```

---

### Subagent Packet Generation
```bash
# Generate a zero-loss Subagent Task Contract packet for worker delegation
bin/harness brief task-001 --role "@builder"

# Generate a brief for independent adversarial review
bin/harness brief task-001 --role "@critic"
```

---

### Kaizen, Skills & Generational GC (v3.1)
```bash
# Kaizen proposal lifecycle & Rule of Two distillation
bin/khoros kaizen list                    # List quarantined proposals
bin/khoros kaizen inspect <proposal-id>   # Inspect proposal diff and canary results
bin/khoros kaizen approve <proposal-id>   # Promote proposal into production jigs/rules
bin/khoros kaizen reject <proposal-id>    # Reject proposal

# Skill trajectory mining & lifecycle
bin/khoros skill list                     # List active workspace skills
bin/khoros skill inspect <slug>           # Inspect skill documentation and triggers
bin/khoros skill mine <task-id> <slug>    # Mine verified task trace into a skill

# Generational GC & capability restoration
bin/khoros gc                             # Run Macro-GC (EWMA utility decay & 3-phase eviction)
bin/khoros restore <capability-id>        # Restore archived capability back to ACTIVE
```

---

## 2. Authoring a Custom Agent Capsule

To create a new domain capsule, create `.harness/capsules/<capsule_id>/capsule.yaml` or `.harness/capsules/<capsule_id>.yaml`:

```yaml
id: "backend-sql-builder"
version: "3.0.0"

charter:
  role: "Principal Database & SQL Engineer"
  goal: "Design normalized relational schemas and write performant, index-backed SQL migrations."
  archetypes: ["feature", "refactor", "bugfix"]
  escalation_conditions:
    - "Destructive migration required (DROP TABLE/COLUMN)"
    - "Cross-service foreign key required outside bounded context"

cognitive_budget:
  system_charter_ratio: 0.15     # 15% Charter & Invariants
  tool_schema_ratio: 0.15         # 15% Tool Schemas
  distilled_memory_ratio: 0.15   # 15% Kaizen Rules
  working_scratchpad_ratio: 0.35 # 35% Working Memory
  headroom_ratio: 0.20           # 20% Generation Buffer

capabilities:
  skills:
    - "managing-python-dependencies"
  jigs:
    - "sql-injection-ast-assert"
    - "foreign-key-index-check"

rules_and_invariants:
  pareto_budget_cap: 12
  hard_constraints:
    - id: "SQL-INV-01"
      rule: "All migrations must include an idempotent down/rollback migration."
      enforcement: "STATIC_CHECK"
    - id: "SQL-INV-02"
      rule: "Never execute DDL without wrapping in a transactional migration block."
      enforcement: "AST_LINTER"
```

---

## 3. Adding an In-Station Poka-Yoke Jig

In-station jigs live in `.harness/kernel/jigs.py`. To register a new write-time check:

```python
# .harness/kernel/jigs.py
class InStationJigRunner:
    def validate_content(self, file_path: str, content: str, ...):
        # Add deterministic validation logic:
        # 1. Parse AST
        # 2. Check invariants
        # 3. Append to violations list if invalid
        ...
```

---

## 4. Running Tests & Quality Verification

```bash
# Run the complete unit test suite (Microkernel, Event Store, Jigs, Capsules, Attribution)
python3 -m unittest discover tests/unit

# Run full project verification gate
bin/harness verify
```

---

*Return to [Wiki Home](Home.md)*
