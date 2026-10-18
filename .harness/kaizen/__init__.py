"""
PDH v3.0 Kaizen Self-Improvement Engine
Provides causal credit attribution, quarantined proposal management, and offline distillation.
"""

from .attribution import assign_credit_attribution

__all__ = ["assign_credit_attribution"]
