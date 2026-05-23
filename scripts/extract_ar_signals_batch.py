"""Phase H-extract: batch-extract structured AR signals.

Walks `company_annual_reports`, finds rows where:
  * `ar_url` is populated, AND
  * no `ar_signals` row exists yet for this annual_report_id at
    (model_version, prompt_version) matching the running service.

For each candidate it downloads the AR PDF, pypdf-extracts the
text, chunks it, calls Anthropic Sonnet 4.5 per chunk via
`backend.services.ar_intel_service.extract_ar_signals_from_url`,
merges + validates + SEBI-sanitises, and UPSERTs into ar_signals
via `save_signals`. Cost-capped, resumable, --dry-run safe.

DO NOT auto-run from cron. Anthropic Sonnet on AR-sized inputs
costs roughly ~$0.20-$0.40 per AR -- this is operator-triggered
only (see .github/workflows/ar-backfill.yml in H-operator-workflow).

Usage:

    python scripts/extract_ar_signals_batch.py --dry-run
    python scripts/extract_ar_signals_batch.py --tickers RELIANCE,ITC
    python scripts/extract_ar_signals_batch.py --max-rows 200 \\
        --cost-cap-usd 100 --resume-from-id 1500

Flags:
    --tickers          Comma-separated ticker list to restrict the
                       batch. Default: all rows with ar_url.
    --max-rows N       Stop after processing N rows (default unlimited).
    --rate-limit S     Sleep S seconds between Anthropic calls
                       (default 1.0).
    --cost-cap-usd N   Hard-stop the batch once cumulative spend
                       crosses N USD. Default 100.
    --resume-from-id   Skip company_annual_reports.id below N.
    --dry-run          Walk + log, no LLM calls, no writes.

Pre-flight:
    Hard-stop on >50% extraction failures in the first 5 rows.

Exit codes:
    0  ran cleanly (possibly hit cost cap / max-rows)
    1  no DB session / fatal init error
    2  pre-flight smoke test failed (>50% extraction failures)

Cost notes:
    Sonnet 4.5 pricing $3 in / $15 out per Mtoken. A typical
    100-page AR yields ~80k chars -> ~22k tokens. Split into 2-3
    chunks (chunk cap 60k chars / ~17k tokens), each emitting
    ~1000 output tokens, the per-AR spend is ~$0.20-$0.30.
    --cost-cap-usd 100 permits ~400 ARs / a fifth of the target.
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

logger = logging.getLogger("yieldiq.batch.ar_signals")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

PREFLIGHT_SAMPLE = 5
PREFLIGHT_MAX_FAIL_RATE = 0.5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default=None,
                        help="Comma-separated ticker list to restrict the batch.")
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--rate-limit", type=float, default=1.0)
    parser.add_argument("--cost-cap-usd", type=float, default=100.0,
                        help="Hard-stop when cumulative spend >= this USD.")
    parser.add_argument("--resume-from-id", type=int, default=None,
                        help="Skip company_annual_reports.id below this value.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import create_engine, text
    import os

    from backend.services import ar_intel_service as ari

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set — aborting")
        return 1
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    engine = create_engine(db_url, pool_pre_ping=True)

    # Build candidate query. We LEFT JOIN ar_signals to skip
    # rows already extracted at the running service's
    # (model_version, prompt_version). This means a re-extract
    # at a bumped prompt_version naturally re-processes the row.
    where_clauses = ["car.ar_url IS NOT NULL", "car.ar_url <> ''"]
    params: dict[str, object] = {
        "model_version": ari.EXTRACTOR_VERSION,
        "prompt_version": ari.PROMPT_VERSION,
    }
    if args.resume_from_id is not None:
        where_clauses.append("car.id >= :resume_from_id")
        params["resume_from_id"] = args.resume_from_id
    if args.tickers:
        wanted = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if wanted:
            where_clauses.append("car.ticker = ANY(:tickers)")
            params["tickers"] = wanted

    sql = text(f"""
        SELECT car.id, car.ticker, car.fiscal_year, car.ar_url
          FROM company_annual_reports car
          LEFT JOIN ar_signals s
                 ON s.annual_report_id = car.id
                AND s.model_version = :model_version
                AND s.prompt_version = :prompt_version
         WHERE {' AND '.join(where_clauses)}
           AND s.id IS NULL
         ORDER BY car.fiscal_year DESC, car.id ASC
    """)

    with engine.connect() as conn:
        rows = list(conn.execute(sql, params).fetchall())

    logger.info(
        "found %d candidate rows | model=%s prompt_v=%d | dry_run=%s | cap=$%.2f | max_rows=%s",
        len(rows), ari.EXTRACTOR_VERSION, ari.PROMPT_VERSION,
        args.dry_run, args.cost_cap_usd, args.max_rows,
    )

    if not rows:
        logger.info("nothing to do.")
        return 0

    processed = 0
    cumulative_cost = 0.0
    n_withheld = 0
    n_failed = 0
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
            "[%d/%d] %s FY%s ar_id=%s spend_so_far=$%.4f withheld=%d failed=%d",
            processed + 1, len(rows), row.ticker, row.fiscal_year,
            row.id, cumulative_cost, n_withheld, n_failed,
        )

        if args.dry_run:
            processed += 1
            continue

        try:
            result = ari.extract_ar_signals_from_url(row.ticker, row.ar_url)
        except NotImplementedError:
            logger.error(
                "ANTHROPIC_API_KEY not set and no client injected — "
                "cannot extract. Aborting batch.",
            )
            return 1
        except Exception as exc:
            logger.warning("extract failed ar_id=%s: %s", row.id, exc)
            n_failed += 1
            processed += 1
            if args.rate_limit > 0:
                time.sleep(args.rate_limit)
            # Pre-flight gate: bail if the first PREFLIGHT_SAMPLE
            # rows have >50% failures.
            if (
                processed <= PREFLIGHT_SAMPLE
                and processed >= 3
                and n_failed / processed > PREFLIGHT_MAX_FAIL_RATE
            ):
                logger.error(
                    "PRE-FLIGHT FAILED: %d/%d (%.0f%%) extraction failures "
                    "in the first %d rows. Aborting batch — fix the source "
                    "URLs or PDF parser before re-running.",
                    n_failed, processed,
                    100.0 * n_failed / processed, processed,
                )
                return 2
            continue

        # Persist (including extraction_failed placeholder rows so
        # we never re-spend on a known-bad AR).
        ok = ari.save_signals(
            int(row.id), result.signals,
            quality_flag=result.quality_flag,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
        )
        if not ok:
            logger.warning("save_signals returned False for ar_id=%s", row.id)

        if result.quality_flag == "sebi_withheld":
            n_withheld += 1
        elif result.quality_flag == "extraction_failed":
            n_failed += 1

        cumulative_cost += result.cost_usd
        processed += 1

        if processed % 5 == 0:
            logger.info(
                "PROGRESS: processed=%d spend=$%.4f cap=$%.2f "
                "withheld=%d failed=%d",
                processed, cumulative_cost, args.cost_cap_usd,
                n_withheld, n_failed,
            )

        # Pre-flight gate on real failures too.
        if (
            processed <= PREFLIGHT_SAMPLE
            and processed >= 3
            and n_failed / processed > PREFLIGHT_MAX_FAIL_RATE
        ):
            logger.error(
                "PRE-FLIGHT FAILED: %d/%d (%.0f%%) extraction failures "
                "in the first %d rows. Aborting batch.",
                n_failed, processed,
                100.0 * n_failed / processed, processed,
            )
            return 2

        if args.rate_limit > 0:
            time.sleep(args.rate_limit)

    logger.info(
        "done. processed=%d spend=$%.4f cost_cap_hit=%s "
        "withheld=%d failed=%d dry_run=%s",
        processed, cumulative_cost, cost_cap_hit,
        n_withheld, n_failed, args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
