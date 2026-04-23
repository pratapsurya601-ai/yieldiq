"""SEBI compliance tests for the AI summary post-filter.

Covers ``backend/services/analysis/sebi_filter.py`` directly and,
through it, ``NarrativeMixin.get_ai_summary`` /
``NarrativeMixin.generate_narrative_summary`` in
``backend/services/analysis/narrative.py``.

Policy under test (PR-B, 2026-04):
  1. Banned words (case-insensitive, word-boundary) must never appear
     in the final output.
  2. Every output must begin with the mandatory
     "Model-generated description of metrics. Not investment advice."
     prefix.
  3. If the LLM returns SEBI-unsafe text, the filter must retry once
     with a stricter re-prompt. If the retry is still unsafe, the
     deterministic template fallback must be used. The template is
     guaranteed banned-free by construction.
  4. A clean LLM response passes through untouched (modulo the
     mandatory prefix).

LLM calls are intercepted via a fake callable — no Groq dependency,
no network.
"""
from __future__ import annotations

import os
import pytest

# Import ``sebi_filter`` by file path. The parent package
# (``backend.services.analysis``) has an ``__init__`` that eagerly
# imports sibling modules (``utils``, ``constants``, etc.) which in
# turn pull in ``screener.moat_engine`` — a transitive import chain
# that is irrelevant to the SEBI filter and brittle under minimal
# test environments. ``sebi_filter`` itself is import-neutral (stdlib
# only), so we load it standalone via ``importlib.util``.
import importlib.util as _importlib_util
import pathlib as _pathlib

_SEBI_FILTER_PATH = (
    _pathlib.Path(__file__).resolve().parent.parent
    / "services" / "analysis" / "sebi_filter.py"
)
_spec = _importlib_util.spec_from_file_location(
    "backend_sebi_filter_under_test", str(_SEBI_FILTER_PATH)
)
_sebi_filter = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_sebi_filter)

BANNED_WORDS = _sebi_filter.BANNED_WORDS
SEBI_PREFIX = _sebi_filter.SEBI_PREFIX
deterministic_template = _sebi_filter.deterministic_template
enforce = _sebi_filter.enforce
find_banned = _sebi_filter.find_banned


# 10 fixture tickers spanning sectors. Each tuple carries enough
# metric values for the deterministic template to render cleanly.
FIXTURE_TICKERS: list[dict] = [
    {
        "ticker": "TITAN",
        "company_name": "Titan Company Ltd",
        "current_price": 3520.0,
        "fair_value": 2890.0,
        "mos_pct": -21.8,
        "piotroski": 7,
        "moat": "Wide",
        "rev_cagr_3y": 0.215,
        "roe": 32.1,
    },
    {
        "ticker": "RELIANCE",
        "company_name": "Reliance Industries Ltd",
        "current_price": 1342.0,
        "fair_value": 879.0,
        "mos_pct": -35.0,
        "piotroski": 6,
        "moat": "Narrow",
        "rev_cagr_3y": 0.115,
        "roe": 9.2,
    },
    {
        "ticker": "HDFCBANK",
        "company_name": "HDFC Bank Ltd",
        "current_price": 1705.0,
        "fair_value": 1980.0,
        "mos_pct": 13.9,
        "piotroski": 6,
        "moat": "Narrow",
        "rev_cagr_3y": 0.182,
        "roe": 16.8,
    },
    {
        "ticker": "TCS",
        "company_name": "Tata Consultancy Services",
        "current_price": 3890.0,
        "fair_value": 4120.0,
        "mos_pct": 5.6,
        "piotroski": 8,
        "moat": "Wide",
        "rev_cagr_3y": 0.094,
        "roe": 54.9,
    },
    {
        "ticker": "INFY",
        "company_name": "Infosys Ltd",
        "current_price": 1580.0,
        "fair_value": 1650.0,
        "mos_pct": 4.2,
        "piotroski": 7,
        "moat": "Wide",
        "rev_cagr_3y": 0.088,
        "roe": 31.2,
    },
    {
        "ticker": "HINDUNILVR",
        "company_name": "Hindustan Unilever Ltd",
        "current_price": 2350.0,
        "fair_value": 2110.0,
        "mos_pct": -10.2,
        "piotroski": 6,
        "moat": "Wide",
        "rev_cagr_3y": 0.061,
        "roe": 18.9,
    },
    {
        "ticker": "SBIN",
        "company_name": "State Bank of India",
        "current_price": 805.0,
        "fair_value": 940.0,
        "mos_pct": 14.3,
        "piotroski": 5,
        "moat": "Narrow",
        "rev_cagr_3y": 0.128,
        "roe": 18.1,
    },
    {
        "ticker": "BAJFINANCE",
        "company_name": "Bajaj Finance Ltd",
        "current_price": 7420.0,
        "fair_value": 6980.0,
        "mos_pct": -6.3,
        "piotroski": 7,
        "moat": "Narrow",
        "rev_cagr_3y": 0.241,
        "roe": 22.7,
    },
    {
        "ticker": "ASIANPAINT",
        "company_name": "Asian Paints Ltd",
        "current_price": 2440.0,
        "fair_value": 2160.0,
        "mos_pct": -13.0,
        "piotroski": 6,
        "moat": "Wide",
        "rev_cagr_3y": 0.112,
        "roe": 27.4,
    },
    {
        "ticker": "ITC",
        "company_name": "ITC Ltd",
        "current_price": 438.0,
        "fair_value": 505.0,
        "mos_pct": 13.3,
        "piotroski": 8,
        "moat": "Wide",
        "rev_cagr_3y": 0.079,
        "roe": 28.6,
    },
]


# ── find_banned: vocabulary sanity ──────────────────────────────

@pytest.mark.parametrize("word", list(BANNED_WORDS))
def test_banned_word_detected(word: str):
    """Every banned word must be caught by the regex, regardless of case."""
    # Lowercase
    assert find_banned(f"The stock {word} today.") == word
    # Uppercase
    assert find_banned(f"The stock {word.upper()} today.") is not None
    # Capitalized
    assert find_banned(f"{word.capitalize()} is notable.") is not None


def test_banned_word_boundary_not_triggered_inside_longer_word():
    """\\b boundary — 'strengthen' should NOT match 'strength' alone.

    This guards against the filter being so aggressive that it flags
    benign neighboring tokens. The test documents the intended
    word-boundary semantics.
    """
    # "strong" is a banned word — "strongly" contains it on \b left
    # but not \b right, so it should NOT match. Similarly "weakly".
    assert find_banned("price moves strongly correlated") is None
    # But the bare word must match.
    assert find_banned("strong fundamentals") == "strong"


def test_clean_text_has_no_banned_word():
    clean = (
        "Trades at 1342 vs model fair value of 879, a gap of 35%. "
        "Revenue CAGR 11.5%. Piotroski 6/9."
    )
    assert find_banned(clean) is None


# ── deterministic_template: always SEBI-safe ────────────────────

@pytest.mark.parametrize("fixture", FIXTURE_TICKERS, ids=lambda f: f["ticker"])
def test_template_is_banned_free(fixture: dict):
    """Deterministic template output must never contain a banned word."""
    out = deterministic_template(fixture)
    assert find_banned(out) is None, (
        f"Template for {fixture['ticker']} contains banned word: {out!r}"
    )


@pytest.mark.parametrize("fixture", FIXTURE_TICKERS, ids=lambda f: f["ticker"])
def test_template_has_prefix(fixture: dict):
    out = deterministic_template(fixture)
    assert out.startswith(SEBI_PREFIX), (
        f"Template for {fixture['ticker']} missing prefix: {out!r}"
    )


def test_template_strips_banned_moat_label():
    """Defensive: if an upstream 'moat' label literally spells a
    banned word (e.g. 'Strong'), the template substitutes
    'unrated' rather than emit the banned token."""
    ctx = {
        "ticker": "TEST",
        "company_name": "Test Co",
        "current_price": 100.0,
        "fair_value": 110.0,
        "mos_pct": 10.0,
        "piotroski": 5,
        "moat": "Strong",  # would leak "strong" into output
        "rev_cagr_3y": 0.10,
        "roe": 15.0,
    }
    out = deterministic_template(ctx)
    assert find_banned(out) is None


# ── enforce: retry + fallback orchestration ─────────────────────

def _make_call_counter():
    """Helper: returns (closure, state_dict). state_dict tracks how
    many times the closure has been invoked and with what retry hint."""
    state = {"calls": 0, "hints": []}

    def track(responses: list[str]):
        def _call(hint):
            state["calls"] += 1
            state["hints"].append(hint)
            idx = state["calls"] - 1
            if idx < len(responses):
                return responses[idx]
            return ""

        return _call

    return state, track


@pytest.mark.parametrize("fixture", FIXTURE_TICKERS, ids=lambda f: f["ticker"])
def test_dirty_llm_response_falls_through_to_template(fixture: dict):
    """LLM returns banned-word output twice -> fall back to template."""
    state, track = _make_call_counter()
    dirty_responses = [
        # First attempt — a close paraphrase of the real-world offender.
        (
            f"{fixture['company_name']} appears overvalued by "
            f"{abs(fixture['mos_pct']):.1f}%, with a standout strength "
            f"in revenue CAGR but a concern around its narrow moat."
        ),
        # Retry — still dirty (simulates a stubborn model).
        (
            f"The stock looks expensive and we would not recommend a buy."
        ),
    ]
    call = track(dirty_responses)

    out = enforce(call, fixture, ticker=fixture["ticker"])

    # Retry happened.
    assert state["calls"] == 2
    assert state["hints"][0] is None
    assert state["hints"][1] is not None, (
        "Retry must pass a banned-word hint to the caller"
    )

    # Final output is banned-free and carries the mandatory prefix.
    assert out.startswith(SEBI_PREFIX)
    assert find_banned(out) is None, f"Banned word leaked: {out!r}"


@pytest.mark.parametrize("fixture", FIXTURE_TICKERS, ids=lambda f: f["ticker"])
def test_clean_llm_response_passes_through(fixture: dict):
    """A clean LLM response is used verbatim (modulo the prefix)."""
    state, track = _make_call_counter()
    clean_body = (
        f"{fixture['company_name']} trades at "
        f"{fixture['current_price']:.2f} vs model fair value of "
        f"{fixture['fair_value']:.2f}. Piotroski "
        f"{fixture['piotroski']}/9. Moat label: {fixture['moat']}."
    )
    # Pre-flight: the clean response itself must be banned-free, or
    # the test is invalid. "Narrow" / "Wide" are not in BANNED_WORDS.
    assert find_banned(clean_body) is None
    call = track([clean_body])

    out = enforce(call, fixture, ticker=fixture["ticker"])

    # Only one LLM call — no retry needed on clean text.
    assert state["calls"] == 1
    assert out.startswith(SEBI_PREFIX)
    assert clean_body in out
    assert find_banned(out) is None


def test_retry_succeeds_after_dirty_first_attempt():
    """First output dirty, retry clean -> use retry, do not fall
    through to template."""
    fixture = FIXTURE_TICKERS[0]
    state, track = _make_call_counter()
    call = track([
        "The stock appears overvalued.",  # dirty
        (
            f"{fixture['company_name']} trades at "
            f"{fixture['current_price']:.2f} vs model fair value "
            f"{fixture['fair_value']:.2f}."
        ),  # clean
    ])

    out = enforce(call, fixture, ticker=fixture["ticker"])

    assert state["calls"] == 2
    assert out.startswith(SEBI_PREFIX)
    assert find_banned(out) is None
    # Evidence this is the retry output, not the template.
    assert "trades at" in out


def test_llm_exception_falls_back_to_template():
    """If both LLM calls raise, the template must still be returned."""
    fixture = FIXTURE_TICKERS[1]  # RELIANCE

    def _boom(hint):
        raise RuntimeError("groq down")

    out = enforce(_boom, fixture, ticker=fixture["ticker"])

    assert out.startswith(SEBI_PREFIX)
    assert find_banned(out) is None
    # Template signature: includes "Piotroski F-score:"
    assert "Piotroski F-score" in out


def test_empty_llm_response_falls_back_to_template():
    """Empty LLM response on both tries -> template."""
    fixture = FIXTURE_TICKERS[2]  # HDFCBANK
    state, track = _make_call_counter()
    call = track(["", ""])

    out = enforce(call, fixture, ticker=fixture["ticker"])

    # Both attempts happened.
    assert state["calls"] == 2
    assert out.startswith(SEBI_PREFIX)
    assert find_banned(out) is None
    assert "Piotroski F-score" in out


# ── End-to-end: narrative.py get_ai_summary honors the filter ──

# ── End-to-end integration: gated by the analysis package init.
# The package ``backend.services.analysis`` has a transitive import
# chain into ``screener.moat_engine`` that some minimal CI envs
# cannot satisfy (no numpy, or utils-name-shadowing from the
# dashboard/ dir). When those deps are unavailable we skip these
# two tests with a clear reason — the unit tests above already
# exercise the filter logic exhaustively.

def _narrative_import_ok() -> bool:
    try:
        import backend.services.analysis.narrative  # noqa: F401
        return True
    except Exception:
        return False


pytestmark_integration = pytest.mark.skipif(
    not _narrative_import_ok(),
    reason=(
        "backend.services.analysis.narrative unavailable in this env "
        "(pre-existing transitive import issue — unrelated to PR)"
    ),
)


@pytestmark_integration
def test_get_ai_summary_integration_dirty_fallback(monkeypatch):
    """Full ``NarrativeMixin.get_ai_summary`` path with Groq stubbed.

    We monkey-patch the ``groq.Groq`` client so both attempts return a
    banned-word response, and verify the final output is the
    deterministic template (not the dirty LLM text).
    """
    # Ensure the env gate passes.
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")

    from backend.models.responses import (
        AnalysisResponse,
        CompanyInfo,
        InsightCards,
        QualityOutput,
        ValuationOutput,
    )
    from backend.services.analysis.narrative import NarrativeMixin

    # Build a minimal AnalysisResponse.
    fixture = FIXTURE_TICKERS[0]  # TITAN
    analysis = AnalysisResponse(
        ticker=fixture["ticker"],
        company=CompanyInfo(
            ticker=fixture["ticker"],
            company_name=fixture["company_name"],
            sector="Consumer Discretionary",
        ),
        valuation=ValuationOutput(
            fair_value=fixture["fair_value"],
            current_price=fixture["current_price"],
            margin_of_safety=fixture["mos_pct"],
            verdict="overvalued",
        ),
        quality=QualityOutput(
            piotroski_score=fixture["piotroski"],
            moat=fixture["moat"],
            revenue_cagr_3y=fixture["rev_cagr_3y"],
            roe=fixture["roe"],
        ),
        insights=InsightCards(),
    )

    # Stub the Groq client. narrative.py does `from groq import Groq`
    # inside the closure, so we register a synthetic module.
    import sys
    import types

    class _FakeChoice:
        def __init__(self, text: str):
            self.message = types.SimpleNamespace(content=text)

    class _FakeResp:
        def __init__(self, text: str):
            self.choices = [_FakeChoice(text)]

    dirty_outputs = iter([
        (
            "Titan appears overvalued by 21.8%, with a standout "
            "strength in revenue growth but a concern around its "
            "premium valuation."
        ),
        "This one looks expensive — we would not recommend a buy.",
    ])

    class _FakeClient:
        def __init__(self, api_key=None):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            return _FakeResp(next(dirty_outputs))

    fake_groq = types.ModuleType("groq")
    fake_groq.Groq = _FakeClient
    monkeypatch.setitem(sys.modules, "groq", fake_groq)

    class _Svc(NarrativeMixin):
        pass

    out = _Svc().get_ai_summary(fixture["ticker"], analysis)

    assert out, "get_ai_summary must not return empty when key is set"
    assert out.startswith(SEBI_PREFIX), (
        f"Missing SEBI prefix: {out!r}"
    )
    assert find_banned(out) is None, f"Banned word leaked: {out!r}"
    # Template-signature check — confirms fall-through, not echo.
    assert "Piotroski F-score" in out


@pytestmark_integration
def test_get_ai_summary_integration_clean_passthrough(monkeypatch):
    """Clean LLM output should be used (plus the mandatory prefix)."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")

    from backend.models.responses import (
        AnalysisResponse,
        CompanyInfo,
        InsightCards,
        QualityOutput,
        ValuationOutput,
    )
    from backend.services.analysis.narrative import NarrativeMixin

    fixture = FIXTURE_TICKERS[3]  # TCS
    analysis = AnalysisResponse(
        ticker=fixture["ticker"],
        company=CompanyInfo(
            ticker=fixture["ticker"],
            company_name=fixture["company_name"],
            sector="IT Services",
        ),
        valuation=ValuationOutput(
            fair_value=fixture["fair_value"],
            current_price=fixture["current_price"],
            margin_of_safety=fixture["mos_pct"],
            verdict="fairly_valued",
        ),
        quality=QualityOutput(
            piotroski_score=fixture["piotroski"],
            moat=fixture["moat"],
            revenue_cagr_3y=fixture["rev_cagr_3y"],
            roe=fixture["roe"],
        ),
        insights=InsightCards(),
    )

    clean_body = (
        f"{fixture['company_name']} trades at 3890 vs model fair "
        f"value 4120, with revenue CAGR of 9.4%."
    )
    # Sanity: the seed body is itself banned-free.
    assert find_banned(clean_body) is None

    import sys
    import types

    class _FakeChoice:
        def __init__(self, text: str):
            self.message = types.SimpleNamespace(content=text)

    class _FakeResp:
        def __init__(self, text: str):
            self.choices = [_FakeChoice(text)]

    class _FakeClient:
        def __init__(self, api_key=None):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            return _FakeResp(clean_body)

    fake_groq = types.ModuleType("groq")
    fake_groq.Groq = _FakeClient
    monkeypatch.setitem(sys.modules, "groq", fake_groq)

    class _Svc(NarrativeMixin):
        pass

    out = _Svc().get_ai_summary(fixture["ticker"], analysis)

    assert out.startswith(SEBI_PREFIX)
    assert find_banned(out) is None
    # The clean body (or its first sentence) should appear.
    assert "trades at 3890" in out


@pytestmark_integration
def test_missing_groq_key_returns_empty(monkeypatch):
    """No env key -> feature silently no-ops (returns "")."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    from backend.models.responses import (
        AnalysisResponse,
        CompanyInfo,
        InsightCards,
        QualityOutput,
        ValuationOutput,
    )
    from backend.services.analysis.narrative import NarrativeMixin

    analysis = AnalysisResponse(
        ticker="TCS",
        company=CompanyInfo(ticker="TCS", company_name="TCS"),
        valuation=ValuationOutput(
            fair_value=4120.0,
            current_price=3890.0,
            margin_of_safety=5.6,
            verdict="fairly_valued",
        ),
        quality=QualityOutput(),
        insights=InsightCards(),
    )

    class _Svc(NarrativeMixin):
        pass

    assert _Svc().get_ai_summary("TCS", analysis) == ""
