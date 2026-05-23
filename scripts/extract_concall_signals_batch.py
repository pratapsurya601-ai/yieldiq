"""Phase G-intel-phase1 (b): batch extract structured concall signals.

Walks the `concall_transcripts` table looking for rows that:
  * have `transcript_text` populated (Day-104b PDF extraction already ran), AND
  * do NOT yet have a `concall_signals` row linked via transcript_id.

For each candidate, calls Anthropic Sonnet 4.5 via
`backend.services.concall_intel_service.extract_concall_signals_full`,
persists the structured signals + cost + quality_flag via
`save_signals`. Cost-capped and resumable mirroring
scripts/backfill_concall_summaries.py.

DO NOT auto-run from cron. Anthropic Sonnet costs ~10x Groq Llama —
this is operator-triggered (the GitHub Actions workflow in
G-operator-workflow gives the operator a one-button UI).

Usage:

    python scripts/extract_concall_signals_batch.py --dry-run
    python scripts/extract_concall_signals_batch.py --max-rows 100
    python scripts/extract_concall_signals_batch.py \\
        --cost-cap-usd 50 --resume-from-id 1500

Flags:
    --dry-run         Walk + log, no LLM calls, no writes.
    --max-rows N      Stop after processing N rows (default unlimited).
    --rate-limit S    Sleep S seconds between Anthropic calls
                      (default 1.0 -- polite to the API).
    --cost-cap-usd N  Hard-stop the batch once cumulative spend
                      crosses N USD. Default 50 (intentionally lower
                      than G-cost's $100 because per-row spend is
                      ~10x: ~$0.03-$0.05 vs ~$0.007-$0.010).
    --resume-from-id  Skip concall_transcripts.id below N. Use after
                      a cost-cap stop.

Exit codes:
    0  ran cleanly (possibly hit cost cap or max-rows)
    1  no DB session / fatal init error

Cost notes:
    Sonnet 4.5 pricing $3 in / $15 out per Mtoken. A typical 20-page
    concall ~12k input tokens + ~600 output -> $0.045/row. So
    --cost-cap-usd 50 permits roughly 1,100 rows.

    Prompt caching cuts repeat-batch input cost dramatically — the
    system prompt is identical across calls, so cache_read tokens
    quickly dominate the input side once the cache warms up. Watch
    the per-row cost in the progress log to confirm.
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

logger = logging.getLogger("yieldiq.batch.concall_signals")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _resolve_fiscal_period(row, signals: dict) -> str:
    """Pick the fiscal_period to UPSERT into concall_signals.

    Priority: explicit Q?-FY?? from the row's parsed subject, else the
    LLM's stated `fiscal_period`, else a fallback to filing-date year.
    """
    # backend.services.concall_service has the subject parser; importing
    # locally to avoid circular issues at module load.
    from backend.services.concall_service import _parse_period_from_subject
    parsed = _parse_period_from_subject(row.subject or "")
    if parsed and parsed.startswith("Q") and "-FY" in parsed:
        # Normalise "Q3-FY25" -> "Q3FY25" (concall_signals convention).
        return parsed.replace("-", "")
    llm_period = (signals.get("fiscal_period") or "").strip()
    if llm_period:
        return llm_period
    if row.filing_date:
        return f"FY{str(row.filing_date.year)[-2:]}"
    return "UNKNOWN"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--rate-limit", type=float, default=1.0)
    parser.add_argument(
        "--cost-cap-usd", type=float, default=50.0,
        help="Hard-stop when cumulative spend >= this USD (default 50).",
    )
    parser.add_argument(
        "--resume-from-id", type=int, default=None,
        help="Skip concall_transcripts.id below this value.",
    )
    args = parser.parse_args()

    from sqlalchemy import text
    from backend.models.concalls import ConcallTranscript
    from backend.services import concall_intel_service as intel
    from backend.services import concall_service

    session = concall_service._get_library_session()
    if session is None:
        logger.error("no DB session available — aborting")
        return 1

    try:
        # Candidate rows: transcript_text populated, no concall_signals
        # row already extracted for this transcript_id.
        q = (
            session.query(ConcallTranscript)
            .filter(ConcallTranscript.transcript_text.isnot(None))
        )
        if args.resume_from_id is not None:
            q = q.filter(ConcallTranscript.id >= args.resume_from_id)
        candidates = q.order_by(ConcallTranscript.filing_date.desc()).all()

        # Filter out rows that already have a signals row (NOT EXISTS).
        # Doing this in Python after the fetch keeps the SQL simple
        # against SQLite test fixtures; real Postgres can do it in
        # one query but the in-memory test DB doesn't carry the
        # concall_signals table.
        already = set()
        try:
            rs = session.execute(text(
                "SELECT transcript_id FROM concall_signals "
                "WHERE transcript_id IS NOT NULL"
            )).fetchall()
            already = {int(r[0]) for r in rs}
        except Exception as exc:
            logger.info("could not pre-load existing signals "
                        "(table may not exist in test env): %s", exc)

        rows = [r for r in candidates if r.id not in already]
    finally:
        try:
            session.close()
        except Exception:
            pass

    logger.info(
        "found %d candidate rows (resume_from_id=%s, %d already extracted skipped)",
        len(rows), args.resume_from_id, len(candidates) - len(rows)
        if 'candidates' in dir() else 0,
    )
    logger.info(
        "cost cap: $%.2f | dry_run=%s | rate_limit=%.2fs | max_rows=%s",
        args.cost_cap_usd, args.dry_run, args.rate_limit, args.max_rows,
    )

    processed = 0
    cumulative_cost = 0.0
    n_withheld = 0
    n_schema_fail = 0
    cost_cap_hit = False

    for row in rows:
        if args.max_rows is not None and processed >= args.max_rows:
            logger.info("max-rows %d reached; stopping", args.max_rows)
            break

        if cumulative_cost >= args.cost_cap_usd:
            cost_cap_hit = True
            logger.warning(
                "COST CAP HIT — cumulative $%.4f >= $%.2f. Last id=%s. "
                "Re-run with --resume-from-id=%s to continue.",
                cumulative_cost, args.cost_cap_usd, row.id, row.id,
            )
            break

        logger.info(
            "[%d/%d] %s %s id=%s spend_so_far=$%.4f withheld=%d",
            processed + 1, len(rows), row.ticker,
            row.filing_date.isoformat() if row.filing_date else "?",
            row.id, cumulative_cost, n_withheld,
        )

        if args.dry_run:
            processed += 1
            continue

        try:
            result = intel.extract_concall_signals_full(
                row.ticker, row.transcript_text or "",
            )
        except ValueError as exc:
            # Schema or transcript-length failure — count and move on.
            n_schema_fail += 1
            logger.warning("schema/validation fail id=%s: %s", row.id, exc)
            processed += 1
            continue
        except NotImplementedError:
            logger.error(
                "ANTHROPIC_API_KEY not set and no client injected — "
                "cannot extract. Aborting batch.",
            )
            return 1
        except Exception as exc:
            logger.warning("anthropic call failed id=%s: %s", row.id, exc)
            processed += 1
            time.sleep(args.rate_limit)
            continue

        # Persist
        fiscal_period = _resolve_fiscal_period(row, result.signals)
        ok = intel.save_signals(
            row.ticker, fiscal_period, result.signals,
            quality_flag=result.quality_flag,
            transcript_id=row.id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
        )
        if not ok:
            logger.warning("save_signals returned False for id=%s", row.id)

        if result.quality_flag == "sebi_withheld":
            n_withheld += 1

        cumulative_cost += result.cost_usd
        processed += 1

        if processed % 10 == 0:
            logger.info(
                "PROGRESS: processed=%d spend=$%.4f cap=$%.2f withheld=%d schema_fail=%d",
                processed, cumulative_cost, args.cost_cap_usd,
                n_withheld, n_schema_fail,
            )

        if args.rate_limit > 0:
            time.sleep(args.rate_limit)

    logger.info(
        "done. processed=%d spend=$%.4f cost_cap_hit=%s "
        "withheld=%d schema_fail=%d dry_run=%s",
        processed, cumulative_cost, cost_cap_hit,
        n_withheld, n_schema_fail, args.dry_run,
    )
    if n_schema_fail and processed > 0:
        rate = 100.0 * n_schema_fail / processed
        if rate > 30.0:
            logger.error(
                "SCHEMA-FAIL RATE %.1f%% EXCEEDS 30%% — prompt needs "
                "human iteration; consider pausing the batch.",
                rate,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
