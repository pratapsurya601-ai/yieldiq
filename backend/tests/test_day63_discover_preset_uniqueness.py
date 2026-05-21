"""Day-63 (2026-05-21): Discover preset uniqueness fix.

Audit 2026-05-20: all three Discover screens (Wide-Moat at Discount,
Deep Value, High-Margin Growers) led with the SAME 3 tickers
(WAAREEINDO/EIEL/WEBELSOLAR at +0%) because:

  (a) `_is_growth_quality` was just "score >= 75" --- no growth or
      margin requirement, so it picked up any high-score stock.
  (b) The sort was `(score, mos) desc` for ALL presets --- so the top
      picks were the same regardless of which filter passed.

Fix
---
1. `_is_growth_quality` now requires revenue_cagr_3y >= 0.08 (8%) on
   top of score >= 70. Falls open with score >= 75 when CAGR is
   missing entirely (defensive backstop).
2. Sort is preset-specific via `_PRESET_SORT_KEYS`:
   - buffett:        MoS desc, then score   (largest discount on top)
   - deep_value:     MoS desc, then score   (genuinely-deepest value)
   - growth_quality: revenue CAGR desc, then score (real growth first)
3. SQL pulls `revenue_cagr_3y` and the candidate tuple now carries it.

Together: top-3 of each preset now ranks by its OWN primary signal,
so leaderboards differ structurally even when filter universes
overlap.
"""
from __future__ import annotations
from pathlib import Path


_SVC = (
    Path(__file__).resolve().parents[2]
    / "backend" / "routers" / "screener.py"
)


# ── Filter tightening ──────────────────────────────────────


def test_growth_quality_filter_takes_revenue_cagr():
    src = _SVC.read_text(encoding="utf-8")
    assert "def _is_growth_quality(score, mos, moat, pe, rev_cagr)" in src
    # The 8% growth threshold is the new gate
    assert "return rev_cagr >= 0.08" in src
    # Backstop when cagr is missing
    assert "if rev_cagr is None:" in src


def test_all_filter_callbacks_take_five_args():
    """The full filter family must accept (score, mos, moat, pe,
    rev_cagr) so a tuple-arity drift between callers can't ship."""
    src = _SVC.read_text(encoding="utf-8")
    for fn in ("_is_buffett", "_is_deep_value", "_is_growth_quality", "_is_custom"):
        assert f"def {fn}(score, mos, moat, pe, rev_cagr)" in src, fn


# ── Per-preset sort keys ───────────────────────────────────


def test_preset_sort_keys_defined():
    src = _SVC.read_text(encoding="utf-8")
    assert "_PRESET_SORT_KEYS = {" in src
    # buffett + deep_value rank by MoS first
    assert '"buffett":        lambda c: (c[2], c[1])' in src
    assert '"deep_value":     lambda c: (c[2], c[1])' in src
    # growth_quality ranks by revenue_cagr first (index 3 in tuple)
    assert '"growth_quality": lambda c: ((c[3] or 0), c[1])' in src


def test_sort_call_uses_preset_specific_key():
    src = _SVC.read_text(encoding="utf-8")
    # The legacy global sort line is gone
    assert "candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)" not in src
    # Replaced by the preset-specific sort
    assert "candidates.sort(key=sort_key, reverse=True)" in src


# ── SQL pulls revenue_cagr_3y ──────────────────────────────


def test_sql_pulls_revenue_cagr():
    src = _SVC.read_text(encoding="utf-8")
    assert "revenue_cagr_3y" in src
    assert "(payload->'quality'->>'revenue_cagr_3y')::float" in src


def test_candidate_tuple_carries_rev_cagr():
    src = _SVC.read_text(encoding="utf-8")
    # Both push sites (analysis_cache scan + in-memory cache scan)
    # append a 4-tuple with the CAGR.
    assert "candidates.append((full_ticker, score, mos, _rev_cagr))" in src
    assert "candidates.append((val.ticker, score, mos, _rev_cagr2))" in src


def test_filter_callers_pass_rev_cagr():
    src = _SVC.read_text(encoding="utf-8")
    assert "filter_fn(score, mos, moat, pe, _rev_cagr)" in src
    assert "filter_fn(score, mos, moat, pe, _rev_cagr2)" in src
