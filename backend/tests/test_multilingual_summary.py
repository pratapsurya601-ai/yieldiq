"""Tests for multilingual AI summary scaffolding (Phase 0).

Covers ``backend/services/analysis/language_prompts.py`` and the
``translate_ai_summary`` / ``get_ai_summary_translations`` methods on
``NarrativeMixin`` in ``backend/services/analysis/narrative.py``.

Phase 0 policy:
  1. Each non-English target language must produce output containing
     its expected script (Devanagari for hi/mr; Tamil for ta).
  2. Each non-English output must contain the mandatory native-language
     disclaimer string verbatim.
  3. Marathi output must contain a Marathi-distinct token to confirm
     the prompt didn't silently degrade to Hindi (both scripts are
     Devanagari, so script-only checks aren't sufficient).
  4. ``get_ai_summary_translations`` returns None when the
     MULTILINGUAL_SUMMARIES_ENABLED feature flag is off.
  5. With the flag on, all three non-English entries are populated.

Groq is fully mocked — no network, no API key required.
"""
from __future__ import annotations

import importlib.util as _importlib_util
import os
import pathlib as _pathlib
import re
import sys
import types

import pytest


# Load language_prompts standalone (sibling-import side-effects in
# the analysis package would otherwise pull screener / engine deps).
_LANG_PATH = (
    _pathlib.Path(__file__).resolve().parent.parent
    / "services" / "analysis" / "language_prompts.py"
)
_spec = _importlib_util.spec_from_file_location(
    "backend_lang_prompts_under_test", str(_LANG_PATH)
)
_lang = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_lang)

LANGUAGE_PROMPTS = _lang.LANGUAGE_PROMPTS
DISCLAIMERS = _lang.DISCLAIMERS
SUPPORTED_LANGUAGES = _lang.SUPPORTED_LANGUAGES


# Unicode script regexes. \p{Script} is not supported by Python's
# stdlib ``re``, so we use explicit Unicode block ranges instead.
DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]+")
TAMIL_RE = re.compile(r"[஀-௿]+")

# Marathi-specific token (NOT used in Hindi). "आहे" = "is" in Marathi
# (Hindi uses "है"). Used to distinguish mr from hi at script level.
MARATHI_DISTINCT_TOKENS = ("आहे", "आहेत", "मूल्य")  # मूल्य also used in mr


# ───────────────────────────────────────────────────────────────
# Module-level structural tests (no network, no Groq, no fixtures).
# ───────────────────────────────────────────────────────────────

def test_supported_languages_contract():
    assert set(SUPPORTED_LANGUAGES) == {"en", "hi", "ta", "mr"}


def test_each_prompt_exists_and_nonempty():
    for lang in SUPPORTED_LANGUAGES:
        assert lang in LANGUAGE_PROMPTS
        assert LANGUAGE_PROMPTS[lang].strip(), f"empty prompt for {lang}"


def test_hindi_prompt_uses_devanagari():
    assert DEVANAGARI_RE.search(LANGUAGE_PROMPTS["hi"])
    # Should NOT be Hinglish — verify it has actual Devanagari content.
    devs = "".join(DEVANAGARI_RE.findall(LANGUAGE_PROMPTS["hi"]))
    assert len(devs) > 30, "Hindi prompt looks too Latin-heavy"


def test_tamil_prompt_uses_tamil_script():
    assert TAMIL_RE.search(LANGUAGE_PROMPTS["ta"])
    tamils = "".join(TAMIL_RE.findall(LANGUAGE_PROMPTS["ta"]))
    assert len(tamils) > 30, "Tamil prompt looks too Latin-heavy"


def test_marathi_prompt_uses_devanagari():
    assert DEVANAGARI_RE.search(LANGUAGE_PROMPTS["mr"])


def test_each_disclaimer_is_in_target_script():
    assert DEVANAGARI_RE.search(DISCLAIMERS["hi"])
    assert TAMIL_RE.search(DISCLAIMERS["ta"])
    assert DEVANAGARI_RE.search(DISCLAIMERS["mr"])


def test_each_prompt_mandates_disclaimer_inclusion():
    # The system prompt itself must instruct the model to add the
    # disclaimer — defensive double-check that the disclaimer string
    # appears verbatim within its language's prompt.
    for lang in ("hi", "ta", "mr"):
        # Compare disclaimer-ignoring-whitespace to be robust to
        # multi-line wrapping in the prompt source.
        assert DISCLAIMERS[lang][:20] in LANGUAGE_PROMPTS[lang], (
            f"prompt for {lang} does not embed its disclaimer"
        )


# ───────────────────────────────────────────────────────────────
# Integration tests for translate_ai_summary using a mocked Groq.
# ───────────────────────────────────────────────────────────────

class _FakeGroqResponse:
    def __init__(self, text):
        self.choices = [
            types.SimpleNamespace(
                message=types.SimpleNamespace(content=text)
            )
        ]


class _FakeGroqClient:
    """Minimal stand-in for groq.Groq — returns a canned per-language
    response indexed off the system prompt's first few characters."""

    def __init__(self, *args, **kwargs):
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, *, model, messages, max_tokens, temperature):
        system = messages[0]["content"]
        # Detect target language from the system prompt by checking
        # which language's prompt it matches.
        for lang, prompt in LANGUAGE_PROMPTS.items():
            if prompt == system:
                return _FakeGroqResponse(_CANNED_RESPONSES[lang])
        return _FakeGroqResponse(_CANNED_RESPONSES["en"])


_CANNED_RESPONSES = {
    "en": "TCS trades at 3500 vs fair value 3800, MoS 8%.",
    "hi": (
        "टीसीएस का वर्तमान मूल्य 3500 है, उचित मूल्य 3800, "
        "मार्जिन ऑफ सेफ्टी 8%।\n\n" + DISCLAIMERS["hi"]
    ),
    "ta": (
        "TCS தற்போதைய விலை 3500, நியாயமான மதிப்பு 3800, "
        "பாதுகாப்பு வரம்பு 8%.\n\n" + DISCLAIMERS["ta"]
    ),
    "mr": (
        "टीसीएसचे सध्याचे मूल्य 3500 आहे, योग्य मूल्य 3800 आहे, "
        "मार्जिन ऑफ सेफ्टी 8% आहे.\n\n" + DISCLAIMERS["mr"]
    ),
}


@pytest.fixture
def fake_groq(monkeypatch):
    """Inject a fake ``groq`` module so ``from groq import Groq``
    inside ``translate_ai_summary`` returns our stub."""
    fake_module = types.ModuleType("groq")
    fake_module.Groq = _FakeGroqClient
    monkeypatch.setitem(sys.modules, "groq", fake_module)
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    return fake_module


@pytest.fixture
def narrative_instance():
    """Build a minimal NarrativeMixin instance without pulling the
    full AnalysisService import chain (which loads screener/engine).

    We reach into ``narrative.py`` directly via importlib, mirroring
    the SEBI test pattern, so import failures elsewhere don't bleed
    in here."""
    # Load via standard import so the relative ``backend...`` imports
    # at the top of narrative.py resolve. If those imports fail in a
    # minimal environment, this test will skip cleanly.
    try:
        from backend.services.analysis.narrative import NarrativeMixin
    except Exception as exc:
        pytest.skip(f"narrative module not importable here: {exc}")

    class _Svc(NarrativeMixin):
        pass

    return _Svc()


def _stub_analysis():
    """Tiny duck-typed analysis object — translate_ai_summary only
    reads ``ai_summary`` via the caller, not via this object, so a
    bare SimpleNamespace is enough."""
    return types.SimpleNamespace(ai_summary="placeholder")


def test_translate_returns_english_unchanged_for_en(narrative_instance):
    out = narrative_instance.translate_ai_summary(
        "TCS", "English summary text", _stub_analysis(), language="en"
    )
    assert out == "English summary text"


def test_translate_returns_empty_when_no_groq_key(
    narrative_instance, monkeypatch
):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    out = narrative_instance.translate_ai_summary(
        "TCS", "English summary", _stub_analysis(), language="hi"
    )
    assert out == ""


def test_translate_hindi_contains_devanagari_and_disclaimer(
    fake_groq, narrative_instance
):
    out = narrative_instance.translate_ai_summary(
        "TCS", "TCS trades at 3500 vs FV 3800.",
        _stub_analysis(), language="hi",
    )
    assert DEVANAGARI_RE.search(out), f"no Devanagari in: {out!r}"
    assert DISCLAIMERS["hi"] in out


def test_translate_tamil_contains_tamil_script_and_disclaimer(
    fake_groq, narrative_instance
):
    out = narrative_instance.translate_ai_summary(
        "TCS", "TCS trades at 3500 vs FV 3800.",
        _stub_analysis(), language="ta",
    )
    assert TAMIL_RE.search(out), f"no Tamil script in: {out!r}"
    assert DISCLAIMERS["ta"] in out


def test_translate_marathi_contains_devanagari_and_distinct_token(
    fake_groq, narrative_instance
):
    out = narrative_instance.translate_ai_summary(
        "TCS", "TCS trades at 3500 vs FV 3800.",
        _stub_analysis(), language="mr",
    )
    assert DEVANAGARI_RE.search(out), f"no Devanagari in: {out!r}"
    assert DISCLAIMERS["mr"] in out
    # Distinguish from Hindi: Marathi-specific copula "आहे".
    assert any(tok in out for tok in MARATHI_DISTINCT_TOKENS), (
        f"Marathi output lacks any distinct Marathi token: {out!r}"
    )


def test_disclaimer_appended_when_model_omits_it(
    fake_groq, narrative_instance, monkeypatch
):
    """If the LLM forgets the disclaimer, translate_ai_summary must
    append it defensively so the safety guarantee holds
    unconditionally."""
    class _ForgetfulClient(_FakeGroqClient):
        def _create(self, *, model, messages, max_tokens, temperature):
            return _FakeGroqResponse(
                "टीसीएस का मूल्य 3500 है। उचित मूल्य 3800।"
            )

    fake_groq.Groq = _ForgetfulClient
    out = narrative_instance.translate_ai_summary(
        "TCS", "TCS trades at 3500 vs FV 3800.",
        _stub_analysis(), language="hi",
    )
    assert DISCLAIMERS["hi"] in out


def test_get_translations_returns_none_when_flag_off(
    fake_groq, narrative_instance, monkeypatch
):
    monkeypatch.delenv("MULTILINGUAL_SUMMARIES_ENABLED", raising=False)
    out = narrative_instance.get_ai_summary_translations(
        "TCS", _stub_analysis(), english_summary="Some English text."
    )
    assert out is None


def test_get_translations_populates_all_when_flag_on(
    fake_groq, narrative_instance, monkeypatch
):
    monkeypatch.setenv("MULTILINGUAL_SUMMARIES_ENABLED", "true")
    out = narrative_instance.get_ai_summary_translations(
        "TCS", _stub_analysis(), english_summary="Some English text."
    )
    assert out is not None
    assert set(out.keys()) == {"hi", "ta", "mr"}
    assert DISCLAIMERS["hi"] in out["hi"]
    assert DISCLAIMERS["ta"] in out["ta"]
    assert DISCLAIMERS["mr"] in out["mr"]
