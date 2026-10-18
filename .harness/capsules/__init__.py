"""
PDH v3.0 Agent Capsule Specification & Loader
Provides modular domain encapsulation: Charters, Cognitive Budgets, Invariants, and Jigs.
"""

from .loader import AgentCapsule, CapsuleLoader

__all__ = ["AgentCapsule", "CapsuleLoader"]
