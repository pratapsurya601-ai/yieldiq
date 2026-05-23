"""Phase A.2.2 self-tests.

Covers:
1. Stocks validator fuzzy industry calibration (A.2.1 finding fix)
2. CronHeartbeatsValidator: missing / stale / healthy paths
3. ShareholdingPatternValidator: sum-to-100, promoter band, recency
4. CompanyQuarterlyResultsValidator: recency, null rates, revenue band
5. CagrServiceOutputValidator: coverage floors, plausibility band,
   skip-when-DB-unset path
6. db_loaders_a2_2: graceful-None when DATABASE_URL unset

Total ≈ 22 tests.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.services.data_quality.validators.cagr_service_output import (
    CAGR_BAND_5Y,
    CANARY_TICKERS as CAGR_CANARIES,
    CagrServiceOutputSample,
    CagrServiceOutputValidator,
    MIN_3Y_POPULATED,
    MIN_5Y_POPULATED,
)
from backend.services.data_quality.validators.company_quarterly_results import (
    CANARY_TICKERS as CQR_CANARIES,
    CompanyQuarterlyResultsSample,
    CompanyQuarterlyResultsValidator,
    HDFCBANK_REVENUE_BAND_CR,
)
from backend.services.data_quality.validators.cron_heartbeats import (
    CronHeartbeatsSample,
    CronHeartbeatsValidator,
    EXPECTED_WORKFLOWS,
    STALENESS_MULTIPLIER,
)
from backend.services.data_quality.validators.shareholding_pattern import (
    PROMOTER_PCT_BANDS,
    ShareholdingPatternSample,
    ShareholdingPatternValidator,
    SUM_CANARY_TICKERS,
)
from backend.services.data_quality.validators.stocks import (
    CANARY_INDUSTRY_TOKENS,
    StocksSample,
    StocksValidator,
)

_NOW = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. Stocks validator — A.2.2 fuzzy industry calibration
# ---------------------------------------------------------------------------


def _stocks_sample_with_canaries(**overrides) -> StocksSample:
    canaries = {
        "HDFCBANK": "Nifty Private Bank",
        "TCS": "IT - Software",
        "RELIANCE": "Refineries / Oil & Gas",
        "NESTLEIND": "FMCG",
        "MARUTI": "Automobile - Passenger Cars",
    }
    canaries.update(overrides.get("canary_industries", {}))
    return StocksSample(
        row_count=2_000,
        prior_row_count=2_000,
        industry_empty_count=50,
        sector_empty_count=20,
        is_active_null_count=0,
        sample_size=2_000,
        hdfcbank_industry=canaries["HDFCBANK"],
        last_update=_NOW - timedelta(hours=24),
        canary_industries=canaries,
    )


def test_stocks_a22_nifty_private_bank_now_passes():
    """A.2.1 false-positive: 'Nifty Private Bank' was rejected by the
    rigid prefix check. A.2.2's fuzzy match must accept it."""
    sample = _stocks_sample_with_canaries()
    v = StocksValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "green", [c for c in res.checks if c.status != "pass"]


def test_stocks_a22_all_five_canaries_pass():
    sample = _stocks_sample_with_canaries()
    v = StocksValidator(sample_loader=lambda: sample)
    res = v.run()
    check = next(c for c in res.checks if c.name == "known_good.HDFCBANK.industry")
    assert check.status == "pass"
    # All 5 should appear in threshold.canaries
    assert set(check.threshold["canaries"].keys()) == set(CANARY_INDUSTRY_TOKENS.keys())


def test_stocks_a22_hdfcbank_misclassified_as_it_still_fails():
    """The fuzzy match must still catch wholesale mis-categorisation."""
    sample = _stocks_sample_with_canaries(canary_industries={"HDFCBANK": "IT - Software"})
    v = StocksValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_stocks_a22_tcs_classified_as_bank_fails():
    sample = _stocks_sample_with_canaries(canary_industries={"TCS": "Private Bank"})
    v = StocksValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_stocks_a22_legacy_caller_without_canary_industries_still_works():
    """Backwards compat: A.1-style caller passes only hdfcbank_industry."""
    sample = StocksSample(
        row_count=2_000,
        prior_row_count=2_000,
        industry_empty_count=50,
        sector_empty_count=20,
        is_active_null_count=0,
        sample_size=2_000,
        hdfcbank_industry="Banks - Private Sector",  # A.1 value
        last_update=_NOW - timedelta(hours=24),
    )
    v = StocksValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "green"


# ---------------------------------------------------------------------------
# 2. CronHeartbeatsValidator
# ---------------------------------------------------------------------------


def _ch_sample_healthy() -> CronHeartbeatsSample:
    fresh_beats: dict = {}
    now = datetime.now(timezone.utc)
    for wf, interval in EXPECTED_WORKFLOWS.items():
        # Half the threshold => clearly fresh.
        fresh_beats[wf] = (now - timedelta(minutes=interval / 2), interval)
    return CronHeartbeatsSample(
        row_count=len(EXPECTED_WORKFLOWS),
        prior_row_count=len(EXPECTED_WORKFLOWS),
        schema_columns=["workflow_name", "last_success_at", "expected_interval_minutes", "consecutive_misses", "updated_at"],
        heartbeats=fresh_beats,
    )


def test_cron_heartbeats_healthy_is_green():
    v = CronHeartbeatsValidator(sample_loader=_ch_sample_healthy)
    res = v.run()
    assert res.overall_status == "green", [c for c in res.checks if c.status != "pass"]


def test_cron_heartbeats_missing_workflow_is_red():
    sample = _ch_sample_healthy()
    # Drop one workflow → missing
    sample.heartbeats.pop("nightly-ingest")
    v = CronHeartbeatsValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"
    failed = [c for c in res.checks if c.status == "fail"]
    assert any(c.name == "cron_workflow_heartbeats" for c in failed)
    details_blob = " ".join(c.details for c in failed)
    assert "nightly-ingest" in details_blob


def test_cron_heartbeats_stale_workflow_is_red():
    sample = _ch_sample_healthy()
    interval = EXPECTED_WORKFLOWS["data-quality-validate"]
    # 10x interval => unambiguously beyond the 2x staleness threshold
    # regardless of when the test is actually executed relative to _NOW.
    sample.heartbeats["data-quality-validate"] = (
        datetime.now(timezone.utc) - timedelta(minutes=interval * 10),
        interval,
    )
    v = CronHeartbeatsValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_cron_heartbeats_naive_timestamp_handled():
    """A naive datetime (no tzinfo) from the DB should not crash."""
    sample = _ch_sample_healthy()
    interval = EXPECTED_WORKFLOWS["cron-deadman-checker"]
    naive = datetime.utcnow().replace(microsecond=0)  # naive
    sample.heartbeats["cron-deadman-checker"] = (naive, interval)
    v = CronHeartbeatsValidator(sample_loader=lambda: sample)
    res = v.run()  # must not raise
    assert res.overall_status in {"green", "yellow", "red"}


# ---------------------------------------------------------------------------
# 3. ShareholdingPatternValidator
# ---------------------------------------------------------------------------


def _sh_sample_healthy() -> ShareholdingPatternSample:
    pcts = {
        # Sum-to-100 canaries
        "HDFCBANK": {"promoter_pct": 25.0, "fii_pct": 50.0, "dii_pct": 18.0, "public_pct": 7.0},
        "TCS": {"promoter_pct": 72.0, "fii_pct": 15.0, "dii_pct": 8.0, "public_pct": 5.0},
        "RELIANCE": {"promoter_pct": 50.0, "fii_pct": 25.0, "dii_pct": 15.0, "public_pct": 10.0},
        "INFY": {"promoter_pct": 14.5, "fii_pct": 33.0, "dii_pct": 35.5, "public_pct": 17.0},
        "ICICIBANK": {"promoter_pct": 0.0, "fii_pct": 50.0, "dii_pct": 40.0, "public_pct": 10.0},
        # Promoter-band canary
        "KOTAKBANK": {"promoter_pct": 26.0, "fii_pct": 40.0, "dii_pct": 25.0, "public_pct": 9.0},
    }
    return ShareholdingPatternSample(
        row_count=10_000,
        prior_row_count=9_950,
        schema_columns=["ticker", "quarter_end", "promoter_pct", "fii_pct", "dii_pct", "public_pct"],
        last_update=_NOW - timedelta(days=45),
        latest_pcts=pcts,
    )


def test_shareholding_healthy_is_green():
    v = ShareholdingPatternValidator(sample_loader=_sh_sample_healthy)
    res = v.run()
    assert res.overall_status == "green", [c for c in res.checks if c.status != "pass"]


def test_shareholding_sum_not_100_is_red():
    sample = _sh_sample_healthy()
    sample.latest_pcts["HDFCBANK"] = {
        "promoter_pct": 25.0, "fii_pct": 50.0, "dii_pct": 18.0, "public_pct": 0.0,
    }  # sums to 93
    v = ShareholdingPatternValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_shareholding_dropped_bucket_is_red():
    sample = _sh_sample_healthy()
    sample.latest_pcts["TCS"]["public_pct"] = None
    v = ShareholdingPatternValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_shareholding_promoter_band_violation_is_red():
    sample = _sh_sample_healthy()
    sample.latest_pcts["HDFCBANK"]["promoter_pct"] = 5.0  # absurd for HDFCBANK
    # Fix sum so the sum-check doesn't also fire (band check focuses)
    sample.latest_pcts["HDFCBANK"]["public_pct"] = 27.0
    v = ShareholdingPatternValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_shareholding_stale_quarter_is_red():
    sample = _sh_sample_healthy()
    sample.last_update = _NOW - timedelta(days=200)  # way past 100d
    v = ShareholdingPatternValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


# ---------------------------------------------------------------------------
# 4. CompanyQuarterlyResultsValidator
# ---------------------------------------------------------------------------


def _cqr_sample_healthy() -> CompanyQuarterlyResultsSample:
    latest = _NOW - timedelta(days=30)
    return CompanyQuarterlyResultsSample(
        row_count=50_000,
        prior_row_count=49_500,
        schema_columns=["ticker", "period_end", "is_consolidated", "revenue_cr", "net_profit_cr"],
        last_update=latest,
        canary_latest_period_end={t: latest for t in CQR_CANARIES},
        revenue_null_count=1,
        revenue_sample_size=40,
        profit_null_count=1,
        profit_sample_size=40,
        hdfcbank_latest_revenue_cr=78_000.0,
    )


def test_cqr_healthy_is_green():
    v = CompanyQuarterlyResultsValidator(sample_loader=_cqr_sample_healthy)
    res = v.run()
    assert res.overall_status == "green", [c for c in res.checks if c.status != "pass"]


def test_cqr_canary_missing_filing_is_red():
    sample = _cqr_sample_healthy()
    sample.canary_latest_period_end["RELIANCE"] = None
    v = CompanyQuarterlyResultsValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_cqr_stale_canary_filing_is_red():
    sample = _cqr_sample_healthy()
    sample.canary_latest_period_end["INFY"] = _NOW - timedelta(days=200)
    v = CompanyQuarterlyResultsValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_cqr_hdfcbank_revenue_unit_bug_is_red():
    """Off-by-100 unit bug: 780 (Cr?) is way below the band."""
    sample = _cqr_sample_healthy()
    sample.hdfcbank_latest_revenue_cr = 780.0
    v = CompanyQuarterlyResultsValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_cqr_revenue_high_null_rate_is_red():
    sample = _cqr_sample_healthy()
    sample.revenue_null_count = 20  # 50% null
    v = CompanyQuarterlyResultsValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


# ---------------------------------------------------------------------------
# 5. CagrServiceOutputValidator
# ---------------------------------------------------------------------------


def _cagr_sample_healthy() -> CagrServiceOutputSample:
    panels = {}
    for t in CAGR_CANARIES:
        panels[t] = {"stock": {"3y": 12.0, "5y": 14.0, "10y": 11.0, "status": "ok"}}
    return CagrServiceOutputSample(panels=panels)


def test_cagr_healthy_is_green():
    v = CagrServiceOutputValidator(sample_loader=_cagr_sample_healthy)
    res = v.run()
    assert res.overall_status == "green", [c for c in res.checks if c.status != "pass"]


def test_cagr_meets_minimum_5y_coverage():
    """Exactly MIN_5Y_POPULATED filled, rest None — should pass coverage."""
    sample = _cagr_sample_healthy()
    # Null out (len-MIN_5Y_POPULATED) tickers' 5y values
    tickers = list(CAGR_CANARIES)
    for t in tickers[MIN_5Y_POPULATED:]:
        sample.panels[t]["stock"]["5y"] = None
    v = CagrServiceOutputValidator(sample_loader=lambda: sample)
    res = v.run()
    # 5y coverage check must pass at the floor
    five_y = next(c for c in res.checks if c.name == "cagr_coverage.5y")
    assert five_y.status == "pass"


def test_cagr_below_5y_floor_is_red():
    sample = _cagr_sample_healthy()
    # All None except one
    for t in list(CAGR_CANARIES)[1:]:
        sample.panels[t]["stock"]["5y"] = None
    v = CagrServiceOutputValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_cagr_below_3y_floor_is_red():
    sample = _cagr_sample_healthy()
    for t in list(CAGR_CANARIES)[2:]:  # only 2 populated, need 4
        sample.panels[t]["stock"]["3y"] = None
    v = CagrServiceOutputValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_cagr_absurd_magnitude_is_red():
    """+1300% CAGR = unit/magnitude bug."""
    sample = _cagr_sample_healthy()
    sample.panels["TCS"]["stock"]["5y"] = 1300.0
    v = CagrServiceOutputValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_cagr_validator_skips_when_db_url_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    v = CagrServiceOutputValidator()
    with pytest.raises(NotImplementedError):
        v._load_sample_from_db()


# ---------------------------------------------------------------------------
# 6. db_loaders_a2_2 graceful-skip path
# ---------------------------------------------------------------------------


def test_a2_2_loaders_return_none_when_database_url_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from backend.services.data_quality.db_loaders_a2_2 import (
        load_company_quarterly_results_sample,
        load_cron_heartbeats_sample,
        load_shareholding_pattern_sample,
    )
    assert load_cron_heartbeats_sample() is None
    assert load_shareholding_pattern_sample() is None
    assert load_company_quarterly_results_sample() is None


def test_a2_2_validators_skip_when_db_url_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from backend.services.data_quality.validators.company_quarterly_results import (
        CompanyQuarterlyResultsValidator,
    )
    from backend.services.data_quality.validators.cron_heartbeats import (
        CronHeartbeatsValidator,
    )
    from backend.services.data_quality.validators.shareholding_pattern import (
        ShareholdingPatternValidator,
    )

    for cls in (
        CronHeartbeatsValidator,
        ShareholdingPatternValidator,
        CompanyQuarterlyResultsValidator,
    ):
        with pytest.raises(NotImplementedError):
            cls()._load_sample_from_db()
