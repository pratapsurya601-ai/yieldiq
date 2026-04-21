# backend/services/analysis/narrative.py
# ═══════════════════════════════════════════════════════════════
# Narrative + AI summary generation — Groq client plumbing + SEBI
# post-filter. Exposed as a mixin so AnalysisService (in service.py)
# can compose it in without touching the logic. Every method is
# copied verbatim from the historical analysis_service.py monolith.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from backend.models.responses import AnalysisResponse


class NarrativeMixin:
    """Mixin providing narrative/AI summary methods for AnalysisService.

    Split out of analysis_service.py as part of the subpackage refactor.
    Kept as a mixin (rather than a free function) so existing
    ``self.generate_narrative_summary(...)`` / ``self.get_ai_summary(...)``
    / ``self.ensure_ai_summary(...)`` call sites on AnalysisService
    remain byte-identical."""

    # ── Narrative one-sentence summary (feat/ai-narrative-summary) ─
    # Richer variant of ``get_ai_summary`` that is cached alongside
    # the analysis payload and rendered ABOVE the Prism hex. Target
    # output: "TCS appears undervalued by 32.7%. Exceptional 54.9%
    # ROCE, wide moat in IT services, but growth is slowing vs 5-year
    # average." — one or two sentences, ~30-45 words, mentions
    # verdict, one standout strength, one concern.
    #
    # Separate from ``get_ai_summary`` (which is a narrower factual
    # descriptor used by /public/stock-summary snippet feeds) so we
    # can keep both endpoints stable while this one evolves.
    def generate_narrative_summary(
        self,
        ticker: str,
        analysis: AnalysisResponse,
    ) -> str:
        """Return a 1-2-sentence narrative summary. Empty string on failure.

        Constraints:
          - Groq-only (llama-3.3-70b-versatile) — matches the rest of
            the codebase (prism_narration_service, get_ai_summary).
          - SEBI-safe: no "buy", "sell", "hold", "accumulate", "recommend",
            "target price". Post-filter rejects any output that contains
            those words and returns "" instead.
          - Skipped when verdict is data_limited / unavailable / avoid /
            under_review (no useful story to tell, and speculative
            prose would mislead).
          - Skipped when GROQ_API_KEY is missing. Feature silently
            no-ops; the UI hides the component when the field is empty.
          - Never raises. Returns "" on any error path.

        Cost: ~1 call per cold compute. At 500 flagship tickers
        computed once per 24h, this is ≤500 Groq calls/day. At
        llama-3.3-70b-versatile rates (free tier up to 30 RPM /
        ~14,400 RPD) this is well inside quota.
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

        # Build the prompt. Include growth + quality + moat so the
        # LLM has enough to pick a real strength + concern.
        try:
            _q = analysis.quality
            _c = analysis.company

            _name = getattr(_c, "company_name", None) or ticker
            _sector = getattr(_c, "sector", None) or "unlisted sector"
            _mos = getattr(_v, "margin_of_safety", None)
            _roce = getattr(_q, "roce", None)
            _roe = getattr(_q, "roe", None)
            _moat = getattr(_q, "moat", None) or "Unrated"
            _cagr5 = getattr(_q, "revenue_cagr_5y", None)
            _cagr3 = getattr(_q, "revenue_cagr_3y", None)
            _piotroski = getattr(_q, "piotroski_score", None)
            _de = getattr(_q, "de_ratio", None)
            _int_cov = getattr(_q, "interest_coverage", None)
            _score = getattr(_q, "yieldiq_score", None)

            # Direction phrasing — factual, neutral.
            if _mos is None:
                _direction = "trades near its model fair value"
            elif _mos >= 15:
                _direction = f"appears undervalued by {abs(_mos):.1f}%"
            elif _mos >= -15:
                _direction = "trades close to its model fair value"
            else:
                _direction = f"appears overvalued by {abs(_mos):.1f}%"

            def _fmt_pct(val, dp: int = 1) -> str:
                if val is None:
                    return "n/a"
                try:
                    return f"{float(val):.{dp}f}%"
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
                f"Verdict phrase: '{_direction}'\n"
                f"ROCE: {_fmt_pct(_roce)} | ROE: {_fmt_pct(_roe)}\n"
                f"Moat: {_moat}\n"
                f"Revenue CAGR 3y: {_fmt_pct(_cagr3)} | 5y: {_fmt_pct(_cagr5)}\n"
                f"Piotroski: {_piotroski if _piotroski is not None else 'n/a'}/9\n"
                f"D/E: {_fmt_num(_de)} | Interest coverage: {_fmt_num(_int_cov, 1)}x\n"
                f"YieldIQ score: {_score if _score is not None else 'n/a'}/100\n"
            )

            _system = (
                "You are a concise Indian equity analyst. Write a single "
                "plain-English summary of the analysis below for a retail "
                "investor. Mention the verdict (undervalued/overvalued or "
                "fairly valued), ONE standout strength, and ONE concern "
                "or watch-item. Be specific — use the numbers given. "
                "Length: 30-45 words, one or two sentences max. "
                "Neutral tone: do NOT use the words buy, sell, hold, "
                "accumulate, recommend, or target price. Do NOT include "
                "a disclaimer (rendered separately). Reply with ONLY "
                "the sentence(s), no preamble, no markdown, no bullets."
            )
            _user = f"Data:\n{_data_block}\nSummary:"
        except Exception as exc:
            _log.error(
                f"[{ticker}] narrative prompt build failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return ""

        # SEBI post-filter — identical policy to prism_narration_service.
        import re as _re
        _FORBIDDEN = _re.compile(
            r"\b(buy|sell|hold|accumulate|recommend|recommendation|"
            r"target\s+price|price\s+target|should\s+(buy|sell|hold))\b",
            _re.IGNORECASE,
        )

        def _clean(text: str) -> str:
            if not text:
                return ""
            s = text.strip().strip('"').strip("'").strip()
            for _pfx in (
                "Summary:", "summary:",
                "Here is the summary:", "Here's the summary:",
                "Here is a summary:", "Here's a summary:",
            ):
                if s.startswith(_pfx):
                    s = s[len(_pfx):].strip()
            # Hard length cap to protect the UI layout.
            if len(s) > 400:
                s = s[:397].rstrip() + "..."
            return s

        try:
            from groq import Groq as _Groq
            _client = _Groq(api_key=_groq_key)
            _resp = _client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _system},
                    {"role": "user", "content": _user},
                ],
                max_tokens=180,
                temperature=0.3,
            )
        except Exception as exc:
            _log.warning(
                f"[{ticker}] narrative Groq call failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return ""

        try:
            _raw = _resp.choices[0].message.content or ""
        except Exception:
            return ""

        _out = _clean(_raw)
        if not _out:
            _log.warning(f"[{ticker}] narrative Groq returned empty text")
            return ""
        if _FORBIDDEN.search(_out):
            _log.info(
                f"[{ticker}] narrative rejected by SEBI filter: {_out[:80]!r}"
            )
            return ""
        _log.info(
            f"[{ticker}] narrative ok ({len(_out)} chars) via Groq"
        )
        return _out

    def get_ai_summary(self, ticker: str, analysis: AnalysisResponse) -> str:
        """Generate a ONE-sentence factual stock summary (<=280 chars).

        Previous implementation (pre FIX-AI-SUMMARY-FLAGSHIPS) imported
        ``dashboard.utils.data_helpers.generate_ai_summary`` and called it
        with 6 positional args. That function actually requires 13
        positional args, so every call raised ``TypeError`` and the
        exception handler returned "" -- which is why every flagship had
        ``ai_summary_snippet: null`` on the public /stock-summary endpoint.

        This replacement:
          - Builds its own compact prompt from the canonical AnalysisResponse
            so output is always consistent with the rest of the payload.
          - Generates EXACTLY ONE sentence (<=280 chars). The public
            endpoint truncates ai_summary to 200 chars for the snippet,
            so a 3-paragraph answer was always going to be clipped.
          - Is SEBI-compliant: no "buy" / "sell" / "hold", uses
            "appears undervalued/overvalued by the model" framing.
          - Uses Groq (llama-3.3-70b-versatile) as the single provider.
            Returns "" on any failure so the UI degrades gracefully
            (empty slot, never 500).

        ENV VAR REQUIREMENT (prod): GROQ_API_KEY must be set on Railway.
        If missing, the method logs a WARNING and returns "" -- the
        feature silently no-ops rather than breaking the endpoint.
        """
        import logging
        import os as _os
        _log = logging.getLogger("yieldiq.ai_summary")

        _groq_key = _os.environ.get("GROQ_API_KEY", "").strip()
        if not _groq_key:
            _log.warning(
                f"[{ticker}] AI summary skipped: GROQ_API_KEY is not set in "
                f"the environment. Add it on Railway to enable "
                f"ai_summary_snippet on public stock-summary responses."
            )
            return ""

        # Build a compact, factual prompt off the canonical AnalysisResponse.
        try:
            _v = analysis.valuation
            _q = analysis.quality
            _c = analysis.company
            _mos = getattr(_v, "margin_of_safety", None)
            _moat = getattr(_q, "moat", None) or "unrated"
            _sector = getattr(_c, "sector", None) or "unlisted sector"
            _name = getattr(_c, "company_name", None) or ticker
            _score = getattr(_q, "yieldiq_score", None)
            _grade = getattr(_q, "grade", None)
            # Direction phrase -- factual, no buy/sell.
            if _mos is None:
                _direction = "trading near its model fair value"
            elif _mos >= 15:
                _direction = "appears undervalued by the model"
            elif _mos >= 0:
                _direction = "trading close to its model fair value"
            elif _mos >= -15:
                _direction = "trading slightly above its model fair value"
            else:
                _direction = "appears overvalued by the model"

            _mos_line = (
                f"Margin of safety vs model fair value: {_mos:.1f}%\n"
                if _mos is not None else "Margin of safety: unavailable\n"
            )
            _score_line = (
                f"YieldIQ score: {_score}/100 (grade {_grade or 'unrated'}).\n"
                if _score is not None else ""
            )
            _prompt = (
                "You are a senior equity analyst writing for a retail investor. "
                "Write EXACTLY ONE factual sentence (max 280 characters) "
                "describing this stock. Be balanced and specific. "
                "Use neutral language. Do NOT say 'buy', 'sell', or 'hold'. "
                "Do NOT include a disclaimer (the UI renders one separately).\n\n"
                f"Stock: {_name} ({ticker})\n"
                f"Sector: {_sector}\n"
                f"Economic moat: {_moat}\n"
                f"{_mos_line}"
                f"Model framing you may use: '{_direction}'.\n"
                f"{_score_line}"
                "Write one sentence. No preamble, no bullet, no headers."
            )
        except Exception as exc:
            _log.error(
                f"[{ticker}] AI summary prompt build failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return ""

        def _clean_one_sentence(text: str) -> str:
            """Collapse LLM output to a single sentence <=280 chars."""
            if not text:
                return ""
            s = text.strip().strip('"').strip("'").strip()
            for _prefix in (
                "Summary:", "summary:",
                "Here is the summary:", "Here's the summary:",
            ):
                if s.startswith(_prefix):
                    s = s[len(_prefix):].strip()
            import re as _re
            _match = _re.split(r"(?<=[.!?])\s+", s, maxsplit=1)
            if _match:
                s = _match[0].strip()
            if len(s) > 280:
                s = s[:277].rstrip() + "..."
            return s

        # -- Groq (single provider) ---------------------------------
        try:
            from groq import Groq as _Groq
            _client = _Groq(api_key=_groq_key)
            _resp = _client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": _prompt}],
                max_tokens=120,
                temperature=0.2,
            )
            _out = _clean_one_sentence(_resp.choices[0].message.content or "")
            if _out:
                _log.info(f"[{ticker}] AI summary via Groq ({len(_out)} chars)")
                return _out
            _log.warning(f"[{ticker}] Groq returned empty summary")
        except Exception as exc:
            _log.error(f"[{ticker}] Groq call failed: {type(exc).__name__}: {exc}")

        return ""

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
          2. Check in-memory cache key ``ai_summary:{ticker}`` (written by
             /api/v1/analysis/{ticker}/summary endpoint and by
             scripts/warm_ai_summaries.py) -> attach and return.
          3. If ``generate_if_missing=True``, call ``get_ai_summary``
             inline (synchronous LLM call -- ONLY the warmup script
             should pass this flag; the request path must not, to keep
             p50 < 200ms).

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
            _cached_text: str | None = None
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
