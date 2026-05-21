# backend/tests/test_day74b_reliance_payout.py
"""Regression test for Day-74 FIX-RELIANCE-PAYOUT-ZERO (2026-05-21).

Bug: even after the 2026-05-18 FIX-DIVIDEND-PAYOUT-ZERO, Reliance
still rendered "Payout 0%" via the standalone
/api/v1/analysis/{ticker}/dividends route. Root cause: that route
calls ``DividendService.get_dividends(ticker, enriched=None)`` — the
2026-05-18 recovery branch in ``_build_from_series`` is gated on
``enriched`` being truthy, so it never fires on the standalone route.

Fix: when enriched is absent, fall back to yfinance ``.info``
``trailingEps`` (the same recovery the non-DB-first ``_fetch`` path
uses at lines ~120-133). Probed live 2026-05-21:

    /api/v1/public/dividends/RELIANCE → last_dividend 5.5, 9 payments
    /api/v1/analysis/RELIANCE/dividends → payout_ratio_pct: 0.0 (bug)

These tests pin:
  1. enriched=None + yf_info with trailingEps → payout computed
  2. enriched=None + no yf_info → service falls back to yfinance live
     (we monkeypatch yfinance.Ticker so the test is offline)
  3. enriched present continues to win (no regression on the
     2026-05-18 path)
  4. neither EPS source available → payout stays 0 (no fabrication)
"""
from __future__ import annotations

from datetime import date, timedelta

from backend.services.dividend_service import DividendService


def _series_with_total(total_per_share: float) -> list[dict]:
    """Single annual payment summing to ``total_per_share`` (Reliance
    pays one final dividend per year)."""
    return [
        {"ex_date": date.today() - timedelta(days=90), "amount": total_per_share}
    ]


def test_reliance_payout_recovered_from_yf_info_trailing_eps_when_enriched_none():
    """The bug case: standalone /dividends route passes enriched=None.
    yf_info has trailingEps but no payoutRatio."""
    # Reliance-ish: ttm dividend ₹5.5/share, trailingEps ~ ₹50.
    series = _series_with_total(5.5)
    yf_info = {
        "currentPrice": 1450.0,
        "trailingEps": 50.0,
        # NOTE: no payoutRatio (the yfinance gap that caused the bug)
    }

    svc = DividendService()
    out = svc._build_from_series("RELIANCE.NS", series, enriched=None, yf_info=yf_info)

    assert out["has_dividends"] is True
    assert out["last_dividend_value"] == 5.5
    # Payout = 5.5 / 50 * 100 = 11.0%
    assert out["payout_ratio_pct"] > 0, (
        f"FIX-RELIANCE-PAYOUT-ZERO regressed — payout still 0 with "
        f"enriched=None and trailingEps available: {out}"
    )
    assert 5 < out["payout_ratio_pct"] < 20


def test_reliance_payout_falls_back_to_live_yfinance_when_yf_info_empty(monkeypatch):
    """Cold standalone-endpoint path: no yf_info at all. The service
    fetches yfinance .info once to recover trailingEps."""
    series = _series_with_total(5.5)

    class _FakeTicker:
        def __init__(self, _t):
            pass

        # Used by the Day-67 streak fallback path; harmless empty.
        @property
        def dividends(self):
            return None

        @property
        def info(self):
            return {"trailingEps": 50.0}

    import yfinance as _yf
    monkeypatch.setattr(_yf, "Ticker", _FakeTicker)

    svc = DividendService()
    out = svc._build_from_series("RELIANCE.NS", series, enriched=None, yf_info=None)

    assert out["payout_ratio_pct"] > 0
    assert 5 < out["payout_ratio_pct"] < 20


def test_reliance_payout_prefers_late_payout_ratio_from_yfinance(monkeypatch):
    """If the cold yfinance fetch returns a populated payoutRatio,
    we use it instead of computing from trailingEps."""
    series = _series_with_total(5.5)

    class _FakeTicker:
        def __init__(self, _t):
            pass

        @property
        def dividends(self):
            return None

        @property
        def info(self):
            return {"trailingEps": 50.0, "payoutRatio": 0.092}  # 9.2%

    import yfinance as _yf
    monkeypatch.setattr(_yf, "Ticker", _FakeTicker)

    svc = DividendService()
    out = svc._build_from_series("RELIANCE.NS", series, enriched=None, yf_info=None)
    assert out["payout_ratio_pct"] == 9.2


def test_enriched_path_still_wins_when_present():
    """No regression: the 2026-05-18 enriched-based recovery still
    fires before the new yfinance fallback."""
    series = _series_with_total(5.5)
    enriched = {
        # PAT ₹81,000 cr → 810,000,000,000; shares 676.6 cr → 6,766,000,000
        # EPS = 81000e9 / 6.766e9 ≈ ₹119.7? Let's use realistic absolute units.
        # latest_pat in INR, shares as count → use a clean EPS = ₹50:
        "latest_pat": 500_000_000_000.0,
        "shares": 10_000_000_000.0,
    }
    # yf_info has no payoutRatio → recovery should fire from enriched.
    yf_info = {"currentPrice": 1450.0}

    svc = DividendService()
    out = svc._build_from_series("RELIANCE.NS", series, enriched, yf_info)
    # 5.5 / 50 * 100 = 11.0%
    assert out["payout_ratio_pct"] == 11.0


def test_no_eps_source_anywhere_stays_zero(monkeypatch):
    """If neither enriched nor yfinance can supply EPS, we do NOT
    fabricate a payout — 0% is the honest answer here."""
    series = _series_with_total(5.5)

    class _FakeTicker:
        def __init__(self, _t):
            pass

        @property
        def dividends(self):
            return None

        @property
        def info(self):
            return {}  # no trailingEps, no payoutRatio

    import yfinance as _yf
    monkeypatch.setattr(_yf, "Ticker", _FakeTicker)

    svc = DividendService()
    out = svc._build_from_series("RELIANCE.NS", series, enriched=None, yf_info=None)
    assert out["payout_ratio_pct"] == 0
