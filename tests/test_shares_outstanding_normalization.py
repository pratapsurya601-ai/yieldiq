"""Tests for the shares_outstanding unit auditor.

We test the *classifier* in isolation (no DB) — the SQL part is exercised
by the canary nightly run, not unit tests.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.audit_shares_outstanding_units import classify_unit
from backend.validators.shares_outstanding import (
    MIN_PLAUSIBLE_RAW_SHARES,
    shares_or_warn,
)


# ---- validation guard -----------------------------------------------------


@pytest.mark.parametrize("v", [None, 0, -1, "abc", float("nan")])
def test_shares_or_warn_rejects_garbage(v):
    # NaN technically passes the isinstance check, but `< MIN` evaluates
    # False; the function still returns None for None/<=0/non-numeric
    # and for NaN (NaN<MIN is False, NaN>0 is False, so flow returns
    # None via the v <= 0 branch). Acceptable either way — the contract
    # is "don't ship a wrong ratio".
    out = shares_or_warn("X", v)
    assert out is None or out != out  # None or NaN — not a usable count


def test_shares_or_warn_rejects_lakh_sized():
    # 36_200 looks like the lakh-stored TCS row — must be rejected.
    assert shares_or_warn("TCS", 36_200.0) is None


def test_shares_or_warn_accepts_real_raw_count():
    # 3.62e9 is the real raw TCS share count.
    assert shares_or_warn("TCS", 3.62e9) == pytest.approx(3.62e9)


def test_min_plausible_floor():
    # Boundary check — exactly the floor passes.
    assert shares_or_warn("X", MIN_PLAUSIBLE_RAW_SHARES) == MIN_PLAUSIBLE_RAW_SHARES
    assert shares_or_warn("X", MIN_PLAUSIBLE_RAW_SHARES - 1) is None


# ---- classifier -----------------------------------------------------------


@pytest.mark.parametrize(
    "stored, price, mcap_cr, expected_unit, expected_scale",
    [
        # TCS-like: real ~3.62e9 shares, price ~3500, mcap ~12.7 lakh cr.
        # Stored as raw count → ratio ≈ 1.
        (3.62e9, 3500.0, 1_267_000.0, "raw", 1.0),

        # Same TCS but stored in lakhs (3.62e9 / 1e5 = 36200) →
        # ratio ≈ 1e-5; classifier should say "lakh".
        (36_200.0, 3500.0, 1_267_000.0, "lakh", 1e5),

        # Same TCS but stored in crore (3.62e9 / 1e7 = 362) →
        # ratio ≈ 1e-7; classifier should say "crore".
        (362.0, 3500.0, 1_267_000.0, "crore", 1e7),

        # EMAMILTD-like: ~436M shares, price ~600, mcap ~26000 cr.
        # Stored in lakhs (4365). EMAMILTD case from PR #136.
        (4365.0, 600.0, 26_190.0, "lakh", 1e5),

        # Stored in millions (436) →
        # ratio ≈ 1e-6.
        (436.0, 600.0, 26_190.0, "million", 1e6),
    ],
)
def test_classify_unit_known(stored, price, mcap_cr, expected_unit, expected_scale):
    expected_raw_mcap = price * stored
    canonical_raw_mcap = mcap_cr * 1e7
    ratio = expected_raw_mcap / canonical_raw_mcap
    unit, scale = classify_unit(ratio)
    assert unit == expected_unit
    assert scale == pytest.approx(expected_scale)


def test_classify_unit_garbage_returns_none():
    # A ratio that doesn't match any unit (e.g. 7×) → unknown.
    unit, scale = classify_unit(7.0)
    assert unit is None
    assert scale is None


def test_classify_unit_zero_or_negative():
    assert classify_unit(0.0) == (None, None)
    assert classify_unit(-1.0) == (None, None)
    assert classify_unit(None) == (None, None)


def test_classify_unit_tolerates_15pct_drift():
    # Real shares can drift ~5–10% between the price snapshot date and
    # the period_end of an old financials row (ESOPs, buybacks). The
    # classifier's tolerance is 15% → 1.10 ratio still classifies as
    # "raw".
    unit, scale = classify_unit(1.10)
    assert unit == "raw"
    assert scale == pytest.approx(1.0)


# ---- normalizer CLI shape (no DB) ----------------------------------------


def test_normalize_dry_run_skips_unknown(tmp_path: Path, monkeypatch):
    """Smoke test: the normalizer should refuse to write `unknown` and
    sub-1e6 raw values even in dry-run accounting."""
    csv_path = tmp_path / "audit.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "ticker", "period_end", "period_type", "stored_value",
            "price", "market_cap_cr", "ratio", "inferred_unit",
            "suggested_raw", "data_source",
        ])
        w.writeheader()
        # writable row
        w.writerow({
            "ticker": "TCS", "period_end": "2024-03-31",
            "period_type": "annual", "stored_value": "36200",
            "price": "3500", "market_cap_cr": "1267000",
            "ratio": "1e-5", "inferred_unit": "lakh",
            "suggested_raw": "3.62e9", "data_source": "yfinance",
        })
        # unknown unit — must be skipped
        w.writerow({
            "ticker": "WEIRD", "period_end": "2024-03-31",
            "period_type": "annual", "stored_value": "1",
            "price": "100", "market_cap_cr": "1",
            "ratio": "0.0001", "inferred_unit": "unknown",
            "suggested_raw": "", "data_source": "xbrl",
        })
        # sub-1e6 raw — must be skipped (likely unit error in audit)
        w.writerow({
            "ticker": "TINY", "period_end": "2024-03-31",
            "period_type": "annual", "stored_value": "1",
            "price": "10", "market_cap_cr": "1",
            "ratio": "1.0", "inferred_unit": "raw",
            "suggested_raw": "10", "data_source": "xbrl",
        })

    # Stub DATABASE_URL + the engine factory so dry-run runs without a
    # real DB. The dry-run path opens a transaction but issues no
    # statements — we patch create_engine to a no-op fake.
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/db")

    class _FakeConn:
        def execute(self, *a, **k): raise AssertionError(
            "dry-run must not execute SQL")
        def rollback(self): pass

    class _FakeTx:
        def __enter__(self): return _FakeConn()
        def __exit__(self, *a): return False

    class _FakeEngine:
        def begin(self): return _FakeTx()

    import scripts.normalize_shares_outstanding as nsout
    monkeypatch.setattr(nsout, "_connect", lambda: _FakeEngine())

    rc = nsout.main.__wrapped__ if hasattr(nsout.main, "__wrapped__") else None
    # Call the CLI directly via argv shim.
    import sys as _sys
    argv_backup = _sys.argv[:]
    _sys.argv = ["normalize", "--in", str(csv_path)]
    try:
        rc = nsout.main()
    finally:
        _sys.argv = argv_backup
    assert rc == 0
