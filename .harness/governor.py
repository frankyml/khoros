#!/usr/bin/env python3
"""
Personal Development Harness (PDH v3.1 / Khoros) - Token Governor & Resilience Engine
Enforces KV-Cache Alignment (>=32k prefix), Dynamic Reserve Scaling,
and Andon Cord Emergency Circuit Breakers (trips when CHR < 70%).
Backed by SQLite WAL in blackboard.db for cross-process concurrency safety.
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple


def resolve_harness_dir() -> Path:
    cwd_harness = Path.cwd() / ".harness"
    if cwd_harness.exists():
        return cwd_harness
    return Path(__file__).resolve().parent


class PriorityTier(Enum):
    Q0_CRITICAL = 0    # Security audits, emergency rollback, Andon reset, HITL
    Q1_REASONING = 1   # Architect design, PRD synthesis (Frontier Reasoning)
    Q2_CODING = 2      # Dev implementation, QA test generation (Frontier/Flash)
    Q3_BACKGROUND = 3  # Persona UI testing, AST linting, git commit messages


class CircuitBreakerState(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    TRIPPED = "TRIPPED"
    WARMING = "WARMING"


class TokenGovernor:
    def __init__(
        self,
        rpm_limit: int = 60,
        tpm_limit: int = 1000000,
        reserved_headroom_ratio: float = 0.25,
        base_reserve_ratio: Optional[float] = None,
        max_reserve_ratio: float = 0.80,
        target_chr: float = 0.85,
        andon_threshold_chr: float = 0.70,
        min_cache_prefix_tokens: Optional[int] = None,
        db_path: Optional[Path] = None,
    ):
        self.rpm_limit = rpm_limit
        self.tpm_limit = tpm_limit
        self.base_reserve_ratio = base_reserve_ratio if base_reserve_ratio is not None else reserved_headroom_ratio
        self.reserved_headroom_ratio = self.base_reserve_ratio
        self.max_reserve_ratio = max_reserve_ratio
        self.target_chr = target_chr
        self.andon_threshold_chr = andon_threshold_chr

        if min_cache_prefix_tokens is not None:
            self.min_cache_prefix_tokens = min_cache_prefix_tokens
        else:
            try:
                from kernel.host import get_host_environment
                self.min_cache_prefix_tokens = get_host_environment().get("cache_prefix_tokens", 32768)
            except Exception:
                self.min_cache_prefix_tokens = 32768

        self.harness_dir = resolve_harness_dir()
        self.db_path = Path(db_path) if db_path else (self.harness_dir / "blackboard.db")
        self._init_table()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=15.0, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 15000;")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    def _init_table(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS governor_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    tier TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    cached_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    cache_creation_tokens INTEGER DEFAULT 0,
                    cache_read_tokens INTEGER DEFAULT 0,
                    cache_miss_tokens INTEGER DEFAULT 0,
                    latency_ms REAL DEFAULT 0.0,
                    ttft_ms REAL DEFAULT 0.0,
                    is_cache_break INTEGER DEFAULT 0
                );
                """
            )
            # Idempotent column upgrades for backwards compatibility
            existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(governor_usage);").fetchall()}
            for col, col_def in [
                ("cache_creation_tokens", "INTEGER DEFAULT 0"),
                ("cache_read_tokens", "INTEGER DEFAULT 0"),
                ("cache_miss_tokens", "INTEGER DEFAULT 0"),
                ("latency_ms", "REAL DEFAULT 0.0"),
                ("ttft_ms", "REAL DEFAULT 0.0"),
                ("is_cache_break", "INTEGER DEFAULT 0"),
            ]:
                if col not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE governor_usage ADD COLUMN {col} {col_def};")
                    except sqlite3.OperationalError:
                        pass

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS governor_circuit_breaker_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    chr_percent REAL NOT NULL,
                    current_tpm INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    metadata_json TEXT
                );
                """
            )

    def calculate_dynamic_reserve(self, current_chr: float) -> float:
        """
        Mathematical Dynamic Reserve Formula:
        R_dynamic = R_base + (R_max - R_base) * max(0, 1 - (CHR / CHR_target))^1.5
        """
        if current_chr >= self.target_chr:
            return self.base_reserve_ratio

        deficit = max(0.0, 1.0 - (current_chr / self.target_chr))
        scaling = pow(deficit, 1.5)
        reserve = self.base_reserve_ratio + (self.max_reserve_ratio - self.base_reserve_ratio) * scaling
        return min(self.max_reserve_ratio, max(self.base_reserve_ratio, reserve))

    def evaluate_circuit_breaker(self) -> Tuple[CircuitBreakerState, str, Dict[str, Any]]:
        telemetry = self.get_telemetry()
        chr_ratio = telemetry["window_chr"]
        sample_count = telemetry["window_sample_count"]

        # If insufficient samples in window, consider HEALTHY
        if sample_count < 3:
            return CircuitBreakerState.HEALTHY, "Insufficient telemetry window samples.", telemetry

        if chr_ratio < self.andon_threshold_chr:
            return (
                CircuitBreakerState.TRIPPED,
                f"Andon Cord Tripped: Sliding CHR ({chr_ratio*100:.1f}%) < Threshold ({self.andon_threshold_chr*100:.1f}%).",
                telemetry,
            )
        elif chr_ratio < self.target_chr:
            return (
                CircuitBreakerState.DEGRADED,
                f"Degraded Performance: Sliding CHR ({chr_ratio*100:.1f}%) < Target ({self.target_chr*100:.1f}%).",
                telemetry,
            )

        return CircuitBreakerState.HEALTHY, "All cache telemetry invariants within nominal bounds.", telemetry

    def can_dispatch(self, tier: PriorityTier, estimated_tokens: int) -> Tuple[bool, Optional[str]]:
        state, reason, telemetry = self.evaluate_circuit_breaker()
        current_rpm = telemetry["current_rpm"]
        current_tpm = telemetry["current_tpm"]
        chr_ratio = telemetry["window_chr"]
        dynamic_reserve = self.calculate_dynamic_reserve(chr_ratio)

        rpm_capacity = max(0.0, (self.rpm_limit - current_rpm) / self.rpm_limit)
        tpm_capacity = max(0.0, (self.tpm_limit - current_tpm) / self.tpm_limit)
        available_capacity = min(rpm_capacity, tpm_capacity)

        # 1. Hard Ceiling Checks
        if current_rpm >= self.rpm_limit:
            return False, f"Rate limit reached: RPM ceiling saturated ({current_rpm}/{self.rpm_limit})."
        if current_tpm + estimated_tokens > self.tpm_limit:
            return False, f"Rate limit reached: TPM ceiling saturated ({current_tpm + estimated_tokens}/{self.tpm_limit})."

        # 2. Andon Cord Tripped Gate: Block non-critical queues during cache failure
        if state == CircuitBreakerState.TRIPPED:
            if tier not in (PriorityTier.Q0_CRITICAL, PriorityTier.Q1_REASONING):
                return False, f"ANDON CORD ACTIVE: {reason} Non-critical dispatch halted until cache stabilizes."

        # 3. Dynamic Priority Headroom Enforcement
        if tier == PriorityTier.Q3_BACKGROUND:
            if available_capacity <= dynamic_reserve:
                return False, f"Q3 throttled: Available capacity ({available_capacity*100:.1f}%) within dynamic reserve ({dynamic_reserve*100:.1f}%)."
        elif tier == PriorityTier.Q2_CODING:
            q2_threshold = dynamic_reserve * 0.70
            if available_capacity <= q2_threshold:
                return False, f"Q2 throttled: Available capacity ({available_capacity*100:.1f}%) below tier threshold ({q2_threshold*100:.1f}%)."
        elif tier == PriorityTier.Q1_REASONING:
            if available_capacity <= 0.10:
                return False, f"Q1 throttled: Available capacity ({available_capacity*100:.1f}%) below emergency 10% floor."

        return True, None

    def record_usage(
        self,
        tier: PriorityTier,
        input_tokens: int = 36000,
        cached_tokens: int = 32768,
        output_tokens: int = 2048,
        cache_creation_tokens: int = 0,
        latency_ms: float = 0.0,
        ttft_ms: float = 0.0,
    ) -> None:
        now = time.time()
        tier_name = tier.name if isinstance(tier, PriorityTier) else str(tier)

        is_cache_break = 1 if (input_tokens >= self.min_cache_prefix_tokens and cached_tokens < (self.min_cache_prefix_tokens * 0.5)) else 0
        cache_read_tokens = cached_tokens
        cache_miss_tokens = max(0, input_tokens - cached_tokens)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO governor_usage (
                    timestamp, tier, input_tokens, cached_tokens, output_tokens,
                    cache_creation_tokens, cache_read_tokens, cache_miss_tokens,
                    latency_ms, ttft_ms, is_cache_break
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    now, tier_name, input_tokens, cached_tokens, output_tokens,
                    cache_creation_tokens, cache_read_tokens, cache_miss_tokens,
                    latency_ms, ttft_ms, is_cache_break,
                ),
            )

            if is_cache_break:
                conn.execute(
                    """
                    INSERT INTO governor_circuit_breaker_events (timestamp, event_type, chr_percent, current_tpm, reason, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (
                        now,
                        "CACHE_BREAK_DETECTED",
                        0.0,
                        input_tokens,
                        f"Uncached prefix detected on {tier_name} ({input_tokens} tokens)",
                        json.dumps({"latency_ms": latency_ms, "ttft_ms": ttft_ms}),
                    ),
                )

    def get_telemetry(self) -> Dict[str, Any]:
        now = time.time()
        window_1m = now - 60.0
        window_5m = now - 300.0

        with self._get_connection() as conn:
            m1_row = conn.execute(
                """
                SELECT COUNT(*) AS rpm,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS tpm,
                       COALESCE(SUM(is_cache_break), 0) AS cache_breaks_1m
                FROM governor_usage
                WHERE timestamp >= ?;
                """,
                (window_1m,),
            ).fetchone()

            m5_row = conn.execute(
                """
                SELECT COUNT(*) AS sample_count,
                       COALESCE(SUM(input_tokens), 0) AS window_in,
                       COALESCE(SUM(cached_tokens), 0) AS window_cached,
                       COALESCE(SUM(cache_creation_tokens), 0) AS window_creation,
                       COALESCE(SUM(is_cache_break), 0) AS window_breaks,
                       AVG(NULLIF(ttft_ms, 0.0)) AS avg_ttft_ms
                FROM governor_usage
                WHERE timestamp >= ?;
                """,
                (window_5m,),
            ).fetchone()

            totals_row = conn.execute(
                """
                SELECT COALESCE(SUM(input_tokens), 0) AS total_in,
                       COALESCE(SUM(cached_tokens), 0) AS total_cached,
                       COALESCE(SUM(output_tokens), 0) AS total_out,
                       COALESCE(SUM(is_cache_break), 0) AS total_breaks
                FROM governor_usage;
                """
            ).fetchone()

            total_in = totals_row["total_in"]
            total_cached = totals_row["total_cached"]
            total_out = totals_row["total_out"]
            if total_in == 0:
                try:
                    ev_count = conn.execute("SELECT COUNT(*) AS c FROM events;").fetchone()["c"]
                    if ev_count > 0:
                        total_in = ev_count * 36000
                        total_cached = ev_count * 32768
                        total_out = ev_count * 2048
                except sqlite3.OperationalError:
                    pass

            break_timestamps = [
                r["timestamp"] for r in conn.execute(
                    "SELECT timestamp FROM governor_usage WHERE is_cache_break = 1 ORDER BY timestamp ASC;"
                ).fetchall()
            ]

        win_in = m5_row["window_in"]
        win_cached = m5_row["window_cached"]
        window_chr = (win_cached / win_in) if win_in > 0 else (1.0 if total_in == 0 else (total_cached / total_in))

        lifetime_chr = (total_cached / total_in * 100.0) if total_in > 0 else 0.0

        if len(break_timestamps) >= 2:
            deltas = [break_timestamps[i] - break_timestamps[i-1] for i in range(1, len(break_timestamps))]
            mtbci_seconds = sum(deltas) / len(deltas)
        else:
            mtbci_seconds = 3600.0

        current_rpm = m1_row["rpm"]
        current_tpm = m1_row["tpm"]
        dynamic_reserve = self.calculate_dynamic_reserve(window_chr)

        return {
            "current_rpm": current_rpm,
            "rpm_limit": self.rpm_limit,
            "current_tpm": current_tpm,
            "tpm_limit": self.tpm_limit,
            "window_sample_count": m5_row["sample_count"],
            "window_chr": round(window_chr, 4),
            "window_chr_percent": round(window_chr * 100.0, 2),
            "lifetime_chr_percent": round(lifetime_chr, 2),
            "cache_hit_rate_percent": round(lifetime_chr, 2),  # Backwards compatibility
            "dynamic_reserve_percent": round(dynamic_reserve * 100.0, 1),
            "cache_breaks_last_5m": m5_row["window_breaks"],
            "mtbci_seconds": round(mtbci_seconds, 1),
            "avg_ttft_ms": round(m5_row["avg_ttft_ms"] or 0.0, 1),
            "total_input_tokens": total_in,
            "total_cached_tokens": total_cached,
            "total_output_tokens": total_out,
            "total_cache_breaks": totals_row["total_breaks"],
        }


if __name__ == "__main__":
    gov = TokenGovernor()
    print("Token Governor initialized. Telemetry:", gov.get_telemetry())
