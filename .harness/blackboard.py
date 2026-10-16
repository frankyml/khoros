#!/usr/bin/env python3
"""
Personal Development Harness (PDH) - Blackboard Engine
SQLite in WAL Mode with Monotonic Fencing Tokens and Atomic CAS Leases.
"""

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = Path(__file__).resolve().parent / "blackboard.db"


class Blackboard:
    def __init__(self, db_path: Path = DB_PATH, lease_ttl_seconds: int = 300):
        self.db_path = db_path
        self.lease_ttl_seconds = lease_ttl_seconds
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
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
                """
            )

    def create_task(self, task_id: str, title: str, payload: Optional[Dict[str, Any]] = None) -> None:
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO tasks (id, title, status, fencing_token, created_at, updated_at, payload_json)
                VALUES (?, ?, 'PENDING', 0, ?, ?, ?)
                """,
                (task_id, title, now, now, json.dumps(payload or {})),
            )

    def claim_task(self, task_id: str, worker: str) -> Tuple[bool, int]:
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
                WHERE id = ? AND (status = 'PENDING' OR lease_expires_at < ?)
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

    def heartbeat(self, task_id: str, fencing_token: int) -> bool:
        now = time.time()
        lease_expires = now + self.lease_ttl_seconds
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND fencing_token = ? AND status = 'CLAIMED';
                """,
                (lease_expires, now, task_id, fencing_token),
            )
            return cursor.rowcount > 0

    def complete_task(self, task_id: str, fencing_token: int, result: Optional[Dict[str, Any]] = None) -> bool:
        now = time.time()
        success = False
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = 'REVIEW_REQUESTED', updated_at = ?
                WHERE id = ? AND fencing_token = ? AND status = 'CLAIMED';
                """,
                (now, task_id, fencing_token),
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
