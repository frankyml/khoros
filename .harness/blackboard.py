#!/usr/bin/env python3
"""
Personal Development Harness (PDH) v2.0 - Blackboard Engine
SQLite in WAL Mode with Monotonic Fencing Tokens, Atomic CAS Leases,
Task Contracts, and DAG Dependency Resolution.
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


def resolve_harness_dir() -> Path:
    cwd_harness = Path.cwd() / ".harness"
    if cwd_harness.exists():
        return cwd_harness
    return Path(__file__).resolve().parent


class Blackboard:
    def __init__(self, db_path: Optional[Path] = None, lease_ttl_seconds: int = 1800):
        self.harness_dir = resolve_harness_dir()
        self.db_path = Path(db_path) if db_path else (self.harness_dir / "blackboard.db")
        self.lease_ttl_seconds = lease_ttl_seconds
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 10000;")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    owner TEXT,
                    status TEXT NOT NULL, -- PENDING, CLAIMED, REVIEW_REQUESTED, COMPLETED, FAILED
                    fencing_token INTEGER NOT NULL DEFAULT 0,
                    lease_expires_at REAL,
                    payload_json TEXT,
                    task_type TEXT NOT NULL DEFAULT 'feature',
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_checkpoints (
                    task_id TEXT NOT NULL,
                    checkpoint_hash TEXT NOT NULL,
                    ast_state_json TEXT,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (task_id, checkpoint_hash)
                );

                CREATE TABLE IF NOT EXISTS governor_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    tier TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    cached_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS file_leases (
                    file_path TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    holder_capsule TEXT NOT NULL,
                    lease_expires_at REAL NOT NULL,
                    fencing_token INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS capability_registry (
                    capability_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,                     -- JIG, CLI_TOOL, SKILL, DYNAMIC_CAPSULE
                    generation INTEGER NOT NULL DEFAULT 1,  -- 0=Ephemeral, 1=Staged, 2=Canonical
                    risk_tier INTEGER NOT NULL DEFAULT 1,   -- 1=AST/Read-only, 2=Worktree file, 3=Shell/Mutating
                    version TEXT NOT NULL DEFAULT '1.0.0',
                    file_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    semantic_description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE, SOFT_DEPRECATED, COLD_ARCHIVE, PURGED
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS capability_telemetry (
                    capability_id TEXT PRIMARY KEY,
                    invocations_total INTEGER NOT NULL DEFAULT 0,
                    invocations_success INTEGER NOT NULL DEFAULT 0,
                    invocations_failed INTEGER NOT NULL DEFAULT 0,
                    last_invoked_at REAL NOT NULL,
                    utility_score REAL NOT NULL DEFAULT 1.0,
                    FOREIGN KEY(capability_id) REFERENCES capability_registry(capability_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS capability_dependencies (
                    source_id TEXT NOT NULL,
                    depends_on_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL DEFAULT 'DEPENDS_ON', -- COMPOSES, CALLS, SHADOWS, DEPENDS_ON
                    PRIMARY KEY(source_id, depends_on_id)
                );

                CREATE TABLE IF NOT EXISTS failure_signatures (
                    signature_id TEXT PRIMARY KEY,
                    ast_structural_hash TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    exemplar_diff TEXT NOT NULL,
                    recurrence_count INTEGER NOT NULL DEFAULT 1,
                    first_seen_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    distillation_status TEXT NOT NULL DEFAULT 'PENDING' -- PENDING, DISTILLED, DISMISSED
                );
                CREATE INDEX IF NOT EXISTS idx_failure_sig_hash ON failure_signatures(ast_structural_hash);

                CREATE TABLE IF NOT EXISTS kaizen_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,              -- JIG, TOOL, SKILL
                    slug TEXT NOT NULL,
                    risk_tier INTEGER NOT NULL DEFAULT 1,   -- 1, 2, 3
                    source_code TEXT NOT NULL,
                    test_code TEXT NOT NULL,
                    attribution_vector TEXT NOT NULL DEFAULT '[]', -- JSON: [alpha_spec, alpha_impl, alpha_eval, alpha_tool]
                    canary_scanned_files INTEGER NOT NULL DEFAULT 0,
                    canary_false_positives INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'QUARANTINED', -- QUARANTINED, APPROVED, REJECTED, AUTO_ADMITTED
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            # Backwards-compatible migration for v1.0 databases
            existing_cols = {
                row["name"] for row in conn.execute("PRAGMA table_info(tasks);").fetchall()
            }
            if "task_type" not in existing_cols:
                conn.execute("ALTER TABLE tasks ADD COLUMN task_type TEXT NOT NULL DEFAULT 'feature';")
            if "depends_on_json" not in existing_cols:
                conn.execute("ALTER TABLE tasks ADD COLUMN depends_on_json TEXT NOT NULL DEFAULT '[]';")

    def create_task(
        self,
        task_id: str,
        title: str,
        payload: Optional[Dict[str, Any]] = None,
        task_type: Optional[str] = None,
        depends_on: Optional[List[str]] = None,
    ) -> None:
        now = time.time()
        payload_dict = dict(payload or {})
        resolved_type = task_type or payload_dict.get("task_type", "feature")
        resolved_deps = depends_on if depends_on is not None else payload_dict.get("depends_on", [])
        payload_dict["task_type"] = resolved_type
        payload_dict["depends_on"] = resolved_deps

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    id, title, owner, status, fencing_token, lease_expires_at,
                    payload_json, task_type, depends_on_json, created_at, updated_at
                )
                VALUES (
                    ?, ?,
                    COALESCE((SELECT owner FROM tasks WHERE id = ?), NULL),
                    COALESCE((SELECT status FROM tasks WHERE id = ?), 'PENDING'),
                    COALESCE((SELECT fencing_token FROM tasks WHERE id = ?), 0),
                    COALESCE((SELECT lease_expires_at FROM tasks WHERE id = ?), NULL),
                    ?,
                    ?,
                    ?,
                    COALESCE((SELECT created_at FROM tasks WHERE id = ?), ?),
                    ?
                )
                """,
                (
                    task_id,
                    title,
                    task_id,
                    task_id,
                    task_id,
                    task_id,
                    json.dumps(payload_dict),
                    resolved_type,
                    json.dumps(resolved_deps),
                    task_id,
                    now,
                    now,
                ),
            )

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?;", (task_id,)).fetchone()
            return dict(row) if row else None

    def get_task_dependencies(self, task_id: str) -> List[str]:
        task = self.get_task(task_id)
        if not task:
            return []
        deps = []
        if task.get("depends_on_json"):
            try:
                deps = json.loads(task["depends_on_json"])
            except Exception:
                deps = []
        if not deps and task.get("payload_json"):
            try:
                deps = json.loads(task["payload_json"]).get("depends_on", [])
            except Exception:
                deps = []
        return [d for d in deps if d]

    def are_dependencies_met(self, task_id: str) -> Tuple[bool, List[str]]:
        deps = self.get_task_dependencies(task_id)
        if not deps:
            return True, []
        tasks_by_id = {t["id"]: t for t in self.list_tasks()}
        unmet = []
        for dep_id in deps:
            dep_task = tasks_by_id.get(dep_id)
            if not dep_task or dep_task["status"] != "COMPLETED":
                unmet.append(dep_id)
        return len(unmet) == 0, unmet

    def get_task_contract(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Builds a deterministic Task Contract from the blackboard to eliminate
        the multi-agent 'telephone game' when delegating to subagents.
        """
        task = self.get_task(task_id)
        if not task:
            return None
        payload = {}
        if task.get("payload_json"):
            try:
                payload = json.loads(task["payload_json"])
            except Exception:
                payload = {}
        deps = self.get_task_dependencies(task_id)
        met, unmet = self.are_dependencies_met(task_id)

        # Gather summaries of completed prerequisite tasks for context continuity
        dep_summaries = {}
        if deps:
            all_tasks = {t["id"]: t for t in self.list_tasks()}
            for d in deps:
                if d in all_tasks and all_tasks[d].get("payload_json"):
                    try:
                        dp = json.loads(all_tasks[d]["payload_json"])
                        if dp.get("last_result"):
                            dep_summaries[d] = dp["last_result"]
                    except Exception:
                        pass

        return {
            "id": task["id"],
            "title": task["title"],
            "status": task["status"],
            "owner": task["owner"],
            "fencing_token": task["fencing_token"],
            "task_type": task.get("task_type") or payload.get("task_type", "feature"),
            "priority": payload.get("priority", "Q2"),
            "depends_on": deps,
            "dependencies_met": met,
            "unmet_dependencies": unmet,
            "dependency_outputs": dep_summaries,
            "scope_files": payload.get("scope_files", []),
            "acceptance_criteria": payload.get("acceptance_criteria", []),
            "spec_path": payload.get("spec_path"),
            "verification_cmd": payload.get("verification_cmd", "harness verify"),
        }

    def claim_task(self, task_id: str, worker: str) -> Tuple[bool, int]:
        met, unmet = self.are_dependencies_met(task_id)
        if not met:
            return False, -1

        now = time.time()
        lease_expires = now + self.lease_ttl_seconds
        fencing_token = -1
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET owner = ?,
                    status = 'CLAIMED',
                    fencing_token = fencing_token + 1,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE id = ? AND (status = 'PENDING' OR status = 'CLAIMED' AND (lease_expires_at IS NULL OR lease_expires_at < ?))
                RETURNING fencing_token;
                """,
                (worker, lease_expires, now, task_id, now),
            )
            row = cursor.fetchone()
            if row:
                fencing_token = row["fencing_token"]

        if fencing_token != -1:
            self.publish_event(
                trace_id=task_id,
                sender=worker,
                recipient="orchestrator",
                event_type="TASK_CLAIMED",
                severity="INFO",
                payload={"fencing_token": fencing_token},
            )
            return True, fencing_token
        return False, -1

    def heartbeat(self, task_id: str, fencing_token: Optional[int] = None) -> bool:
        now = time.time()
        lease_expires = now + self.lease_ttl_seconds
        with self._get_connection() as conn:
            if fencing_token is not None:
                cursor = conn.execute(
                    """
                    UPDATE tasks
                    SET lease_expires_at = ?, updated_at = ?
                    WHERE id = ? AND fencing_token = ? AND status = 'CLAIMED';
                    """,
                    (lease_expires, now, task_id, fencing_token),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE tasks
                    SET lease_expires_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'CLAIMED';
                    """,
                    (lease_expires, now, task_id),
                )
            return cursor.rowcount > 0

    def complete_task(
        self,
        task_id: str,
        fencing_token: Optional[int] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        now = time.time()
        success = False
        task = self.get_task(task_id)
        payload = {}
        if task and task.get("payload_json"):
            try:
                payload = json.loads(task["payload_json"])
            except Exception:
                payload = {}
        if result:
            payload["last_result"] = result
        payload_str = json.dumps(payload)

        with self._get_connection() as conn:
            if fencing_token is not None:
                cursor = conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'REVIEW_REQUESTED', payload_json = ?, updated_at = ?
                    WHERE id = ? AND fencing_token = ? AND status IN ('CLAIMED', 'PENDING');
                    """,
                    (payload_str, now, task_id, fencing_token),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'REVIEW_REQUESTED',
                        fencing_token = CASE WHEN fencing_token = 0 THEN 1 ELSE fencing_token END,
                        owner = COALESCE(owner, ?),
                        payload_json = ?,
                        updated_at = ?
                    WHERE id = ? AND status IN ('CLAIMED', 'PENDING', 'REVIEW_REQUESTED');
                    """,
                    (f"worker-{task_id}", payload_str, now, task_id),
                )
            success = cursor.rowcount > 0

        if success:
            self.publish_event(
                trace_id=task_id,
                sender="worker",
                recipient="orchestrator",
                event_type="TASK_SUBMITTED_FOR_REVIEW",
                severity="INFO",
                payload=result or {},
            )
            return True
        return False

    def publish_event(
        self,
        trace_id: str,
        sender: str,
        recipient: str,
        event_type: str,
        severity: str,
        payload: Dict[str, Any],
    ) -> int:
        iso_now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (timestamp, trace_id, sender, recipient, event_type, severity, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING seq;
                """,
                (iso_now, trace_id, sender, recipient, event_type, severity, json.dumps(payload)),
            )
            return cursor.fetchone()["seq"]

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM tasks ORDER BY created_at ASC;")
            return [dict(r) for r in cursor.fetchall()]

    def list_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM events ORDER BY seq DESC LIMIT ?;", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def register_capability(
        self,
        capability_id: str,
        cap_type: str,
        file_path: str,
        content_hash: str,
        semantic_description: str,
        risk_tier: int = 1,
        version: str = "1.0.0",
        generation: int = 1,
        status: str = "ACTIVE",
    ) -> None:
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO capability_registry (
                    capability_id, type, generation, risk_tier, version, file_path, content_hash, semantic_description, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                    type = excluded.type,
                    generation = excluded.generation,
                    risk_tier = excluded.risk_tier,
                    version = excluded.version,
                    file_path = excluded.file_path,
                    content_hash = excluded.content_hash,
                    semantic_description = excluded.semantic_description,
                    status = excluded.status,
                    updated_at = excluded.updated_at;
                """,
                (capability_id, cap_type, generation, risk_tier, version, file_path, content_hash, semantic_description, status, now, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO capability_telemetry (capability_id, invocations_total, invocations_success, invocations_failed, last_invoked_at, utility_score)
                VALUES (?, 0, 0, 0, ?, 1.0);
                """,
                (capability_id, now),
            )

    def get_capability(self, capability_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT c.*, t.invocations_total, t.invocations_success, t.invocations_failed, t.utility_score, t.last_invoked_at
                FROM capability_registry c
                LEFT JOIN capability_telemetry t ON c.capability_id = t.capability_id
                WHERE c.capability_id = ?;
                """,
                (capability_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_capabilities(self, status: Optional[str] = "ACTIVE", cap_type: Optional[str] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT c.*, t.invocations_total, t.invocations_success, t.invocations_failed, t.utility_score, t.last_invoked_at
            FROM capability_registry c
            LEFT JOIN capability_telemetry t ON c.capability_id = t.capability_id
            WHERE 1=1
        """
        params: List[Any] = []
        if status:
            query += " AND c.status = ?"
            params.append(status)
        if cap_type:
            query += " AND c.type = ?"
            params.append(cap_type)
        query += " ORDER BY c.created_at ASC;"
        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def record_capability_invocation(self, capability_id: str, success: bool = True, lambda_decay: float = 0.95) -> float:
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT utility_score, invocations_total, invocations_success, invocations_failed FROM capability_telemetry WHERE capability_id = ?;",
                (capability_id,),
            )
            row = cursor.fetchone()
            if not row:
                u_score = 1.0
                inv_total = 0
                inv_succ = 0
                inv_fail = 0
            else:
                u_score = row["utility_score"]
                inv_total = row["invocations_total"]
                inv_succ = row["invocations_success"]
                inv_fail = row["invocations_failed"]

            # EWMA utility decay: Ut = lambda * Ut-1 + (1 - lambda) * I
            indicator = 1.0 if success else -0.5
            new_u_score = max(0.0, min(1.0, (lambda_decay * u_score) + ((1.0 - lambda_decay) * indicator)))
            inv_total += 1
            if success:
                inv_succ += 1
            else:
                inv_fail += 1

            conn.execute(
                """
                INSERT INTO capability_telemetry (capability_id, invocations_total, invocations_success, invocations_failed, last_invoked_at, utility_score)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                    invocations_total = excluded.invocations_total,
                    invocations_success = excluded.invocations_success,
                    invocations_failed = excluded.invocations_failed,
                    last_invoked_at = excluded.last_invoked_at,
                    utility_score = excluded.utility_score;
                """,
                (capability_id, inv_total, inv_succ, inv_fail, now, new_u_score),
            )
            return new_u_score

    def log_failure_signature(self, ast_structural_hash: str, error_type: str, exemplar_diff: str) -> Tuple[str, int]:
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT signature_id, recurrence_count FROM failure_signatures WHERE ast_structural_hash = ?;",
                (ast_structural_hash,),
            )
            row = cursor.fetchone()
            if row:
                sig_id = row["signature_id"]
                new_count = row["recurrence_count"] + 1
                conn.execute(
                    """
                    UPDATE failure_signatures
                    SET recurrence_count = ?, last_seen_at = ?, exemplar_diff = ?
                    WHERE signature_id = ?;
                    """,
                    (new_count, now, exemplar_diff, sig_id),
                )
                return sig_id, new_count
            else:
                import uuid
                sig_id = f"sig-{uuid.uuid4().hex[:8]}"
                conn.execute(
                    """
                    INSERT INTO failure_signatures (signature_id, ast_structural_hash, error_type, exemplar_diff, recurrence_count, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?);
                    """,
                    (sig_id, ast_structural_hash, error_type, exemplar_diff, now, now),
                )
                return sig_id, 1

    def create_kaizen_proposal(
        self,
        proposal_id: str,
        target_type: str,
        slug: str,
        source_code: str,
        test_code: str,
        risk_tier: int = 1,
        attribution_vector: Optional[List[float]] = None,
        canary_scanned: int = 0,
        canary_fp: int = 0,
        status: str = "QUARANTINED",
    ) -> None:
        now = time.time()
        attr_json = json.dumps(attribution_vector or [0.0, 1.0, 0.0, 0.0])
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO kaizen_proposals (
                    proposal_id, target_type, slug, risk_tier, source_code, test_code, attribution_vector, canary_scanned_files, canary_false_positives, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    source_code = excluded.source_code,
                    test_code = excluded.test_code,
                    canary_scanned_files = excluded.canary_scanned_files,
                    canary_false_positives = excluded.canary_false_positives,
                    status = excluded.status,
                    updated_at = excluded.updated_at;
                """,
                (proposal_id, target_type, slug, risk_tier, source_code, test_code, attr_json, canary_scanned, canary_fp, status, now, now),
            )

    def list_kaizen_proposals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM kaizen_proposals"
        params: List[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC;"
        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def update_kaizen_proposal_status(self, proposal_id: str, status: str) -> bool:
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE kaizen_proposals SET status = ?, updated_at = ? WHERE proposal_id = ?;",
                (status, now, proposal_id),
            )
            return cursor.rowcount > 0

    def recover_expired_leases(self) -> int:
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = 'PENDING',
                    owner = NULL,
                    fencing_token = fencing_token + 1,
                    updated_at = ?
                WHERE status = 'CLAIMED' AND lease_expires_at < ?;
                """,
                (now, now),
            )
            return cursor.rowcount


if __name__ == "__main__":
    bb = Blackboard()
    print(f"Blackboard SQLite initialized at: {bb.db_path}")
