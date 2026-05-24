"""Public-serializer suppression of extreme MoS values (2026-05-24).

Bug repro: KALYANI.NS shipped to /public/stock-summary with
`margin_of_safety=829.0` because the Phase B.2 `mos_is_extreme` gate
only downgraded the verdict to `under_review` and added a caution note
— the raw 829 still flowed through the public serializer and rendered
as "+829% upside" on the SEO page, contradicting the verdict chip.

Policy (option (a) in the issue): public serializers strip the value
to None when `valuation.mos_is_extreme=True`. The internal
`valuation.margin_of_safety` field is intentionally NOT touched so
admin / canary-diff / debugging views still see the unsuppressed
number.

These tests pin the helper in isolation so the rule is enforceable
without spinning up FastAPI + Pydantic + the analysis pipeline. The
helper is the single SoT used by:
  * routers/public.py:_extract_analysis_summary (stock-summary)
  * routers/analysis.py:get_og_data (og-data)
  * routers/analysis.py:get_analysis_preview (preview)
"""
from backend.services.summary_projection import resolve_display_mos


# ─────────────────────────────────────────────────────────────────
# Suppression cases — flag fires → public surface gets None.
# ─────────────────────────────────────────────────────────────────

def test_extreme_mos_suppressed_to_none_kalyani_repro():
    """KALYANI.NS shape: raw MoS=829, mos_is_extreme=True → None."""
    assert resolve_display_mos(829.0, True) is None


def test_extreme_mos_suppressed_for_negative_extreme():
    """Symmetric — extreme negative MoS also suppresses (the gate is |MoS|)."""
    assert resolve_display_mos(-450.0, True) is None


def test_extreme_mos_suppressed_when_raw_value_is_already_none():
    """Defensive: flag + None raw should still suppress (no crash)."""
    assert resolve_display_mos(None, True) is None


# ─────────────────────────────────────────────────────────────────
# Pass-through cases — flag clear → original value flows through.
# ─────────────────────────────────────────────────────────────────

def test_normal_mos_passes_through_unchanged():
    """The common case: undervalued stock with MoS=43% → 43.0."""
    assert resolve_display_mos(43.0, False) == 43.0


def test_zero_mos_passes_through_as_zero_not_none():
    """At-fair-value: MoS=0 must surface as 0, not get treated as missing."""
    assert resolve_display_mos(0.0, False) == 0.0


def test_negative_mos_passes_through_for_overvalued_stocks():
    """Overvalued (MoS=-25%) must still render — only `extreme` is hidden."""
    assert resolve_display_mos(-25.0, False) == -25.0


def test_none_raw_mos_passes_through_as_none_when_flag_clear():
    """Genuinely missing MoS (compute failed) → None even without flag."""
    assert resolve_display_mos(None, False) is None


def test_mos_rounded_to_one_decimal_place_for_display_parity():
    """Display parity with /public/stock-summary's previous `round(_, 1)`."""
    assert resolve_display_mos(42.678, False) == 42.7


# ─────────────────────────────────────────────────────────────────
# Integration-ish: confirm the public summary projection actually
# uses the helper (by exercising _extract_analysis_summary against a
# minimal duck-typed result object).
# ─────────────────────────────────────────────────────────────────

def test_extract_analysis_summary_suppresses_mos_when_extreme():
    """End-to-end through _extract_analysis_summary: extreme → mos=None."""
    import types

    from backend.routers.public import _extract_analysis_summary

    valuation = types.SimpleNamespace(
        current_price=138.09,
        margin_of_safety=829.0,
        mos_is_extreme=True,
        mos_extreme_note="Model shows significant undervaluation...",
        fair_value=1282.90,
        base_case=1282.90,
        bear_case=900.0,
        bull_case=1500.0,
        wacc=0.12,
        confidence_score=50,
        verdict="under_review",
        fair_value_source="dcf",
        valuation_model="dcf",
        peer_cap_details=None,
    )
    quality = types.SimpleNamespace(
        yieldiq_score=60, grade="B", moat="narrow",
        piotroski_score=6, roe=18.0, de_ratio=0.3,
        roce=15.0, debt_ebitda=None, interest_coverage=None,
        current_ratio=None, asset_turnover=None,
        revenue_cagr_3y=None, revenue_cagr_5y=None,
    )
    company = types.SimpleNamespace(
        company_name="Kalyani Steels", sector="Metals",
        industry="Steel", exchange="NSE", currency="INR",
        market_cap=12345.0,
    )
    result = types.SimpleNamespace(
        ticker="KALYANI.NS",
        valuation=valuation, quality=quality, company=company,
        insights=None, ai_summary=None, timestamp="2026-05-24T00:00:00Z",
    )

    out = _extract_analysis_summary(result)
    assert out["mos"] is None
    assert out["mos_pct"] is None
    # Verdict stays — frontend reads chip + note for the user message.
    assert out["verdict"] == "under_review"


def test_extract_analysis_summary_passes_through_normal_mos():
    """End-to-end through _extract_analysis_summary: normal → mos=43.0."""
    import types

    from backend.routers.public import _extract_analysis_summary

    valuation = types.SimpleNamespace(
        current_price=100.0,
        margin_of_safety=43.0,
        mos_is_extreme=False,
        mos_extreme_note=None,
        fair_value=143.0,
        base_case=143.0,
        bear_case=120.0,
        bull_case=170.0,
        wacc=0.11,
        confidence_score=80,
        verdict="undervalued",
        fair_value_source="dcf",
        valuation_model="dcf",
        peer_cap_details=None,
    )
    quality = types.SimpleNamespace(
        yieldiq_score=75, grade="A", moat="wide",
        piotroski_score=8, roe=22.0, de_ratio=0.1,
        roce=20.0, debt_ebitda=None, interest_coverage=None,
        current_ratio=None, asset_turnover=None,
        revenue_cagr_3y=None, revenue_cagr_5y=None,
    )
    company = types.SimpleNamespace(
        company_name="Demo Co", sector="IT",
        industry="Software", exchange="NSE", currency="INR",
        market_cap=50000.0,
    )
    result = types.SimpleNamespace(
        ticker="DEMO.NS",
        valuation=valuation, quality=quality, company=company,
        insights=None, ai_summary=None, timestamp="2026-05-24T00:00:00Z",
    )

    out = _extract_analysis_summary(result)
    assert out["mos"] == 43.0
    assert out["mos_pct"] == 43.0
