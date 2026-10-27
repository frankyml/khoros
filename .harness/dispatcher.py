#!/usr/bin/env python3
"""
Personal Development Harness (PDH) v2.0 - Intelligent Task Dispatcher & Lead Router
Enforces DAG dependency barriers, 2-worker concurrency cap, Token Governor capacity checks,
Player-Coach complexity triage, and zero-loss Subagent Prompt Packet generation.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HARNESS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_DIR))

from blackboard import Blackboard
from governor import PriorityTier, TokenGovernor


class LeadRouter:
    """
    Implements the SOTA 'Player-Coach' Adaptive Lead Orchestrator routing logic.
    Classifies tasks into Complexity Tiers (T0-T3) to avoid subagent latency/telephone-game
    on simple tasks while enforcing Blackboard Contracts + Generator-Verifier separation on complex tasks.
    """

    RESEARCH_KEYWORDS = ("analyse", "analyze", "research", "state of the art", "sota", "compare", "investigate", "audit", "explore")
    BUGFIX_KEYWORDS = ("bug", "fix", "crash", "error", "regression", "broken", "fail", "exception", "fault")
    ARCHITECTURE_KEYWORDS = ("architecture", "iterate", "redesign", "refactor", "migrate", "harness", "system", "multi-agent", "orchestrator")

    def triage(
        self,
        request_text: str,
        scope_files: Optional[List[str]] = None,
        explicit_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        text_lower = request_text.lower()
        files = scope_files or []
        file_count = len(files)

        # Determine task archetype
        if explicit_type:
            task_type = explicit_type.lower()
        elif any(kw in text_lower for kw in self.BUGFIX_KEYWORDS):
            task_type = "bugfix"
        elif any(kw in text_lower for kw in self.RESEARCH_KEYWORDS) and not any(
            w in text_lower for w in ("implement", "build", "create", "write")
        ):
            task_type = "research"
        elif any(kw in text_lower for kw in self.ARCHITECTURE_KEYWORDS):
            task_type = "refactor"
        else:
            task_type = "feature"

        # Determine recommended spec type
        spec_map = {
            "feature": "prd",
            "refactor": "rfc",
            "bugfix": "rca",
            "research": "brief",
            "ops": "rfc",
            "qa": "rca",
        }
        recommended_spec = spec_map.get(task_type, "rfc")

        # Complexity scoring
        word_count = len(request_text.split())
        is_multi_domain = any(kw in text_lower for kw in ("architecture", "multi-agent", "end-to-end", "across", "all ", "full", "iterate"))

        if file_count <= 1 and word_count < 20 and not is_multi_domain and task_type != "research":
            tier = "T0_MICRO"
            execution_mode = "DIRECT_FAST_PATH"
            recommended_roles = ["@lead"]
            use_worktree = False
            needs_spec = False
            rationale = "Single-scope micro task: execute directly in @lead main loop to avoid subagent startup overhead and context compression."
        elif file_count <= 3 and not is_multi_domain and task_type in ("bugfix", "feature"):
            tier = "T1_SCOPED"
            execution_mode = "DIRECT_WITH_VERIFY"
            recommended_roles = ["@lead", "@critic"]
            use_worktree = False
            needs_spec = task_type == "bugfix"
            rationale = "Scoped 1-3 file task: track in blackboard.db, execute in @lead loop, and run deterministic 'harness verify' gate."
        elif task_type == "research":
            tier = "T2_ORCHESTRATED"
            execution_mode = "SUBAGENT_FAN_OUT"
            recommended_roles = ["@lead", "@explorer", "@critic"]
            use_worktree = False
            needs_spec = True
            rationale = "Deep research/analysis task: delegate broad exploration to read-only @explorer subagents to protect @lead context window, then synthesize."
        else:
            tier = "T2_ORCHESTRATED" if file_count <= 6 else "T3_PARALLEL_DAG"
            execution_mode = "SUBAGENT_FAN_OUT"
            recommended_roles = ["@lead", "@architect", "@builder", "@critic"]
            use_worktree = True
            needs_spec = True
            rationale = (
                "Complex/multi-component task: author spec & DAG in blackboard.db, dispatch isolated @builder subagents "
                "(Workspace='share'), and enforce independent @critic verification."
            )

        return {
            "tier": tier,
            "task_type": task_type,
            "execution_mode": execution_mode,
            "recommended_spec": recommended_spec if needs_spec else "none",
            "recommended_roles": recommended_roles,
            "workspace_isolation": "share" if use_worktree else "inherit",
            "max_parallel_workers": 2 if use_worktree else 1,
            "rationale": rationale,
        }


class TaskDispatcher:
    def __init__(self, max_concurrent: int = 2, db_path: Optional[Path] = None):
        self.bb = Blackboard(db_path=db_path)
        self.gov = TokenGovernor(db_path=db_path)
        self.max_concurrent = max_concurrent
        self.router = LeadRouter()

    def get_active_worker_count(self) -> int:
        tasks = self.bb.list_tasks()
        return sum(1 for t in tasks if t["status"] == "CLAIMED")

    def _map_priority_tier(self, task: Dict) -> PriorityTier:
        payload = {}
        if task.get("payload_json"):
            try:
                payload = json.loads(task["payload_json"])
            except Exception:
                pass
        tier_str = payload.get("priority", "Q2")
        tier_map = {
            "Q0": PriorityTier.Q0_CRITICAL,
            "Q1": PriorityTier.Q1_REASONING,
            "Q2": PriorityTier.Q2_CODING,
            "Q3": PriorityTier.Q3_BACKGROUND,
        }
        return tier_map.get(tier_str, PriorityTier.Q2_CODING)

    def find_dispatchable_task(self, target_task_id: Optional[str] = None) -> Optional[Dict]:
        # Reclaim any expired leases automatically before checking concurrency
        self.bb.recover_expired_leases()

        tasks = self.bb.list_tasks()
        active_count = self.get_active_worker_count()

        if active_count >= self.max_concurrent:
            return None

        pending_tasks = [t for t in tasks if t["status"] == "PENDING"]
        if target_task_id:
            pending_tasks = [t for t in pending_tasks if t["id"] == target_task_id]

        if not pending_tasks:
            return None

        for task in pending_tasks:
            # Enforce DAG dependency barrier
            deps_met, _ = self.bb.are_dependencies_met(task["id"])
            if not deps_met:
                continue

            tier = self._map_priority_tier(task)
            can_run, _ = self.gov.can_dispatch(tier, estimated_tokens=15000)
            if not can_run:
                continue
            return task

        return None

    def dispatch_next(
        self,
        worker_name: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        if task_id:
            deps_met, unmet = self.bb.are_dependencies_met(task_id)
            if not deps_met:
                return (
                    False,
                    f"Blocked by DAG dependency barrier: Task '{task_id}' waits on {', '.join(unmet)} to reach COMPLETED.",
                )

        task = self.find_dispatchable_task(target_task_id=task_id)
        if not task:
            active = self.get_active_worker_count()
            if active >= self.max_concurrent:
                return False, f"Concurrency limit reached ({active}/{self.max_concurrent} active workers)."
            if task_id:
                return False, f"Task '{task_id}' is not in PENDING state or does not exist."
            return False, "No dispatchable pending tasks found (or pending tasks are waiting on unmet dependencies)."

        assigned_worker = worker_name or f"worker-{task['id']}"
        success, token = self.bb.claim_task(task["id"], assigned_worker)
        if success:
            tier = self._map_priority_tier(task)
            self.bb.publish_event(
                trace_id=task["id"],
                sender="dispatcher",
                recipient=assigned_worker,
                event_type="TASK_DISPATCHED",
                severity="INFO",
                payload={"fencing_token": token, "task_title": task["title"]},
            )
            return True, f"Dispatched '{task['id']}' to '{assigned_worker}' (Fencing Token: {token})"
        return False, f"Failed to claim task '{task['id']}' (race condition, unmet dependency, or lease collision)."

    def generate_subagent_packet(self, task_id: str, role: str = "@builder") -> str:
        """
        Generates a structured, zero-loss Subagent Task Brief from blackboard.db
        so subagents invoked via Antigravity's invoke_subagent have exact context.
        """
        contract = self.bb.get_task_contract(task_id)
        if not contract:
            return f"Error: Task '{task_id}' not found in blackboard."

        scope_str = (
            "\n".join(f"  - `{f}`" for f in contract["scope_files"])
            if contract["scope_files"]
            else "  - (Determine from repository structure and spec)"
        )
        criteria_str = (
            "\n".join(f"  - [ ] {c}" for c in contract["acceptance_criteria"])
            if contract["acceptance_criteria"]
            else "  - [ ] All unit/integration tests and `harness verify` pass with zero errors."
        )
        dep_str = "None"
        if contract["dependency_outputs"]:
            dep_lines = [f"  - **{k}**: {json.dumps(v)}" for k, v in contract["dependency_outputs"].items()]
            dep_str = "\n" + "\n".join(dep_lines)

        spec_line = f"`{contract['spec_path']}`" if contract.get("spec_path") else "See `docs/` or task description"

        return f"""# PDH v2.0 Subagent Dispatch Packet
**Assigned Role**: `{role}`
**Task ID**: `{contract['id']}`
**Title**: {contract['title']}
**Task Type**: `{contract['task_type']}` | **Priority**: `{contract['priority']}` | **Fencing Token**: `{contract['fencing_token']}`
**Reference Spec**: {spec_line}

## 1. Scope & Target Files
{scope_str}

## 2. Prerequisite Task Outputs (Blackboard Context)
{dep_str}

## 3. Acceptance Criteria
{criteria_str}

## 4. Mandatory Execution & Verification Protocol
1. Claim or heartbeat the task if not already claimed:
   `harness heartbeat {contract['id']}`
2. Implement only the scoped changes required to satisfy the acceptance criteria.
3. Run the deterministic verification pipeline before finishing:
   `{contract['verification_cmd']}`
4. Submit your completed work to the blackboard for `@critic` / `@lead` review:
   `harness submit {contract['id']} --summary "<concise summary of changes and verification>"`
"""


if __name__ == "__main__":
    dispatcher = TaskDispatcher()
    ok, msg = dispatcher.dispatch_next()
    print(msg)
