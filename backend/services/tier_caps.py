# Single source of truth for paid-tier feature caps.
# Frontend pricing page text MUST match these numbers.
# Backend enforcement MUST use these constants — no hardcoded
# integers in route handlers.

from typing import Literal

Tier = Literal["free", "analyst", "pro"]

BROKER_ACCOUNT_CAPS: dict[str, int] = {
    "free": 1,        # not advertised but exists per pricing page implicit "1 portfolio / 1 broker account"
    "analyst": 5,
    "pro": 10,
}

COMPARE_TICKER_CAPS: dict[str, int] = {
    "free": 2,        # generous default; pricing page doesn't gate Compare for Free
    "analyst": 3,
    "pro": 5,
}


def cap_for(tier: str, feature: str) -> int:
    """Return the cap for `feature` at `tier`. Falls back to free-tier
    cap on unknown tier so misconfigs degrade safely (low cap, not high)."""
    table = {
        "broker_accounts": BROKER_ACCOUNT_CAPS,
        "compare_tickers": COMPARE_TICKER_CAPS,
    }.get(feature)
    if table is None:
        raise ValueError(f"Unknown tier-cap feature: {feature}")
    return table.get(tier, table["free"])
