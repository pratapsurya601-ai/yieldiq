"""Concrete validators.

Each validator implements the ``Validator`` protocol and registers
itself via the module-level ``REGISTRY`` list so the orchestrator can
discover them without hard-coding imports. Add a new validator by
importing it here and appending it to REGISTRY.

A.1 shipped 2: daily_prices, stocks.
A.2.1 adds 4: corporate_actions, consensus_estimates, ratio_history,
peer_groups.
A.2.2 will add the remaining 5 (compounded_growth, company_quarterly
TTM, shareholding_pattern, cron_heartbeats, nse_industry_master).
"""
from __future__ import annotations

from .consensus_estimates import ConsensusEstimatesValidator
from .corporate_actions import CorporateActionsValidator
from .daily_prices import DailyPricesValidator
from .peer_groups import PeerGroupsValidator
from .ratio_history import RatioHistoryValidator
from .stocks import StocksValidator

REGISTRY: list[type] = [
    DailyPricesValidator,
    StocksValidator,
    CorporateActionsValidator,
    ConsensusEstimatesValidator,
    RatioHistoryValidator,
    PeerGroupsValidator,
]

__all__ = [
    "REGISTRY",
    "DailyPricesValidator",
    "StocksValidator",
    "CorporateActionsValidator",
    "ConsensusEstimatesValidator",
    "RatioHistoryValidator",
    "PeerGroupsValidator",
]
