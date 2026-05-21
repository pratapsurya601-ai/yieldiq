"""Day-73 (2026-05-21): post-demerger detect-and-route via IPO framework.

Bug D context
-------------
ITCHOTELS (Jan-2025 demerger) and ABLBL (recent demerger) were
returning broken analyses: FV=0, verdict="fairly_valued",
revenue_cagr_3y=null. Root cause: generic DCF cannot stitch
pre/post-demerger bases — the trailing FCF series is mathematically
meaningless across a structural-break boundary.

Fix
---
Detect-and-route. When `has_structural_break(ticker)` is True AND
fewer than ~8 quarters (~2y) have elapsed since the most recent
structural event, route through the IPO framework's existing
`compute_sector_relative_fv` peer-multiple path. Tag the response
with `valuation_engine_used = "relative_post_demerger"`. Validators
skip the DCF-calibrated `fair_value_ratio` / `margin_of_safety`
bounds and the `PHANTOM_REVENUE_CAGR` rule (Rule 7) on this engine
label — all three were designed to gate DCF outputs, not peer-
multiple outputs.

Tests below are source-text guards + a math-only behaviour check on
the new `quarters_since_event` helper (no DB required).

Sector-scope: * (every non-financial / non-utility / non-REIT /
non-ETF ticker with a recent structural break).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


_REPO = Path(__file__).resolve().parents[2]
_SERVICE = _REPO / "backend" / "services" / "analysis" / "service.py"
_CORP = _REPO / "backend" / "services" / "corporate_actions_service.py"
_VALIDATORS = _REPO / "backend" / "services" / "validators.py"
_CACHE = _REPO / "backend" / "services" / "cache_service.py"
_SAFETY_NET = _REPO / "backend" / "services" / "dcf_collapse_safety_net.py"


def test_quarters_since_event_exists():
    """The new helper must be defined in corporate_actions_service."""
    src = _CORP.read_text(encoding="utf-8")
    assert "def quarters_since_event(" in src, (
        "quarters_since_event() helper missing from corporate_actions_service.py"
    )


def test_service_wires_pre_dcf_branch():
    """service.py must call quarters_since_event AND the IPO-framework
    peer-multiple helper from a pre-DCF, pre-Tier-2 branch."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "quarters_since_event" in src, (
        "service.py does not import quarters_since_event"
    )
    assert "_post_demerger_route" in src, (
        "service.py does not flag the post-demerger route"
    )
    # The route reuses the existing IPO-framework peer-multiple helper
    # rather than inventing a parallel valuation path.
    assert "_ipo_compute_sector_relative_fv" in src
    # The branch must run BEFORE the Tier-2 cohort init at L1891 — the
    # source ordering is the simplest invariant to assert.
    pre_dcf_idx = src.find("_post_demerger_route = False")
    tier2_idx = src.find("_tier2_result = None")
    assert pre_dcf_idx > 0 and tier2_idx > 0 and pre_dcf_idx < tier2_idx, (
        "post-demerger branch must precede the Tier-2 init"
    )


def test_service_surfaces_relative_post_demerger_label():
    """valuation_engine_used must surface 'relative_post_demerger' when
    the new branch fires (frontend + validators consume this label)."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert '"relative_post_demerger"' in src, (
        "engine label 'relative_post_demerger' not emitted by service.py"
    )


def test_validators_skip_dcf_rules_on_relative_engine():
    """validators.py must skip fair_value_ratio + margin_of_safety bounds
    and the PHANTOM_REVENUE_CAGR (Rule 7) gate when
    valuation_engine_used == 'relative_post_demerger'."""
    src = _VALIDATORS.read_text(encoding="utf-8")
    assert '"relative_post_demerger"' in src
    assert "_skip_dcf_shaped_rules" in src, (
        "validators.py is missing the _skip_dcf_shaped_rules opt-out"
    )
    # The opt-out gate must guard Rule 7 (PHANTOM_REVENUE_CAGR). The
    # gate is expressed as `and not _skip_dcf_shaped_rules` inside the
    # `if has_structural_break is not None ...` block that wraps the
    # rule. Use the LAST PHANTOM_REVENUE_CAGR occurrence (the actual
    # f-string emit at ~L558) rather than the first (which lives in
    # the opt-out doc-comment) so the locality check is meaningful.
    rule7_idx = src.rfind("PHANTOM_REVENUE_CAGR")
    skip_idx_before_rule7 = src.rfind("_skip_dcf_shaped_rules", 0, rule7_idx)
    # The nearest preceding occurrence must be within ~30 source
    # lines of the rule emission (i.e. the gating `if`-block, not
    # the upstream opt-out flag definition far above).
    rule7_line = src.count("\n", 0, rule7_idx)
    skip_line = src.count("\n", 0, skip_idx_before_rule7)
    assert skip_idx_before_rule7 > 0 and (rule7_line - skip_line) < 30, (
        "Rule 7 (PHANTOM_REVENUE_CAGR) is not gated by _skip_dcf_shaped_rules"
    )


def test_safety_net_lists_post_demerger_engine_as_authoritative():
    """The DCF-collapse safety net must NOT second-guess a post-demerger
    relative-valuation FV (its [0.1, 5.0] gate is DCF-calibrated)."""
    src = _SAFETY_NET.read_text(encoding="utf-8")
    assert '"relative_post_demerger"' in src


def test_cache_version_bumped_to_131():
    """CACHE_VERSION must bump 130 -> 131 so affected tickers re-compute."""
    src = _CACHE.read_text(encoding="utf-8")
    assert "CACHE_VERSION = 131" in src


def test_quarters_since_event_math_with_mocked_row():
    """Math-only behaviour test: feed a mocked corp-actions row and
    assert quarters_since_event returns the expected quarter count.

    Two scenarios:
      (a) Event 6 months ago -> 2 quarters elapsed.
      (b) No matching structural row -> None.
    """
    from datetime import date, timedelta
    from backend.services import corporate_actions_service as cas

    today = date.today()
    six_months_ago = today - timedelta(days=180)
    mocked_row_six_months = [{
        "ticker": "ITCHOTELS",
        "ex_date": six_months_ago,
        "action_type": "DEMERGER",
        "multiplier": None,
        "source_url": "test",
        "source_doc": "test",
        "notes": "",
        "data_source": "test",
        "data_quality_rank": 1,
    }]

    with patch.object(cas, "get_actions", return_value=mocked_row_six_months):
        q = cas.quarters_since_event("ITCHOTELS")
    # 180 days ≈ 5.9 months -> 5 whole months (depending on
    # day-of-month rollover) -> 1 or 2 whole quarters. Assert the
    # band rather than an exact value to absorb the rollover edge.
    assert q in (1, 2), f"expected 1 or 2 quarters, got {q}"

    # (b) Empty / no structural rows -> None.
    with patch.object(cas, "get_actions", return_value=[]):
        assert cas.quarters_since_event("NOSUCH") is None

    # (c) Non-structural row (DIVIDEND) must be ignored -> None.
    nonstructural = [{
        "ticker": "X", "ex_date": six_months_ago,
        "action_type": "DIVIDEND", "multiplier": None,
        "source_url": "", "source_doc": "", "notes": "",
        "data_source": "", "data_quality_rank": 1,
    }]
    with patch.object(cas, "get_actions", return_value=nonstructural):
        assert cas.quarters_since_event("X") is None
