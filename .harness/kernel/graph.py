#!/usr/bin/env python3
"""
PDH v3.0 Dual-Graph State Machine & Execution Runner
Unrolls cyclic logical state machines into an immutable acyclic physical execution ledger.
Enforces anti-deadlock circuit breakers (N <= 3 iterations) and join barriers.
"""

import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from .event_store import KernelEventStore


class TransitionGuard:
    def __init__(self, name: str, predicate: Callable[[Dict[str, Any]], bool], failure_reason: str = ""):
        self.name = name
        self.predicate = predicate
        self.failure_reason = failure_reason

    def evaluate(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        try:
            ok = self.predicate(context)
            return (ok, "" if ok else self.failure_reason)
        except Exception as e:
            return (False, f"Guard exception: {str(e)}")


class StateNode:
    def __init__(self, name: str, is_terminal: bool = False, max_retries: int = 3):
        self.name = name
        self.is_terminal = is_terminal
        self.max_retries = max_retries
        self.transitions: Dict[str, Tuple[str, Optional[TransitionGuard]]] = {}

    def add_transition(
        self, action: str, target_state: str, guard: Optional[TransitionGuard] = None
    ) -> None:
        self.transitions[action] = (target_state, guard)


class ExecutionGraph:
    """
    Dual-Graph execution engine:
    Logical Graph: Cyclical (SUB_ASSEMBLY <-> AUDITING).
    Physical Graph: Acyclic unrolled epochs (epoch=1, epoch=2, ...) recorded in KernelEventStore.
    """

    def __init__(self, event_store: KernelEventStore):
        self.event_store = event_store
        self.nodes: Dict[str, StateNode] = {}
        self._build_default_factory_graph()

    def _build_default_factory_graph(self) -> None:
        # Standard 4-station assembly state machine
        s_pending = StateNode("PENDING")
        s_cad = StateNode("STATION_1_CAD")
        s_sub = StateNode("STATION_2_SUB_ASSEMBLY")
        s_audit = StateNode("STATION_3_AUDIT")
        s_pacemaker = StateNode("STATION_4_PACEMAKER", is_terminal=True)
        s_deadlock = StateNode("DEADLOCK_ESCALATED", is_terminal=True)
        s_failed = StateNode("FAILED", is_terminal=True)

        # Station 1 -> Station 2
        s_pending.add_transition("dispatch", "STATION_1_CAD")
        s_cad.add_transition("contract_ready", "STATION_2_SUB_ASSEMBLY")

        # Station 2 -> Station 3
        s_sub.add_transition("poka_yoke_pass", "STATION_3_AUDIT")
        s_sub.add_transition("andon_pull", "FAILED")

        # Station 3: Pass -> Station 4, Reject -> Station 2 (Loopback)
        s_audit.add_transition("audit_approved", "STATION_4_PACEMAKER")
        s_audit.add_transition(
            "audit_rejected",
            "STATION_2_SUB_ASSEMBLY",
            guard=TransitionGuard(
                "CircuitBreakerMax3",
                lambda ctx: ctx.get("epoch", 1) < 3,
                failure_reason="Anti-deadlock circuit breaker tripped: exceeded 3 review cycles.",
            ),
        )

        for n in [s_pending, s_cad, s_sub, s_audit, s_pacemaker, s_deadlock, s_failed]:
            self.nodes[n.name] = n

    def register_node(self, node: StateNode) -> None:
        self.nodes[node.name] = node

    def check_barrier_sync(self, task_id: str) -> Tuple[bool, List[str]]:
        """
        AND-Join: Verifies that all upstream tasks declared in dependencies have completed.
        """
        proj = self.event_store.get_projection(task_id)
        if not proj:
            return False, ["Task not found"]

        deps = proj.get("dependencies", [])
        unmet = []
        for d in deps:
            d_proj = self.event_store.get_projection(d)
            if not d_proj or d_proj["status"] not in ["STATION_4_PACEMAKER", "COMPLETED"]:
                unmet.append(d)

        return (len(unmet) == 0, unmet)

    def transition(
        self,
        task_id: str,
        action: str,
        caller_capsule: str,
        context_patch: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Performs an atomic state transition on a task.
        Emits transition events to the WAL and increments the execution epoch if looping back.
        """
        proj = self.event_store.get_projection(task_id)
        if not proj:
            return False, f"Task '{task_id}' does not exist.", {}

        curr_state = proj["status"]
        node = self.nodes.get(curr_state)
        if not node:
            return False, f"Unknown current state: '{curr_state}'", {}

        if action not in node.transitions:
            return (
                False,
                f"Invalid transition action '{action}' from state '{curr_state}'. Valid actions: {list(node.transitions.keys())}",
                {},
            )

        target_state, guard = node.transitions[action]
        current_epoch = proj.get("current_epoch", 1)

        ctx = {
            "task_id": task_id,
            "current_state": curr_state,
            "target_state": target_state,
            "epoch": current_epoch,
            **(context_patch or {}),
        }

        # Evaluate transition guard if present
        if guard:
            ok, reason = guard.evaluate(ctx)
            if not ok:
                # If circuit breaker trips, transition to DEADLOCK_ESCALATED
                self.event_store.emit_event(
                    "CIRCUIT_BREAKER_TRIPPED",
                    task_id=task_id,
                    payload={"action": action, "reason": reason, "epoch": current_epoch},
                    emitted_by=caller_capsule,
                    epoch=current_epoch,
                )
                self.event_store.upsert_projection(
                    task_id=task_id,
                    status="DEADLOCK_ESCALATED",
                    archetype=proj["archetype"],
                    contract=proj["payload"],
                    owner=proj["owner"],
                    dependencies=proj["dependencies"],
                    epoch=current_epoch,
                    fencing_token=proj["fencing_token"] + 1,
                )
                return False, f"Guard failed: {reason}. Escalated to DEADLOCK_ESCALATED.", proj

        # If looping back to an earlier station (e.g. audit_rejected -> sub_assembly), advance epoch
        next_epoch = current_epoch
        if action == "audit_rejected":
            next_epoch += 1

        next_fencing_token = proj["fencing_token"] + 1

        # Emit state transition event
        self.event_store.emit_event(
            "STATE_TRANSITION",
            task_id=task_id,
            payload={
                "from_state": curr_state,
                "to_state": target_state,
                "action": action,
                "epoch": next_epoch,
                "context": context_patch or {},
            },
            emitted_by=caller_capsule,
            epoch=next_epoch,
        )

        # Update projection
        self.event_store.upsert_projection(
            task_id=task_id,
            status=target_state,
            archetype=proj["archetype"],
            contract=proj["payload"],
            owner=proj["owner"],
            dependencies=proj["dependencies"],
            epoch=next_epoch,
            fencing_token=next_fencing_token,
        )

        updated_proj = self.event_store.get_projection(task_id)
        return True, f"Transitioned to {target_state} (epoch {next_epoch}).", updated_proj
