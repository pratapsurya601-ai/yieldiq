"""Concrete validators.

Each validator implements the ``Validator`` protocol and registers
itself via the module-level ``REGISTRY`` list so the orchestrator can
discover them without hard-coding imports. Add a new validator by
importing it here and appending it to REGISTRY.

A.1 shipped 2: daily_prices, stocks.
A.2.1 added 4: corporate_actions, consensus_estimates, ratio_history,
peer_groups.
A.2.2 adds 4 table validators + 1 service validator:
cron_heartbeats, shareholding_pattern, company_quarterly_results,
cagr_service_output (service, not a table). The 5th "validator" in
A.2.2 is an in-place calibration update to the stocks validator (fuzzy
industry tokens) — no new module needed.
"""
from __future__ import annotations

from .cagr_service_output import CagrServiceOutputValidator
from .company_quarterly_results import CompanyQuarterlyResultsValidator
from .consensus_estimates import ConsensusEstimatesValidator
from .corporate_actions import CorporateActionsValidator
from .cron_heartbeats import CronHeartbeatsValidator
from .daily_prices import DailyPricesValidator
from .peer_groups import PeerGroupsValidator
from .ratio_history import RatioHistoryValidator
from .shareholding_pattern import ShareholdingPatternValidator
from .stocks import StocksValidator

REGISTRY: list[type] = [
    DailyPricesValidator,
    StocksValidator,
    CorporateActionsValidator,
    ConsensusEstimatesValidator,
    RatioHistoryValidator,
    PeerGroupsValidator,
    # A.2.2 additions
    CronHeartbeatsValidator,
    ShareholdingPatternValidator,
    CompanyQuarterlyResultsValidator,
    CagrServiceOutputValidator,
]

__all__ = [
    "REGISTRY",
    "DailyPricesValidator",
    "StocksValidator",
    "CorporateActionsValidator",
    "ConsensusEstimatesValidator",
    "RatioHistoryValidator",
    "PeerGroupsValidator",
    "CronHeartbeatsValidator",
    "ShareholdingPatternValidator",
    "CompanyQuarterlyResultsValidator",
    "CagrServiceOutputValidator",
]
