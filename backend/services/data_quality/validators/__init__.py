"""Concrete validators (Phase A.1).

Each validator subclasses `BaseValidator` and registers itself via the
module-level `REGISTRY` list so the orchestrator can discover them
without hard-coding imports. Add a new validator by importing it here
and appending it to REGISTRY.

A.1 ships two: `daily_prices` and `stocks`. A.2 adds the remaining 9.
"""
from __future__ import annotations

from .daily_prices import DailyPricesValidator
from .stocks import StocksValidator

REGISTRY: list[type] = [
    DailyPricesValidator,
    StocksValidator,
]

__all__ = ["REGISTRY", "DailyPricesValidator", "StocksValidator"]
