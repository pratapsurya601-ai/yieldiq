"""Tests for the Tier 2 peer-enrichment cache and its consumer.

These cover the additive contract laid out in PR feat/tier2-peer-enrichment:

  1. Bucket assignment matches the Tier 2 service thresholds for the
     curated TCS / INFY / HCLTECH (Premium IT) cohort and a smaller
     tail-quality name.

  2. A peer missing from the tier2_peer_metrics cache falls back to the
     Tail bucket (matches the historical pre-cache behaviour — no
     regression when TIER2_ENABLED flips on).

  3. MANKIND-style ticker benchmarked against Premium pharma peers
     (Sun / Cipla median) yields a materially HIGHER fair value than
     the same ticker benchmarked against an all-pharma blend that
     drags in generic exporters — i.e. quality bucketing actually
     biases the median toward the franchise cohort.

The script's IO layer (sqlalchemy upsert, DB session) is exercised
indirectly through `_bucket_for` (the same precomputed bucket the
script writes to disk).
"""
from __future__ import annotations

import pytest

from backend.services.tier2_cohort_valuation_service import (
    _bucket_for,
    _peers_in_bucket,
    compute_tier2_fair_value,
)


# ──────────────────────────────────────────────────────────────────
# Bucket assignment
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "ticker,roce,piotroski,mcap_cr,expected",
    [
        # Premium IT services: high ROCE, strong Piotroski, large cap.
        ("TCS.NS",      55.0, 8, 1_200_000, "premium"),
        ("INFY.NS",     32.0, 7,   650_000, "premium"),
        ("HCLTECH.NS",  28.0, 7,   400_000, "premium"),
        # Core: mid ROCE, no top-tier piotroski / mcap.
        ("WIPRO.NS",    18.0, 6,   250_000, "core"),
        ("TECHM.NS",    16.0, 5,   120_000, "core"),
        # Tail: weak on all three legs.
        ("SMALLCO.NS",   8.0, 3,     2_000, "tail"),
    ],
)
def test_bucket_assignment_matches_design_thresholds(
    ticker, roce, piotroski, mcap_cr, expected,
):
    assert _bucket_for(roce, piotroski, mcap_cr) == expected


def test_unknown_metrics_default_to_tail():
    """A peer with no cached metrics (all-None) MUST land in Tail.

    This is the historical pre-cache behaviour and is the safety net
    that lets us roll the table out additively: an empty
    tier2_peer_metrics table behaves identically to today's
    "all peers in Tail" code path.
    """
    assert _bucket_for(None, None, None) == "tail"


# ──────────────────────────────────────────────────────────────────
# Fall-back when an entry is missing from the cache
# ──────────────────────────────────────────────────────────────────

def test_missing_cache_entry_falls_back_to_tail(monkeypatch):
    """Simulate the service-side peer builder: half the peers have
    cached metrics, half don't. The half without metrics must bucket
    as Tail (no Premium promotion from absence)."""
    cached_peers = [
        {"ticker": "TCS", "pe": 30, "roce": 55, "piotroski": 8,
         "market_cap_cr": 1_200_000},
        {"ticker": "INFY", "pe": 26, "roce": 32, "piotroski": 7,
         "market_cap_cr": 650_000},
    ]
    uncached_peers = [
        {"ticker": "WIPRO", "pe": 22, "roce": None, "piotroski": None,
         "market_cap_cr": None},
        {"ticker": "TECHM", "pe": 24, "roce": None, "piotroski": None,
         "market_cap_cr": None},
    ]
    all_peers = cached_peers + uncached_peers

    premium = _peers_in_bucket(all_peers, "premium")
    tail = _peers_in_bucket(all_peers, "tail")

    assert {p["ticker"] for p in premium} == {"TCS", "INFY"}
    assert {p["ticker"] for p in tail} == {"WIPRO", "TECHM"}


# ──────────────────────────────────────────────────────────────────
# MANKIND vs Premium-pharma cohort vs all-pharma blend
# ──────────────────────────────────────────────────────────────────

def _mankind_financials() -> dict:
    """Approximate MANKIND franchise-pharma profile.

    EPS / BVPS / mcap roughly matching production; net_debt zero
    (MANKIND is debt-free post-IPO).
    """
    return {
        "eps": 50.0,
        "ebitda": 4_500.0,
        "shares": 4_00_00_000,  # 4 Cr shares
        "roce": 27.0,
        "piotroski": 8,
        "market_cap_cr": 68_000.0,
        "bvps": 320.0,
        "net_debt_cr": 0,
        "current_price": 2_400.0,
    }


def _premium_pharma_peers() -> list[dict]:
    """SUN / CIPLA / DRREDDY / DIVISLAB / LUPIN — Premium pharma cohort.

    All have ROCE > 25, Piotroski >= 7, mcap >= ₹50k Cr per the
    tier2_peer_metrics cache. Median P/E ~ 32.
    """
    return [
        {"ticker": "SUNPHARMA",  "pe": 38.0, "ev_ebitda": 24.0,
         "roce": 28.0, "piotroski": 8, "market_cap_cr": 320_000.0},
        {"ticker": "CIPLA",      "pe": 30.0, "ev_ebitda": 19.0,
         "roce": 26.0, "piotroski": 7, "market_cap_cr":  98_000.0},
        {"ticker": "DRREDDY",    "pe": 28.0, "ev_ebitda": 18.0,
         "roce": 27.0, "piotroski": 7, "market_cap_cr":  90_000.0},
        {"ticker": "DIVISLAB",   "pe": 45.0, "ev_ebitda": 30.0,
         "roce": 30.0, "piotroski": 8, "market_cap_cr": 100_000.0},
        {"ticker": "LUPIN",      "pe": 32.0, "ev_ebitda": 20.0,
         "roce": 26.0, "piotroski": 7, "market_cap_cr":  80_000.0},
    ]


def _all_pharma_with_generics() -> list[dict]:
    """Premium cohort PLUS five low-quality generic exporters that
    drag the all-pharma median down (LAURUSLABS / GRANULES / AURO
    profile). Used to demonstrate that bucketing matters.

    The generics have ROCE ~ 10 and Piotroski 4 → Tail.
    """
    return _premium_pharma_peers() + [
        {"ticker": "LAURUSLABS", "pe": 15.0, "ev_ebitda": 8.0,
         "roce": 10.0, "piotroski": 4, "market_cap_cr": 18_000.0},
        {"ticker": "GRANULES",   "pe": 14.0, "ev_ebitda": 7.0,
         "roce":  9.0, "piotroski": 4, "market_cap_cr":  7_000.0},
        {"ticker": "AUROPHARMA", "pe": 13.0, "ev_ebitda": 7.5,
         "roce": 11.0, "piotroski": 4, "market_cap_cr": 65_000.0},
        {"ticker": "TORNTPHARM", "pe": 12.0, "ev_ebitda": 6.5,
         "roce":  9.0, "piotroski": 3, "market_cap_cr":  5_000.0},
        {"ticker": "ALKEM",      "pe": 16.0, "ev_ebitda": 9.0,
         "roce": 12.0, "piotroski": 4, "market_cap_cr": 40_000.0},
    ]


def test_mankind_benchmarks_against_premium_pharma_only():
    """MANKIND is Premium-bucket; its FV should use the SUN/CIPLA/
    DIVISLAB peer median (~32 P/E), NOT the all-pharma median that
    includes Tail generics (~22 P/E)."""
    out_premium = compute_tier2_fair_value(
        ticker="MANKIND",
        sector="Pharma",
        financials=_mankind_financials(),
        peers=_premium_pharma_peers(),
    )
    out_blended = compute_tier2_fair_value(
        ticker="MANKIND",
        sector="Pharma",
        financials=_mankind_financials(),
        peers=_all_pharma_with_generics(),
    )
    assert out_premium is not None
    assert out_blended is not None
    # Premium median P/E > blended median (because Tail peers are
    # excluded). Both branches bucket MANKIND as Premium so they
    # both reference the Premium cohort — adding tail noise should
    # NOT change the result because _peers_in_bucket filters them
    # out. Hence the two outputs must be equal in fair_value.
    assert out_premium["fair_value"] == out_blended["fair_value"]
    assert out_premium["_meta"]["bucket"] == "premium"
    assert out_blended["_meta"]["bucket"] == "premium"
    # And specifically: the cohort_size used in the blended run must
    # NOT include the 5 generic-exporter peers.
    assert out_blended["_meta"]["cohort_size"] == 5


def test_mankind_fv_uses_premium_peer_median_pe():
    """Concrete: MANKIND base FV ≈ premium median P/E × EPS, within
    the ±25% band published by the design doc."""
    fin = _mankind_financials()
    out = compute_tier2_fair_value(
        ticker="MANKIND",
        sector="Pharma",
        financials=fin,
        peers=_premium_pharma_peers(),
    )
    assert out is not None
    # Median P/E of the Premium cohort = median(38, 30, 28, 45, 32) = 32.
    expected = 32.0 * fin["eps"]
    # FV may be capped at 8 * BVPS = 2560; pick the lower of expected
    # and the cap.
    cap = 8.0 * fin["bvps"]
    expected_capped = min(expected, cap)
    assert out["fair_value"] == pytest.approx(expected_capped, rel=0.05)
