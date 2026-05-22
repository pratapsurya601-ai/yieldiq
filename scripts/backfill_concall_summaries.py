"""Day-104b: backfill AI summaries for existing concall_transcripts rows.

Walks the `concall_transcripts` table, picks rows that have a `pdf_url`
and no `ai_summary`, fetches + summarises each one.

DO NOT auto-run from cron — Groq cost is small per call but can stack
on a wide ticker universe. Operator runs this manually after a
deployment with the AI-cache PR live.

Usage (run from repo root):

    python scripts/backfill_concall_summaries.py --dry-run
    python scripts/backfill_concall_summaries.py --max-tickers 20
    python scripts/backfill_concall_summaries.py --rate-limit 1.0

Flags:
    --dry-run         Print what would be summarised; touch nothing.
    --max-tickers N   Cap distinct tickers processed in this run.
    --rate-limit S    Sleep S seconds between Groq calls (default 0.5).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = logging.getLogger("yieldiq.backfill.concall_summaries")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-tickers", type=int, default=None)
    parser.add_argument("--rate-limit", type=float, default=0.5)
    args = parser.parse_args()

    from backend.models.concalls import ConcallTranscript
    from backend.services import concall_service

    session = concall_service._get_library_session()
    if session is None:
        logger.error("no DB session available — aborting")
        return 1

    try:
        rows = (
            session.query(ConcallTranscript)
            .filter(ConcallTranscript.pdf_url.isnot(None))
            .filter(ConcallTranscript.ai_summary.is_(None))
            .order_by(ConcallTranscript.filing_date.desc())
            .all()
        )
    finally:
        try:
            session.close()
        except Exception:
            pass

    logger.info("found %d rows needing summary", len(rows))

    seen_tickers: set[str] = set()
    processed = 0
    for row in rows:
        if args.max_tickers is not None:
            if row.ticker not in seen_tickers and len(seen_tickers) >= args.max_tickers:
                continue
        seen_tickers.add(row.ticker)

        logger.info(
            "[%d/%d] %s %s id=%s",
            processed + 1, len(rows), row.ticker,
            row.filing_date.isoformat() if row.filing_date else "?",
            row.id,
        )

        if args.dry_run:
            processed += 1
            continue

        try:
            concall_service.populate_concall_summary(row.id)
        except Exception as exc:
            logger.warning("populate failed id=%s: %s", row.id, exc)

        processed += 1
        if args.rate_limit > 0:
            time.sleep(args.rate_limit)

    logger.info(
        "done. processed=%d distinct_tickers=%d dry_run=%s",
        processed, len(seen_tickers), args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
