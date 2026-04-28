"""Ingest related-party transactions from BSE/NSE annual-report PDFs.

SCAFFOLDING ONLY. The PDF parsing and LLM-extraction calls are stubbed
(see TODOs). What this script DOES wire up today:

  * Argparse skeleton (--tickers / --top / --all / --year / --dry-run /
    --use-sample-fixture).
  * Polite HTTP retry helper (carry-over pattern from
    backfill_concall_transcripts.py).
  * Idempotent UPSERT into related_party_transactions (matches the
    composite UNIQUE in migration 017).
  * Sample-fallback path so the rest of the pipeline (service layer,
    summary aggregation, red-flag rules, frontend chip) can be developed
    and tested without a working extractor.

Source URL patterns (documented for the Phase-2 implementer):

  BSE annual-report PDFs are served from
    https://www.bseindia.com/xml-data/corpfiling/AttachLive/{guid}.pdf
  Index page (per-company, per-year):
    https://www.bseindia.com/corporates/ann.html?scrip={bse_code}

  NSE annual-report listing:
    https://www.nseindia.com/companies-listing/corporate-filings-annual-reports
  JSON feed:
    https://www.nseindia.com/api/annual-reports?index=equities&symbol={NSE_SYMBOL}

  SEBI's online portal (cross-check):
    https://www.sebi.gov.in/sebi_data/...

Apply migration first:
    DATABASE_URL=... python scripts/apply_migration.py \\
        data_pipeline/migrations/017_related_party_transactions.sql

Usage:
    DATABASE_URL=... python scripts/ingest_annual_reports.py \\
        --tickers RELIANCE,TCS --year 2025 --dry-run
    DATABASE_URL=... python scripts/ingest_annual_reports.py \\
        --use-sample-fixture --year 2025

Phase-2 work is gated on:
  * Choosing the section-finding regex strategy (PyMuPDF text vs
    pdfplumber word boxes vs OCR fallback for scanned ARs).
  * Choosing Groq vs Gemini for extraction (cost vs accuracy tradeoff —
    see docs/related_party_analyzer_design.md).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("rpt_ingest")

DEFAULT_SLEEP = 1.5
DEFAULT_TOP = 100

# AOC-2 / MGT-9 section-header regex starter set. Phase-2 work will
# expand this — annual reports are surprisingly free-form. Some put
# AOC-2 as a standalone schedule, others embed it inside Notes.
SECTION_HEADER_PATTERNS = [
    r"\bForm\s*AOC[-\s]*2\b",
    r"\bMGT[-\s]*9\b",
    r"\bRelated\s+Party\s+Transactions\b",
    r"\bParticulars\s+of\s+contracts.*related\s+parties\b",
]


# ---------------------------------------------------------------------------
# HTTP fetch + page-range identification — STUBBED.
# ---------------------------------------------------------------------------

def fetch_annual_report_pdf(ticker: str, fiscal_year: int) -> Optional[bytes]:
    """Download the AR PDF for (ticker, FY). STUB.

    Phase-1 implementation:
      1. Resolve ticker → BSE code via existing universe data.
      2. Hit BSE listing page, parse for the AR matching the FY.
      3. GET the PDF, follow redirects, return bytes.
      4. Fall back to NSE feed if BSE 404s.
    """
    # TODO(phase-1): real BSE / NSE fetch with retries + polite sleep.
    logger.info("STUB fetch_annual_report_pdf(%s, %s)", ticker, fiscal_year)
    return None


def find_rpt_page_range(pdf_bytes: bytes) -> Optional[tuple[int, int]]:
    """Locate AOC-2 / MGT-9 / RPT-notes section. STUB.

    Phase-1 implementation:
      * Use PyMuPDF (fitz) to extract text per page.
      * Match SECTION_HEADER_PATTERNS against each page.
      * Walk forwards until the next major section header to bound the
        end page (typically "Signatures to the Standalone Financial
        Statements" or the start of the next note).
    """
    # TODO(phase-1): PDF parsing via PyMuPDF or pdfplumber.
    return None


# ---------------------------------------------------------------------------
# LLM extraction — STUBBED. See backend/services/related_party_service.py
# for the prompt template.
# ---------------------------------------------------------------------------

def extract_rpts_with_llm(
    pdf_bytes: bytes,
    page_start: int,
    page_end: int,
    ticker: str,
    fiscal_year: int,
) -> List[Dict[str, Any]]:
    """Phase-2 LLM call. STUB."""
    # TODO(phase-2): Groq or Gemini call. Use LLM_SYSTEM_PROMPT /
    # LLM_USER_PROMPT_TEMPLATE from related_party_service.
    return []


# ---------------------------------------------------------------------------
# Sample-fixture loader — supports the --use-sample-fixture path.
# ---------------------------------------------------------------------------

SAMPLE_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "sample_rpts.json"


def load_sample_rows(
    tickers: Optional[List[str]],
    fiscal_year: Optional[int],
) -> List[Dict[str, Any]]:
    if not SAMPLE_FIXTURE_PATH.exists():
        logger.warning("Sample fixture missing at %s", SAMPLE_FIXTURE_PATH)
        return []
    with open(SAMPLE_FIXTURE_PATH, encoding="utf-8") as fh:
        blob = json.load(fh)
    rows: List[Dict[str, Any]] = list(blob.get("rows", []))
    if tickers:
        wanted = {t.upper() for t in tickers}
        rows = [r for r in rows if r["ticker"].upper() in wanted]
    if fiscal_year:
        rows = [r for r in rows if int(r["fiscal_year"]) == int(fiscal_year)]
    return rows


# ---------------------------------------------------------------------------
# DB writer — idempotent UPSERT.
# ---------------------------------------------------------------------------

UPSERT_SQL = """
INSERT INTO related_party_transactions (
    ticker, fiscal_year, source_filing, related_party_name, related_party_type,
    txn_type, amount_inr, is_arms_length, description, source_pdf_url,
    source_page, llm_extracted, llm_confidence, human_reviewed
) VALUES (
    :ticker, :fiscal_year, :source_filing, :related_party_name, :related_party_type,
    :txn_type, :amount_inr, :is_arms_length, :description, :source_pdf_url,
    :source_page, :llm_extracted, :llm_confidence, :human_reviewed
)
ON CONFLICT (ticker, fiscal_year, related_party_name, txn_type, amount_inr)
DO UPDATE SET
    is_arms_length = EXCLUDED.is_arms_length,
    description    = COALESCE(EXCLUDED.description, related_party_transactions.description),
    llm_confidence = GREATEST(
        COALESCE(EXCLUDED.llm_confidence, 0),
        COALESCE(related_party_transactions.llm_confidence, 0)
    ),
    fetched_at = NOW();
"""


def upsert_rows(rows: Iterable[Dict[str, Any]], dry_run: bool) -> int:
    rows = list(rows)
    if dry_run:
        logger.info("DRY-RUN: would upsert %d rows", len(rows))
        return 0

    try:
        from sqlalchemy import text
        from db.engine import get_engine  # type: ignore
    except Exception as exc:
        logger.error("DB layer not importable: %s", exc)
        return 0

    written = 0
    with get_engine().begin() as conn:
        for r in rows:
            conn.execute(text(UPSERT_SQL), {
                "ticker": r["ticker"].upper(),
                "fiscal_year": int(r["fiscal_year"]),
                "source_filing": r.get("source_filing", "AnnualReport"),
                "related_party_name": r["related_party_name"],
                "related_party_type": r.get("related_party_type"),
                "txn_type": r["txn_type"],
                "amount_inr": r.get("amount_inr"),
                "is_arms_length": r.get("is_arms_length"),
                "description": r.get("description"),
                "source_pdf_url": r.get("source_pdf_url"),
                "source_page": r.get("source_page"),
                "llm_extracted": r.get("llm_extracted", True),
                "llm_confidence": r.get("llm_confidence"),
                "human_reviewed": r.get("human_reviewed", False),
            })
            written += 1
    return written


# ---------------------------------------------------------------------------
# Per-ticker pipeline driver.
# ---------------------------------------------------------------------------

def process_ticker(ticker: str, fiscal_year: int, sleep_s: float) -> List[Dict[str, Any]]:
    """STUB end-to-end pipeline for one (ticker, FY)."""
    pdf = fetch_annual_report_pdf(ticker, fiscal_year)
    if pdf is None:
        logger.info("[%s FY%s] no AR PDF — skipping (Phase-1 work)", ticker, fiscal_year)
        return []
    page_range = find_rpt_page_range(pdf)
    if page_range is None:
        logger.info("[%s FY%s] could not locate RPT section", ticker, fiscal_year)
        return []
    p0, p1 = page_range
    rows = extract_rpts_with_llm(pdf, p0, p1, ticker, fiscal_year)
    time.sleep(sleep_s)
    return rows


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--tickers", help="Comma-separated ticker override")
    p.add_argument("--top", type=int, default=DEFAULT_TOP,
                   help="Top-N tickers by market cap (default 100)")
    p.add_argument("--all", action="store_true", help="All active tickers")
    p.add_argument("--year", type=int, required=True, help="Fiscal year, e.g. 2025")
    p.add_argument("--sleep", type=float, default=DEFAULT_SLEEP,
                   help="Seconds between requests (default 1.5)")
    p.add_argument("--dry-run", action="store_true", help="Compute but do not write")
    p.add_argument("--use-sample-fixture", action="store_true",
                   help="Skip the (stubbed) PDF/LLM path and ingest from "
                        "tests/fixtures/sample_rpts.json instead. Useful for "
                        "exercising the rest of the pipeline.")
    return p.parse_args(argv)


def _resolve_tickers(args) -> List[str]:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.use_sample_fixture:
        # All five fixture tickers.
        return ["RELIANCE", "INFY", "TCS", "ADANIENT", "NIRMA"]
    # Production path would hit the universe-resolver here.
    # TODO(phase-1): wire to data_pipeline universe lookup once Phase-1
    # PDF/LLM extraction is real.
    logger.warning("No --tickers provided and not using fixture. "
                   "Phase-1 universe resolver not implemented yet.")
    return []


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    tickers = _resolve_tickers(args)
    logger.info("Ingest plan: %d tickers, FY%s, dry_run=%s, sample=%s",
                len(tickers), args.year, args.dry_run, args.use_sample_fixture)

    all_rows: List[Dict[str, Any]] = []
    if args.use_sample_fixture:
        all_rows = load_sample_rows(tickers, args.year)
        logger.info("Sample fixture provided %d rows", len(all_rows))
    else:
        for t in tickers:
            try:
                rows = process_ticker(t, args.year, sleep_s=args.sleep)
                all_rows.extend(rows)
            except Exception:
                logger.exception("[%s] failed; continuing", t)

    written = upsert_rows(all_rows, dry_run=args.dry_run)
    logger.info("Done. rows_collected=%d rows_written=%d", len(all_rows), written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
