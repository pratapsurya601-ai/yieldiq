"""Phase I-ingest-b: Anthropic-extract bank operational stats
(branches / ATMs / customer base) from bank annual report PDFs
into ``bank_operational_kpis`` (migration 061).

Sibling to ``scripts/extract_ar_signals_batch.py`` (Phase H).
Shares the chunking / PDF download / cost accounting plumbing
from ``backend.services.ar_intel_service`` but uses the narrow,
bank-specific prompt in ``backend.services.bank_ops_prompt``.

Restricted to the canonical 38-ticker commercial-bank universe
(``PURE_BANK_TICKERS_FOR_DE``); non-bank annual reports are
skipped at the candidate-selection step so we don't burn
Anthropic spend on rows the prompt isn't designed for.

Persists with ``source='ar_anthropic'`` so the row coexists with
any ``source='bse_xbrl'`` row for the same (ticker, period_end,
period_type) -- the migration's UNIQUE includes ``source`` for
exactly this reason.

Usage::

    python scripts/extract_bank_ops_from_ar.py --dry-run
    python scripts/extract_bank_ops_from_ar.py --tickers HDFCBANK,SBIN
    python scripts/extract_bank_ops_from_ar.py --cost-cap-usd 30 \\
        --max-rows 40 --resume-from-id 1500

Flags::

    --tickers          Comma-separated bank-ticker list. Default:
                       all rows in company_annual_reports whose
                       ticker is in PURE_BANK_TICKERS_FOR_DE.
    --max-rows N       Stop after N annual reports.
    --cost-cap-usd N   Hard-stop on cumulative spend (default $30).
                       Per-AR spend ~$0.05-$0.10 because we only
                       call the narrow ops prompt on each chunk
                       (max ~800 output tokens).
    --resume-from-id   Skip company_annual_reports.id below N.
    --rate-limit S     Sleep S seconds between Anthropic calls
                       (default 1.0).
    --dry-run          Walk + log, no LLM calls, no DB writes.

Exit codes::

    0  ran cleanly
    1  fatal init error
    2  pre-flight failed (>50% extraction failures in first 5)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("yieldiq.extract.bank_ops_ar")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

PREFLIGHT_SAMPLE = 5
PREFLIGHT_MAX_FAIL_RATE = 0.5


def _connect():
    """Open the Neon Postgres connection. Returns None on failure."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL not set -- aborting")
        return None
    try:
        import psycopg2  # type: ignore
    except ImportError as exc:
        logger.error("psycopg2 not installed: %s", exc)
        return None
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return psycopg2.connect(url)


def _bank_universe() -> frozenset[str]:
    from backend.services.analysis.sector_overrides import (
        PURE_BANK_TICKERS_FOR_DE,
    )
    return PURE_BANK_TICKERS_FOR_DE


def _parse_period_end(s: str | None) -> date | None:
    """YYYY-MM-DD string -> date. Tolerant of None / bad input."""
    if not s or not isinstance(s, str):
        return None
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def _upsert_bank_ops(conn, ticker: str, period_end: date, period_type: str,
                     result, ar_url: str | None) -> bool:
    """UPSERT a bank_operational_kpis row from a BankOpsResult.

    COALESCE preserves any prior populated columns -- e.g. an
    earlier ar_anthropic run that already captured ATMs will
    not be wiped if a re-run can only resolve branches.
    """
    from psycopg2.extras import execute_values  # noqa: F401  (kept for symmetry with other scripts)
    sql = """
        INSERT INTO bank_operational_kpis (
            ticker, period_end, period_type,
            branches_total, branches_tier1, branches_tier2, branches_tier3,
            atms_total, customers_millions,
            source, source_url
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s
        )
        ON CONFLICT (ticker, period_end, period_type, source)
        DO UPDATE SET
            branches_total     = COALESCE(EXCLUDED.branches_total,
                                          bank_operational_kpis.branches_total),
            branches_tier1     = COALESCE(EXCLUDED.branches_tier1,
                                          bank_operational_kpis.branches_tier1),
            branches_tier2     = COALESCE(EXCLUDED.branches_tier2,
                                          bank_operational_kpis.branches_tier2),
            branches_tier3     = COALESCE(EXCLUDED.branches_tier3,
                                          bank_operational_kpis.branches_tier3),
            atms_total         = COALESCE(EXCLUDED.atms_total,
                                          bank_operational_kpis.atms_total),
            customers_millions = COALESCE(EXCLUDED.customers_millions,
                                          bank_operational_kpis.customers_millions),
            source_url         = COALESCE(EXCLUDED.source_url,
                                          bank_operational_kpis.source_url),
            extracted_at       = now()
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (
                ticker, period_end, period_type,
                result.branches_total, result.branches_tier1,
                result.branches_tier2, result.branches_tier3,
                result.atms_total, result.customers_millions,
                "ar_anthropic", ar_url,
            ))
        return True
    except Exception as exc:
        logger.warning("upsert failed for %s %s: %s", ticker, period_end, exc)
        return False


def _extract_for_ar(ticker: str, ar_url: str, *, anthropic_client,
                    model: str):
    """Download an AR PDF, chunk it, ask the bank-ops prompt on
    each chunk, merge, sanitise. Returns a BankOpsResult.
    """
    from backend.services import ar_intel_service as ari
    from backend.services import bank_ops_prompt as bop

    pdf_bytes = ari.download_ar_pdf(ar_url)
    text = ari.extract_text_from_pdf_bytes(pdf_bytes)
    if len(text.strip()) < ari.MIN_TEXT_CHARS:
        return bop.BankOpsResult(
            quality_flag="extraction_failed", model=model,
        )
    chunks = ari.chunk_ar_text(text)
    if not chunks:
        return bop.BankOpsResult(
            quality_flag="extraction_failed", model=model,
        )

    chunk_payloads: list[dict] = []
    total_in = total_out = total_cache = 0
    for chunk in chunks:
        try:
            parsed, in_tok, out_tok, cache_read = bop.call_anthropic_for_chunk(
                anthropic_client, ticker, chunk["text"],
                chunk_id=chunk["chunk_id"], heading=chunk.get("heading"),
                model=model,
            )
        except Exception as exc:
            logger.warning(
                "bank_ops chunk %s failed for %s: %s",
                chunk["chunk_id"], ticker, exc,
            )
            continue
        chunk_payloads.append(parsed)
        total_in += in_tok
        total_out += out_tok
        total_cache += cache_read

    if not chunk_payloads:
        return bop.BankOpsResult(
            quality_flag="extraction_failed",
            input_tokens=total_in + total_cache,
            output_tokens=total_out,
            cost_usd=ari.compute_anthropic_cost_usd(
                model, total_in + total_cache, total_out,
            ),
            model=model,
        )

    merged = bop.merge_chunk_results(chunk_payloads)
    try:
        bop.validate_schema(merged)
    except ValueError as exc:
        logger.warning("bank_ops schema validation failed %s: %s", ticker, exc)
        return bop.BankOpsResult(
            quality_flag="extraction_failed",
            input_tokens=total_in + total_cache,
            output_tokens=total_out,
            cost_usd=ari.compute_anthropic_cost_usd(
                model, total_in + total_cache, total_out,
            ),
            model=model,
        )

    hits = bop.scan_for_banned_vocab(merged)
    quality = "sebi_withheld" if hits else "ok"
    if hits:
        logger.warning(
            "bank_ops SEBI banned vocab in output for %s: %s",
            ticker, hits[:5],
        )

    return bop.BankOpsResult(
        branches_total=_safe_int(merged.get("branches_total")),
        branches_tier1=_safe_int(merged.get("branches_tier1")),
        branches_tier2=_safe_int(merged.get("branches_tier2")),
        branches_tier3=_safe_int(merged.get("branches_tier3")),
        atms_total=_safe_int(merged.get("atms_total")),
        customers_millions=_safe_float(merged.get("customers_millions")),
        period_end=merged.get("period_end"),
        period_type=merged.get("period_type"),
        source_section=merged.get("source_section"),
        notes=merged.get("notes"),
        quality_flag=quality,
        input_tokens=total_in + total_cache,
        output_tokens=total_out,
        cost_usd=ari.compute_anthropic_cost_usd(
            model, total_in + total_cache, total_out,
        ),
        model=model,
        sanitizer_hits=hits,
    )


def _safe_int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default=None)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--cost-cap-usd", type=float, default=30.0)
    parser.add_argument("--resume-from-id", type=int, default=None)
    parser.add_argument("--rate-limit", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import create_engine, text
    from backend.services import ar_intel_service as ari
    from backend.services import bank_ops_prompt as bop

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set -- aborting")
        return 1
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    engine = create_engine(db_url, pool_pre_ping=True)

    bank_set = _bank_universe()
    if args.tickers:
        requested = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        # Intersect against the bank universe -- silently drop
        # non-banks to keep the prompt scope honest.
        tickers = [t for t in requested if t in bank_set]
        dropped = [t for t in requested if t not in bank_set]
        if dropped:
            logger.warning(
                "dropping non-bank tickers (not in PURE_BANK_TICKERS_FOR_DE): %s",
                dropped,
            )
    else:
        tickers = sorted(bank_set)

    where = [
        "car.ar_url IS NOT NULL", "car.ar_url <> ''",
        "car.ticker = ANY(:tickers)",
    ]
    params: dict = {"tickers": tickers}
    if args.resume_from_id is not None:
        where.append("car.id >= :resume_from_id")
        params["resume_from_id"] = args.resume_from_id

    sql = text(f"""
        SELECT car.id, car.ticker, car.fiscal_year, car.ar_url
          FROM company_annual_reports car
         WHERE {' AND '.join(where)}
         ORDER BY car.fiscal_year DESC, car.id ASC
    """)
    with engine.connect() as conn:
        rows = list(conn.execute(sql, params).fetchall())

    logger.info(
        "candidates=%d cap=$%.2f max_rows=%s dry_run=%s",
        len(rows), args.cost_cap_usd, args.max_rows, args.dry_run,
    )
    if not rows:
        logger.info("nothing to do.")
        return 0

    anthropic_client = None
    if not args.dry_run:
        anthropic_client = ari._build_anthropic_client()  # noqa: SLF001
        if anthropic_client is None:
            logger.error(
                "ANTHROPIC_API_KEY not set or client init failed -- aborting"
            )
            return 1

    db_conn = None if args.dry_run else _connect()
    if not args.dry_run and db_conn is None:
        return 1

    processed = 0
    cumulative_cost = 0.0
    n_failed = 0
    n_withheld = 0
    n_written = 0

    try:
        for row in rows:
            if args.max_rows is not None and processed >= args.max_rows:
                logger.info("--max-rows %d reached", args.max_rows)
                break
            if cumulative_cost >= args.cost_cap_usd:
                logger.warning(
                    "COST CAP HIT $%.4f >= $%.2f at id=%s. Re-run with "
                    "--resume-from-id=%s to continue.",
                    cumulative_cost, args.cost_cap_usd, row.id, row.id,
                )
                break

            logger.info(
                "[%d/%d] %s FY%s ar_id=%s spend=$%.4f failed=%d withheld=%d",
                processed + 1, len(rows), row.ticker, row.fiscal_year,
                row.id, cumulative_cost, n_failed, n_withheld,
            )
            if args.dry_run:
                processed += 1
                continue

            try:
                result = _extract_for_ar(
                    row.ticker, row.ar_url,
                    anthropic_client=anthropic_client,
                    model=bop.DEFAULT_ANTHROPIC_MODEL,
                )
            except Exception as exc:
                logger.warning("extract failed ar_id=%s: %s", row.id, exc)
                n_failed += 1
                processed += 1
                if args.rate_limit > 0:
                    time.sleep(args.rate_limit)
                if _preflight_trip(processed, n_failed):
                    return 2
                continue

            cumulative_cost += result.cost_usd
            if result.quality_flag == "sebi_withheld":
                n_withheld += 1
            elif result.quality_flag == "extraction_failed":
                n_failed += 1

            # Pick the period_end: prefer the LLM-extracted one;
            # fall back to FY-end from company_annual_reports.
            period_end = _parse_period_end(result.period_end)
            if period_end is None and row.fiscal_year:
                period_end = date(int(row.fiscal_year), 3, 31)
            if period_end is None:
                logger.warning(
                    "no resolvable period_end for ar_id=%s ticker=%s -- "
                    "skipping persist", row.id, row.ticker,
                )
                processed += 1
                continue

            period_type = result.period_type or "annual"

            # Skip if every operational field is null -- nothing to
            # write that wouldn't be all-NULL.
            if result.populated_field_count() == 0:
                logger.info(
                    "no operational fields extracted for %s FY%s -- "
                    "skipping write (no garbage rows).",
                    row.ticker, row.fiscal_year,
                )
            elif result.quality_flag == "ok":
                if _upsert_bank_ops(
                    db_conn, row.ticker, period_end, period_type,
                    result, row.ar_url,
                ):
                    db_conn.commit()
                    n_written += 1
                else:
                    db_conn.rollback()

            processed += 1
            if _preflight_trip(processed, n_failed):
                return 2
            if args.rate_limit > 0:
                time.sleep(args.rate_limit)
    finally:
        if db_conn is not None:
            try:
                db_conn.close()
            except Exception:
                pass

    logger.info(
        "done. processed=%d written=%d spend=$%.4f failed=%d withheld=%d dry_run=%s",
        processed, n_written, cumulative_cost, n_failed, n_withheld,
        args.dry_run,
    )
    return 0


def _preflight_trip(processed: int, failed: int) -> bool:
    """True iff we've crossed the >50% failure rate threshold in
    the first PREFLIGHT_SAMPLE rows.
    """
    if (
        processed <= PREFLIGHT_SAMPLE
        and processed >= 3
        and failed / processed > PREFLIGHT_MAX_FAIL_RATE
    ):
        logger.error(
            "PRE-FLIGHT FAILED: %d/%d (%.0f%%) extraction failures in "
            "the first %d rows. Aborting -- fix the source URLs or "
            "prompt before re-running.",
            failed, processed, 100.0 * failed / processed, processed,
        )
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
