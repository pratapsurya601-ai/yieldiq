# screener/investment_advisor.py
# ─────────────────────────────────────────────────────────────
# COMPATIBILITY SHIM — file renamed to screener/valuation_model.py
# All imports should be updated to use valuation_model directly.
# ─────────────────────────────────────────────────────────────
from screener.valuation_model import (
    score_fundamentals,
    estimate_holding_period,
    compute_price_targets,
    generate_valuation_summary,
    generate_valuation_summary as generate_investment_plan,
)

__all__ = [
    "score_fundamentals",
    "estimate_holding_period",
    "compute_price_targets",
    "generate_valuation_summary",
    "generate_investment_plan",
]
