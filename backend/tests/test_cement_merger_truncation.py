# backend/tests/test_cement_merger_truncation.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for the cement extension of the structural-break
# CAGR overlay (data_pipeline/migrations/043_seed_cement_mergers.sql
# + the AMBUJACEM sector mistag fix in
# backend/services/analysis/constants.py).
#
# Scope:
#   * ULTRACEMCO seeded MATERIAL_ACQUISITION (Kesoram 2024-09 +
#     India Cements 2024-12) truncates the post-2024 CAGR window.
#   * AMBUJACEM TICKER_SECTOR_OVERRIDES entry resolves to "Cement",
#     not yfinance's "General/Diversified".
#   * SHREECEM has no seed row → byte-identical to plain CAGR
#     (regression guard for the 4 in-band cement names that should
#     keep their existing behaviour).
#   * ACC Adani takeover (REVERSE_MERGER 2022-09) also triggers
#     truncation when in-window.
#
# Hermetic: monkeypatches get_actions so no live Postgres is
# required. Mirrors the shape of test_corporate_actions_growth.py.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services import corporate_actions_service as cas
from backend.services.analysis.constants import TICKER_SECTOR_OVERRIDES
from backend.services.analysis.utils import _resolve_sector


# Synthetic UltraTech revenue series (₹ Cr × 1e7 → raw INR, oldest→newest)
# FY21..FY25. FY25 includes the consolidated Kesoram + India Cements bump.
ULTRACEMCO_REV = [
    45_000 * 1e7,    # FY21
    52_000 * 1e7,    # FY22
    63_000 * 1e7,    # FY23
    70_000 * 1e7,    # FY24
    91_000 * 1e7,    # FY25 — Kesoram + India Cements consolidated
]

# Synthetic ACC revenue series spanning the Sep-2022 Adani takeover.
ACC_REV = [
    14_000 * 1e7,    # FY21 (Holcim era)
    17_000 * 1e7,    # FY22 (Holcim era)
    18_500 * 1e7,    # FY23 — takeover FY (Sep-2022 close)
    19_500 * 1e7,    # FY24 (Adani era)
    21_000 * 1e7,    # FY25 (Adani era)
]

# Synthetic SHREECEM series — clean (no M&A), used as the regression-
# guard cohort. Numbers irrelevant beyond producing a well-defined CAGR.
SHREECEM_REV = [
    14_000 * 1e7, 16_000 * 1e7, 18_000 * 1e7,
    20_000 * 1e7, 22_000 * 1e7,
]

LATEST_PE_FY25 = date(2025, 3, 31)


def _seed_ultracemco(monkeypatch) -> None:
    """Inject both UltraTech MATERIAL_ACQUISITION rows."""
    rows = [
        {"ticker": "ULTRACEMCO", "ex_date": date(2024, 9, 1),
         "action_type": "MATERIAL_ACQUISITION"},
        {"ticker": "ULTRACEMCO", "ex_date": date(2024, 12, 1),
         "action_type": "MATERIAL_ACQUISITION"},
    ]
    monkeypatch.setattr(cas, "get_actions", lambda *a, **kw: rows)


def _seed_acc(monkeypatch) -> None:
    rows = [
        {"ticker": "ACC", "ex_date": date(2022, 9, 1),
         "action_type": "REVERSE_MERGER"},
    ]
    monkeypatch.setattr(cas, "get_actions", lambda *a, **kw: rows)


def _seed_none(monkeypatch) -> None:
    monkeypatch.setattr(cas, "get_actions", lambda *a, **kw: [])


# ── 1. ULTRACEMCO: seeded acquisition truncates window ──────────
def test_ultracemco_with_seeded_acquisition_truncates(monkeypatch):
    """Both Kesoram and India Cements ex_dates land in FY25 (the
    Indian fiscal year that closes 2025-03-31). With FY25 as the
    merger FY and no post-break tail in the series, the 3y horizon
    is unsatisfiable → returns None. Acceptable grace-window
    outcome (same shape as HDFCBANK FY24 in
    test_corporate_actions_growth).
    """
    _seed_ultracemco(monkeypatch)
    out = cas.compute_cagr_structural_aware(
        "ULTRACEMCO", "revenue", years=3,
        series=ULTRACEMCO_REV,
        latest_period_end=LATEST_PE_FY25,
    )
    # The phantom revenue bump from FY24→FY25 (~30%) MUST NOT
    # surface. Either we truncate to None (grace-window) or to a
    # number well below the pre-fix ~19% 3y CAGR (~91/45)^(1/3) - 1.
    assert out is None or out < 0.18, (
        f"ULTRACEMCO post-M&A 3y CAGR={out!r} — truncation gate did "
        f"not fire (expected None during grace window or <18%)"
    )


def test_ultracemco_no_seed_reproduces_phantom_growth(monkeypatch):
    """Regression guard: without the seed row, the legacy plain CAGR
    reads the M&A revenue bump as organic growth and over-reports.
    Pins the pre-fix state so any future drop of the seed migration
    becomes visible in CI.
    """
    _seed_none(monkeypatch)
    out = cas.compute_cagr_structural_aware(
        "ULTRACEMCO", "revenue", years=3,
        series=ULTRACEMCO_REV,
        latest_period_end=LATEST_PE_FY25,
    )
    assert out is not None
    # (91/52)^(1/3) - 1 ≈ 0.205 — meaningfully above the truncated
    # number. Loose lower bound to avoid coupling to series tweaks.
    assert out > 0.15


# ── 2. AMBUJACEM sector mistag fix ──────────────────────────────
def test_ambujacem_sector_override_returns_cement():
    """AMBUJACEM must resolve to "Cement" via TICKER_SECTOR_OVERRIDES
    even when yfinance hands us "General/Diversified". This is the
    second half of the cement M&A truncation fix — sector-driven
    routing (is_etf / is_regulated_utility / is_bank_like, the
    cyclical-detection fallback, the frontend sector facet, peer-
    cohort queries) all key off the sector string.
    """
    # Direct dict assertion — the override is the source of truth.
    assert TICKER_SECTOR_OVERRIDES.get("AMBUJACEM") == "Cement"
    assert TICKER_SECTOR_OVERRIDES.get("AMBUJACEM.NS") == "Cement"

    # End-to-end: _resolve_sector consumes the override even when the
    # raw yfinance string is the mistag value.
    resolved = _resolve_sector("General/Diversified", clean_ticker="AMBUJACEM")
    assert resolved == "Cement", (
        f"AMBUJACEM sector resolved to {resolved!r}, expected 'Cement' — "
        f"TICKER_SECTOR_OVERRIDES did not take precedence over the "
        f"yfinance-supplied 'General/Diversified' mistag."
    )


def test_ambujacem_sector_override_wins_over_yfinance_blank():
    """Even when yfinance returns no sector at all, the override must
    still fire (the override is the curated truth, not a fallback).
    """
    resolved = _resolve_sector("", clean_ticker="AMBUJACEM")
    assert resolved == "Cement"


# ── 3. ACC: Adani takeover REVERSE_MERGER truncates ─────────────
def test_acc_adani_reverse_merger_truncates(monkeypatch):
    """The Sep-2022 Adani takeover falls in FY23. With FY24+FY25 as
    the post-break tail (2 points), the 3y horizon needs 4 → None.
    """
    _seed_acc(monkeypatch)
    out = cas.compute_cagr_structural_aware(
        "ACC", "revenue", years=3,
        series=ACC_REV,
        latest_period_end=LATEST_PE_FY25,
    )
    assert out is None


def test_acc_adani_reverse_merger_1y_post_break_band(monkeypatch):
    """1y CAGR over the post-Adani years (FY24→FY25) IS computable
    once truncated, and should reflect Adani-era organic growth
    rather than the cross-regime bump.
    """
    _seed_acc(monkeypatch)
    out_1y = cas.compute_cagr_structural_aware(
        "ACC", "revenue", years=1,
        series=ACC_REV,
        latest_period_end=LATEST_PE_FY25,
    )
    # 21000/19500 - 1 ≈ 0.077.
    assert out_1y is not None
    assert 0.05 <= out_1y <= 0.10


# ── 4. SHREECEM regression guard: no seed → no-op ───────────────
def test_shreecem_no_seed_byte_identical_to_plain_cagr(monkeypatch):
    """SHREECEM has no M&A history and intentionally NO row in
    043_seed_cement_mergers.sql. compute_cagr_structural_aware must
    return a number byte-identical to plain compute_revenue_cagr —
    same contract as the bank-cohort regression guard
    test_clean_ticker_no_seed_byte_identical_to_plain_cagr.
    Guarantees the cement extension does not perturb the 4 in-band
    cement names (SHREECEM, DALBHARAT, JKCEMENT, RAMCOCEM).
    """
    _seed_none(monkeypatch)
    out = cas.compute_cagr_structural_aware(
        "SHREECEM", "revenue", years=3,
        series=SHREECEM_REV,
        latest_period_end=LATEST_PE_FY25,
    )
    from backend.services.ratios_service import compute_revenue_cagr
    expected = compute_revenue_cagr(SHREECEM_REV, 3)
    assert out == expected


def test_shreecem_not_in_sector_overrides():
    """SHREECEM's sector already resolves correctly via yfinance —
    must NOT have an entry in TICKER_SECTOR_OVERRIDES (or else a
    future yfinance change is silently masked).
    """
    assert "SHREECEM" not in TICKER_SECTOR_OVERRIDES
    assert "SHREECEM.NS" not in TICKER_SECTOR_OVERRIDES
