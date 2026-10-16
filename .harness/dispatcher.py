#!/usr/bin/env python3
"""
Personal Development Harness (PDH) - Intelligent Task Dispatcher
Enforces role barrier invariants, 2-worker concurrency cap, and Token Governor capacity checks.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HARNESS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_DIR))

from blackboard import Blackboard
from governor import PriorityTier, TokenGovernor


class TaskDispatcher:
    def __init__(self, max_concurrent: int = 2):
        self.bb = Blackboard()
        self.gov = TokenGovernor()
        self.max_concurrent = max_concurrent

    def get_active_worker_count(self) -> int:
        tasks = self.bb.list_tasks()
        return sum(1 for t in tasks if t["status"] == "CLAIMED")

    def find_dispatchable_task(self) -> Optional[Dict]:
        tasks = self.bb.list_tasks()
        active_count = self.get_active_worker_count()

        if active_count >= self.max_concurrent:
            return None

        # Prioritize PENDING tasks by order
        pending_tasks = [t for t in tasks if t["status"] == "PENDING"]
        if not pending_tasks:
            return None

        for task in pending_tasks:
            payload = {}
            if task.get("payload_json"):
                try:
                    import json
                    payload = json.loads(task["payload_json"])
                except Exception:
                    pass

            role = payload.get("assigned_role", "dev_mobile")
            tier_str = payload.get("priority", "Q2")

            # Map tier
            tier_map = {
                "Q0": PriorityTier.Q0_CRITICAL,
                "Q1": PriorityTier.Q1_REASONING,
                "Q2": PriorityTier.Q2_CODING,
                "Q3": PriorityTier.Q3_BACKGROUND,
            }
            tier = tier_map.get(tier_str, PriorityTier.Q2_CODING)

            can_run, reason = self.gov.can_dispatch(tier, estimated_tokens=15000)
            if not can_run:
                continue

            return task

        return None

    def dispatch_next(self, worker_name: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        task = self.find_dispatchable_task()
        if not task:
            active = self.get_active_worker_count()
            if active >= self.max_concurrent:
                return False, f"Concurrency limit reached ({active}/{self.max_concurrent} active workers)."
            return False, "No dispatchable pending tasks found."

        assigned_worker = worker_name or f"worker-{task['id']}"
        success, token = self.bb.claim_task(task["id"], assigned_worker)
        if success:
            self.bb.publish_event(
                trace_id=task["id"],
                sender="dispatcher",
                recipient=assigned_worker,
                event_type="TASK_DISPATCHED",
                severity="INFO",
                payload={"fencing_token": token, "task_title": task["title"]},
            )
            return True, f"Dispatched '{task['id']}' to '{assigned_worker}' (Fencing Token: {token})"
        return False, f"Failed to claim task '{task['id']}' (race condition or lease collision)."


if __name__ == "__main__":
    dispatcher = TaskDispatcher()
    ok, msg = dispatcher.dispatch_next()
    print(msg)
