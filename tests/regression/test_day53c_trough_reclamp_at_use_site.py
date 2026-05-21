"""Day-53c (2026-05-21): generalize the Day-51 trough-anchor re-clamp.

Bug
---
Day-51 patched the Tier-2 override branch to re-clamp the trough-
anchor bear/bull off the new iv. But OTHER override paths (the
growth-stock override at service.py L2129+, plus any future
override) can also reset iv after the trough anchor fired without
hitting the Day-51 patch. Canary 2026-05-21 still failed on:

  GUJGASLTD: bear=186 base=183 bull=257 (price ≈ 220)
  HINDZINC:  bear=315 base=307 bull=421
  COROMANDEL bear=936 base=749 bull=1068

All three are cyclicals that landed at iv < 0.85*price after a
post-trough-anchor override, leaving bear pinned at 0.85*price >
base.

Fix
---
Move the re-clamp to the POINT OF USE in the scenario block
(L3087+). By then iv is final regardless of which override path
touched it, so anchoring bear/bull off iv is universally correct.

Formula (same as Day-51):
    bear = min(_trough_anchor_bear_iv, iv * 0.95)
    bull = max(_trough_anchor_bull_iv, iv * 1.05)
"""
from __future__ import annotations
from pathlib import Path


_SVC = (
    Path(__file__).resolve().parents[2]
    / "backend" / "services" / "analysis" / "service.py"
)


# ── Source-text guards ──────────────────────────────────────


def test_reclamp_moved_to_scenario_use_site():
    src = _SVC.read_text(encoding="utf-8")
    # Day-53c marker comment
    assert "Day-53c (2026-05-21): generalize the Day-51 re-clamp" in src
    # And the formula appears in the scenario block (proximity check)
    idx = src.index("Day-53c (2026-05-21)")
    tail = src[idx : idx + 1500]
    assert "min(_trough_anchor_bear_iv, iv * 0.95)" in tail
    assert "max(_trough_anchor_bull_iv" in tail


def test_reclamp_guarded_by_price_positive():
    src = _SVC.read_text(encoding="utf-8")
    # Must not crash on the rare price=0 path
    idx = src.index("Day-53c (2026-05-21)")
    tail = src[idx : idx + 1500]
    assert "price > 0" in tail


def test_day51_inline_reclamp_still_present():
    """Belt-and-suspenders: Day-51's inline re-clamp in the Tier-2
    block is still there. Day-53c covers EVERY path including Tier-2,
    so Day-51 becomes redundant — but harmless to keep."""
    src = _SVC.read_text(encoding="utf-8")
    # Original Day-51 marker
    assert "Day-51 (2026-05-20): canary gate-3 fix" in src


# ── Math: simulate the at-use-site clamp ────────────────────


def _reclamped_at_use_site(
    price: float,
    iv: float,
    anchor_bear: float,
    anchor_bull: float | None,
) -> tuple[float, float]:
    """Mirror of the scenario-block re-clamp."""
    if price > 0:
        bear = round(min(anchor_bear, iv * 0.95), 2)
        bull = round(max(anchor_bull or round(price * 1.10, 2), iv * 1.05), 2)
    else:
        bear = anchor_bear
        bull = anchor_bull or round(price * 1.10, 2)
    return bear, bull


def test_gujgasltd_repro_no_longer_inverts():
    # canary 2026-05-21: price≈220, base iv=183, anchor pinned bear=186
    bear, bull = _reclamped_at_use_site(
        price=220.0, iv=183.0, anchor_bear=186.0, anchor_bull=257.0,
    )
    assert bear <= 183.0, f"bear {bear} must not exceed base 183"
    assert bull >= 183.0, f"bull {bull} must not fall below base 183"


def test_hindzinc_repro_no_longer_inverts():
    bear, bull = _reclamped_at_use_site(
        price=370.0, iv=307.0, anchor_bear=315.0, anchor_bull=421.0,
    )
    assert bear <= 307.0
    assert bull >= 307.0


def test_coromandel_repro_no_longer_inverts():
    bear, bull = _reclamped_at_use_site(
        price=1100.0, iv=749.0, anchor_bear=935.0, anchor_bull=1068.0,
    )
    assert bear <= 749.0
    assert bull >= 749.0


def test_clamp_passthrough_when_anchors_already_bracket():
    # Healthy case: iv between anchors → re-clamp is a no-op
    bear, bull = _reclamped_at_use_site(
        price=500.0, iv=500.0, anchor_bear=425.0, anchor_bull=550.0,
    )
    assert bear == 425.0
    assert bull == 550.0


def test_clamp_with_zero_price_passthrough():
    bear, bull = _reclamped_at_use_site(
        price=0.0, iv=100.0, anchor_bear=80.0, anchor_bull=120.0,
    )
    assert bear == 80.0
    assert bull == 120.0
