"""Day-? (2026-05-24): cache-warm coverage guarantee.

The cache-warm cron (.github/workflows/cache_warmup_top500.yml)
fetches the warm-set from /api/v1/public/top-tickers, which previously
relied entirely on a dynamic ORDER BY market_cap_cr DESC query against
market_metrics. When upstream market_metrics returned NULL mcap for
any row (auth flip, rate-limit, schema drift) the offending ticker
silently dropped out of the warm set and users hit cold-compute
(~2.7s p50) for hours until the next data refresh.

2026-05-24 FV/MoS audit found LT.NS, KOTAKBANK.NS, BAJFINANCE.NS,
AXISBANK.NS — all unambiguous top-15 large-caps — absent from
analysis_cache after a full warmup cycle.

Fix: the endpoint now prepends a curated TOP_TICKERS_MUST_INCLUDE
allowlist that is unconditional. This test pins the four audit
tickers to that allowlist so a future refactor cannot drop them.
"""
from __future__ import annotations


def test_must_include_covers_audit_tickers():
    """LT, KOTAKBANK, BAJFINANCE, AXISBANK must be in the warm-set
    even when the dynamic mcap query returns nothing for them.

    These four names were the canonical 2026-05-24 FV/MoS audit
    miss — they are obvious top-15 large-caps but silently fell out
    of the warm set when market_metrics flaked.
    """
    from backend.routers.public import TOP_TICKERS_MUST_INCLUDE

    required = {"LT.NS", "KOTAKBANK.NS", "BAJFINANCE.NS", "AXISBANK.NS"}
    actual = set(TOP_TICKERS_MUST_INCLUDE)
    missing = required - actual
    assert not missing, (
        f"Cache-warm must-include set is missing audit-critical tickers: "
        f"{sorted(missing)}. These dropped out of cache during the "
        f"2026-05-24 audit because market_metrics had stale mcap data; "
        f"keep them pinned here unconditionally."
    )


def test_must_include_covers_top_10_mcap():
    """The top-10 NSE large-caps by market cap should always be in
    the warm-set, period. They drive a disproportionate share of user
    traffic and a cold miss on any of them is user-visible.
    """
    from backend.routers.public import TOP_TICKERS_MUST_INCLUDE

    top10 = {
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS",
        "ICICIBANK.NS", "BHARTIARTL.NS", "ITC.NS", "SBIN.NS",
        "LT.NS", "HINDUNILVR.NS",
    }
    actual = set(TOP_TICKERS_MUST_INCLUDE)
    missing = top10 - actual
    assert not missing, f"Top-10 mcap names missing from warm set: {sorted(missing)}"


def test_must_include_uses_dot_ns_suffix():
    """The cache-warm script calls /api/v1/analysis/{ticker} which
    expects the full ``BASE.NS`` form (or normalises bare → .NS, but
    we should be explicit). Pin the format here so a future commit
    that bare-strips the list silently changes the API contract.
    """
    from backend.routers.public import TOP_TICKERS_MUST_INCLUDE

    for t in TOP_TICKERS_MUST_INCLUDE:
        assert t.endswith(".NS"), (
            f"TOP_TICKERS_MUST_INCLUDE entry {t!r} missing .NS suffix — "
            f"the warm-script calls /api/v1/analysis/{{ticker}} with the "
            f"value verbatim, so a bare ticker breaks the contract."
        )


def test_must_include_no_duplicates():
    """Dedup guard — the endpoint's own dedupe loop should make this
    redundant, but a duplicated entry in the literal is almost
    certainly a copy-paste error.
    """
    from backend.routers.public import TOP_TICKERS_MUST_INCLUDE

    assert len(TOP_TICKERS_MUST_INCLUDE) == len(set(TOP_TICKERS_MUST_INCLUDE)), (
        "Duplicate entries in TOP_TICKERS_MUST_INCLUDE"
    )
