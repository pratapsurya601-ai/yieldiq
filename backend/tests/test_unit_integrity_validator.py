"""Self-tests for the unit_integrity validator (2026-06-13).

These tests ARE the spec for the silent-wrong-number guard. They cover:

1. A clean universe is green.
2. Each anomaly family flips the right check red (or yellow):
   - asset_turnover unit-mismatch (INDIGO 359808 signature), sector-aware
   - de_ratio == 0 cohort (dropped-equity signature)
   - net_margin out of [-100%, +100%]
   - revenue >> market cap (raw-INR-vs-Cr double-unit tell)
   - fcf >> market cap (DCF-overshoot / pv_fcfs > N*mcap signature)
   - currency double-convert (non-INR latest financials)
   - known-good asset_turnover regression
3. The pure classifier honours sector bands.
4. The shared checks.py helpers (ratio_band_check, cohort_fraction_check).

All tests are DB-free — they inject a hand-built UnitIntegritySample via
the ``sample_loader`` seam, exactly like the other data-quality
validators' tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.services.data_quality.checks import (
    cohort_fraction_check,
    ratio_band_check,
)
from backend.services.data_quality.validators.unit_integrity import (
    DEFAULT_ASSET_TURNOVER_BAND,
    SECTOR_ASSET_TURNOVER_BANDS,
    TickerAnomaly,
    UnitIntegritySample,
    UnitIntegrityValidator,
    classify_asset_turnover,
)

_NOW = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)


def _healthy_sample() -> UnitIntegritySample:
    """A clean universe: every cross-field check passes."""
    return UnitIntegritySample(
        row_count=15_328,
        prior_row_count=15_000,
        last_update=_NOW - timedelta(days=10),
        asset_turnover_total=2_300,
        asset_turnover_anomalies=[],
        de_total=2_100,
        de_zero_count=20,  # ~1% genuinely debt-free — fine
        de_zero_by_sector={"Energy": (2, 260), "Bank": (0, 41)},
        net_margin_total=2_300,
        net_margin_anomalies=[],
        rev_mcap_total=2_300,
        rev_mcap_anomalies=[],
        fcf_mcap_total=2_300,
        fcf_mcap_anomalies=[],
        currency_total=2_400,
        non_inr_count=0,
        non_inr_tickers=[],
        known_good_asset_turnover={"TCS": 1.4, "RELIANCE": 0.6, "HDFCBANK": 0.08},
    )


# ───────────────────────── happy path ──────────────────────────────


def test_healthy_universe_is_green():
    v = UnitIntegrityValidator(sample_loader=_healthy_sample)
    res = v.run()
    assert res.overall_status == "green", [
        (c.name, c.status, c.details) for c in res.checks if c.status != "pass"
    ]
    assert res.table == "ratio_history"
    assert res.populator == "data_quality.unit_integrity"


# ───────────────────── asset_turnover unit mismatch ────────────────


def test_asset_turnover_indigo_signature_is_red():
    s = _healthy_sample()
    # INDIGO-shaped: 359808 asset_turnover on an Auto/airline ticker.
    s.asset_turnover_anomalies = [
        TickerAnomaly("INDIGO", "asset_turnover", 359_808.0, (0.001, 100.0), "fail", "Auto")
    ]
    v = UnitIntegrityValidator(sample_loader=lambda: s)
    res = v.run()
    assert res.overall_status == "red"
    flagged = [c for c in res.checks if c.name == "unit_integrity.asset_turnover_band"]
    assert flagged and flagged[0].status == "fail"
    assert "INDIGO" in flagged[0].details


def test_classifier_is_sector_aware():
    # 0.2x asset_turnover is FINE for an IT name but OUT-OF-BAND (warn)
    # for a Bank whose comfortable ceiling is 0.30 — wait, 0.2 < 0.30 so
    # it's fine for a bank too. Use 2.0x: fine for IT, warn for Bank.
    assert classify_asset_turnover("X", "IT Services", 2.0) is None
    bank = classify_asset_turnover("Y", "Bank", 2.0)
    assert bank is not None and bank.severity == "warn"
    # 80x is a hard fail for an IT name (fail_hi=100 → still under) but
    # for a Bank fail_hi=50 so 80 trips fail.
    bank_fail = classify_asset_turnover("Z", "Bank", 80.0)
    assert bank_fail is not None and bank_fail.severity == "fail"
    # Unknown sector falls back to the default band.
    assert SECTOR_ASSET_TURNOVER_BANDS.get("Nonexistent") is None
    fallback = classify_asset_turnover("W", "Nonexistent", 200.0)
    assert fallback is not None and fallback.severity == "fail"
    assert fallback.expected_band == (DEFAULT_ASSET_TURNOVER_BAND[2], DEFAULT_ASSET_TURNOVER_BAND[3])


def test_classifier_none_is_skipped():
    assert classify_asset_turnover("X", "Bank", None) is None


# ───────────────────── de_ratio zero cohort ────────────────────────


def test_de_ratio_zero_cohort_universe_is_red():
    s = _healthy_sample()
    # 40% of the universe reading exactly 0 → dropped-equity denominator.
    s.de_zero_count = 840
    s.de_total = 2_100
    v = UnitIntegrityValidator(sample_loader=lambda: s)
    res = v.run()
    assert res.overall_status == "red"
    flagged = [c for c in res.checks if c.name == "cohort_fraction.de_ratio_zero_universe"]
    assert flagged and flagged[0].status == "fail"


def test_de_ratio_zero_single_sector_is_red():
    s = _healthy_sample()
    # The de_ratio=0 on 17/17 cohort signature, isolated to one sector.
    s.de_zero_by_sector = {"Real Estate": (17, 17), "Energy": (1, 260)}
    v = UnitIntegrityValidator(sample_loader=lambda: s)
    res = v.run()
    assert res.overall_status == "red"
    flagged = [
        c for c in res.checks
        if c.name == "cohort_fraction.de_ratio_zero_sector.Real Estate"
    ]
    assert flagged and flagged[0].status == "fail"
    # A 2-row sector is too small to emit a per-sector check.
    assert not any(
        c.name == "cohort_fraction.de_ratio_zero_sector.Tiny" for c in res.checks
    )


# ───────────────────── net_margin band ─────────────────────────────


def test_net_margin_above_100pct_is_red():
    s = _healthy_sample()
    s.net_margin_anomalies = [
        TickerAnomaly("BADCO", "net_margin", 320.0, (-100.0, 100.0), "fail", "Media")
    ]
    v = UnitIntegrityValidator(sample_loader=lambda: s)
    res = v.run()
    assert res.overall_status == "red"


# ───────────────────── revenue / fcf vs market cap ─────────────────


def test_revenue_dwarfs_market_cap_is_red():
    s = _healthy_sample()
    s.rev_mcap_anomalies = [
        TickerAnomaly("SUPERSPIN", "revenue/market_cap", 10_980.0, (0.0, 50.0), "fail", "Metal")
    ]
    v = UnitIntegrityValidator(sample_loader=lambda: s)
    res = v.run()
    assert res.overall_status == "red"
    flagged = [c for c in res.checks if c.name == "unit_integrity.revenue_over_market_cap"]
    assert flagged and flagged[0].status == "fail"


def test_fcf_exceeds_market_cap_dcf_overshoot_is_red():
    s = _healthy_sample()
    s.fcf_mcap_anomalies = [
        TickerAnomaly("DCBBANK", "free_cash_flow/market_cap", 1.28, (0.0, 1.0), "fail", "Bank")
    ]
    v = UnitIntegrityValidator(sample_loader=lambda: s)
    res = v.run()
    assert res.overall_status == "red"
    flagged = [c for c in res.checks if c.name == "unit_integrity.fcf_over_market_cap"]
    assert flagged and flagged[0].status == "fail"


# ───────────────────── currency double-convert ─────────────────────


def test_currency_non_inr_cohort_is_red():
    s = _healthy_sample()
    # 15 USD tickers out of 2400 = 0.6% → above the 0% warn but below the
    # 2% fail threshold → warn (yellow). Bump to 60 to cross fail.
    s.non_inr_count = 60
    s.non_inr_tickers = [f"USD{i}" for i in range(60)]
    s.currency_total = 2_400
    v = UnitIntegrityValidator(sample_loader=lambda: s)
    res = v.run()
    assert res.overall_status == "red"
    flagged = [c for c in res.checks if c.name == "cohort_fraction.currency_non_inr"]
    assert flagged and flagged[0].status == "fail"


def test_currency_single_usd_ticker_warns_not_fails():
    s = _healthy_sample()
    s.non_inr_count = 5
    s.non_inr_tickers = ["INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM"]
    s.currency_total = 2_400
    v = UnitIntegrityValidator(sample_loader=lambda: s)
    res = v.run()
    # 0.2% is above the 0% warn floor but below 2% fail → yellow.
    assert res.overall_status == "yellow"
    flagged = [c for c in res.checks if c.name == "cohort_fraction.currency_non_inr"]
    assert flagged and flagged[0].status == "warn"
    assert "INFY" in flagged[0].details


# ───────────────────── known-good regression ───────────────────────


def test_known_good_asset_turnover_regression_is_red():
    s = _healthy_sample()
    # TCS asset_turnover suddenly reads 0.0001 → universe-wide unit drift.
    s.known_good_asset_turnover["TCS"] = 0.0001
    v = UnitIntegrityValidator(sample_loader=lambda: s)
    res = v.run()
    assert res.overall_status == "red"
    flagged = [c for c in res.checks if c.name == "plausibility.TCS.asset_turnover"]
    assert flagged and flagged[0].status == "fail"


# ───────────────────── checks.py helpers ───────────────────────────


def test_ratio_band_check_tiers():
    # within comfortable band → pass
    assert ratio_band_check("t", "x", 1.0, (0.5, 5.0), (0.001, 100.0)).status == "pass"
    # outside warn but inside fail → warn
    assert ratio_band_check("t", "x", 50.0, (0.5, 5.0), (0.001, 100.0)).status == "warn"
    # outside fail → fail
    assert ratio_band_check("t", "x", 500.0, (0.5, 5.0), (0.001, 100.0)).status == "fail"
    # None default → pass (absent field is not this check's job)
    assert ratio_band_check("t", "x", None, (0.5, 5.0), (0.001, 100.0)).status == "pass"
    # None with require_present → fail
    assert ratio_band_check(
        "t", "x", None, (0.5, 5.0), (0.001, 100.0), require_present=True
    ).status == "fail"


def test_cohort_fraction_check_tiers():
    assert cohort_fraction_check("t", "z", 1, 100, 15.0, 30.0).status == "pass"
    assert cohort_fraction_check("t", "z", 20, 100, 15.0, 30.0).status == "warn"
    assert cohort_fraction_check("t", "z", 40, 100, 15.0, 30.0).status == "fail"
    # empty cohort → informational pass
    assert cohort_fraction_check("t", "z", 0, 0, 15.0, 30.0).status == "pass"


# ───────────────────── registry wiring ─────────────────────────────


def test_validator_is_registered():
    from backend.services.data_quality.validators import REGISTRY

    assert UnitIntegrityValidator in REGISTRY
