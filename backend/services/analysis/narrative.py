# backend/services/analysis/narrative.py
# ═══════════════════════════════════════════════════════════════
# Narrative + AI summary generation — Groq client plumbing + SEBI
# post-filter. Exposed as a mixin so AnalysisService (in service.py)
# can compose it in without touching the logic.
#
# SEBI hardening (PR-B, 2026-04): the old per-method banned-word
# regexes were duplicated and inconsistent. All policy now lives in
# ``backend/services/analysis/sebi_filter.py`` (banned vocabulary,
# prompt preamble, mandatory prefix, retry + fallback template).
# This module only assembles the data block and the stock-specific
# prompt, then hands off to ``sebi_filter.enforce(...)``.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from backend.models.responses import AnalysisResponse
from backend.services.analysis.sebi_filter import (
    SEBI_SYSTEM_PREAMBLE,
    deterministic_template,
    enforce,
)


def _build_fallback_ctx(ticker: str, analysis: AnalysisResponse) -> dict:
    """Extract the fields the deterministic template needs. Kept tiny
    and defensive — used both on the happy path (never hit) and on
    every failure path, so it must never raise."""
    try:
        v = analysis.valuation
    except Exception:
        v = None
    try:
        q = analysis.quality
    except Exception:
        q = None
    try:
        c = analysis.company
    except Exception:
        c = None

    def _g(obj, attr):
        try:
            return getattr(obj, attr, None)
        except Exception:
            return None

    return {
        "ticker": ticker,
        "company_name": _g(c, "company_name") or ticker,
        "current_price": _g(v, "current_price"),
        "fair_value": _g(v, "fair_value"),
        "mos_pct": _g(v, "margin_of_safety"),
        "piotroski": _g(q, "piotroski_score"),
        "moat": _g(q, "moat") or "unrated",
        "rev_cagr_3y": _g(q, "revenue_cagr_3y"),
        "roe": _g(q, "roe"),
    }


class NarrativeMixin:
    """Mixin providing narrative/AI summary methods for AnalysisService.

    Split out of analysis_service.py as part of the subpackage refactor.
    Kept as a mixin (rather than a free function) so existing
    ``self.generate_narrative_summary(...)`` / ``self.get_ai_summary(...)``
    / ``self.ensure_ai_summary(...)`` call sites on AnalysisService
    remain byte-identical."""

    # ── Narrative one-sentence summary (feat/ai-narrative-summary) ─
    def generate_narrative_summary(
        self,
        ticker: str,
        analysis: AnalysisResponse,
    ) -> str:
        """Return a 1-2-sentence narrative summary.

        SEBI policy (PR-B):
          - Prompt is led with the SEBI factual-description preamble
            and an explicit banned-word block.
          - LLM output is post-filtered with ``sebi_filter.enforce``:
            retry once on banned-word hit; deterministic template if
            retry also fails.
          - Output always starts with the mandatory
            "Model-generated description of metrics. Not investment
            advice." prefix.
          - Skipped (returns "") only when GROQ_API_KEY missing or
            when verdict is data_limited / unavailable / under_review
            (no useful numbers to describe).
        """
        import logging
        import os as _os
        _log = logging.getLogger("yieldiq.ai_summary")

        _groq_key = _os.environ.get("GROQ_API_KEY", "").strip()
        if not _groq_key:
            _log.info(
                f"[{ticker}] narrative summary skipped: GROQ_API_KEY not set"
            )
            return ""

        # Tier/verdict gate — don't fabricate a narrative when the
        # underlying analysis is degraded.
        try:
            _v = analysis.valuation
            _verdict = str(getattr(_v, "verdict", "") or "").lower()
            _bad_verdicts = {
                "data_limited",
                "unavailable",
                "under_review",
                "avoid",
                "",
            }
            if _verdict in _bad_verdicts:
                _log.info(
                    f"[{ticker}] narrative skipped: verdict={_verdict!r}"
                )
                return ""
            _fv = float(getattr(_v, "fair_value", 0) or 0)
            _cp = float(getattr(_v, "current_price", 0) or 0)
            if _fv <= 0 or _cp <= 0:
                _log.info(
                    f"[{ticker}] narrative skipped: fv={_fv} cp={_cp}"
                )
                return ""
        except Exception as exc:
            _log.warning(
                f"[{ticker}] narrative gate check failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return ""

        # Assemble the factual data block. No verdict phrase — the
        # LLM is told to describe numbers, not render a verdict.
        try:
            _q = analysis.quality
            _c = analysis.company

            _name = getattr(_c, "company_name", None) or ticker
            _sector = getattr(_c, "sector", None) or "unlisted sector"
            _mos = getattr(_v, "margin_of_safety", None)
            _roce = getattr(_q, "roce", None)
            _roe = getattr(_q, "roe", None)
            _moat = getattr(_q, "moat", None) or "unrated"
            _cagr5 = getattr(_q, "revenue_cagr_5y", None)
            _cagr3 = getattr(_q, "revenue_cagr_3y", None)
            _piotroski = getattr(_q, "piotroski_score", None)
            _de = getattr(_q, "de_ratio", None)
            _int_cov = getattr(_q, "interest_coverage", None)
            _score = getattr(_q, "yieldiq_score", None)

            def _fmt_pct(val, dp: int = 1) -> str:
                if val is None:
                    return "n/a"
                try:
                    return f"{float(val):.{dp}f}%"
                except Exception:
                    return "n/a"

            def _fmt_cagr_pct(val, dp: int = 1) -> str:
                if val is None:
                    return "n/a"
                try:
                    v = float(val)
                    if abs(v) >= 1.5:
                        return f"{v:.{dp}f}%"
                    return f"{v * 100:.{dp}f}%"
                except Exception:
                    return "n/a"

            def _fmt_num(val, dp: int = 2) -> str:
                if val is None:
                    return "n/a"
                try:
                    return f"{float(val):.{dp}f}"
                except Exception:
                    return "n/a"

            _data_block = (
                f"Ticker: {ticker} ({_name})\n"
                f"Sector: {_sector}\n"
                f"Fair Value: {_fmt_num(_fv)} | Current: {_fmt_num(_cp)} | "
                f"MoS: {_fmt_pct(_mos)}\n"
                f"ROCE: {_fmt_pct(_roce)} | ROE: {_fmt_pct(_roe)}\n"
                f"Moat label: {_moat}\n"
                f"Revenue CAGR 3y: {_fmt_cagr_pct(_cagr3)} | 5y: {_fmt_cagr_pct(_cagr5)}\n"
                f"Piotroski: {_piotroski if _piotroski is not None else 'n/a'}/9\n"
                f"D/E: {_fmt_num(_de)} | Interest coverage: {_fmt_num(_int_cov, 1)}x\n"
                f"YieldIQ score: {_score if _score is not None else 'n/a'}/100\n"
            )

            _base_user = (
                "Describe the following stock's metrics in 30-45 words, "
                "one or two sentences. Use ONLY numeric facts from the "
                "data block. Do NOT render a verdict. Do NOT use the "
                "words: appears, should, concern, strength, weakness, "
                "buy, sell, hold, outperform, underperform, expensive, "
                "cheap, undervalued, overvalued, attractive, poor, "
                "strong, weak. Reply with ONLY the description, no "
                "preamble, no markdown, no bullets, no disclaimer.\n\n"
                f"Data:\n{_data_block}\nDescription:"
            )
        except Exception as exc:
            _log.error(
                f"[{ticker}] narrative prompt build failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return ""

        def _call_llm(retry_hint):
            """Inner closure — makes the Groq call, returns cleaned text.

            ``retry_hint`` is None on first attempt, or the offending
            banned word on retry.
            """
            import re as _re

            user_prompt = _base_user
            if retry_hint:
                user_prompt = (
                    f"Your previous output contained subjective "
                    f"language (\"{retry_hint}\"). Regenerate using "
                    f"only factual metric descriptions.\n\n"
                    + _base_user
                )

            try:
                from groq import Groq as _Groq
                _client = _Groq(api_key=_groq_key)
                _resp = _client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": SEBI_SYSTEM_PREAMBLE},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=180,
                    temperature=0.2,
                )
                _raw = _resp.choices[0].message.content or ""
            except Exception as exc:
                _log.warning(
                    f"[{ticker}] narrative Groq call failed "
                    f"(retry={retry_hint!r}): "
                    f"{type(exc).__name__}: {exc}"
                )
                return ""

            s = _raw.strip().strip('"').strip("'").strip()
            for _pfx in (
                "Summary:", "summary:",
                "Description:", "description:",
                "Here is the summary:", "Here's the summary:",
                "Here is the description:", "Here's the description:",
            ):
                if s.startswith(_pfx):
                    s = s[len(_pfx):].strip()
            if len(s) > 400:
                s = s[:397].rstrip() + "..."
            return s

        _ctx = _build_fallback_ctx(ticker, analysis)
        _out = enforce(
            _call_llm,
            _ctx,
            logger=_log,
            ticker=ticker,
        )
        _log.info(
            f"[{ticker}] narrative ok ({len(_out)} chars) "
            f"(may be template-fallback)"
        )
        return _out

    def get_ai_summary(self, ticker: str, analysis: AnalysisResponse) -> str:
        """Generate a factual stock summary.

        SEBI policy (PR-B): identical filter/retry/fallback pipeline
        as ``generate_narrative_summary``. Length cap enforced at 320
        chars to leave room for the "Model-generated..." prefix within
        the public snippet's 400-char budget.

        Returns "" only when GROQ_API_KEY is missing. Otherwise always
        returns a SEBI-safe string (LLM or deterministic template).
        """
        import logging
        import os as _os
        _log = logging.getLogger("yieldiq.ai_summary")

        _groq_key = _os.environ.get("GROQ_API_KEY", "").strip()
        if not _groq_key:
            _log.warning(
                f"[{ticker}] AI summary skipped: GROQ_API_KEY is not set in "
                f"the environment."
            )
            return ""

        try:
            _v = analysis.valuation
            _q = analysis.quality
            _c = analysis.company
            _name = getattr(_c, "company_name", None) or ticker
            _sector = getattr(_c, "sector", None) or "unlisted sector"
            _mos = getattr(_v, "margin_of_safety", None)
            _fv = getattr(_v, "fair_value", None)
            _cp = getattr(_v, "current_price", None)
            _moat = getattr(_q, "moat", None) or "unrated"
            _roe = getattr(_q, "roe", None)
            _piotroski = getattr(_q, "piotroski_score", None)
            _score = getattr(_q, "yieldiq_score", None)

            def _fmt(val, dp=2):
                if val is None:
                    return "n/a"
                try:
                    return f"{float(val):.{dp}f}"
                except Exception:
                    return "n/a"

            _data_block = (
                f"Stock: {_name} ({ticker})\n"
                f"Sector: {_sector}\n"
                f"Current price: {_fmt(_cp)} | Fair value: {_fmt(_fv)}\n"
                f"MoS: {_fmt(_mos, 1)}%\n"
                f"Moat label: {_moat}\n"
                f"ROE: {_fmt(_roe, 1)}%\n"
                f"Piotroski: {_piotroski if _piotroski is not None else 'n/a'}/9\n"
                f"YieldIQ score: {_score if _score is not None else 'n/a'}/100\n"
            )

            _base_user = (
                "Describe this stock's metrics in ONE sentence (max 260 "
                "characters). Use ONLY numeric facts from the data "
                "block. Do NOT render a verdict. Do NOT use the words: "
                "appears, should, concern, strength, weakness, buy, "
                "sell, hold, outperform, underperform, expensive, "
                "cheap, undervalued, overvalued, attractive, poor, "
                "strong, weak. No preamble, no markdown, no "
                "disclaimer.\n\n"
                f"Data:\n{_data_block}\nDescription:"
            )
        except Exception as exc:
            _log.error(
                f"[{ticker}] AI summary prompt build failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return ""

        def _call_llm(retry_hint):
            user_prompt = _base_user
            if retry_hint:
                user_prompt = (
                    f"Your previous output contained subjective "
                    f"language (\"{retry_hint}\"). Regenerate using "
                    f"only factual metric descriptions.\n\n"
                    + _base_user
                )
            try:
                from groq import Groq as _Groq
                _client = _Groq(api_key=_groq_key)
                _resp = _client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": SEBI_SYSTEM_PREAMBLE},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=140,
                    temperature=0.15,
                )
                _raw = _resp.choices[0].message.content or ""
            except Exception as exc:
                _log.error(
                    f"[{ticker}] Groq call failed (retry={retry_hint!r}): "
                    f"{type(exc).__name__}: {exc}"
                )
                return ""

            import re as _re
            s = _raw.strip().strip('"').strip("'").strip()
            for _pfx in (
                "Summary:", "summary:",
                "Description:", "description:",
                "Here is the summary:", "Here's the summary:",
                "Here is the description:", "Here's the description:",
            ):
                if s.startswith(_pfx):
                    s = s[len(_pfx):].strip()
            # Collapse to one sentence.
            _split = _re.split(r"(?<=[.!?])\s+", s, maxsplit=1)
            if _split:
                s = _split[0].strip()
            if len(s) > 260:
                s = s[:257].rstrip() + "..."
            return s

        _ctx = _build_fallback_ctx(ticker, analysis)
        _out = enforce(
            _call_llm,
            _ctx,
            logger=_log,
            ticker=ticker,
        )
        _log.info(
            f"[{ticker}] AI summary ok ({len(_out)} chars) "
            f"(may be template-fallback)"
        )
        return _out

    def ensure_ai_summary(
        self,
        ticker: str,
        analysis: AnalysisResponse,
        *,
        generate_if_missing: bool = False,
    ) -> AnalysisResponse:
        """Attach a cached AI summary to ``analysis.ai_summary`` if one exists.

        Non-blocking helper for the /public/stock-summary hot path.
        Read order:

          1. If ``analysis.ai_summary`` is already populated -> return as-is.
          2. Check in-memory cache key ``ai_summary:{ticker}`` -> attach.
          3. If ``generate_if_missing=True``, call ``get_ai_summary``
             inline (synchronous LLM call -- warmup script only).

        By default, returns quickly with whatever it found in cache and
        lets the out-of-band warmup job populate the rest. Never raises.
        """
        import logging
        _log = logging.getLogger("yieldiq.ai_summary")
        try:
            if getattr(analysis, "ai_summary", None):
                return analysis

            from backend.services.cache_service import cache as _cache
            _cached = _cache.get(f"ai_summary:{ticker}")
            _cached_text = None
            if isinstance(_cached, dict):
                _cached_text = _cached.get("summary")
            elif isinstance(_cached, str):
                _cached_text = _cached
            if _cached_text:
                try:
                    analysis.ai_summary = _cached_text
                except Exception:
                    try:
                        analysis = analysis.model_copy(
                            update={"ai_summary": _cached_text}
                        )
                    except Exception:
                        pass
                return analysis

            if generate_if_missing:
                _text = self.get_ai_summary(ticker, analysis)
                if _text:
                    try:
                        analysis.ai_summary = _text
                    except Exception:
                        try:
                            analysis = analysis.model_copy(
                                update={"ai_summary": _text}
                            )
                        except Exception:
                            pass
                    try:
                        _cache.set(
                            f"ai_summary:{ticker}",
                            {"summary": _text},
                            ttl=86400,
                        )
                    except Exception as exc:
                        _log.warning(
                            f"[{ticker}] ai_summary cache set failed: {exc}"
                        )
            return analysis
        except Exception as exc:
            _log.warning(
                f"[{ticker}] ensure_ai_summary failed, returning analysis "
                f"unchanged: {type(exc).__name__}: {exc}"
            )
            return analysis
