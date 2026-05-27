# backend/services/funds/__init__.py
# Mutual Funds Phase 2 — returns + risk + score compute service.
#
# Public surface (consumed by recompute.py and backend/tests):
#   * compute_returns.compute_returns_for_scheme
#   * compute_risk.compute_risk_for_scheme
#   * compute_score.compute_score_for_scheme
#   * recompute.recompute_all
#
# All compute is rule-based, pure-python, vectorised via numpy. No LLM
# is invoked anywhere in this package — that is intentional and matches
# the equity-side YieldIQ Score design (project memory note).
from __future__ import annotations

__all__ = [
    "compute_returns",
    "compute_risk",
    "compute_score",
    "recompute",
]
