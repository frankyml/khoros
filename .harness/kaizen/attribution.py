#!/usr/bin/env python3
"""
PDH v3.0 Causal Credit Attribution Engine
Implements the 3-stage elimination DAG algorithm to mathematically apportion
fault between Specification (Lead), Implementation (Builder), Verification (Critic),
and Infrastructure/Tooling.
"""

from typing import Any, Dict
from kernel.event_store import KernelEventStore


def assign_credit_attribution(
    event_store: KernelEventStore, task_id: str, failure_event: Dict[str, Any]
) -> Dict[str, float]:
    """
    Computes causal credit attribution vector for a failed task trajectory.
    Returns: {"spec": alpha_spec, "impl": alpha_impl, "eval": alpha_eval, "tool": alpha_tool}
    """
    proj = event_store.get_projection(task_id)
    payload = failure_event.get("payload", {})
    event_type = failure_event.get("event_type", "")

    # Default attribution vector
    vec = {"spec": 0.0, "impl": 0.0, "eval": 0.0, "tool": 0.0}

    # 1. Tool or Infrastructure Failure
    if event_type in ["TOOL_CRASH", "LEASE_TIMEOUT", "IO_PERMISSION_DENIED"]:
        vec["tool"] = 1.0
        return vec

    # 2. In-Station Poka-Yoke Invariant Violation
    if event_type == "POKA_YOKE_VIOLATION":
        contract = proj.get("payload", {}) if proj else {}
        hard_constraints = contract.get("hard_constraints", [])
        violations = payload.get("violations", [])

        # Check if the violated rule was explicitly in the contract
        known_rules = {c.get("id") for c in hard_constraints if isinstance(c, dict)}
        contract_covered = any(v.get("rule") in known_rules for v in violations)

        if contract_covered:
            # Contract explicitly declared this invariant, yet Builder committed it
            vec["impl"] = 0.85
            vec["eval"] = 0.15
        else:
            # Spec omitted the invariant constraint
            vec["spec"] = 0.70
            vec["impl"] = 0.30
        return vec

    # 3. Adversarial Critic Rejection in Station 3
    if event_type == "STATE_TRANSITION" and payload.get("action") == "audit_rejected":
        # Check if rejection was due to missed acceptance criteria
        reason = payload.get("context", {}).get("reason", "").lower()
        if "criteria" in reason or "requirement" in reason:
            vec["impl"] = 0.80
            vec["spec"] = 0.20
        else:
            # Architectural or edge-case critique
            vec["impl"] = 0.50
            vec["spec"] = 0.50
        return vec

    # 4. Post-Approval Trunk Regression (Critic False Negative)
    if event_type == "TRUNK_INTEGRATION_FAILED":
        vec["eval"] = 0.60
        vec["spec"] = 0.30
        vec["impl"] = 0.10
        return vec

    # 5. Default Fallback
    vec["spec"] = 0.50
    vec["impl"] = 0.50
    return vec
