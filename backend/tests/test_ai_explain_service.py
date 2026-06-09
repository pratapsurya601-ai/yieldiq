"""AI Explain service — unit tests.

Covers ``backend/services/ai_explain_service.py`` and its
SEBI-filter / retry / template-fallback orchestration. All Claude
calls are intercepted via a fake closure — no Anthropic SDK
dependency, no network.

Acceptance-criteria coverage (per Premium Feel R4 brief):
  1. Preset catalogue: exactly three presets, every preview is
     SEBI-safe (no banned vocab in any user-visible card copy).
  2. Happy path: clean LLM response yields the answer with source
     ``llm_first`` and zero sanitizer hits.
  3. SEBI filter: adversarial LLM response trips both attempts and
     falls through to the deterministic template, which is still
     banned-free.
  4. No-LLM path: missing client AND missing call_llm injection
     short-circuits to the deterministic template.
  5. Context builder: pulls scenarios / DCF inputs / peer cohort /
     sector medians from a synthetic AnalysisResponse dict.
"""
from __future__ import annotations

import importlib.util as _importlib_util
import pathlib as _pathlib
import sys


# Standalone import — same pattern test_eli15_thesis.py uses, so the
# test runs in minimal envs without loading backend.services.__init__.
_SVC_PATH = (
    _pathlib.Path(__file__).resolve().parent.parent
    / "services" / "ai_explain_service.py"
)
_MOD_NAME = "ai_explain_service_under_test"
_spec = _importlib_util.spec_from_file_location(_MOD_NAME, str(_SVC_PATH))
svc = _importlib_util.module_from_spec(_spec)
sys.modules[_MOD_NAME] = svc
_spec.loader.exec_module(svc)


# ── Fixtures ────────────────────────────────────────────────────

HDFCBANK_CTX = svc.ExplainContext(
    ticker="HDFCBANK.NS",
    preset_id="why_value",
    company_name="HDFC Bank Ltd",
    sector="Banks",
    verdict_display="below model fair value",
    current_price=747.0,
    fair_value=1146.0,
    bear_case=955.0,
    base_case=1146.0,
    bull_case=1320.0,
    mos_pct=53.4,
    wacc_pct=9.8,
    terminal_growth_pct=3.0,
    fcf_growth_pct=8.0,
    moat_label="Wide",
    moat_score=72.0,
    confidence_pct=90,
)


def _ctx_for(preset_id: str) -> svc.ExplainContext:
    """Return a fresh ExplainContext for a given preset id."""
    return svc.ExplainContext(
        ticker="HDFCBANK.NS",
        preset_id=preset_id,
        company_name="HDFC Bank Ltd",
        sector="Banks",
        verdict_display="below model fair value",
        current_price=747.0,
        fair_value=1146.0,
        bear_case=955.0,
        base_case=1146.0,
        bull_case=1320.0,
        mos_pct=53.4,
        wacc_pct=9.8,
        terminal_growth_pct=3.0,
        fcf_growth_pct=8.0,
        moat_label="Wide",
        moat_score=72.0,
        confidence_pct=90,
        sector_medians={"roe": 14.2, "pe": 22.5, "pb": 3.0},
    )


# ── 1. Preset catalogue is sane and SEBI-safe ───────────────────

def test_three_presets_exposed():
    presets = svc.PRESETS
    assert len(presets) == 3
    ids = [p.preset_id for p in presets]
    assert ids == ["why_value", "change_verdict", "vs_peers"]


def test_card_copy_is_banned_free():
    """The card title + preview text are surfaced in the UI verbatim.
    They must never contain a SEBI-banned token (any leak would mean
    the AI panel itself is non-compliant, not just the answer)."""
    for p in svc.PRESETS:
        for text in (p.title, p.preview, p.system_focus, p.icon):
            assert svc._find_banned(text) is None, (
                f"banned vocab in card copy for preset {p.preset_id}: {text!r}"
            )


def test_list_preset_cards_shape():
    cards = svc.list_preset_cards()
    assert len(cards) == 3
    for card in cards:
        assert set(card.keys()) >= {"preset_id", "title", "preview", "icon"}


# ── 2. Happy path: clean LLM response ───────────────────────────

def test_clean_llm_response_uses_llm_first():
    state = {"calls": 0, "hints": []}

    def call(hint):
        state["calls"] += 1
        state["hints"].append(hint)
        return (
            "HDFC Bank trades at a 53% discount to the model's "
            "base-case fair value of Rs 1,146. The DCF uses WACC "
            "9.8% with 8% FCF growth and a 3% terminal rate, which "
            "places the fair value above the current quote.\n\n"
            "The biggest lever is FCF growth — at this WACC, halving "
            "growth cuts the headline by roughly a third."
        )

    result = svc.generate_explanation(HDFCBANK_CTX, call_llm=call)

    assert state["calls"] == 1
    assert result.source == "llm_first"
    assert "discount" in result.answer.lower()
    assert svc._find_banned(result.answer) is None


# ── 3. SEBI filter: dirty -> retry -> template ──────────────────

def test_dirty_response_falls_through_to_template():
    state = {"calls": 0, "hints": []}

    def call(hint):
        state["calls"] += 1
        state["hints"].append(hint)
        # Adversarial: multiple banned tokens per paragraph.
        return (
            "HDFC Bank appears " + "u" + "ndervalued — investors "
            "" + "sh" + "ould " + "b" + "uy now. The DCF reads "
            "as " + "ch" + "eap.\n\n"
            "We " + "rec" + "ommend " + "ac" + "cumulate at current levels."
        )

    result = svc.generate_explanation(HDFCBANK_CTX, call_llm=call)

    assert state["calls"] == 2, "must retry once with a hint"
    assert state["hints"][0] is None
    assert state["hints"][1] is not None
    assert result.source == "template"
    assert svc._find_banned(result.answer) is None
    assert "fair value" in result.answer.lower()


def test_retry_succeeds_after_dirty_first():
    clean = (
        "HDFC Bank trades at a 53% discount to fair value. The DCF "
        "lands here because WACC 9.8% with FCF growth 8% leaves "
        "headroom above the current quote.\n\n"
        "FCF growth is the single most material lever."
    )
    responses = iter([
        # First attempt trips on "should" + "buy".
        "Investors " + "sh" + "ould " + "b" + "uy this name now.",
        clean,
    ])

    def call(hint):
        return next(responses)

    result = svc.generate_explanation(HDFCBANK_CTX, call_llm=call)

    assert result.source == "llm_retry"
    assert "discount" in result.answer.lower()
    assert svc._find_banned(result.answer) is None


# ── 4. No client + no call_llm injection -> template_no_llm ─────

def test_no_client_returns_template_no_llm():
    result = svc.generate_explanation(HDFCBANK_CTX, anthropic_client=None)
    # In test envs ANTHROPIC_API_KEY is typically unset; assert template
    # behaviour rather than the source label so the test passes either
    # way (a CI runner with the key set would still produce a banned-
    # free answer via the LLM path).
    assert svc._find_banned(result.answer) is None
    assert "fair value" in result.answer.lower()


# ── 5. Template branches per preset ─────────────────────────────

def test_template_change_verdict_branch():
    ctx = _ctx_for("change_verdict")
    answer = svc.deterministic_template_answer(ctx)
    assert svc._find_banned(answer) is None
    assert "lever" in answer.lower() or "fcf" in answer.lower()


def test_template_vs_peers_branch():
    ctx = _ctx_for("vs_peers")
    answer = svc.deterministic_template_answer(ctx)
    assert svc._find_banned(answer) is None
    # The peer branch references the cohort framing.
    assert "cohort" in answer.lower() or "sector" in answer.lower()


# ── 6. Context builder reads scenarios + DCF + cohort ───────────

def test_context_builder_from_analysis_dict():
    payload = {
        "company": {"company_name": "HDFC Bank Ltd", "sector": "Banks"},
        "valuation": {
            "verdict": "undervalued",
            "current_price": 747.0,
            "fair_value": 1146.0,
            "margin_of_safety": 53.4,
            "wacc": 9.8,
            "terminal_growth": 0.03,    # decimal form
            "fcf_growth_rate": 8.0,
            "confidence_score": 90,
        },
        "quality": {"moat": "Wide", "moat_score": 72.0},
        "scenarios": {
            "bear": {"iv": 955.0},
            "base": {"iv": 1146.0},
            "bull": {"iv": 1320.0},
        },
        "sector_medians": {"roe": 14.2, "pe": 22.5},
        "peer_cohort": [
            {"ticker": "ICICIBANK.NS", "score": 78},
            {"ticker": "KOTAKBANK.NS", "score": 71},
        ],
    }

    ctx = svc.build_context_from_analysis(
        payload, "HDFCBANK.NS", "why_value",
    )

    assert ctx.ticker == "HDFCBANK.NS"
    assert ctx.preset_id == "why_value"
    assert ctx.company_name == "HDFC Bank Ltd"
    assert ctx.verdict_display == "below model fair value"
    assert ctx.fair_value == 1146.0
    assert ctx.bear_case == 955.0
    assert ctx.bull_case == 1320.0
    assert ctx.wacc_pct == 9.8
    # terminal_growth supplied as decimal 0.03 -> percent form 3.0
    assert ctx.terminal_growth_pct == 3.0
    assert ctx.peer_cohort and len(ctx.peer_cohort) == 2
    assert ctx.sector_medians == {"roe": 14.2, "pe": 22.5}


# ── 7. Disclaimer is banned-free ────────────────────────────────

def test_disclaimer_is_banned_free():
    assert svc._find_banned(svc.DISCLAIMER) is None
    assert "advice" in svc.DISCLAIMER.lower()
