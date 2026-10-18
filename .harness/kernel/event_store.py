#!/usr/bin/env python3
"""
PDH v3.0 Microkernel Event Store
Append-only SQLite WAL ledger supporting atomic BEGIN IMMEDIATE transactions,
event-sourced projections, distributed file leases, and quarantined Kaizen proposals.
"""

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


class KernelEventStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 10000;")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write_connection(self) -> Iterator[sqlite3.Connection]:
        """
        Acquires an immediate write lock to guarantee zero-contention serialization
        under concurrent multi-agent squad workers.
        """
        conn = sqlite3.connect(str(self.db_path), timeout=20.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 15000;")
            conn.execute("BEGIN IMMEDIATE;")
            yield conn
            if conn.in_transaction:
                conn.execute("COMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK;")
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        conn = sqlite3.connect(str(self.db_path), timeout=20.0)
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 15000;")
            conn.executescript(
                """
                -- 1. Append-Only Event Stream
                CREATE TABLE IF NOT EXISTS kernel_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    epoch INTEGER NOT NULL DEFAULT 1,
                    payload_json TEXT NOT NULL,
                    emitted_by TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_task_epoch ON kernel_events(task_id, epoch);

                -- 2. State Projections (Materialized View of Active Tasks)
                CREATE TABLE IF NOT EXISTS task_projections (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    archetype TEXT NOT NULL,
                    owner TEXT,
                    fencing_token INTEGER NOT NULL DEFAULT 0,
                    current_epoch INTEGER NOT NULL DEFAULT 1,
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    contract_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL
                );

                -- 3. Distributed File Lease Registry
                CREATE TABLE IF NOT EXISTS file_leases (
                    file_path TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    holder_capsule TEXT NOT NULL,
                    lease_expires_at REAL NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES task_projections(task_id) ON DELETE CASCADE
                );

                -- 4. Quarantined Kaizen Proposals (Security Isolation)
                CREATE TABLE IF NOT EXISTS kaizen_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    capsule_id TEXT NOT NULL,
                    proposal_type TEXT NOT NULL,       -- LINTER_AST, RULE_INVARIANT, PROMPT_EXEMPLAR
                    target_path TEXT NOT NULL,
                    diff_payload TEXT NOT NULL,
                    support_count INTEGER DEFAULT 1,    -- Requires N >= 3 incidents
                    status TEXT DEFAULT 'QUARANTINED', -- QUARANTINED, APPROVED, REJECTED
                    created_at REAL NOT NULL
                );
                """
            )
        finally:
            conn.close()

    def emit_event(
        self,
        event_type: str,
        task_id: str,
        payload: Dict[str, Any],
        emitted_by: str,
        epoch: int = 1,
    ) -> int:
        now = time.time()
        payload_str = json.dumps(payload, sort_keys=True)
        with self._write_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO kernel_events (event_type, task_id, epoch, payload_json, emitted_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (event_type, task_id, epoch, payload_str, emitted_by, now),
            )
            event_id = cur.lastrowid
        return event_id

    def get_events(
        self, task_id: Optional[str] = None, since_id: int = 0
    ) -> List[Dict[str, Any]]:
        with self._read_connection() as conn:
            if task_id:
                rows = conn.execute(
                    """
                    SELECT event_id, event_type, task_id, epoch, payload_json, emitted_by, created_at
                    FROM kernel_events
                    WHERE task_id = ? AND event_id > ?
                    ORDER BY event_id ASC;
                    """,
                    (task_id, since_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT event_id, event_type, task_id, epoch, payload_json, emitted_by, created_at
                    FROM kernel_events
                    WHERE event_id > ?
                    ORDER BY event_id ASC;
                    """,
                    (since_id,),
                ).fetchall()

            return [
                {
                    "event_id": r["event_id"],
                    "event_type": r["event_type"],
                    "task_id": r["task_id"],
                    "epoch": r["epoch"],
                    "payload": json.loads(r["payload_json"]),
                    "emitted_by": r["emitted_by"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def upsert_projection(
        self,
        task_id: str,
        status: str,
        archetype: str,
        contract: Dict[str, Any],
        owner: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        epoch: int = 1,
        fencing_token: Optional[int] = None,
    ) -> None:
        now = time.time()
        contract_hash = hashlib.sha256(
            json.dumps(contract, sort_keys=True).encode("utf-8")
        ).hexdigest()
        deps_json = json.dumps(dependencies or [])
        payload_json = json.dumps(contract)

        with self._write_connection() as conn:
            existing = conn.execute(
                "SELECT fencing_token FROM task_projections WHERE task_id = ?;",
                (task_id,),
            ).fetchone()
            if existing and fencing_token is None:
                token = existing["fencing_token"]
            else:
                token = fencing_token if fencing_token is not None else 0

            conn.execute(
                """
                INSERT INTO task_projections (
                    task_id, status, archetype, owner, fencing_token, current_epoch,
                    dependencies_json, contract_hash, payload_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status = excluded.status,
                    archetype = excluded.archetype,
                    owner = COALESCE(excluded.owner, task_projections.owner),
                    fencing_token = excluded.fencing_token,
                    current_epoch = excluded.current_epoch,
                    dependencies_json = excluded.dependencies_json,
                    contract_hash = excluded.contract_hash,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at;
                """,
                (
                    task_id,
                    status,
                    archetype,
                    owner,
                    token,
                    epoch,
                    deps_json,
                    contract_hash,
                    payload_json,
                    now,
                ),
            )

    def get_projection(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._read_connection() as conn:
            row = conn.execute(
                """
                SELECT task_id, status, archetype, owner, fencing_token, current_epoch,
                       dependencies_json, contract_hash, payload_json, updated_at
                FROM task_projections
                WHERE task_id = ?;
                """,
                (task_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "task_id": row["task_id"],
                "status": row["status"],
                "archetype": row["archetype"],
                "owner": row["owner"],
                "fencing_token": row["fencing_token"],
                "current_epoch": row["current_epoch"],
                "dependencies": json.loads(row["dependencies_json"]),
                "contract_hash": row["contract_hash"],
                "payload": json.loads(row["payload_json"]),
                "updated_at": row["updated_at"],
            }

    def list_projections(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._read_connection() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM task_projections WHERE status = ? ORDER BY updated_at DESC;",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM task_projections ORDER BY updated_at DESC;"
                ).fetchall()
            return [
                {
                    "task_id": r["task_id"],
                    "status": r["status"],
                    "archetype": r["archetype"],
                    "owner": r["owner"],
                    "fencing_token": r["fencing_token"],
                    "current_epoch": r["current_epoch"],
                    "dependencies": json.loads(r["dependencies_json"]),
                    "contract_hash": r["contract_hash"],
                    "payload": json.loads(r["payload_json"]),
                    "updated_at": r["updated_at"],
                }
                for r in rows
            ]

    # Distributed File Leases
    def acquire_file_leases(
        self,
        files: List[str],
        task_id: str,
        holder_capsule: str,
        fencing_token: int,
        ttl_seconds: int = 1800,
    ) -> Tuple[bool, List[str]]:
        """
        Atomically claims a set of file leases for a worker.
        If any file is already leased by an unexpired worker, returns (False, [conflicting_files]).
        """
        now = time.time()
        expires_at = now + ttl_seconds
        conflicts = []

        with self._write_connection() as conn:
            # Check for active conflicting leases
            for f in files:
                row = conn.execute(
                    """
                    SELECT task_id, holder_capsule, lease_expires_at
                    FROM file_leases
                    WHERE file_path = ? AND lease_expires_at > ? AND task_id != ?;
                    """,
                    (f, now, task_id),
                ).fetchone()
                if row:
                    conflicts.append(f)

            if conflicts:
                return False, conflicts

            # Insert / refresh leases
            for f in files:
                conn.execute(
                    """
                    INSERT INTO file_leases (file_path, task_id, holder_capsule, lease_expires_at, fencing_token)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(file_path) DO UPDATE SET
                        task_id = excluded.task_id,
                        holder_capsule = excluded.holder_capsule,
                        lease_expires_at = excluded.lease_expires_at,
                        fencing_token = excluded.fencing_token;
                    """,
                    (f, task_id, holder_capsule, expires_at, fencing_token),
                )

        return True, []

    def release_file_leases(self, task_id: str) -> int:
        with self._write_connection() as conn:
            cur = conn.execute(
                "DELETE FROM file_leases WHERE task_id = ?;", (task_id,)
            )
            return cur.rowcount

    # Quarantined Kaizen Proposals
    def submit_kaizen_proposal(
        self,
        proposal_id: str,
        capsule_id: str,
        proposal_type: str,
        target_path: str,
        diff_payload: str,
    ) -> None:
        now = time.time()
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT INTO kaizen_proposals (
                    proposal_id, capsule_id, proposal_type, target_path, diff_payload, support_count, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, 1, 'QUARANTINED', ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    support_count = kaizen_proposals.support_count + 1,
                    diff_payload = excluded.diff_payload;
                """,
                (proposal_id, capsule_id, proposal_type, target_path, diff_payload, now),
            )

    def list_kaizen_proposals(
        self, status: str = "QUARANTINED"
    ) -> List[Dict[str, Any]]:
        with self._read_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM kaizen_proposals WHERE status = ? ORDER BY created_at DESC;",
                (status,),
            ).fetchall()
            return [dict(r) for r in rows]

    def approve_kaizen_proposal(self, proposal_id: str) -> bool:
        with self._write_connection() as conn:
            cur = conn.execute(
                "UPDATE kaizen_proposals SET status = 'APPROVED' WHERE proposal_id = ? AND status = 'QUARANTINED';",
                (proposal_id,),
            )
            return cur.rowcount > 0
