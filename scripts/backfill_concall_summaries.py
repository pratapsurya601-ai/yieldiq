"""Day-104b + Phase G-cost: backfill AI summaries for concall_transcripts.

Walks the `concall_transcripts` table, picks rows that have a `pdf_url`
and no `ai_summary`, fetches + summarises each one via Groq Llama 3.3
70B and persists token + USD spend (Phase G-cost columns added by
migration 058).

DO NOT auto-run from cron — Groq cost is small per call but can stack
on a wide ticker universe. Operator runs this manually (or via the
Phase G-operator-workflow GitHub Action) after a deploy with the
AI-cache PR live.

Usage (run from repo root):

    python scripts/backfill_concall_summaries.py --dry-run
    python scripts/backfill_concall_summaries.py --max-tickers 20
    python scripts/backfill_concall_summaries.py --rate-limit 1.0 \\
        --cost-cap-usd 25 --resume-from-id 1500

Flags:
    --dry-run         Print what would be summarised; touch nothing.
    --max-tickers N   Cap distinct tickers processed in this run.
    --rate-limit S    Sleep S seconds between Groq calls (default 0.5).
    --cost-cap-usd N  Hard-stop the batch once cumulative cost (across
                      this run's Groq spend) exceeds N. Default 100.
                      Counted from the persisted ai_cost_usd column
                      ONLY for rows this invocation populated — does
                      NOT include sunk spend from prior runs.
    --resume-from-id  Skip rows with concall_transcripts.id < N. Use
                      after a cost-cap stop to continue from the next
                      row instead of re-walking the whole queue.

Exit codes:
    0  ran cleanly (possibly hit cost cap; logged)
    1  no DB session / fatal init error

Cost notes:
    Per-row spend on Llama 3.3 70B (a ~20-page concall PDF, ~12k input
    tokens, ~400 output tokens) is roughly $0.007-$0.010 — so $100 cap
    permits ~10,000-15,000 rows. Cost is recomputed per row from
    `compute_groq_cost_usd` in backend.services.concall_service so a
    pricing change in one place automatically updates here.
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
    parser.add_argument(
        "--cost-cap-usd", type=float, default=100.0,
        help="Hard-stop batch when cumulative spend exceeds this USD "
             "amount (default 100). Counted from rows populated by "
             "this run only.",
    )
    parser.add_argument(
        "--resume-from-id", type=int, default=None,
        help="Skip rows with concall_transcripts.id below this value. "
             "Use to continue after a previous cost-cap stop.",
    )
    args = parser.parse_args()

    from backend.models.concalls import ConcallTranscript
    from backend.services import concall_service

    session = concall_service._get_library_session()
    if session is None:
        logger.error("no DB session available — aborting")
        return 1

    try:
        q = (
            session.query(ConcallTranscript)
            .filter(ConcallTranscript.pdf_url.isnot(None))
            .filter(ConcallTranscript.ai_summary.is_(None))
        )
        if args.resume_from_id is not None:
            q = q.filter(ConcallTranscript.id >= args.resume_from_id)
        rows = q.order_by(ConcallTranscript.filing_date.desc()).all()
    finally:
        try:
            session.close()
        except Exception:
            pass

    logger.info(
        "found %d rows needing summary (resume_from_id=%s)",
        len(rows), args.resume_from_id,
    )
    logger.info(
        "cost cap: $%.2f USD | dry_run=%s | rate_limit=%.2fs",
        args.cost_cap_usd, args.dry_run, args.rate_limit,
    )

    seen_tickers: set[str] = set()
    processed = 0
    cumulative_cost = 0.0
    cost_cap_hit = False

    for row in rows:
        if args.max_tickers is not None:
            if row.ticker not in seen_tickers and len(seen_tickers) >= args.max_tickers:
                continue
        seen_tickers.add(row.ticker)

        # Cost-cap pre-check. We check BEFORE the next call so we never
        # incur a "one more call" overrun. Worst case the cap is
        # observed exactly at the boundary.
        if cumulative_cost >= args.cost_cap_usd:
            cost_cap_hit = True
            logger.warning(
                "COST CAP HIT — cumulative spend $%.4f >= $%.2f. "
                "Stopping. Last processed id=%s. Re-run with "
                "--resume-from-id=%s to continue.",
                cumulative_cost, args.cost_cap_usd,
                row.id, row.id,
            )
            break

        logger.info(
            "[%d/%d] %s %s id=%s spend_so_far=$%.4f",
            processed + 1, len(rows), row.ticker,
            row.filing_date.isoformat() if row.filing_date else "?",
            row.id, cumulative_cost,
        )

        if args.dry_run:
            processed += 1
            continue

        try:
            concall_service.populate_concall_summary(row.id)
        except Exception as exc:
            logger.warning("populate failed id=%s: %s", row.id, exc)

        # Re-read the row to pick up the cost the service just
        # persisted. Cheap; one PK lookup.
        try:
            session2 = concall_service._get_library_session()
            if session2 is not None:
                refreshed = session2.get(ConcallTranscript, row.id)
                if refreshed is not None and refreshed.ai_cost_usd is not None:
                    cumulative_cost += float(refreshed.ai_cost_usd)
                session2.close()
        except Exception as exc:
            logger.warning("could not re-read cost for id=%s: %s", row.id, exc)

        processed += 1
        if processed % 10 == 0:
            logger.info(
                "PROGRESS: processed=%d cumulative_cost=$%.4f cap=$%.2f",
                processed, cumulative_cost, args.cost_cap_usd,
            )

        if args.rate_limit > 0:
            time.sleep(args.rate_limit)

    logger.info(
        "done. processed=%d distinct_tickers=%d cumulative_cost=$%.4f "
        "cost_cap_hit=%s dry_run=%s",
        processed, len(seen_tickers), cumulative_cost,
        cost_cap_hit, args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
