"""Tests for the 2026-05-18 pharma DCF fix (PR feat/pharma-dcf-fix).

Covers the four code-level changes shipped in the PR; the fifth change
(CACHE_VERSION bump 102 → 104) is a metadata-only edit and has no unit
test.

1. `pharma_rd_adjusted` FCF candidate is now voted on in the median
   selection at `models/forecaster._compute_fcf_base` (sector-gated to
   pharma).
2. `backend.services.analysis.ipo_framework.is_recent_ipo` accepts a
   `sector` kwarg and routes through `_RECENT_IPO_WINDOW_MONTHS_BY_SECTOR`
   so pharma gets 60 months vs the 36-month default.
3. `ticker_overrides.get_override("MANKIND")` returns a non-None entry
   with `terminal_growth_override == 0.05` and the .NS / MANKINDPHARMA
   aliases resolve to the same entry.
4. `is_usd_reporter` routes DRREDDY-with-USD-info through the USD path
   even though DRREDDY is NOT in the static allow-list (covers the
   "yfinance flipped back to USD" scenario; live verification 2026-05-18
   returned INR so the static list was intentionally left unchanged in
   this PR).
5. Negative case: TCS / RELIANCE / HDFCBANK get no pharma-specific
   routing (sector-gates hold).
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from backend.services.analysis import ticker_overrides
from backend.services.analysis import ipo_framework
from backend.services.currency_conversion_service import (
    USD_REPORTER_TICKERS,
    is_usd_reporter,
)
from models.forecaster import _compute_fcf_base


# ─────────────────────────────────────────────────────────────────
# 1. pharma_rd_adjusted candidate actually voted on
# ─────────────────────────────────────────────────────────────────

def _pharma_enriched(*, latest_fcf, latest_revenue, op_margin, sector="pharma"):
    years = list(range(2020, 2026))
    n = len(years)
    cf_df = pd.DataFrame({
        "year": years,
        "fcf": [latest_fcf * 0.6, latest_fcf * 0.7, latest_fcf * 0.8,
                latest_fcf * 0.9, latest_fcf * 0.95, latest_fcf],
        "cfo": [latest_fcf * 1.2] * n,
        "capex": [-latest_fcf * 0.2] * n,
    })
    income_df = pd.DataFrame({
        "year": years,
        "revenue": [latest_revenue * 0.85] * 3 + [latest_revenue * 0.92,
                                                  latest_revenue * 0.97,
                                                  latest_revenue],
        "op_margin": [op_margin] * n,
    })
    return {
        "ticker": "MANKIND",
        "latest_fcf": latest_fcf,
        "latest_revenue": latest_revenue,
        "op_margin": op_margin,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": sector,
    }


def test_pharma_rd_adjusted_candidate_voted():
    """When sector == 'pharma' and revenue/op_margin clear the gates,
    `pharma_rd_adjusted` must appear in `_fcf_candidates` and the stash
    flag `_pharma_rd_used` must be True."""
    # Mid-cap pharma: ~₹12,000 Cr revenue, 22% op margin, modest FCF.
    enriched = _pharma_enriched(
        latest_fcf=1.5e10,        # ₹1,500 Cr (depressed by M&A capex)
        latest_revenue=1.2e11,    # ₹12,000 Cr
        op_margin=0.22,
    )
    base, method = _compute_fcf_base(enriched)

    cands = enriched.get("_fcf_candidates", {})
    assert "pharma_rd_adjusted" in cands, (
        f"pharma_rd_adjusted must be computed for pharma (got {list(cands.keys())})"
    )
    assert enriched.get("_pharma_rd_used") is True, (
        "_pharma_rd_used must be True when pharma_rd_adjusted is in the pool"
    )
    assert base > 0


def test_pharma_rd_adjusted_not_used_for_non_pharma():
    """IT-services / banking / metals tickers must NOT see
    `pharma_rd_adjusted` in their candidate dict — the candidate's
    computation block is sector-gated AND the selection vote is too."""
    for sector in ("it_services", "banks", "metals", "fmcg", "auto"):
        enriched = _pharma_enriched(
            latest_fcf=1.5e10,
            latest_revenue=1.2e11,
            op_margin=0.22,
            sector=sector,
        )
        _compute_fcf_base(enriched)
        cands = enriched.get("_fcf_candidates", {})
        assert "pharma_rd_adjusted" not in cands, (
            f"sector={sector!r} must NOT receive pharma_rd_adjusted "
            f"(got {list(cands.keys())})"
        )
        assert enriched.get("_pharma_rd_used") is False


# ─────────────────────────────────────────────────────────────────
# 2. Recent-IPO window sector-aware (pharma=60, default=36)
# ─────────────────────────────────────────────────────────────────

def test_recent_ipo_window_pharma_60_months():
    """A pharma ticker listed 48 months ago must STILL be recent under
    the 60-month pharma window, but NOT under the default 36-month
    window."""
    today = date.today()
    # 48 months ago
    yr = today.year - 4
    mo = today.month
    listing = f"{yr:04d}-{mo:02d}-{today.day:02d}"

    # Without sector → default 36-month window → NOT recent
    assert ipo_framework.is_recent_ipo("MANKIND", listing) is False
    # With sector="pharma" → 60-month window → still recent
    assert ipo_framework.is_recent_ipo(
        "MANKIND", listing, sector="pharma"
    ) is True


def test_recent_ipo_window_default_36_months_for_it():
    """IT-services keeps the 36-month default window."""
    today = date.today()
    # 24 months ago — still recent under either window
    yr = today.year - 2
    listing_recent = f"{yr:04d}-{today.month:02d}-{today.day:02d}"
    assert ipo_framework.is_recent_ipo(
        "FOO", listing_recent, sector="it_services"
    ) is True

    # 40 months ago — recent under pharma's 60m, NOT under IT's 36m
    yr_old = today.year - 4
    mo_old = today.month + 8
    if mo_old > 12:
        mo_old -= 12
        yr_old += 1
    listing_old = f"{yr_old:04d}-{mo_old:02d}-{min(today.day, 28):02d}"
    assert ipo_framework.is_recent_ipo(
        "FOO", listing_old, sector="it_services"
    ) is False


def test_recent_ipo_window_unknown_sector_falls_back_to_default():
    """Unknown sector slug must fall back to the 36-month default."""
    today = date.today()
    yr = today.year - 4  # 48 months ago
    listing = f"{yr:04d}-{today.month:02d}-{today.day:02d}"
    assert ipo_framework.is_recent_ipo(
        "FOO", listing, sector="some_unknown_sector"
    ) is False


def test_recent_ipo_window_legacy_single_arg_still_works():
    """The original 2-arg call signature must remain back-compatible."""
    today = date.today()
    yr = today.year - 2
    listing = f"{yr:04d}-{today.month:02d}-{today.day:02d}"
    assert ipo_framework.is_recent_ipo("FOO", listing) is True


# ─────────────────────────────────────────────────────────────────
# 3. MANKIND ticker override
# ─────────────────────────────────────────────────────────────────

def test_mankind_override_terminal_growth():
    entry = ticker_overrides.get_override("MANKIND")
    assert entry is not None, "MANKIND override must exist"
    assert entry.get("terminal_growth_override") == 0.05


def test_mankind_aliases_resolve_to_same_override():
    base = ticker_overrides.get_override("MANKIND")
    for alias in ("MANKIND.NS", "MANKINDPHARMA", "MANKINDPHARMA.NS"):
        resolved = ticker_overrides.get_override(alias)
        assert resolved is not None, f"{alias} must resolve to the MANKIND override"
        assert resolved.get("terminal_growth_override") == 0.05, (
            f"{alias} must inherit terminal_growth_override=0.05"
        )


def test_mankind_skip_ipo_routing_flag_set():
    """2026-05-18 prod regression fix: MANKIND must carry
    skip_ipo_routing=True so service.py keeps it on the DCF path even
    though the 60-month pharma IPO window would otherwise route it
    through compute_sector_relative_fv. Without this flag, the cohort
    P/E median (~17x) collapses MANKIND FV to ~₹1,046 — well below the
    [₹1,400, ₹1,900] sensitivity envelope from the design doc."""
    entry = ticker_overrides.get_override("MANKIND")
    assert entry is not None
    assert entry.get("skip_ipo_routing") is True, (
        "MANKIND must opt out of IPO sector-relative routing so the "
        "terminal_growth_override=0.05 and pharma_rd_adjusted FCF "
        "candidate actually fire on the DCF path."
    )
    # Aliases must inherit the flag too.
    for alias in ("MANKIND.NS", "MANKINDPHARMA", "MANKINDPHARMA.NS"):
        resolved = ticker_overrides.get_override(alias)
        assert resolved is not None
        assert resolved.get("skip_ipo_routing") is True, (
            f"{alias} must inherit skip_ipo_routing=True via alias"
        )


def test_skip_ipo_routing_default_off_for_other_tickers():
    """The new opt-out flag must default to absent/falsey for every
    other override entry — only the named cases (currently MANKIND)
    bypass IPO routing. Catches accidental copy-paste of the flag
    onto unrelated overrides."""
    from backend.services.analysis.ticker_overrides import TICKER_OVERRIDES
    for key, entry in TICKER_OVERRIDES.items():
        if not isinstance(entry, dict) or entry.get("_alias_to"):
            continue
        if key == "MANKIND":
            continue
        assert not entry.get("skip_ipo_routing"), (
            f"{key} must NOT set skip_ipo_routing — flag is opt-in for "
            f"named tickers with calibrated terminal_growth_override + "
            f"known cohort-P/E mis-fit."
        )


# ─────────────────────────────────────────────────────────────────
# 4. USD-reporter detection routes DRREDDY through when info says USD
# ─────────────────────────────────────────────────────────────────

def test_drreddy_routes_through_usd_when_info_reports_usd():
    """Even though DRREDDY is intentionally NOT in the static allow-list
    (live yfinance returned INR on 2026-05-18), `is_usd_reporter` must
    still route a DRREDDY.NS ticker through the USD path when the
    `info` dict on a given fetch reports `financialCurrency='USD'`. This
    covers the "yfinance flipped back to USD on a future backfill"
    scenario the design doc §8 warns about."""
    assert "DRREDDY" not in USD_REPORTER_TICKERS, (
        "DRREDDY is intentionally OUT of the static allow-list — see "
        "currency_conversion_service.py comment block and PR body."
    )
    fake_info = {"financialCurrency": "USD"}
    assert is_usd_reporter("DRREDDY.NS", fake_info) is True


def test_drreddy_does_not_route_when_info_reports_inr():
    """The current live state (INR on yfinance) must NOT trigger the
    USD conversion path."""
    fake_info = {"financialCurrency": "INR"}
    assert is_usd_reporter("DRREDDY.NS", fake_info) is False
    # Also when info is missing entirely (the allow-list-only path).
    assert is_usd_reporter("DRREDDY.NS", None) is False


# ─────────────────────────────────────────────────────────────────
# 5. Negative case: non-pharma tickers untouched
# ─────────────────────────────────────────────────────────────────

def test_non_pharma_tickers_no_pharma_routing():
    """TCS / RELIANCE / HDFCBANK must not pick up any of the pharma-
    specific code paths."""
    for tkr in ("TCS", "RELIANCE", "HDFCBANK"):
        # 1. No ticker override on the pharma side. RELIANCE has its
        #    own override but it must NOT carry terminal_growth_override=0.05.
        ov = ticker_overrides.get_override(tkr)
        if ov is not None:
            assert ov.get("terminal_growth_override") != 0.05 or tkr != "MANKIND"
        # 2. is_recent_ipo with a 48-month-old listing must stay False
        #    under each ticker's likely sector (IT / Energy / Banks → all 36m).
        today = date.today()
        yr = today.year - 4
        listing = f"{yr:04d}-{today.month:02d}-{today.day:02d}"
        for sector in ("it_services", "energy", "banks"):
            assert ipo_framework.is_recent_ipo(tkr, listing, sector=sector) is False
        # 3. USD-reporter detection: not in the static allow-list and
        #    no USD info → False.
        assert is_usd_reporter(f"{tkr}.NS", None) is False
        assert is_usd_reporter(f"{tkr}.NS", {"financialCurrency": "INR"}) is False
