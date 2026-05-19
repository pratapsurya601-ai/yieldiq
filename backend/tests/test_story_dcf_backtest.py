"""Offline back-test guard for Story-DCF overrides.

These tests run without a DB. They synthesise a plausible (revenue,
shares, CMP) scenario for every ticker in
``config/story_dcf_overrides.json`` using realistic CMP + revenue
anchors (hardcoded below from public disclosures) and verify that the
operator-curated story parameters produce an FV inside the safety-
net rescue band ``[0.30, 3.5]`` relative to CMP.

If any test here fails it means the override file has drifted into
territory where the engine would refuse its own rescue output — that
override needs operator review BEFORE another canary run touches it.

This is the unit-test counterpart to ``scripts/story_dcf_backtest.py``
(which runs live against the prod DB). Together they form the audit
chain for the 10 APPROXIMATE overrides flagged in the Day-6 commit.
"""
from __future__ import annotations

import pytest

from backend.services.story_dcf_engine import (
    INDUSTRY_STORY_DEFAULTS,
    _SECTOR_TO_INDUSTRY_KEY,
    _load_overrides,
    _params_for,
    compute_story_dcf_fair_value,
)

# Anchors: (revenue_cr, shares_cr, cmp_inr).
# Sourced from FY25 investor decks / latest annual reports. Round to
# 1-2 sig-fig — the test only checks order-of-magnitude reasonableness,
# not pinpoint accuracy.
TICKER_ANCHORS: dict[str, tuple[float, float, float]] = {
    # ticker:   (revenue_cr, shares_cr, cmp)
    "PAYTM":      (10_000,  63.0,  900.0),
    "POLICYBZR":  (4_000,   45.0, 1_500.0),
    "ZOMATO":     (20_000,  900.0,  260.0),
    "NAUKRI":     (2_700,   13.0, 1_400.0),
    "NYKAA":      (8_000,   285.0, 200.0),
    "MEESHO":     (9_000,   90.0,  500.0),
    "SWIGGY":     (16_000,  220.0, 400.0),
    "NUVAMA":     (2_800,    4.0, 6_500.0),
    "GROWW":      (3_500,   60.0,  150.0),
    "ANGELONE":   (4_900,    9.0, 2_500.0),
    # Day-18 (2026-05-20): logistics platform added to Story-DCF cohort
    "DELHIVERY":  (8_900,   75.0,   528.0),
}

# Safety-net rescue band — same constants as
# ``dcf_collapse_safety_net.COLLAPSED_RATIO_LO`` / ``INFLATED_RATIO_HI``.
FV_CMP_LO = 0.30
FV_CMP_HI = 3.50


@pytest.fixture(autouse=True)
def _clear_overrides_cache():
    """Reset the lru_cache so test order doesn't matter."""
    _load_overrides.cache_clear()
    yield
    _load_overrides.cache_clear()


def _industry_key_for(ticker: str) -> str:
    """Reverse-lookup which industry default the override falls under.

    The override file doesn't carry an industry tag — we infer it from
    ticker-by-ticker mapping. Returned strings are KEYS into
    ``_SECTOR_TO_INDUSTRY_KEY`` (i.e. spelled with spaces) so that the
    public ``compute_story_dcf_fair_value`` sector lookup resolves."""
    tag = {
        "PAYTM":     "payments",
        "POLICYBZR": "insurance aggregator",
        "NAUKRI":    "ecommerce",      # job platform; ecommerce defaults fit
        "NUVAMA":    "wealth management",
        "GROWW":     "fintech_broker",
        "ANGELONE":  "fintech_broker",
        "DELHIVERY": "ecommerce",      # logistics platform uses ecommerce defaults
    }
    return tag.get(ticker, "ecommerce")


def _industry_default_key_for(ticker: str) -> str:
    """The key into ``INDUSTRY_STORY_DEFAULTS`` (no spaces)."""
    return {
        "PAYTM":     "payments",
        "POLICYBZR": "insurance_aggregator",
        "NUVAMA":    "wealth_mgmt",
        "GROWW":     "fintech_broker",
        "ANGELONE":  "fintech_broker",
    }.get(ticker, "ecommerce")


# Tickers where the synthetic anchors + current overrides produce an
# FV outside the safety-net rescue band [0.30, 3.5]. These are
# DOCUMENTED OPERATOR-REVIEW ITEMS — the test that lists them stays
# xfail until each override is recalibrated against an investor deck.
# Removing a ticker from this set without updating the override =
# the test fires and forces a discussion.
KNOWN_OUT_OF_BAND: set[str] = {
    # Override produces out-of-band FV OR collapses to None due to
    # negative-FCFF in explicit period — both are "operator review
    # needed" signals.
    "PAYTM",     # FV right at 0.30 edge — payments thin margin
    "ZOMATO",    # FV ≈ 5 — Blinkit reinvest model under-counts long-tail margin
    "POLICYBZR", # insurance aggregator default — share count high vs FCFF base
    "NYKAA",     # 8% op margin × 75% reinvest → FCFFs stay negative
    "MEESHO",    # 10% op margin × 80% reinvest → FCFFs stay negative
    "SWIGGY",    # 10% op margin × 70% reinvest → FCFFs stay negative
    # Day-20 part-2: DELHIVERY retuned (15% margin / 40% reinvest) →
    # FV now in-band at 0.45×. No longer in this set.
}

# Tickers where the INDUSTRY DEFAULT (no override) produces out-of-
# band FV. Separate from KNOWN_OUT_OF_BAND because the override file
# might patch the issue independently of the industry default.
KNOWN_DEFAULT_OUT_OF_BAND: set[str] = {
    "NAUKRI",   # ecommerce default mis-fits high-margin job platform
    "NYKAA",    # default reinvest too aggressive for retail
    "MEESHO",   # default reinvest too aggressive for low-margin retail
    "SWIGGY",   # default reinvest too aggressive for q-comm
    "ZOMATO",   # default reinvest too aggressive for food + q-comm
    "DELHIVERY",# default 15% margin too high for logistics (target ~8%)
}

# Same idea for the CAGR-drift test
KNOWN_CAGR_DRIFT: set[str] = {
    "ZOMATO",    # operator under-counted Blinkit revenue acceleration
    "ANGELONE",  # operator under-counted F&O retail volume growth
}


def test_every_override_produces_finite_fv():
    """Operator-curated parameters must produce a positive, finite FV
    when fed a realistic (revenue, shares, CMP) anchor.

    KNOWN_OUT_OF_BAND tickers are permitted to return None — they're
    under operator review and the safety-net will fall through to
    data_limited. Hard requirement: for the REST, every override must
    produce finite positive FV."""
    overrides = _load_overrides()
    override_tickers = [t for t in overrides if not t.startswith("_")]
    assert override_tickers, "story_dcf_overrides.json contains no tickers"

    failures: list[str] = []
    for ticker in override_tickers:
        anchor = TICKER_ANCHORS.get(ticker)
        if anchor is None:
            failures.append(f"{ticker}: no TICKER_ANCHORS entry — add one")
            continue
        rev_cr, sh_cr, cmp_ = anchor
        result = compute_story_dcf_fair_value(
            ticker=ticker,
            sector=_industry_key_for(ticker),
            financials={
                "revenue": rev_cr * 1e7,      # cr → rupees
                "shares":  sh_cr * 1e7,       # cr → absolute shares
                "current_price": cmp_,
            },
        )
        if ticker in KNOWN_OUT_OF_BAND:
            continue  # operator-review backlog; band test handles it
        if result is None:
            failures.append(f"{ticker}: compute returned None")
            continue
        fv = float(result["fair_value"])
        if not (fv > 0 and fv == fv and fv != float("inf")):
            failures.append(f"{ticker}: FV={fv} invalid")

    assert not failures, "\n".join(failures)


def test_known_out_of_band_overrides_unchanged():
    """The operator-review backlog: these overrides are KNOWN to produce
    FVs outside the safety-net rescue band against synthetic anchors.
    They stay tracked here until each is recalibrated against an investor
    deck. Test passes by confirming the violators are exactly the set we
    expect — neither MORE (regression) nor FEWER (silent fix without
    updating the doc list)."""
    overrides = _load_overrides()
    override_tickers = [t for t in overrides if not t.startswith("_")]

    out_of_band: set[str] = set()
    for ticker in override_tickers:
        anchor = TICKER_ANCHORS.get(ticker)
        if anchor is None:
            continue
        rev_cr, sh_cr, cmp_ = anchor
        result = compute_story_dcf_fair_value(
            ticker=ticker,
            sector=_industry_key_for(ticker),
            financials={
                "revenue": rev_cr * 1e7,
                "shares":  sh_cr * 1e7,
                "current_price": cmp_,
            },
        )
        if result is None:
            # Model collapse counts as out-of-band for review purposes
            out_of_band.add(ticker)
            continue
        fv = float(result["fair_value"])
        ratio = fv / cmp_
        if not (FV_CMP_LO <= ratio <= FV_CMP_HI):
            out_of_band.add(ticker)

    new_violators = out_of_band - KNOWN_OUT_OF_BAND
    silently_fixed = KNOWN_OUT_OF_BAND - out_of_band
    assert not new_violators, (
        f"NEW out-of-band overrides regressed: {sorted(new_violators)} — "
        "either fix the override OR add to KNOWN_OUT_OF_BAND with a note."
    )
    assert not silently_fixed, (
        f"Override was silently recalibrated to pass: {sorted(silently_fixed)} — "
        "remove from KNOWN_OUT_OF_BAND now that it's in-band."
    )


def test_industry_defaults_within_rescue_band_for_each_anchor():
    """Sanity check: even the industry default (no override) should
    produce a sensible FV for the anchor scenarios. This catches the
    case where INDUSTRY_STORY_DEFAULTS itself drifts.

    Only enforces against the tickers NOT in KNOWN_OUT_OF_BAND — those
    are documented operator-review items handled by the dedicated
    backlog test above."""
    out_of_band: list[str] = []
    for ticker, anchor in TICKER_ANCHORS.items():
        if ticker in KNOWN_DEFAULT_OUT_OF_BAND:
            continue
        rev_cr, sh_cr, cmp_ = anchor
        industry_key = _industry_default_key_for(ticker)
        params = INDUSTRY_STORY_DEFAULTS.get(industry_key)
        if params is None:
            continue
        # Bypass override file by passing story_params directly
        result = compute_story_dcf_fair_value(
            ticker="__SYNTHETIC__",   # no override match
            sector=industry_key,
            financials={
                "revenue": rev_cr * 1e7,
                "shares":  sh_cr * 1e7,
                "current_price": cmp_,
            },
            story_params=params,
        )
        if result is None:
            continue
        fv = float(result["fair_value"])
        ratio = fv / cmp_
        # Industry defaults get a wider tolerance (one rung wider than
        # the rescue band) — they don't have per-ticker tuning.
        if not (0.20 <= ratio <= 5.0):
            out_of_band.append(
                f"{industry_key} via {ticker}: ratio={ratio:.2f}"
            )
    assert not out_of_band, "\n".join(out_of_band)


def test_observed_cagr_vs_assumed_growth_alignment():
    """For tickers with public revenue trajectories, the assumed
    ``initial_growth`` should be within 0.20 of a published 2-3y
    historical CAGR. Hardcoded targets from FY23→FY25 investor
    disclosures (rounded). Catches obvious operator typos."""
    # (ticker, observed_2y_cagr_approx)
    HIST_CAGR = {
        "PAYTM":      0.07,   # FY23 8,000 → FY25 ~10,000 (after slowdown)
        "POLICYBZR":  0.40,   # FY23 2,000 → FY25 ~4,000
        "ZOMATO":     0.55,   # FY23 7,000 → FY25 ~20,000 (incl Blinkit)
        "NAUKRI":     0.18,   # FY23 ~2,000 → FY25 ~2,700
        "NYKAA":      0.30,   # FY23 5,000 → FY25 ~8,000
        "ANGELONE":   0.45,   # FY23 ~2,300 → FY25 ~4,900
    }

    drift_outliers: set[str] = set()
    for ticker, observed in HIST_CAGR.items():
        industry_key = _industry_default_key_for(ticker)
        params = _params_for(ticker, industry_key)
        if params is None:
            continue
        drift = abs(params.initial_growth - observed)
        # 0.20 is intentionally lenient — story-DCF projects forward,
        # not backward, and operator may know upcoming step-changes.
        if drift > 0.20:
            drift_outliers.add(ticker)

    new_drift = drift_outliers - KNOWN_CAGR_DRIFT
    silently_fixed = KNOWN_CAGR_DRIFT - drift_outliers
    assert not new_drift, (
        f"NEW CAGR drift outliers: {sorted(new_drift)} — "
        "either fix the override OR add to KNOWN_CAGR_DRIFT with a note."
    )
    assert not silently_fixed, (
        f"Override silently recalibrated for CAGR: {sorted(silently_fixed)} — "
        "remove from KNOWN_CAGR_DRIFT."
    )


def test_terminal_value_not_dominating():
    """If TV is > 90% of EV, the model is effectively a perpetuity
    formula in disguise — the explicit 10y forecast carries no weight.
    This usually means initial_growth is too low or fade_years is too
    short for the chosen WACC."""
    overrides = _load_overrides()
    override_tickers = [t for t in overrides if not t.startswith("_")]

    tv_heavy: set[str] = set()
    for ticker in override_tickers:
        anchor = TICKER_ANCHORS.get(ticker)
        if anchor is None:
            continue
        # KNOWN_OUT_OF_BAND tickers have model breakage that produces
        # extreme TV ratios — skip them here (the band test owns them)
        if ticker in KNOWN_OUT_OF_BAND:
            continue
        rev_cr, sh_cr, cmp_ = anchor
        result = compute_story_dcf_fair_value(
            ticker=ticker,
            sector=_industry_key_for(ticker),
            financials={
                "revenue": rev_cr * 1e7,
                "shares":  sh_cr * 1e7,
                "current_price": cmp_,
            },
        )
        if result is None:
            continue
        tv_pct = result.get("_meta", {}).get("tv_pct_of_ev")
        if tv_pct is not None and tv_pct > 0.90:
            tv_heavy.add(ticker)

    assert not tv_heavy, (
        f"TV dominates EV (> 90%) — explicit forecast irrelevant: {sorted(tv_heavy)}"
    )
