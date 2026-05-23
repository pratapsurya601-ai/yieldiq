"""Phase A.1 self-tests for the data-quality validator framework.

These tests are the spec. Every regression in the framework should be
expressible as a test here before being fixed. Coverage:

1. HealthCheckResult.overall_status math (green/yellow/red derivation)
2. to_jsonb() round-trips cleanly (including datetime + nested checks)
3. Common check helpers at boundary conditions
4. DailyPricesValidator catches the Day-112 adj_close bug
5. StocksValidator catches the Day-111a industry serializer bug
6. Orchestrator exit codes + --dry-run + --table filtering
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

import pytest

from backend.services.data_quality import (
    CheckResult,
    HealthCheckResult,
)
from backend.services.data_quality.checks import (
    known_good_plausibility,
    last_update_recency,
    null_rate_check,
    row_count_stability,
    schema_columns_present,
)
from backend.services.data_quality.validators.daily_prices import (
    EXPECTED_COLUMNS,
    DailyPricesSample,
    DailyPricesValidator,
)
from backend.services.data_quality.validators.stocks import (
    StocksSample,
    StocksValidator,
)


# ---------------------------------------------------------------------------
# 1. HealthCheckResult.overall_status math
# ---------------------------------------------------------------------------


def _ck(status: str, name: str = "x") -> CheckResult:
    return CheckResult(name=name, status=status, details="d")  # type: ignore[arg-type]


def test_overall_status_all_pass_is_green():
    h = HealthCheckResult(table="t", populator="p", last_run_at=None, checks=[_ck("pass"), _ck("pass")])
    assert h.overall_status == "green"


def test_overall_status_empty_checks_is_green():
    # Documented behaviour: a validator with zero checks reports green.
    # Test suite catches "validator silently ran nothing" via separate
    # assertions on len(checks), not via this status.
    h = HealthCheckResult(table="t", populator="p", last_run_at=None, checks=[])
    assert h.overall_status == "green"


def test_overall_status_any_warn_is_yellow():
    h = HealthCheckResult(table="t", populator="p", last_run_at=None, checks=[_ck("pass"), _ck("warn")])
    assert h.overall_status == "yellow"


def test_overall_status_any_fail_is_red_even_with_warns():
    h = HealthCheckResult(
        table="t",
        populator="p",
        last_run_at=None,
        checks=[_ck("pass"), _ck("warn"), _ck("fail")],
    )
    assert h.overall_status == "red"


# ---------------------------------------------------------------------------
# 2. to_jsonb() round-trip
# ---------------------------------------------------------------------------


def test_to_jsonb_round_trips_through_json():
    now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    h = HealthCheckResult(
        table="daily_prices",
        populator="pop",
        last_run_at=now,
        checks=[
            CheckResult(
                name="c1",
                status="pass",
                details="ok",
                threshold={"expected": 100, "actual": 99},
            ),
            CheckResult(name="c2", status="fail", details="bad", threshold={}),
        ],
    )
    payload = h.to_jsonb()
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert decoded["table"] == "daily_prices"
    assert decoded["populator"] == "pop"
    assert decoded["last_run_at"] == now.isoformat()
    assert decoded["overall_status"] == "red"
    assert len(decoded["checks"]) == 2
    assert decoded["checks"][0]["threshold"]["expected"] == 100


def test_to_jsonb_handles_none_last_run_at():
    h = HealthCheckResult(table="t", populator="p", last_run_at=None, checks=[])
    assert h.to_jsonb()["last_run_at"] is None


# ---------------------------------------------------------------------------
# 3. Check-helper boundary conditions
# ---------------------------------------------------------------------------


def test_row_count_stability_no_prior_passes():
    r = row_count_stability("t", current=100, prior=0)
    assert r.status == "pass"


def test_row_count_stability_exact_warn_boundary():
    # Default warn threshold is 5%. Exactly 5% drop -> warn.
    r = row_count_stability("t", current=95, prior=100)
    assert r.status == "warn"


def test_row_count_stability_just_under_warn():
    r = row_count_stability("t", current=96, prior=100)
    assert r.status == "pass"


def test_row_count_stability_exact_fail_boundary():
    r = row_count_stability("t", current=90, prior=100)
    assert r.status == "fail"


def test_row_count_stability_growth_is_pass():
    r = row_count_stability("t", current=200, prior=100)
    assert r.status == "pass"


def test_null_rate_check_at_threshold_passes():
    # 10 nulls / 100 = 10.0%. max=10.0 means "<= 10 passes".
    r = null_rate_check("t", "c", null_count=10, sample_size=100, max_null_pct=10.0)
    assert r.status == "pass"


def test_null_rate_check_just_over_fails():
    r = null_rate_check("t", "c", null_count=11, sample_size=100, max_null_pct=10.0)
    assert r.status == "fail"


def test_null_rate_check_empty_sample_fails():
    r = null_rate_check("t", "c", null_count=0, sample_size=0, max_null_pct=10.0)
    assert r.status == "fail"


def test_known_good_plausibility_inside_passes():
    r = known_good_plausibility("t", "X", "p", actual=500.0, min_value=400.0, max_value=600.0)
    assert r.status == "pass"


def test_known_good_plausibility_below_fails():
    r = known_good_plausibility("t", "X", "p", actual=399.99, min_value=400.0, max_value=600.0)
    assert r.status == "fail"


def test_known_good_plausibility_above_fails():
    r = known_good_plausibility("t", "X", "p", actual=600.01, min_value=400.0, max_value=600.0)
    assert r.status == "fail"


def test_known_good_plausibility_none_fails():
    r = known_good_plausibility("t", "X", "p", actual=None, min_value=400.0, max_value=600.0)
    assert r.status == "fail"


def test_last_update_recency_within_window_passes():
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    r = last_update_recency("t", last_update=now - timedelta(hours=10), max_age_hours=30.0, now=now)
    assert r.status == "pass"


def test_last_update_recency_stale_fails():
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    r = last_update_recency("t", last_update=now - timedelta(hours=72), max_age_hours=30.0, now=now)
    assert r.status == "fail"


def test_last_update_recency_naive_timestamp_handled():
    # Production timestamps from Neon arrive tz-aware, but tests / older
    # data may be naive. The helper coerces to UTC rather than raising.
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 5, 23, 5, 0)
    r = last_update_recency("t", last_update=naive, max_age_hours=30.0, now=now)
    assert r.status == "pass"


def test_last_update_recency_none_fails():
    r = last_update_recency("t", last_update=None, max_age_hours=30.0)
    assert r.status == "fail"


def test_schema_columns_present_subset_ok():
    r = schema_columns_present("t", expected=["a", "b"], actual=["a", "b", "c"])
    assert r.status == "pass"


def test_schema_columns_present_missing_fails():
    r = schema_columns_present("t", expected=["a", "b"], actual=["a"])
    assert r.status == "fail"
    assert "b" in r.threshold["missing"]


# ---------------------------------------------------------------------------
# 4. DailyPricesValidator — Day-112 regression coverage
# ---------------------------------------------------------------------------


def _healthy_daily_prices_sample() -> DailyPricesSample:
    return DailyPricesSample(
        row_count=5_000_000,
        prior_row_count=5_000_000,
        close_null_count=10,  # 0.0002% — well under 1% threshold
        sample_size=5_000_000,
        schema_columns=list(EXPECTED_COLUMNS),
        last_update=datetime.now(timezone.utc) - timedelta(hours=5),
        latest_close={"HDFCBANK": 950.0, "RELIANCE": 1400.0, "TCS": 3500.0},
        adj_close_eq_close_fraction={"NESTLEIND": 0.30, "TCS": 0.20, "RELIANCE": 0.25},
    )


def test_daily_prices_healthy_input_is_green():
    v = DailyPricesValidator(sample_loader=_healthy_daily_prices_sample)
    result = v.run()
    assert result.overall_status == "green", [
        (c.name, c.status, c.details) for c in result.checks if c.status != "pass"
    ]


def test_daily_prices_catches_day112_adj_close_bug():
    """The exact bug Day-112 fixed: adj_close == close_price for ~all rows."""
    sample = _healthy_daily_prices_sample()
    sample.adj_close_eq_close_fraction = {"NESTLEIND": 0.95, "TCS": 0.95, "RELIANCE": 0.95}
    v = DailyPricesValidator(sample_loader=lambda: sample)
    result = v.run()
    assert result.overall_status == "red"
    bad = [c for c in result.checks if c.status == "fail"]
    assert any(c.name == "adj_close_distinct_from_close" for c in bad), bad


def test_daily_prices_catches_close_null_explosion():
    sample = _healthy_daily_prices_sample()
    sample.close_null_count = sample.sample_size // 2  # 50% null
    v = DailyPricesValidator(sample_loader=lambda: sample)
    result = v.run()
    assert result.overall_status == "red"
    assert any(c.name == "null_rate.close_price" and c.status == "fail" for c in result.checks)


def test_daily_prices_catches_implausible_known_good():
    """HDFCBANK at ₹50 means paise-vs-rupees unit bug or stale data."""
    sample = _healthy_daily_prices_sample()
    sample.latest_close["HDFCBANK"] = 50.0
    v = DailyPricesValidator(sample_loader=lambda: sample)
    result = v.run()
    assert result.overall_status == "red"
    assert any(
        c.name == "plausibility.HDFCBANK.close_price" and c.status == "fail"
        for c in result.checks
    )


def test_daily_prices_catches_missing_schema_column():
    sample = _healthy_daily_prices_sample()
    sample.schema_columns = [c for c in sample.schema_columns if c != "adj_close"]
    v = DailyPricesValidator(sample_loader=lambda: sample)
    result = v.run()
    assert result.overall_status == "red"
    assert any(c.name == "schema_columns_present" and c.status == "fail" for c in result.checks)


def test_daily_prices_catches_stale_data():
    sample = _healthy_daily_prices_sample()
    sample.last_update = datetime.now(timezone.utc) - timedelta(hours=72)
    v = DailyPricesValidator(sample_loader=lambda: sample)
    result = v.run()
    assert result.overall_status == "red"


# ---------------------------------------------------------------------------
# 5. StocksValidator — Day-111a regression coverage
# ---------------------------------------------------------------------------


def _healthy_stocks_sample() -> StocksSample:
    return StocksSample(
        row_count=2_000,
        prior_row_count=2_000,
        industry_empty_count=50,    # 2.5% — well under 20% threshold
        sector_empty_count=20,      # 1.0% — well under 5% threshold
        is_active_null_count=0,
        sample_size=2_000,
        hdfcbank_industry="Banks - Private Sector",
        last_update=datetime.now(timezone.utc) - timedelta(hours=24),
    )


def test_stocks_healthy_input_is_green():
    v = StocksValidator(sample_loader=_healthy_stocks_sample)
    result = v.run()
    assert result.overall_status == "green", [
        (c.name, c.status, c.details) for c in result.checks if c.status != "pass"
    ]


def test_stocks_catches_industry_serializer_regression():
    """Day-111a: industry was empty for 96% of tickers."""
    sample = _healthy_stocks_sample()
    sample.industry_empty_count = 1_000  # 50% empty
    v = StocksValidator(sample_loader=lambda: sample)
    result = v.run()
    assert result.overall_status == "red"
    assert any(c.name == "null_rate.industry" and c.status == "fail" for c in result.checks)


def test_stocks_catches_hdfcbank_industry_empty():
    sample = _healthy_stocks_sample()
    sample.hdfcbank_industry = ""
    v = StocksValidator(sample_loader=lambda: sample)
    result = v.run()
    assert result.overall_status == "red"
    assert any(c.name == "known_good.HDFCBANK.industry" and c.status == "fail" for c in result.checks)


def test_stocks_catches_hdfcbank_industry_misclassified():
    sample = _healthy_stocks_sample()
    sample.hdfcbank_industry = "Unknown"  # the exact Day-111a fallback value
    v = StocksValidator(sample_loader=lambda: sample)
    result = v.run()
    assert result.overall_status == "red"


def test_stocks_catches_is_active_nulls():
    sample = _healthy_stocks_sample()
    sample.is_active_null_count = 5  # schema invariant — even one is a regression
    v = StocksValidator(sample_loader=lambda: sample)
    result = v.run()
    assert result.overall_status == "red"


# ---------------------------------------------------------------------------
# 6. Orchestrator
# ---------------------------------------------------------------------------


class _FakeValidator:
    """Drop-in stand-in for a real Validator class."""

    table = "fake"
    populator = "fake.populator"

    def __init__(self, status: str = "green"):
        self._status = status

    def run(self) -> HealthCheckResult:
        ck = CheckResult(
            name="fake",
            status={"green": "pass", "yellow": "warn", "red": "fail"}[self._status],  # type: ignore[arg-type]
            details="synthetic",
        )
        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=[ck],
        )


def _make_validator_cls(name: str, status: str):
    """Build a no-arg validator class the orchestrator can instantiate."""
    return type(name, (_FakeValidator,), {"table": name, "__init__": lambda self: _FakeValidator.__init__(self, status)})


def test_orchestrator_exits_1_on_any_red():
    from scripts import run_data_quality_validators as orch

    GreenV = _make_validator_cls("a", "green")
    RedV = _make_validator_cls("b", "red")
    with patch.object(orch, "REGISTRY", [GreenV, RedV]):
        rc = orch.run(dry_run=True)
    assert rc == 1


def test_orchestrator_exits_0_when_all_green_or_yellow():
    from scripts import run_data_quality_validators as orch

    GreenV = _make_validator_cls("a", "green")
    YellowV = _make_validator_cls("b", "yellow")
    with patch.object(orch, "REGISTRY", [GreenV, YellowV]):
        rc = orch.run(dry_run=True)
    assert rc == 0


def test_orchestrator_dry_run_does_not_write_to_db():
    from scripts import run_data_quality_validators as orch

    RedV = _make_validator_cls("a", "red")
    with patch.object(orch, "REGISTRY", [RedV]), patch.object(orch, "_persist") as persist:
        orch.run(dry_run=True)
    persist.assert_not_called()


def test_orchestrator_writes_when_not_dry_run():
    from scripts import run_data_quality_validators as orch

    GreenV = _make_validator_cls("a", "green")
    with patch.object(orch, "REGISTRY", [GreenV]), patch.object(orch, "_persist") as persist:
        orch.run(dry_run=False)
    assert persist.call_count == 1


def test_orchestrator_table_filter_runs_only_matching():
    from scripts import run_data_quality_validators as orch

    A = _make_validator_cls("alpha", "green")
    B = _make_validator_cls("beta", "red")
    with patch.object(orch, "REGISTRY", [A, B]), patch.object(orch, "_persist") as persist:
        rc = orch.run(dry_run=False, table_filter="alpha")
    assert rc == 0  # would have been 1 if beta had run
    assert persist.call_count == 1
    assert persist.call_args.args[0].table == "alpha"


def test_orchestrator_unknown_table_filter_exits_2():
    from scripts import run_data_quality_validators as orch

    A = _make_validator_cls("alpha", "green")
    with patch.object(orch, "REGISTRY", [A]):
        rc = orch.run(dry_run=True, table_filter="does-not-exist")
    assert rc == 2


def test_orchestrator_skips_validators_with_unwired_loaders(monkeypatch):
    """A.2.1 wired the DB loaders behind ``$DATABASE_URL``; when the env
    var is unset the loaders return None and validators promote that to
    NotImplementedError. The orchestrator's skip path then makes the
    run a no-op rather than a crash, so end-to-end smoke runs are
    possible without a database."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from scripts import run_data_quality_validators as orch

    rc = orch.run(dry_run=True)
    assert rc == 0  # zero results -> nothing red -> exit 0
