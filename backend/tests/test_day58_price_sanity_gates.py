"""Day-58 (2026-05-21): defensive gates on canonical_price.

Two failure modes the prior cascade did NOT catch:

  (a) daily_prices stuck for months — TCS observed 2026-05-21 at
      ₹2,327 (its Nov-2025 low), real market ~₹3,500. If NSE
      bhavcopy ingestion silently stops, daily_prices.close_price
      serves the last good close forever.
  (b) Outlier in a fresh row — INFY 2026-04 hit ₹1,09,652 from
      yfinance .info (a 92x unit bug). Timestamp was fresh so all
      existing staleness checks passed.

Defenses
--------
1. _is_daily_prices_stale: reject daily_prices rows older than
   _DAILY_PRICES_HARD_STALE_DAYS (7 trading days).
2. _is_price_outlier: reject any served price > _OUTLIER_TOLERANCE_PCT
   (40%) away from the 30-day median of daily_prices.

Both fail OPEN on insufficient evidence (new listings, no history).
"""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


_SVC = (
    Path(__file__).resolve().parents[2]
    / "backend" / "services" / "market_data_service.py"
)


# ── Source-text guards ──────────────────────────────────────


def test_day58_constants_defined():
    src = _SVC.read_text(encoding="utf-8")
    assert "_DAILY_PRICES_HARD_STALE_DAYS = 7" in src
    assert "_OUTLIER_TOLERANCE_PCT = 0.40" in src


def test_helpers_defined():
    src = _SVC.read_text(encoding="utf-8")
    assert "def _daily_prices_baseline(" in src
    assert "def _is_price_outlier(" in src
    assert "def _is_daily_prices_stale(" in src


def test_outlier_gate_wired_into_cascade():
    src = _SVC.read_text(encoding="utf-8")
    # The _accept helper is the centralised application point.
    assert "def _accept(px: float, source: str)" in src
    # Both cascade rungs use it
    assert '_accept(float(row[0]), "live_quotes")' in src
    assert '_accept(px, "daily_prices")' in src


def test_staleness_gate_wired_into_daily_prices_rung():
    src = _SVC.read_text(encoding="utf-8")
    assert "_is_daily_prices_stale(row[1])" in src
    # Reject path falls through to yfinance fallback (continue, not break)
    idx = src.index("_is_daily_prices_stale(row[1])")
    tail = src[idx : idx + 800]
    assert "continue" in tail


# ── Math: simulate the gate predicates ──────────────────────


def _import_helpers():
    """Import the helpers without booting the full FastAPI app."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("mds", _SVC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_outlier_predicate_catches_tcs_class_drift():
    """Stale TCS at ₹2,327 with a (hypothetical) median of ₹3,500 →
    deviation = 33%, BELOW the 40% threshold. The staleness gate is
    what catches TCS, not the outlier gate."""
    m = _import_helpers()
    # TCS-like: 33% deviation → NOT flagged by outlier gate alone
    assert not m._is_price_outlier(2327, 3500)
    # 41% deviation → flagged
    assert m._is_price_outlier(2065, 3500)


def test_outlier_predicate_catches_infy_unit_bug():
    """92x unit bug → way outside 40% tolerance."""
    m = _import_helpers()
    assert m._is_price_outlier(109652, 1188)


def test_outlier_predicate_zero_median_falls_open():
    """Insufficient history (median <= 0) must NEVER false-reject."""
    m = _import_helpers()
    assert not m._is_price_outlier(100, 0)
    assert not m._is_price_outlier(100, -1)


def test_outlier_predicate_zero_price_falls_open():
    """Zero price means the cascade is reading garbage upstream;
    the outlier gate shouldn't be the one flagging it (a different
    layer rejects zero prices)."""
    m = _import_helpers()
    assert not m._is_price_outlier(0, 1188)


def test_staleness_predicate_rejects_8_day_old():
    """7 days is the boundary — 8 days is stale."""
    m = _import_helpers()
    eight_days_ago = date.today() - timedelta(days=8)
    assert m._is_daily_prices_stale(eight_days_ago)


def test_staleness_predicate_accepts_yesterday():
    m = _import_helpers()
    yesterday = date.today() - timedelta(days=1)
    assert not m._is_daily_prices_stale(yesterday)


def test_staleness_predicate_accepts_today():
    m = _import_helpers()
    assert not m._is_daily_prices_stale(date.today())


def test_staleness_predicate_handles_datetime_input():
    """daily_prices.trade_date may come back as datetime; the
    predicate must handle both date and datetime."""
    m = _import_helpers()
    eight_days_ago_dt = datetime.now(timezone.utc) - timedelta(days=8)
    assert m._is_daily_prices_stale(eight_days_ago_dt)


def test_staleness_predicate_handles_none():
    m = _import_helpers()
    assert not m._is_daily_prices_stale(None)


def test_tcs_class_staleness_catches_nov_2025_freeze():
    """The actual TCS bug: daily_prices last updated 2026-01-15
    (4+ months stale by 2026-05-21). Must reject."""
    m = _import_helpers()
    jan_15 = date(2026, 1, 15)
    assert m._is_daily_prices_stale(jan_15)
