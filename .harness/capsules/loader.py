#!/usr/bin/env python3
"""
PDH v3.0 Agent Capsule Specification & Loader
Parses declarative capsule.yaml manifests, enforces Pareto-optimal rule budgets (K <= 12),
and calculates mathematical cognitive context allocations.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None



class AgentCapsule:
    MAX_PARETO_RULES = 12

    def __init__(
        self,
        capsule_id: str,
        version: str,
        charter: Dict[str, Any],
        cognitive_budget: Optional[Dict[str, float]] = None,
        capabilities: Optional[Dict[str, Any]] = None,
        rules_and_invariants: Optional[Dict[str, Any]] = None,
        capsule_dir: Optional[Path] = None,
    ):
        self.id = capsule_id
        self.version = version
        self.charter = charter
        self.cognitive_budget = cognitive_budget or {
            "system_charter_ratio": 0.15,
            "tool_schema_ratio": 0.15,
            "distilled_memory_ratio": 0.15,
            "working_scratchpad_ratio": 0.35,
            "headroom_ratio": 0.20,
        }
        self.capabilities = capabilities or {"skills": [], "jigs": [], "mcp_servers": []}
        self.rules_and_invariants = rules_and_invariants or {
            "pareto_budget_cap": self.MAX_PARETO_RULES,
            "hard_constraints": [],
        }
        self.capsule_dir = Path(capsule_dir) if capsule_dir else Path.cwd()

    def calculate_token_allocations(self, total_context_tokens: int = 64000) -> Dict[str, int]:
        """
        Calculates exact token budgets for each tier of the 4-tier cognitive memory hierarchy.
        """
        return {
            "system_charter_tokens": int(total_context_tokens * self.cognitive_budget.get("system_charter_ratio", 0.15)),
            "tool_schema_tokens": int(total_context_tokens * self.cognitive_budget.get("tool_schema_ratio", 0.15)),
            "distilled_memory_tokens": int(total_context_tokens * self.cognitive_budget.get("distilled_memory_ratio", 0.15)),
            "working_scratchpad_tokens": int(total_context_tokens * self.cognitive_budget.get("working_scratchpad_ratio", 0.35)),
            "generation_headroom_tokens": int(total_context_tokens * self.cognitive_budget.get("headroom_ratio", 0.20)),
        }

    def add_rule(self, rule_id: str, rule: str, enforcement: str = "AST_LINTER") -> Tuple[bool, str]:
        """
        Enforces the Pareto-Optimal Rule Budget (K <= 12) to prevent rule bloat and attention dispersion.
        """
        constraints = self.rules_and_invariants.get("hard_constraints", [])
        cap = self.rules_and_invariants.get("pareto_budget_cap", self.MAX_PARETO_RULES)

        # Check if already present
        for c in constraints:
            if c.get("id") == rule_id:
                c["rule"] = rule
                c["enforcement"] = enforcement
                return True, f"Updated existing rule '{rule_id}'."

        if len(constraints) >= cap:
            return (
                False,
                f"Pareto Rule Budget exceeded: Capsule already holds {len(constraints)}/{cap} maximum rules. "
                "Must subsume or prune least-triggered rule before adding new rules.",
            )

        constraints.append({"id": rule_id, "rule": rule, "enforcement": enforcement})
        self.rules_and_invariants["hard_constraints"] = constraints
        return True, f"Added rule '{rule_id}' (Total: {len(constraints)}/{cap})."

    def get_hard_constraints(self) -> List[Dict[str, str]]:
        return self.rules_and_invariants.get("hard_constraints", [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "charter": self.charter,
            "cognitive_budget": self.cognitive_budget,
            "capabilities": self.capabilities,
            "rules_and_invariants": self.rules_and_invariants,
        }


class CapsuleLoader:
    def __init__(self, search_dir: Optional[Path] = None):
        self.search_dir = Path(search_dir) if search_dir else Path.cwd() / ".harness" / "capsules"

    def load_from_yaml(self, yaml_path: Path) -> AgentCapsule:
        with open(yaml_path, "r", encoding="utf-8") as f:
            if yaml is not None and yaml_path.suffix in [".yaml", ".yml"]:
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
        return AgentCapsule(
            capsule_id=data["id"],
            version=str(data.get("version", "3.0.0")),
            charter=data.get("charter", {}),
            cognitive_budget=data.get("cognitive_budget"),
            capabilities=data.get("capabilities"),
            rules_and_invariants=data.get("rules_and_invariants"),
            capsule_dir=yaml_path.parent,
        )

    def load_capsule(self, capsule_id: str) -> Optional[AgentCapsule]:
        # Check <search_dir>/<capsule_id>/capsule.yaml or json equivalents
        candidates = [
            self.search_dir / capsule_id / "capsule.yaml",
            self.search_dir / capsule_id / "capsule.json",
            self.search_dir / f"{capsule_id}.yaml",
            self.search_dir / f"{capsule_id}.yml",
            self.search_dir / f"{capsule_id}.json",
        ]
        for c in candidates:
            if c.exists():
                return self.load_from_yaml(c)

        # Fallback built-in capsules
        return self._get_builtin_capsule(capsule_id)

    def _get_builtin_capsule(self, capsule_id: str) -> Optional[AgentCapsule]:
        builtins = {
            "lead-orchestrator": AgentCapsule(
                capsule_id="lead-orchestrator",
                version="3.0.0",
                charter={
                    "role": "Player-Coach Lead Orchestrator",
                    "goal": "Triage tasks, author DAG task contracts, and coordinate factory stations.",
                    "archetypes": ["feature", "refactor", "bugfix", "research", "ops"],
                },
            ),
            "mobile-builder": AgentCapsule(
                capsule_id="mobile-builder",
                version="3.0.0",
                charter={
                    "role": "Contract-Driven Mobile Engineer",
                    "goal": "Implement fluid native components conforming to design tokens.",
                    "archetypes": ["feature", "ui_revamp", "bugfix"],
                },
                capabilities={"skills": ["generative_ui", "android-cli"], "jigs": ["kmp-design-token-assert"]},
                rules_and_invariants={
                    "pareto_budget_cap": 12,
                    "hard_constraints": [
                        {
                            "id": "INV-01",
                            "rule": "Never use raw hex colors outside design-tokens.json",
                            "enforcement": "AST_LINTER",
                        }
                    ],
                },
            ),
            "adversarial-critic": AgentCapsule(
                capsule_id="adversarial-critic",
                version="3.0.0",
                charter={
                    "role": "Independent Adversarial QA Critic",
                    "goal": "Audit patches with zero confirmation bias and evaluate user personas.",
                    "archetypes": ["qa", "audit", "verification"],
                },
            ),
        }
        return builtins.get(capsule_id)
