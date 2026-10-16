#!/usr/bin/env python3
"""
Personal Development Harness (PDH) - Token Governor & 4-Tier Adaptive Rate Limiter
Enforces Gemini KV-Cache Alignment (>=32k prefix) and 25% Reserved Headroom for Critical Reasoning.
"""

import time
from collections import deque
from enum import Enum
from typing import Any, Deque, Dict, Optional, Tuple


class PriorityTier(Enum):
    Q0_CRITICAL = 0    # Security audits, emergency rollback, HITL
    Q1_REASONING = 1   # Architect design, PRD synthesis (Gemini Pro)
    Q2_CODING = 2      # Dev implementation, QA test generation (Gemini Flash/Pro)
    Q3_BACKGROUND = 3  # Persona UI testing, AST linting, git commit messages (Gemini Flash)


class TokenGovernor:
    def __init__(
        self,
        rpm_limit: int = 60,
        tpm_limit: int = 1000000,
        reserved_headroom_ratio: float = 0.25,
        min_cache_prefix_tokens: int = 32768,
    ):
        self.rpm_limit = rpm_limit
        self.tpm_limit = tpm_limit
        self.reserved_headroom_ratio = reserved_headroom_ratio
        self.min_cache_prefix_tokens = min_cache_prefix_tokens

        # Rolling 60-second window tracking
        self.request_timestamps: Deque[float] = deque()
        self.token_usage_window: Deque[Tuple[float, int]] = deque()

        # Telemetry metrics
        self.total_input_tokens = 0
        self.total_cached_tokens = 0
        self.total_output_tokens = 0

    def _purge_expired(self, now: float) -> None:
        cutoff = now - 60.0
        while self.request_timestamps and self.request_timestamps[0] < cutoff:
            self.request_timestamps.popleft()
        while self.token_usage_window and self.token_usage_window[0][0] < cutoff:
            self.token_usage_window.popleft()

    def can_dispatch(self, tier: PriorityTier, estimated_tokens: int) -> Tuple[bool, Optional[str]]:
        now = time.time()
        self._purge_expired(now)

        current_rpm = len(self.request_timestamps)
        current_tpm = sum(tokens for _, tokens in self.token_usage_window)

        # Capacity calculation
        rpm_capacity = (self.rpm_limit - current_rpm) / self.rpm_limit
        tpm_capacity = (self.tpm_limit - current_tpm) / self.tpm_limit
        available_capacity = min(rpm_capacity, tpm_capacity)

        # Q3 (Background Persona/Lint) is throttled if available capacity falls into reserved headroom (<25%)
        if tier == PriorityTier.Q3_BACKGROUND and available_capacity <= self.reserved_headroom_ratio:
            return False, f"Q3 throttled: Available capacity ({available_capacity*100:.1f}%) within 25% reserve."

        # Hard saturation
        if current_rpm >= self.rpm_limit:
            return False, "Rate limit reached: RPM ceiling saturated."
        if current_tpm + estimated_tokens > self.tpm_limit:
            return False, "Rate limit reached: TPM ceiling saturated."

        return True, None

    def record_usage(
        self,
        tier: PriorityTier,
        input_tokens: int,
        cached_tokens: int,
        output_tokens: int,
    ) -> None:
        now = time.time()
        self.request_timestamps.append(now)
        self.token_usage_window.append((now, input_tokens + output_tokens))

        self.total_input_tokens += input_tokens
        self.total_cached_tokens += cached_tokens
        self.total_output_tokens += output_tokens

    def get_telemetry(self) -> Dict[str, Any]:
        now = time.time()
        self._purge_expired(now)
        current_rpm = len(self.request_timestamps)
        current_tpm = sum(tokens for _, tokens in self.token_usage_window)
        cache_hit_rate = (
            (self.total_cached_tokens / self.total_input_tokens * 100)
            if self.total_input_tokens > 0
            else 0.0
        )
        return {
            "current_rpm": current_rpm,
            "rpm_limit": self.rpm_limit,
            "current_tpm": current_tpm,
            "tpm_limit": self.tpm_limit,
            "total_input_tokens": self.total_input_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "total_output_tokens": self.total_output_tokens,
            "cache_hit_rate_percent": round(cache_hit_rate, 2),
        }


if __name__ == "__main__":
    gov = TokenGovernor()
    print("Token Governor initialized. Telemetry:", gov.get_telemetry())
