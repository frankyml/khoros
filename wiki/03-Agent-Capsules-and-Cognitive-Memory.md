# Chapter 03: Agent Capsules & Cognitive Memory

In **Khoros**, agents are not defined by monolithic, open-ended system prompt files. Instead, domain intelligence, toolkits, constraints, and memory are packaged into **Agent Capsules** (`capsule.yaml`).

```
┌────────────────────────────────────────────────────────┐
│                   AGENT CAPSULE                        │
├────────────────────────────────────────────────────────┤
│ 1. Charter & Boundaries (Role, Intent, Escalation)     │
│ 2. Executable Toolsets & Jigs (Skills, AST linters)    │
│ 3. Cognitive Context Budget (4-tier allocation)        │
│ 4. Rules & Invariants (Pareto-optimal cap K <= 12)     │
│ 5. Memory Stores (Distilled semantic + Episodic cache) │
└────────────────────────────────────────────────────────┘
```

---

## 1. The Declarative Capsule Specification

Agent Capsules are loaded via [`capsules/loader.py`](../.harness/capsules/loader.py). Below is an annotated manifest:

```yaml
id: "mobile-compose-builder"
version: "3.0.0"

charter:
  role: "Senior Jetpack Compose & KMP Engineer"
  goal: "Implement fluid 120Hz native mobile presentation components adhering to design tokens"
  archetypes: ["feature", "ui_revamp", "bugfix"]
  escalation_conditions:
    - "Changes required outside presentation package"
    - "Design tokens missing corresponding color or spacing entry"

cognitive_budget:
  system_charter_ratio: 0.15     # 15% Charter & Invariants
  tool_schema_ratio: 0.15         # 15% Tool Schemas
  distilled_memory_ratio: 0.15   # 15% Kaizen Synthesized Rules
  working_scratchpad_ratio: 0.35 # 35% Trajectory & Active Subgoals
  headroom_ratio: 0.20           # 20% Generation Buffer

capabilities:
  skills:
    - "generative_ui"
    - "android-cli"
  jigs:
    - "kmp-design-token-assert"
    - "no-hardcoded-dp"
  mcp_servers: []

rules_and_invariants:
  pareto_budget_cap: 12          # K <= 12 rules max
  hard_constraints:
    - id: "INV-01"
      rule: "Never use raw hex colors or hardcoded dp values outside Theme.kt / design-tokens.json"
      enforcement: "AST_LINTER"
    - id: "INV-02"
      rule: "Ensure all touch targets measure >= 48dp on both axes"
      enforcement: "STATIC_CHECK"
```

---

## 2. The 4-Tier Cognitive Context Allocation

Treating an LLM's context window as an unbudgeted text stream leads to **attention dispersion**, high latency, and catastrophic prompt dilution.

Khoros enforces a mathematical context budget across 4 tiers:

$$\mathcal{S}_{\text{capsule}} = \langle \mathcal{P}_{\text{charter}}, \mathcal{T}_{\text{exec}}, \mathcal{M}_{\text{semantic}}, \mathcal{M}_{\text{episodic}} \rangle$$

```
┌────────────────────────────────────────────────────────────────────────┐
│                        AGENT CAPSULE CONTEXT BUDGET                    │
│   Total Context Window Budget: B_ctx (e.g., 64,000 tokens)             │
├───────────────────────────────────┬────────────────────────────────────┤
│ 1. Immutable System Charter       │ 2. Executable Tool Schemas         │
│    Role, Intent, Escalation       │    MCP & CLI Signatures            │
│    [Quota: 15% | ~9,600 tokens]   │    [Quota: 15% | ~9,600 tokens]    │
├───────────────────────────────────┼────────────────────────────────────┤
│ 3. Distilled Semantic Memory      │ 4. Short-Term Episodic Memory      │
│    Kaizen Rules & Anti-Patterns   │    Subgoals, Trajectory, AST Diffs │
│    [Quota: 15% | ~9,600 tokens]   │    [Quota: 35% | ~22,400 tokens]   │
├───────────────────────────────────┴────────────────────────────────────┤
│ 5. Generation Headroom & Output Buffer [Quota: 20% | ~12,800 tokens]   │
└────────────────────────────────────────────────────────────────────────┘
```

### Allocation Breakdown:
1. **System Charter & Invariants ($\mathcal{P}_{\text{charter}}$, 15%)**:  
   Read-only identity, boundary definitions, and hard constraints. Immutable during runtime.
2. **Executable Tool Schemas ($\mathcal{T}_{\text{exec}}$, 15%)**:  
   JSON Schema representations of tools and MCP servers. Optimized via semantic lazy loading (only the top-$k$ relevant schemas are injected into the active prompt).
3. **Distilled Semantic Memory ($\mathcal{M}_{\text{semantic}}$, 15%)**:  
   High-density declarative heuristics and negative anti-patterns synthesized by the Kaizen engine. Retrieved using hybrid BM25 + dense vector search over `.harness/memory/<capsule_id>.db`.
4. **Short-Term Episodic Memory ($\mathcal{M}_{\text{episodic}}$, 35%)**:  
   Active reasoning scratchpad and observation trajectory, managed via **Hierarchical Working Memory Compaction (HWMC)**:
   - Sliding window over the last 4 turns.
   - Raw compiler error dumps (e.g. 500 lines of build output) are stripped immediately upon execution, preserving only the normalized AST error signature.
5. **Generation Headroom (20%)**:  
   Reserved exclusively for token generation buffer.

---

## 3. The Pareto-Optimal Rule Budget ($K \le 12$)

### The Hazard of Monotonic Rule Growth
In naive agent systems, when an error occurs, engineers or self-tuning loops append a new rule to the system prompt. Over time, the prompt accumulates dozens of negative rules:
- *"Do not use variable name `tmp`."*
- *"Ensure helper methods are declared after public methods."*
- *"Avoid nesting if-statements."*

This causes **attention dilution**: the LLM fixates on minor syntactic trivia while missing critical functional requirements.

### The Mathematical Pareto Bound
In Khoros, an Agent Capsule enforces a hard Pareto cap:
$$K \le 12 \text{ rules (max 1,000 tokens)}$$

A candidate rule $R_{\text{new}}$ synthesized by the Kaizen engine **cannot be added** if the capsule already holds $K=12$ rules unless:
1. **Semantic Subsumption**: $R_{\text{new}}$ is merged with an existing rule of the same domain category.
2. **Utility Pruning**: The least-triggered rule with the lowest utility score is auto-quarantined for deprecation.

```python
# capsules/loader.py
def add_rule(self, rule_id: str, rule: str, enforcement: str = "AST_LINTER") -> Tuple[bool, str]:
    constraints = self.rules_and_invariants.get("hard_constraints", [])
    cap = self.rules_and_invariants.get("pareto_budget_cap", 12)
    
    if len(constraints) >= cap:
        return False, "Pareto Rule Budget exceeded: Capsule already holds 12/12 rules. Must subsume or prune."
    ...
```

---

*Proceed to [04. The Lean Software Factory](04-The-Lean-Software-Factory.md) to understand assembly stations, Poka-Yoke jigs, and Andon cord mechanisms.*
