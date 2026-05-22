"""Audit#5 P1 — asset_turnover unit-mismatch sanity gate.

INDIGO surfaced an asset_turnover of 359,808.21 on prod (2026-05-22),
which is a textbook unit-mismatch fingerprint: real-world values for
this ratio live in the 0.05x–5x band (banks ~0.05–0.1, capital-light
services up to ~3x, never above 5x). A value six orders of magnitude
above that means revenue and total_assets were in different units
(raw INR vs Crores).

The fix is a sanity gate inside compute_asset_turnover that returns
None when the ratio escapes [0.001, 100], so the UI shows "—" instead
of a clearly-wrong number. Same family as FIX-ROCE-UNIT-MISMATCH and
FIX-CURRENT-RATIO-UNIT.
"""
from __future__ import annotations

import logging

import pytest

from backend.services.ratios_service import compute_asset_turnover


# ───────────────────────── happy path ──────────────────────────────


def test_clean_crores_inputs_returns_expected_ratio():
    """Both inputs in Crores (repo convention) → ratio is correct."""
    # Revenue 10,000 Cr / Total Assets 20,000 Cr = 0.5×
    assert compute_asset_turnover(10_000, 20_000) == 0.5


def test_typical_indian_largecap_range():
    """Real-world values across the universe should pass the gate."""
    # TCS-shaped: ~2.4L Cr revenue / ~1.8L Cr assets ≈ 1.33×
    assert compute_asset_turnover(240_000, 180_000) == 1.33
    # PSU-utility shaped (NTPC): ~1.8L Cr rev / ~5L Cr assets ≈ 0.36×
    assert compute_asset_turnover(180_000, 500_000) == 0.36
    # Bank-shaped (HDFCBANK): ~3L Cr rev / ~36L Cr assets ≈ 0.08×
    assert compute_asset_turnover(300_000, 3_600_000) == 0.08


# ───────────────────────── unit-mismatch guard ─────────────────────


def test_unit_mismatch_revenue_in_rupees_returns_none(caplog):
    """Revenue mistakenly in raw INR (×1e7 scale) vs assets in Crores
    → gate trips, returns None, logs a warning."""
    # 10,000 Cr revenue but accidentally passed as raw INR = 1e11
    # alongside 20,000 Cr assets in their proper Crore unit.
    # Naive ratio = 1e11 / 2e4 = 5e6 — well above the 100× gate.
    with caplog.at_level(logging.WARNING, logger="yieldiq.ratios"):
        result = compute_asset_turnover(1e11, 20_000)
    assert result is None
    assert any("sanity gate tripped" in r.message for r in caplog.records)


def test_unit_mismatch_assets_in_rupees_returns_none(caplog):
    """Inverse mismatch — assets in raw INR (huge) vs revenue in
    Crores (tiny) gives a sub-0.001 ratio that also trips the gate."""
    with caplog.at_level(logging.WARNING, logger="yieldiq.ratios"):
        result = compute_asset_turnover(10_000, 2e11)
    assert result is None
    assert any("sanity gate tripped" in r.message for r in caplog.records)


def test_indigo_shaped_fixture_lands_reasonable_number():
    """INDIGO's real financials (FY26 shape): ~₹80,000 Cr revenue,
    ~₹55,000 Cr total assets → ratio ~1.45×. With both inputs in
    Crores the gate passes and a believable value is returned."""
    result = compute_asset_turnover(80_000, 55_000)
    assert result is not None
    assert 0.5 <= result <= 3.0, (
        f"INDIGO-shaped asset_turnover {result} fell outside the "
        f"plausible 0.5–3.0× band for a domestic airline"
    )


def test_indigo_prod_bug_repro_returns_none(caplog):
    """Reproduce the exact prod symptom: a ratio of 359,808 must be
    suppressed by the gate (>100). Pre-fix this was rendered to the
    user as 'asset_turnover: 359808.21'."""
    # Synthesise the mismatched inputs: small revenue / vanishingly
    # small assets → 3.6e5 ratio.
    with caplog.at_level(logging.WARNING, logger="yieldiq.ratios"):
        result = compute_asset_turnover(35_980_821, 100)
    assert result is None


# ───────────────────────── degenerate inputs ───────────────────────


@pytest.mark.parametrize("rev,ta", [
    (None, 100),
    (100, None),
    (100, 0),
    (100, -5),
    ("oops", 100),
])
def test_degenerate_inputs_return_none(rev, ta):
    assert compute_asset_turnover(rev, ta) is None
