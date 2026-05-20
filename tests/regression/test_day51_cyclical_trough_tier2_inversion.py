"""Day-51 (2026-05-20): canary gate-3 fix for cyclical trough +
Tier-2 cohort interaction.

Bug
---
In ``backend/services/analysis/service.py``:

1. Trough anchor fires when raw DCF iv < 0.2 * price for a cyclical.
   Sets ``_trough_anchor_bear_iv = 0.85 * price``.
2. Tier-2 cohort override runs immediately after and replaces ``iv``
   with the cohort FV, which can be substantially below price.
3. Downstream scenario block (L3060) uses the now-stale
   ``_trough_anchor_bear_iv`` against the new ``iv``.
4. Result: bear ≈ 0.85 × price > base = cohort FV →
   canary gate-3 scenario_dispersion FAIL.

Tickers observed failing in canary 2026-05-20:
- HINDALCO (bear=524 > base=320)
- HINDZINC (bear=316 > base=307)
- COROMANDEL (bear=939 > base=749)
- GUJGASLTD (bear=188 > base=183)

Fix
---
After the Tier-2 override, re-anchor the trough-anchor band:
   bear = min(0.85 * price, iv * 0.95)
   bull = max(1.10 * price, iv * 1.05)

bear ≤ iv * 0.95 → guaranteed bear < base.
bull ≥ iv * 1.05 → guaranteed bull > base.
"""
from __future__ import annotations
from pathlib import Path


_SVC = (
    Path(__file__).resolve().parents[2]
    / "backend" / "services" / "analysis" / "service.py"
)


# ── Source-text guards: the fix is wired into the Tier-2 block ──


def test_tier2_override_block_reclamps_trough_anchor():
    src = _SVC.read_text(encoding="utf-8")
    # The two re-clamp lines must live INSIDE the Tier-2 override
    # branch (i.e. after the iv = float(_tier2_result["fair_value"])
    # assignment). Easiest grep: both clamps reference iv.
    assert "min(0.85 * price, iv * 0.95)" in src
    assert "max(1.10 * price, iv * 1.05)" in src


def test_reclamp_guarded_by_trough_anchor_fired():
    src = _SVC.read_text(encoding="utf-8")
    # The re-clamp must only fire when the trough anchor previously
    # fired — we cannot blanket-recompute the band for every Tier-2
    # result because non-trough cyclicals don't need it.
    # Find the Day-51 comment block and confirm the surrounding `if`.
    needle = "Day-51 (2026-05-20): canary gate-3 fix"
    assert needle in src
    # Cheap proximity check: the guard line must appear after the
    # Day-51 marker and before the re-clamp formula.
    idx = src.index(needle)
    tail = src[idx : idx + 2000]
    assert "_trough_anchor_fired" in tail
    assert "price > 0" in tail


# ── Math-only regression: simulate the clamp formula ───────────


def _reclamped_band(price: float, iv: float) -> tuple[float, float]:
    """Pure-Python mirror of the inline clamp at the patched site."""
    bear = round(min(0.85 * price, iv * 0.95), 2)
    bull = round(max(1.10 * price, iv * 1.05), 2)
    return bear, bull


def test_hindalco_repro_no_longer_inverts():
    # 2026-05-20 canary numbers: price ≈ 617, Tier-2 base = 320.
    bear, bull = _reclamped_band(price=617.0, iv=320.0)
    assert bear <= 320.0, f"bear {bear} must not exceed base 320"
    assert bull >= 320.0, f"bull {bull} must not fall below base 320"
    # Bear stays meaningfully below base (display correctness)
    assert bear < bull


def test_hindzinc_repro_no_longer_inverts():
    # bear=316 base=307 bull=421 → price was the limiter
    bear, bull = _reclamped_band(price=372.0, iv=307.0)
    assert bear <= 307.0
    assert bull >= 307.0


def test_coromandel_repro_no_longer_inverts():
    bear, bull = _reclamped_band(price=1104.0, iv=749.0)
    assert bear <= 749.0
    assert bull >= 749.0


def test_gujgas_repro_no_longer_inverts():
    bear, bull = _reclamped_band(price=221.0, iv=183.0)
    assert bear <= 183.0
    assert bull >= 183.0


# ── Edge cases of the clamp formula ───────────────────────────


def test_clamp_when_iv_equals_price():
    # Healthy cyclical where Tier-2 lands right at price
    bear, bull = _reclamped_band(price=500.0, iv=500.0)
    # bear bounded by 0.85*price = 425 (which is also 0.85*iv)
    assert bear == 425.0
    # bull bounded by 1.10*price = 550 (which is also 1.10*iv)
    assert bull == 550.0


def test_clamp_when_iv_far_above_price():
    # Pathological — Tier-2 thinks the cyclical is dirt cheap
    bear, bull = _reclamped_band(price=100.0, iv=200.0)
    # bear = min(85, 190) = 85
    assert bear == 85.0
    # bull = max(110, 210) = 210
    assert bull == 210.0
    # Both still bracket base
    assert bear <= 200.0 and bull >= 200.0


def test_clamp_preserves_band_width_on_zero_iv():
    # Defensive: iv=0 shouldn't collapse the band to nonsense
    bear, bull = _reclamped_band(price=300.0, iv=0.0)
    # bear = min(255, 0) = 0 — OK, base is also 0 so order holds trivially
    assert bear == 0.0
    # bull = max(330, 0) = 330 — keeps the price-relative bull band
    assert bull == 330.0
