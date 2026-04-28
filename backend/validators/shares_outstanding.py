"""Validation guard for `shares_outstanding_raw` consumers.

Background: PR #136 (peer-cap agent) discovered `financials.shares_outstanding`
is stored in mixed units (lakh for some rows, crore for others) due to
inconsistent ingest paths. The fix is the new `shares_outstanding_raw`
column populated by `scripts/normalize_shares_outstanding.py`.

This module is the consumer-side safety net: any code that reads
`shares_outstanding_raw` and divides/multiplies by it should call
`shares_or_warn()` first. A value smaller than the smallest plausible
NSE-listed share count (~1e6 raw shares) almost certainly indicates
the value is still in lakh-units and would produce a 100×-off ratio.

See `docs/shares_outstanding_units_design.md` for the full design.

Note: `backend/services/peer_cap_service.py` deliberately does NOT use
this guard because its formulation is unit-free (it computes ratios
where the share-count unit cancels out). That's intentional defensive
coding — do not "fix" it to use the raw column.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Smallest plausible raw share count for a real NSE-listed company.
# Even a tiny SME (~10 lakh shares) crosses this floor.
MIN_PLAUSIBLE_RAW_SHARES = 1_000_000.0


def shares_or_warn(ticker: str, raw_shares: float | int | None) -> float | None:
    """Return `raw_shares` as float if it looks like a real raw share count.

    Returns None and logs a warning otherwise so the caller can skip the
    ratio rather than ship a 100×-off answer.
    """
    if raw_shares is None:
        return None
    try:
        v = float(raw_shares)
    except (TypeError, ValueError):
        logger.warning(
            "shares_outstanding_raw=%r for %s is not a number",
            raw_shares, ticker,
        )
        return None
    if v <= 0:
        return None
    if v < MIN_PLAUSIBLE_RAW_SHARES:
        logger.warning(
            "shares_outstanding_raw=%s for %s is below the plausible "
            "floor (%s) — likely a unit error (lakh/crore stored as raw). "
            "Skipping ratio.",
            v, ticker, MIN_PLAUSIBLE_RAW_SHARES,
        )
        return None
    return v
