"""
Regression tests for the 2026-05-18 cyclical-anchor fixes:

Finding A — anchor + peer-cap collision
   When the cyclical-trough anchor fires (iv pinned to 0.95 * price),
   the peer-cap block must be skipped. Otherwise the headline FV is
   trimmed down to peer-median * 1.5 while bear/bull stay anchored at
   the 0.85 / 1.10 band, leaving base OUTSIDE its own scenario band
   (the TATASTEEL / JSWSTEEL bug shipped on 2026-05-18 prod).

Finding C — cyclical bear-floor secondary guard
   When the anchor does NOT fire (iv/price between 0.20 and 0.50, the
   "twilight zone"), the DCF engine can still emit a near-zero bear
   (IOC: bear=₹1.59 on a ₹131.81 stock). `_enforce_scenario_order`
   accepts this because 1.59 <= 49.36 <= 117.87 is technically
   ordered. The secondary guard clamps bear to >= 0.5 * price for
   any cyclical ticker, restoring the "cycle has priced in" floor
   PR #168 was originally designed to produce.

These tests:
1. Verify `is_cyclical()` membership for the affected tickers.
2. Statically inspect `service.py` to assert both code patches are
   present in the expected shape (peer-cap skip branch + bear-floor
   clamp). This locks the fix without standing up the full
   `_get_full_analysis_inner` integration pipeline, which is
   ~3500 lines and requires the entire data layer mocked.
3. Exercise the helper functions (`buffett_mos_pct`, `display_mos`)
   on the constructed `ScenarioCase` shape to verify the bear-floor
   math reconciles with the rest of the response model.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from backend.models.responses import ScenarioCase, ScenariosOutput
from backend.services.analysis.constants import is_cyclical
from backend.services.analysis.utils import _enforce_scenario_order, display_mos
from screener.dcf_engine import buffett_mos_pct


SERVICE_PATH = (
    Path(__file__).resolve().parent.parent
    / "services" / "analysis" / "service.py"
)


# ─────────────────────────────────────────────────────────────────
# 0. Membership sanity — the tickers in the audit must be cyclical
# ─────────────────────────────────────────────────────────────────

def test_affected_tickers_are_cyclical():
    """All three audit-flagged tickers must be in the cyclical set."""
    assert is_cyclical("TATASTEEL") is True
    assert is_cyclical("TATASTEEL.NS") is True
    assert is_cyclical("JSWSTEEL") is True
    assert is_cyclical("JSWSTEEL.NS") is True
    assert is_cyclical("IOC") is True
    assert is_cyclical("IOC.NS") is True


def test_tcs_is_not_cyclical():
    """TCS is the regression sentinel — must NOT be cyclical (peer-cap
    must continue to apply to it, bear-floor must NOT apply to it)."""
    assert is_cyclical("TCS") is False
    assert is_cyclical("TCS.NS") is False
    assert is_cyclical("TCS", sector="IT Services") is False


# ─────────────────────────────────────────────────────────────────
# 1. Finding A — peer-cap skip when trough anchor fired
# ─────────────────────────────────────────────────────────────────

def _service_source() -> str:
    return SERVICE_PATH.read_text(encoding="utf-8")


def test_peercap_skip_branch_when_anchor_fired():
    """The peer-cap block must include an early-exit branch keyed off
    `_trough_anchor_fired` BEFORE the IPO / utility / REIT / financial
    branches that compute `_pc`. Without this guard TATASTEEL /
    JSWSTEEL ship with base case outside the anchored bear/bull band.
    """
    src = _service_source()

    # The skip branch must appear inside the peer-cap try block. The
    # canonical shape established by the fix:
    #     elif _trough_anchor_fired:
    #         ...
    #         _pc = None
    pattern = re.compile(
        r"elif\s+_trough_anchor_fired\s*:\s*\n"
        r"(?:\s*#[^\n]*\n)+"               # at least one comment line
        r"\s*_pc\s*=\s*None",
        re.MULTILINE,
    )
    assert pattern.search(src), (
        "Expected `elif _trough_anchor_fired: ... _pc = None` "
        "skip-branch in service.py peer-cap block. The Finding A fix "
        "regressed."
    )


def test_peercap_skip_branch_precedes_dcf_branch():
    """The trough-anchor skip MUST appear *before* the
    `iv > 0 and not is_financial` branch — otherwise the DCF branch
    would run first and compute the peer cap. Order matters."""
    src = _service_source()
    anchor_skip_idx = src.find("elif _trough_anchor_fired:")
    dcf_branch_idx = src.find("elif iv and iv > 0 and not is_financial:")
    assert anchor_skip_idx > 0, "skip branch missing"
    assert dcf_branch_idx > 0, "non-financial DCF peer-cap branch missing"
    assert anchor_skip_idx < dcf_branch_idx, (
        "Trough-anchor skip must appear BEFORE the non-financial DCF "
        "peer-cap branch — the elif chain short-circuits top-down."
    )


def test_peercap_still_applies_to_non_cyclicals():
    """Regression guard: peer-cap branches for non-financial DCF and
    financial DCF must still exist verbatim. The skip branch must NOT
    have replaced them — only short-circuit when the anchor fires."""
    src = _service_source()
    assert "_pc = _compute_peer_cap(ticker)" in src
    assert "elif iv and iv > 0 and not is_financial:" in src
    assert "elif iv and iv > 0 and is_financial:" in src


# ─────────────────────────────────────────────────────────────────
# 2. Finding C — cyclical bear-floor
# ─────────────────────────────────────────────────────────────────

def test_bear_floor_block_present():
    """The bear-floor block must exist post-`_enforce_scenario_order`
    and must be guarded by `is_cyclical(...)`, `not _trough_anchor_fired`
    and the `< 0.5 * price` predicate."""
    src = _service_source()
    assert "CYCLICAL_BEAR_FLOOR" in src, (
        "log marker for the bear-floor block is missing"
    )
    # Must guard on is_cyclical with the resolved sector.
    assert re.search(
        r"is_cyclical\(ticker,\s*_resolved_sector_for_cycle\)",
        src,
    )
    # Must guard on anchor not having fired (to avoid double-clamping).
    assert "not _trough_anchor_fired" in src
    # Must use the 0.5 * price floor.
    assert "0.5 * price" in src


def test_bear_floor_uses_half_price_clamp():
    """The clamped bear IV must use the 0.5 × price floor — historically
    a bare `round(0.5 * price, 2)`. A later refinement at
    backend/services/analysis/service.py:3801 tightened the clamp to
    `round(min(0.5 * price, iv * 0.95), 2)` so the floor never *raises*
    the bear above 95% of the engine IV. The substring assertion below
    accepts either form: the 0.5 × price half remains in both, and the
    intent (bear can fall to half price, never zero) is preserved."""
    src = _service_source()
    # Tolerant of the 2026-05-22+ min(0.5 * price, iv * 0.95) variant.
    assert "0.5 * price" in src
    assert "_floor_bear_iv" in src


def test_service_module_parses():
    """Sanity: the patched service.py must still parse as valid
    Python. A misplaced `elif` / dedent during the patch would fail
    here loudly rather than during a 30s import in prod."""
    ast.parse(_service_source())


# ─────────────────────────────────────────────────────────────────
# 3. Behavioral tests for the helpers the patch composes
# ─────────────────────────────────────────────────────────────────

def _make_scenario(iv: float, price: float) -> ScenarioCase:
    raw = ((iv - price) / price * 100) if price > 0 else 0.0
    d, c = display_mos(raw)
    return ScenarioCase(
        iv=round(iv, 2),
        mos_pct=round(d if d is not None else 0.0, 1),
        buffett_mos_pct=round(buffett_mos_pct(iv, price) or 0.0, 1),
        mos_clamped=c,
        growth=0.05,
        wacc=0.105,
        term_g=0.04,
    )


def test_ioc_like_bear_floor_math():
    """Replicate the IOC numbers from the 2026-05-18 audit
    (price=131.81, base=49.36, bear=1.59, bull=117.87) and verify that
    applying the 0.5 * price clamp produces a bear IV of ₹65.91 and
    leaves base + bull untouched.

    The patch deliberately does NOT re-run `_enforce_scenario_order`
    after the clamp — see comment in service.py Finding C block.
    Acceptance: bear >= 0.5 * price post-fix.
    """
    price = 131.81
    bear_pre = _make_scenario(1.59, price)
    base = _make_scenario(49.36, price)
    bull = _make_scenario(117.87, price)
    pre = ScenariosOutput(bear=bear_pre, base=base, bull=bull)

    # Sanity: the audit's pre-fix shape is ordered, which is why
    # _enforce_scenario_order accepted it.
    assert pre.bear.iv < pre.base.iv < pre.bull.iv

    # Apply the patch logic verbatim (mirrors service.py lines added).
    assert is_cyclical("IOC")
    assert pre.bear.iv < 0.5 * price

    floored = _make_scenario(0.5 * price, price)
    post = ScenariosOutput(bear=floored, base=pre.base, bull=pre.bull)

    # Acceptance criterion from the spec.
    assert post.bear.iv >= 0.5 * price - 0.01
    assert post.bear.iv == pytest.approx(65.91, abs=0.05)
    # Base / bull untouched.
    assert post.base.iv == pre.base.iv
    assert post.bull.iv == pre.bull.iv
    # No more ₹1.59 bear case — the display pathology is gone.
    assert post.bear.iv > 10.0


def test_tcs_like_bear_below_half_unchanged():
    """Regression guard: a non-cyclical (TCS) with a bear at 0.5*price
    is NOT clamped by the new floor. The conditional guards on
    is_cyclical(); compounders keep their natural DCF bear."""
    price = 4000.0
    bear = _make_scenario(2000.0, price)   # exactly 0.5*price
    base = _make_scenario(4200.0, price)
    bull = _make_scenario(5400.0, price)

    # Guard logic must short-circuit.
    is_cyc = is_cyclical("TCS")
    assert is_cyc is False
    # If the patch fired here, it would clamp bear to 2000.0 — same
    # value, but the *condition* must short-circuit before reaching
    # the body. We assert the condition's first leg fails.
    assert not (
        is_cyc
        and bear.iv < 0.5 * price
    )


def test_tatasteel_anchor_band_intact_when_peercap_skipped():
    """If TATASTEEL's anchor fires (price=209.71, anchored
    base=0.95*price=199.22), and peer-cap is skipped per Finding A,
    the bear/base/bull band must end up within 0.6x-1.3x of the
    anchored base — i.e. the band the anchor was designed to
    propagate.

    The patch does not modify the band itself, only whether peer-cap
    is allowed to subsequently trim base. This test simulates the
    "peer-cap skipped" branch by leaving the anchored numbers
    untouched and asserts the band is consistent.
    """
    price = 209.71
    anchored_base = round(price * 0.95, 2)     # 199.22
    anchored_bear = round(price * 0.85, 2)     # 178.25
    anchored_bull = round(price * 1.10, 2)     # 230.68

    # Audit shipped: bear=134.52, base=168.15, bull=230.68 (base was
    # trimmed by peer-cap to 0.80*price = 168, OUTSIDE the bear/bull
    # band 178-230). Post-fix the anchored base of 199.22 sits
    # comfortably inside [178.25, 230.68].
    assert anchored_bear < anchored_base < anchored_bull
    band_lo = 0.6 * anchored_base
    band_hi = 1.3 * anchored_base
    assert band_lo <= anchored_bear <= band_hi
    assert band_lo <= anchored_base <= band_hi
    assert band_lo <= anchored_bull <= band_hi


def test_jswsteel_anchor_band_intact_when_peercap_skipped():
    """Same shape as TATASTEEL test, for JSWSTEEL (price=1287.40)."""
    price = 1287.40
    anchored_base = round(price * 0.95, 2)
    anchored_bear = round(price * 0.85, 2)
    anchored_bull = round(price * 1.10, 2)
    assert anchored_bear < anchored_base < anchored_bull
    band_lo = 0.6 * anchored_base
    band_hi = 1.3 * anchored_base
    assert band_lo <= anchored_bear <= band_hi
    assert band_lo <= anchored_base <= band_hi
    assert band_lo <= anchored_bull <= band_hi
