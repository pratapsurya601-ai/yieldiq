# backend/services/analysis/language_prompts.py
# ═══════════════════════════════════════════════════════════════
# Multilingual AI summary prompt scaffolding (Phase 0 — review-gated).
#
# This module is intentionally additive and dark-launched. It defines
# the per-language system prompts and a translation helper that calls
# Groq with a target language. Nothing here is wired into the public
# read path until the MULTILINGUAL_SUMMARIES_ENABLED feature flag is
# flipped — and that flag will only be flipped after native-speaker
# review of the sample summaries committed under
# docs/multilingual_samples_for_review.md.
#
# Design notes:
#   - Prompts use formal/respectful financial register, not literal
#     translations of the English prompt. Specific term choices were
#     based on common Indian-English-financial-press conventions:
#       hi: "उचित मूल्य" for fair value; "मार्जिन ऑफ सेफ्टी"
#           transliterated (literal translation sounds clunky).
#       ta: formal "நீங்கள்" form; "நியாயமான மதிப்பு" for fair value.
#       mr: distinct Marathi vocabulary ("योग्य मूल्य"), Devanagari
#           script but NOT Hindi.
#   - Each non-English prompt mandates a target-language disclaimer
#     suffix: "AI-generated translation. English version is
#     authoritative. May contain errors."
#   - Output is post-filtered through the SEBI banned-word check the
#     same way the English path does — banned vocabulary is checked
#     against transliterations as well. (Phase 1: extend the SEBI
#     filter with per-language banned word lists.)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from typing import Literal

Language = Literal["en", "hi", "ta", "mr"]
SUPPORTED_LANGUAGES: tuple[Language, ...] = ("en", "hi", "ta", "mr")


# Native-language disclaimer rendered at the end of every translated
# summary. Verified by tests/test_multilingual_summary.py — if you
# edit these strings, update the test fixtures too.
DISCLAIMERS: dict[str, str] = {
    "en": (
        "AI-generated translation. English version is authoritative. "
        "May contain errors."
    ),
    "hi": (
        "एआई द्वारा उत्पन्न अनुवाद। अंग्रेज़ी संस्करण ही अधिकृत है। "
        "त्रुटियाँ संभव हैं।"
    ),
    "ta": (
        "செயற்கை நுண்ணறிவால் உருவாக்கப்பட்ட மொழிபெயர்ப்பு. "
        "ஆங்கில பதிப்பே அதிகாரபூர்வமானது. பிழைகள் இருக்கக்கூடும்."
    ),
    "mr": (
        "एआय-निर्मित भाषांतर. इंग्रजी आवृत्ती अधिकृत आहे. "
        "त्रुटी असू शकतात."
    ),
}


# Per-language system prompt. The English prompt is unchanged from
# narrative.py's existing register — it is included here only so the
# translation helper has a uniform interface.
LANGUAGE_PROMPTS: dict[str, str] = {
    "en": (
        "You are a SEBI-compliant financial metric describer. Output "
        "factual, numeric descriptions only. No verdict words, no "
        "subjective language. Reply in English."
    ),
    "hi": (
        "आप एक SEBI-अनुरूप वित्तीय मेट्रिक विवरणकर्ता हैं। केवल "
        "तथ्यात्मक, संख्यात्मक विवरण दें। कोई निर्णय-शब्द (जैसे "
        "खरीदें, बेचें, सस्ता, महँगा) न लिखें। शुद्ध, औपचारिक "
        "हिंदी का प्रयोग करें (Hinglish नहीं)। स्थापित वित्तीय "
        "शब्दावली का उपयोग करें: 'उचित मूल्य' (fair value), "
        "'मार्जिन ऑफ सेफ्टी' (transliterated), 'आरओई' (ROE)। "
        "अंत में यह अस्वीकरण जोड़ें: "
        "'एआई द्वारा उत्पन्न अनुवाद। अंग्रेज़ी संस्करण ही अधिकृत है। "
        "त्रुटियाँ संभव हैं।'"
    ),
    "ta": (
        "நீங்கள் ஒரு SEBI-இணக்கமான நிதி அளவுகோல் விளக்கர். "
        "உண்மையான, எண்ணியல் விவரங்களை மட்டும் வழங்கவும். தீர்ப்பு "
        "வார்த்தைகள் (வாங்கவும், விற்கவும், மலிவான, விலையுயர்ந்த) "
        "வேண்டாம். முறையான, மரியாதைக்குரிய தமிழ் ('நீங்கள்' வடிவம்) "
        "பயன்படுத்தவும். துல்லியமான நிதி சொற்கள்: 'நியாயமான மதிப்பு' "
        "(fair value), 'பாதுகாப்பு வரம்பு' (margin of safety), 'ROE' "
        "(ஆங்கிலத்தில் வைக்கவும்). இறுதியில் இந்த மறுப்பை சேர்க்கவும்: "
        "'செயற்கை நுண்ணறிவால் உருவாக்கப்பட்ட மொழிபெயர்ப்பு. "
        "ஆங்கில பதிப்பே அதிகாரபூர்வமானது. பிழைகள் இருக்கக்கூடும்.'"
    ),
    "mr": (
        "तुम्ही एक SEBI-अनुरूप आर्थिक मेट्रिक वर्णनकर्ता आहात. केवळ "
        "तथ्यात्मक, संख्यात्मक वर्णन द्या. निर्णय-शब्द (खरेदी, "
        "विक्री, स्वस्त, महाग) वापरू नका. औपचारिक मराठी (देवनागरी, "
        "हिंदीपेक्षा वेगळी शब्दसंपदा) वापरा. आर्थिक संज्ञा: 'योग्य "
        "मूल्य' (fair value), 'मार्जिन ऑफ सेफ्टी' (transliterated), "
        "'आरओई' (ROE). शेवटी हा अस्वीकरण जोडा: 'एआय-निर्मित "
        "भाषांतर. इंग्रजी आवृत्ती अधिकृत आहे. त्रुटी असू शकतात.'"
    ),
}


def is_supported(language: str) -> bool:
    return language in SUPPORTED_LANGUAGES


def get_system_prompt(language: str) -> str:
    """Return the system prompt for a target language, falling back
    to English if unknown. Never raises."""
    return LANGUAGE_PROMPTS.get(language, LANGUAGE_PROMPTS["en"])


def get_disclaimer(language: str) -> str:
    return DISCLAIMERS.get(language, DISCLAIMERS["en"])


def is_multilingual_enabled() -> bool:
    """Read MULTILINGUAL_SUMMARIES_ENABLED env var. Default OFF.

    Kept as a function (not a module-level constant) so tests can
    monkeypatch os.environ without an import-time race."""
    import os
    return os.environ.get(
        "MULTILINGUAL_SUMMARIES_ENABLED", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
