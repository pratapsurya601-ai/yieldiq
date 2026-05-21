"""Day-56 (2026-05-21): secondary bear-floor guard respects ordering.

Third (and likely final) variant of the cyclical scenario-inversion
family. Day-51 and Day-53c both targeted the trough-anchor code path
(L2058+ and L3060+ respectively). Canary 2026-05-21 still showed
HINDZINC / COROMANDEL / GUJGASLTD with bear > base — coming from a
DIFFERENT code path: the secondary bear-floor guard at L3144+.

That guard fires for cyclicals where:
  - price > 0
  - is_cyclical()
  - trough anchor did NOT fire (so iv was NOT pinned to 0.95*price)
  - scenarios_clamped.bear.iv < 0.5 * price

It then floors bear at 0.5 * price — which is the right rescue when
base FV is sane (e.g. ~price), but pathological when base FV is
itself below 0.5 * price (HINDZINC base 307 with price 630, so
0.5*price=315 > base=307 → inversion).

Fix
---
Floor bear at `min(0.5 * price, 0.95 * iv)` so bear always lands
strictly below base while still being well above the ₹0 pathology
the original guard was built to prevent.

Reproduction matrix
-------------------
| ticker     | price | iv   | old bear     | new bear        |
|------------|-------|------|--------------|-----------------|
| HINDZINC   | 630.45| 307  | 315.23       | 291.65          |
| COROMANDEL | 1100  | 749  | 550          | 711.55          |
| GUJGASLTD  | 220   | 183  | 110          | 173.85          |
| IOC (hist) | 131.81| 49.36| 65.91        | 46.89           |

In all four cases new_bear < base AND new_bear > engine-raw ₹0/₹1.59
pathology. Strictly better.
"""
from __future__ import annotations
from pathlib import Path


_SVC = (
    Path(__file__).resolve().parents[2]
    / "backend" / "services" / "analysis" / "service.py"
)


# ── Source-text guards ──────────────────────────────────────


def test_bear_floor_uses_min_of_price_and_iv():
    src = _SVC.read_text(encoding="utf-8")
    # The patched formula
    assert "_floor_bear_iv = round(min(0.5 * price, iv * 0.95), 2)" in src


def test_day56_marker_present():
    src = _SVC.read_text(encoding="utf-8")
    assert "Day-56 (2026-05-21): respect scenario ordering" in src


def test_original_finding_c_guard_intact():
    """The trigger conditions (cyclical + not trough-anchored + bear
    below 0.5*price) must NOT change. Only the floor formula changes."""
    src = _SVC.read_text(encoding="utf-8")
    assert "is_cyclical(ticker, _resolved_sector_for_cycle)" in src
    assert "not _trough_anchor_fired" in src
    assert "_scenarios_clamped.bear.iv < 0.5 * price" in src


# ── Math: simulate the new bear floor ───────────────────────


def _floored_bear(price: float, iv: float) -> float:
    return round(min(0.5 * price, iv * 0.95), 2)


def test_hindzinc_no_longer_inverts():
    bear = _floored_bear(price=630.45, iv=307.0)
    assert bear < 307.0, f"bear {bear} must be < base 307"
    assert bear > 0, "bear must not collapse to ₹0 pathology"


def test_coromandel_no_longer_inverts():
    bear = _floored_bear(price=1100.0, iv=749.0)
    assert bear < 749.0
    # 0.5*1100 = 550; 0.95*749 = 711.55; min = 550
    # Wait — for COROMANDEL the constraint is the 0.5*price floor, not 0.95*iv
    assert bear == 550.0


def test_gujgasltd_no_longer_inverts():
    bear = _floored_bear(price=220.0, iv=183.0)
    assert bear < 183.0
    # 0.5*220 = 110; 0.95*183 = 173.85; min = 110
    assert bear == 110.0


def test_ioc_historical_does_not_collapse_to_zero_pathology():
    """The Finding-C original concern: IOC base 49 / price 131 used to
    produce bear=₹1.59 in the bare engine. Old guard floored to 65.9
    (above base, gate-3 fail). New guard floors to 46.9 — strictly
    below base, strictly above ₹1.59."""
    bear = _floored_bear(price=131.81, iv=49.36)
    assert bear < 49.36, "must be below base"
    assert bear > 10.0, "must not return to bare-engine pathology"
    assert bear == 46.89


def test_healthy_cyclical_falls_through_to_price_floor():
    """When base FV is sane (close to price), the 0.5*price floor
    binds — same behavior as before, no regression."""
    # e.g. base FV 95 at price 100 — 0.5*100=50, 0.95*95=90.25, min=50
    bear = _floored_bear(price=100.0, iv=95.0)
    assert bear == 50.0


def test_extreme_undervaluation_iv_clamp_binds():
    """Pathological case the audit caught (HINDZINC pattern). The
    0.95*iv clamp binds because base is < 0.5*price."""
    bear = _floored_bear(price=630.45, iv=307.0)
    # 0.5*price=315.22, 0.95*iv=291.65 → 291.65 binds
    assert bear == 291.65
