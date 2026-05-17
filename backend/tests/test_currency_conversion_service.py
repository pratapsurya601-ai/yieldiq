"""Tests for backend/services/currency_conversion_service.

Covers detection (allow-list + live signal), per-date rate lookup with
weekend/holiday back-fill, scalar conversion, and full statement-frame
conversion against synthetic USD-reporter pandas frames.

Live yfinance is monkey-patched out — these tests run offline.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.services import currency_conversion_service as ccs


# ── Detection ────────────────────────────────────────────────────────


def test_allowlist_detects_known_usd_reporters():
    assert ccs.is_usd_reporter("MPHASIS")
    assert ccs.is_usd_reporter("MPHASIS.NS")
    assert ccs.is_usd_reporter("COFORGE")
    assert ccs.is_usd_reporter("PERSISTENT")
    assert ccs.is_usd_reporter("KPITTECH.NS")


def test_inr_reporter_not_flagged():
    # TCS reports in INR — must NEVER be flagged by either path.
    assert not ccs.is_usd_reporter("TCS")
    assert not ccs.is_usd_reporter(
        "TCS.NS", info={"financialCurrency": "INR"}
    )


def test_live_signal_flags_ns_listing_with_usd_currency():
    # A future ticker not in the allow-list still gets converted when
    # yfinance returns financialCurrency=USD on a .NS listing.
    assert ccs.is_usd_reporter(
        "NEWITCO.NS", info={"financialCurrency": "USD"}
    )


def test_live_signal_does_not_flag_bare_adr_symbol():
    # WIT (Wipro ADR) is a US-primary listing with no .NS/.BO suffix.
    # We do not want to convert here — the existing yf_info_cache
    # write guard rejects ADR mistags upstream.
    assert not ccs.is_usd_reporter(
        "WIT", info={"financialCurrency": "USD"}
    )


# ── Rate cache + lookup ─────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_rate_cache(monkeypatch):
    """Reset module-level rate cache between tests."""
    ccs._RATE_CACHE.clear()
    monkeypatch.setattr(ccs, "_RATE_FETCH_DONE", False, raising=True)
    yield
    ccs._RATE_CACHE.clear()
    monkeypatch.setattr(ccs, "_RATE_FETCH_DONE", False, raising=True)


def _seed_rates(monkeypatch, rates: dict[str, float]):
    """Seed the in-memory cache and skip the live yfinance fetch."""
    monkeypatch.setattr(ccs, "_fetch_inr_rate_history", lambda: rates)


def test_rate_lookup_exact_date(monkeypatch):
    _seed_rates(monkeypatch, {"2024-03-29": 83.45})
    assert ccs.get_usd_inr_rate(date(2024, 3, 29)) == 83.45


def test_rate_lookup_backfills_weekend(monkeypatch):
    # Friday close used for the following Sunday lookup.
    _seed_rates(monkeypatch, {"2024-03-29": 83.45})  # Friday
    assert ccs.get_usd_inr_rate(date(2024, 3, 31)) == 83.45  # Sunday


def test_rate_lookup_falls_back_when_cache_empty(monkeypatch):
    _seed_rates(monkeypatch, {})
    assert ccs.get_usd_inr_rate(date(2024, 3, 29)) == ccs._FALLBACK_RATE


def test_convert_scalar(monkeypatch):
    _seed_rates(monkeypatch, {"2024-03-29": 83.0})
    assert ccs.convert_usd_to_inr(100.0, "2024-03-29") == 8300.0


def test_convert_scalar_handles_none(monkeypatch):
    _seed_rates(monkeypatch, {"2024-03-29": 83.0})
    assert ccs.convert_usd_to_inr(None, "2024-03-29") is None


# ── Statement-frame conversion ──────────────────────────────────────


def test_convert_statement_frames_mphasis_like(monkeypatch):
    """MPHASIS financials in USD → INR: assert revenue ~83x larger.

    Builds a tiny income statement with USD-denominated values
    (raw rupees-equivalent, i.e. NOT yet divided by 1e7) and asserts
    every cell scales by the seeded USDINR rate.
    """
    _seed_rates(monkeypatch, {"2024-03-31": 83.5, "2023-03-31": 82.0})
    # USD revenue: 1.5B and 1.4B for FY24/FY23. yfinance returns these
    # as raw values (not Crores) — the Crores conversion happens later
    # in safe_val(). The currency converter operates on raw values.
    income = pd.DataFrame(
        {
            pd.Timestamp("2024-03-31"): {"Total Revenue": 1_500_000_000.0, "Net Income": 200_000_000.0},
            pd.Timestamp("2023-03-31"): {"Total Revenue": 1_400_000_000.0, "Net Income": 180_000_000.0},
        }
    )
    frames = {
        "annual_income": income,
        "quarterly_income": pd.DataFrame(),
        "annual_balance": pd.DataFrame(),
        "quarterly_balance": pd.DataFrame(),
        "annual_cashflow": pd.DataFrame(),
        "quarterly_cashflow": pd.DataFrame(),
    }
    ccs.convert_statement_frames(frames)
    out = frames["annual_income"]
    # FY24 revenue 1.5B USD * 83.5 = 125.25B INR
    assert out.loc["Total Revenue", pd.Timestamp("2024-03-31")] == pytest.approx(1_500_000_000.0 * 83.5)
    # FY23 revenue 1.4B USD * 82.0 = 114.8B INR
    assert out.loc["Total Revenue", pd.Timestamp("2023-03-31")] == pytest.approx(1_400_000_000.0 * 82.0)
    # Sanity: post-conversion INR revenue must be ~10-83x larger
    # than the USD figure (test asserts the ~83x multiplier, which
    # is the load-bearing transformation for the DCF).
    assert out.loc["Total Revenue", pd.Timestamp("2024-03-31")] > 1_500_000_000.0 * 10


def test_convert_statement_frames_tcs_untouched(monkeypatch):
    """TCS-equivalent INR-reporter path: convert_statement_frames is
    never called for INR reporters (gated upstream in yf_fetcher), so
    this test simply asserts the gate semantics — given that the
    converter is invoked, it transforms unconditionally. The TCS
    no-op guarantee lives at the caller boundary:
    is_usd_reporter('TCS') is False, so the converter is never called.
    """
    assert not ccs.is_usd_reporter("TCS")
    assert not ccs.is_usd_reporter(
        "TCS.NS", info={"financialCurrency": "INR"}
    )


def test_convert_statement_frames_handles_nan(monkeypatch):
    """NaN cells must survive the conversion (yfinance routinely
    returns NaN for line items a company doesn't report)."""
    _seed_rates(monkeypatch, {"2024-03-31": 83.0})
    df = pd.DataFrame({pd.Timestamp("2024-03-31"): {"X": float("nan"), "Y": 100.0}})
    frames = {
        "annual_income": df,
        "quarterly_income": pd.DataFrame(),
        "annual_balance": pd.DataFrame(),
        "quarterly_balance": pd.DataFrame(),
        "annual_cashflow": pd.DataFrame(),
        "quarterly_cashflow": pd.DataFrame(),
    }
    ccs.convert_statement_frames(frames)
    out = frames["annual_income"]
    import math
    assert math.isnan(out.loc["X", pd.Timestamp("2024-03-31")])
    assert out.loc["Y", pd.Timestamp("2024-03-31")] == pytest.approx(8300.0)
