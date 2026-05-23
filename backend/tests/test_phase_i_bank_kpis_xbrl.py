"""Phase I-ingest-a (2026-05-26) -- BSE bank-XBRL pipeline tests.

Covers:

* ``as_percent`` decimal-vs-percent coercion + out-of-range guards.
* ``ParsedBankKpiRow.populated_field_count`` / ``is_useful``.
* ``register_provider`` + ``fetch_bank_kpis_for_quarter`` dispatch.
* ``ingest_bank_kpis_from_xbrl._run_preflight`` PASS / FAIL paths.

No live network / DB. A mock provider is registered for the
PASS-path test; the FAIL-path test exercises the default
provider (which always returns []).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.sources import bse_bank_xbrl as bbx  # noqa: E402


# ---------- as_percent ------------------------------------------------------

def test_as_percent_returns_none_for_none():
    assert bbx.as_percent(None) is None


def test_as_percent_returns_none_for_non_numeric():
    assert bbx.as_percent("not-a-number") is None


def test_as_percent_passes_through_percent_in_range():
    assert bbx.as_percent(2.45) == 2.45
    assert bbx.as_percent(100) == 100.0


def test_as_percent_coerces_decimal_under_one():
    # 0.0245 (decimal-encoded) -> 2.45%.
    assert bbx.as_percent(0.0245) == pytest.approx(2.45, abs=0.001)


def test_as_percent_drops_negative():
    assert bbx.as_percent(-1.2) is None


def test_as_percent_drops_over_100():
    # 245 is almost certainly a unit-scale bug, not a 245% ratio.
    assert bbx.as_percent(245) is None


# ---------- ParsedBankKpiRow ------------------------------------------------

def _sample_row(**overrides) -> bbx.ParsedBankKpiRow:
    base = dict(
        ticker="HDFCBANK",
        period_end=date(2024, 12, 31),
        gnpa_pct=1.20,
        nnpa_pct=0.30,
        pcr_pct=72.5,
        casa_pct=38.0,
        cost_to_income_pct=40.1,
        credit_deposit_pct=87.0,
        source="bse_xbrl",
        source_url="https://example.invalid/hdfcbank-q3fy25.xml",
    )
    base.update(overrides)
    return bbx.ParsedBankKpiRow(**base)


def test_populated_field_count_full():
    row = _sample_row()
    assert row.populated_field_count() == 6
    assert row.is_useful() is True


def test_populated_field_count_partial():
    row = _sample_row(
        casa_pct=None, cost_to_income_pct=None, credit_deposit_pct=None,
    )
    assert row.populated_field_count() == 3
    assert row.is_useful() is True


def test_is_useful_false_when_all_none():
    row = _sample_row(
        gnpa_pct=None, nnpa_pct=None, pcr_pct=None,
        casa_pct=None, cost_to_income_pct=None, credit_deposit_pct=None,
    )
    assert row.populated_field_count() == 0
    assert row.is_useful() is False


# ---------- provider dispatch -----------------------------------------------

def test_default_provider_returns_empty():
    rows = bbx.fetch_bank_kpis_for_quarter("HDFCBANK", 20)
    assert rows == []
    assert bbx.is_default_provider() is True


def test_register_provider_dispatches(monkeypatch):
    captured: dict = {}

    def fake_provider(ticker: str, n_quarters: int):
        captured["ticker"] = ticker
        captured["n_quarters"] = n_quarters
        return [
            _sample_row(ticker=ticker),
            _sample_row(ticker=ticker, period_end=date(2024, 9, 30)),
        ]

    # Save + restore the global provider so other tests are unaffected.
    original = bbx._PROVIDER  # noqa: SLF001
    try:
        bbx.register_provider(fake_provider)
        assert bbx.is_default_provider() is False
        rows = bbx.fetch_bank_kpis_for_quarter("AXISBANK", 8)
        assert captured == {"ticker": "AXISBANK", "n_quarters": 8}
        assert len(rows) == 2
        assert all(r.ticker == "AXISBANK" for r in rows)
    finally:
        bbx._PROVIDER = original  # noqa: SLF001


def test_register_provider_rejects_non_callable():
    with pytest.raises(TypeError):
        bbx.register_provider("not-callable")  # type: ignore[arg-type]


def test_fetch_rejects_bad_args():
    with pytest.raises(ValueError):
        bbx.fetch_bank_kpis_for_quarter("", 5)
    with pytest.raises(ValueError):
        bbx.fetch_bank_kpis_for_quarter("HDFCBANK", 0)


# ---------- pre-flight gate -------------------------------------------------

def _import_cli():
    """Import the CLI module fresh so we can call _run_preflight()."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib
    if "ingest_bank_kpis_from_xbrl" in sys.modules:
        return importlib.reload(sys.modules["ingest_bank_kpis_from_xbrl"])
    return importlib.import_module("ingest_bank_kpis_from_xbrl")


def test_preflight_fails_on_default_provider():
    cli = _import_cli()
    passed, per_ticker = cli._run_preflight(20)  # noqa: SLF001
    assert passed is False
    # Default provider isn't even called for per-ticker counts -- the
    # gate trips on is_default_provider() and returns {} per the
    # current implementation.
    assert per_ticker == {}


def test_preflight_passes_when_provider_returns_full_rows():
    cli = _import_cli()

    def good_provider(ticker: str, n_quarters: int):
        # Every pre-flight ticker gets one fully-populated row.
        return [_sample_row(ticker=ticker)]

    original = bbx._PROVIDER  # noqa: SLF001
    try:
        bbx.register_provider(good_provider)
        passed, per_ticker = cli._run_preflight(20)  # noqa: SLF001
        assert passed is True
        assert set(per_ticker.keys()) == set(cli.PREFLIGHT_TICKERS)
        assert all(v == 6 for v in per_ticker.values())
    finally:
        bbx._PROVIDER = original  # noqa: SLF001


def test_preflight_fails_when_too_few_tickers_have_enough_fields():
    cli = _import_cli()

    def weak_provider(ticker: str, n_quarters: int):
        # Only HDFCBANK gets enough fields; SBIN / AXISBANK get 3 each.
        if ticker == "HDFCBANK":
            return [_sample_row(ticker=ticker)]
        return [_sample_row(
            ticker=ticker,
            casa_pct=None, cost_to_income_pct=None, credit_deposit_pct=None,
        )]

    original = bbx._PROVIDER  # noqa: SLF001
    try:
        bbx.register_provider(weak_provider)
        passed, per_ticker = cli._run_preflight(20)  # noqa: SLF001
        # Needs >=2 tickers with >=4 fields. Only HDFCBANK qualifies (6
        # fields); SBIN / AXISBANK at 3 fields fall short.
        assert passed is False
        assert per_ticker["HDFCBANK"] == 6
        assert per_ticker["SBIN"] == 3
        assert per_ticker["AXISBANK"] == 3
    finally:
        bbx._PROVIDER = original  # noqa: SLF001
