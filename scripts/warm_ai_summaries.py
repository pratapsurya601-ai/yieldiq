"""Warm the AI summary cache for flagship tickers.

Why this exists
---------------
``/api/v1/public/stock-summary/{ticker}`` surfaces ``ai_summary_snippet``
(derived from ``AnalysisResponse.ai_summary``), but ``get_full_analysis``
never populates that field -- it's designed to stay out of the hot path
so analysis latency stays ~200ms. The authed ``/analysis/{ticker}/summary``
endpoint generates and caches the summary on-demand, but that only
happens when an authenticated user opens the page -- crawlers and
unauthenticated visitors on the SEO pages never trigger it.

This script closes the gap: it iterates the top-N flagship tickers,
calls the LLM once per ticker, and writes the result into BOTH tiers:

  1. In-memory ``cache_service`` under ``ai_summary:{ticker}`` -- picked
     up by ``AnalysisService.ensure_ai_summary`` on subsequent reads
     (including the public endpoint).
  2. Postgres ``analysis_cache.payload.ai_summary`` -- survives worker
     restarts and is what the public stock-summary endpoint extracts
     when it does its tier-2 cache read.

Run locally
-----------
    # Requires GROQ_API_KEY in the environment.
    python scripts/warm_ai_summaries.py
    python scripts/warm_ai_summaries.py --limit 15
    python scripts/warm_ai_summaries.py --tickers RELIANCE.NS,TCS.NS

Run in prod (Railway one-off)
-----------------------------
    railway run python scripts/warm_ai_summaries.py

Idempotency
-----------
Safe to re-run. If ``AnalysisResponse.ai_summary`` is already populated
for a ticker, that ticker is skipped unless ``--force`` is passed.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("warm_ai_summaries")


# Top-15 flagships -- keep aligned with frontend/homepage featured list.
# The user-facing bug report specifically called out these tickers as
# having ``ai_summary_snippet: null``.
FLAGSHIP_TICKERS: list[str] = [
    "RELIANCE.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "INFY.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "ITC.NS",
    "BHARTIARTL.NS",
    "LT.NS",
    "KOTAKBANK.NS",
    "HINDUNILVR.NS",
    "BAJFINANCE.NS",
    "MARUTI.NS",
    "TITAN.NS",
    "SUNPHARMA.NS",
]


def _preflight_keys() -> bool:
    """Return True iff GROQ_API_KEY is configured."""
    q = os.environ.get("GROQ_API_KEY", "").strip()
    if not q:
        logger.error(
            "GROQ_API_KEY is not set in the environment. "
            "Set it on Railway and re-run."
        )
        return False
    logger.info("Groq key detected")
    return True


def _warm_one(ticker: str, *, force: bool = False) -> tuple[str, bool, str]:
    """Generate + persist an AI summary for one ticker.

    Returns (ticker, success, status_message).
    """
    from backend.services.analysis_service import AnalysisService
    from backend.services.cache_service import cache
    from backend.services import analysis_cache_service

    svc = AnalysisService()

    t0 = time.time()
    try:
        # Use the same get_full_analysis path as the hot endpoints so
        # the AnalysisResponse we feed to the LLM is SoT-consistent.
        analysis = svc.get_full_analysis(ticker)
    except Exception as exc:
        return ticker, False, f"analysis compute failed: {type(exc).__name__}: {exc}"

    if not force and getattr(analysis, "ai_summary", None):
        return ticker, True, "skipped (already populated)"

    summary = svc.get_ai_summary(ticker, analysis)
    if not summary:
        return ticker, False, "LLM returned empty summary (check API key / quota)"

    # Attach to AnalysisResponse and persist both tiers.
    try:
        analysis.ai_summary = summary
    except Exception:
        try:
            analysis = analysis.model_copy(update={"ai_summary": summary})
        except Exception:
            pass

    # Tier 1: in-memory -- picked up by ensure_ai_summary on live reads.
    try:
        cache.set(f"ai_summary:{ticker}", {"summary": summary}, ttl=86400)
    except Exception as exc:
        logger.warning(f"[{ticker}] in-memory cache set failed: {exc}")

    # Tier 1b: refresh the full-analysis in-memory cache so warm workers
    # see the new ai_summary without needing a DB round-trip.
    try:
        cache.set(f"analysis:{ticker}", analysis, ttl=86400)
    except Exception as exc:
        logger.warning(f"[{ticker}] analysis cache refresh failed: {exc}")

    # Tier 2: Postgres analysis_cache -- survives worker restarts so
    # public/stock-summary picks it up on cold hits.
    try:
        _compute_ms = int((time.time() - t0) * 1000)
        analysis_cache_service.save_cached(
            ticker, analysis.model_dump(), _compute_ms
        )
    except Exception as exc:
        logger.warning(f"[{ticker}] analysis_cache persist failed: {exc}")

    _len = len(summary)
    return ticker, True, f"ok ({_len} chars)"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Warm the AI summary cache for flagship tickers."
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default="",
        help="Comma-separated tickers (overrides flagship list)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=len(FLAGSHIP_TICKERS),
        help="Max tickers to process from the flagship list",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if ai_summary is already populated",
    )
    args = parser.parse_args()

    if not _preflight_keys():
        return 2

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        tickers = [
            t if t.endswith(".NS") or t.endswith(".BO") else f"{t}.NS"
            for t in tickers
        ]
    else:
        tickers = FLAGSHIP_TICKERS[: args.limit]

    logger.info(f"Warming AI summaries for {len(tickers)} tickers (force={args.force})")
    ok = 0
    fail = 0
    for t in tickers:
        ticker, success, status = _warm_one(t, force=args.force)
        if success:
            ok += 1
            logger.info(f"  {ticker}: {status}")
        else:
            fail += 1
            logger.error(f"  {ticker}: {status}")
        # Be gentle with Groq's free-tier rate limit (~30 RPM).
        time.sleep(2.0)

    logger.info(f"Done. ok={ok} fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
