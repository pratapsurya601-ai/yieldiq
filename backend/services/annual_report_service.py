# backend/services/annual_report_service.py
# ===============================================================
# Annual Report (AR) augmentation service.
#
# This service ingests annual reports (PDFs) and extracts STRUCTURED
# data using the Claude (Anthropic) API. The extracted data is an
# AUGMENTATION LAYER on top of existing data sources -- it does NOT
# replace daily prices, quarterly results, or live corporate actions.
#
# ARs are uniquely valuable for:
#   * Segment data (fixes conglomerate DCF -- RELIANCE, ITC, etc.)
#   * Capex commitments from MD&A (forward modeling)
#   * Auditor's going-concern flags (early warning)
#   * Contingent liabilities (risk pillar input)
#   * Related-party transactions (governance signal)
#
# Phase 1 (current): scaffold only.
#   * discover_ar_url, download_ar_pdf, extract_ar_structured_data
#     all raise NotImplementedError unless explicitly mocked.
#   * save_ar_data and get_ar_for_ticker are real DB helpers and
#     are exercised by tests against the migration-027 schema.
#   * No anthropic SDK in requirements.txt yet -- added in Phase 2.
#
# Phase 2 (next PR):
#   * Implement discover_ar_url against the BSE filings index.
#   * Implement download_ar_pdf with retry + sha256 capture.
#   * Wire extract_ar_structured_data to the real Anthropic client,
#     with the system prompt embedded and prompt caching enabled.
#
# Phase 3:
#   * Nightly job: backfill top 200 tickers, then keep current.
#   * analysis_service consumes segment_data for conglomerate DCFs.
# ===============================================================
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("yieldiq.annual_report")

EXTRACTOR_VERSION = "ar-extractor-v0-scaffold"

# -- Extracted JSON shape (stored across the JSONB columns of
#    company_annual_reports). Documented here so the Phase-2
#    extractor prompt and the Phase-3 analysis consumers agree
#    on a single source of truth. --------------------------------
#
# {
#   "segment_data": [
#     {"segment": "Food Delivery",
#      "revenue_cr": 12345,
#      "ebitda_cr": 678,
#      "fy": "2024"}
#   ],
#   "capex_commitments": [
#     {"amount_cr": 800,
#      "fy": "2025",
#      "project": "Blinkit dark store expansion"}
#   ],
#   "auditor_flags": [
#     {"type": "going_concern|emphasis_of_matter|qualified_opinion",
#      "description": "...",
#      "as_of": "2024-03-31"}
#   ],
#   "contingent_liabilities": [
#     {"description": "Tax disputes",
#      "amount_cr": 234,
#      "as_of": "2024-03-31"}
#   ],
#   "related_party_transactions": [
#     {"counterparty": "...",
#      "relationship": "subsidiary|kmp|associate|...",
#      "nature": "sales|loans|guarantees|...",
#      "amount_cr": 12.3,
#      "fy": "2024"}
#   ],
#   "mda_summary": "free-text MD&A summary (<=1500 chars)"
# }


# -- Discovery & download (Phase-2 stubs) -----------------------

def discover_ar_url(
    ticker: str,
    fiscal_year: int,
    client: Optional[Any] = None,
) -> Optional[str]:
    """Look up the AR PDF URL for (ticker, fiscal_year).

    Phase-1 scaffold. Phase-2 will scrape the BSE filings index
    (and fall back to NSE / company website) to resolve the URL.

    Args:
        ticker: NSE/BSE ticker symbol.
        fiscal_year: Fiscal year ending March, e.g. 2024 = FY24.
        client: Optional HTTP client (httpx-like) for the Phase-2
            implementation. Kept here so tests can inject a mock
            without re-shaping the API.

    Raises:
        NotImplementedError: until Phase-2 wires the BSE filings
        index scraper. We refuse to silently return None so a
        misconfigured caller fails loudly.
    """
    if client is None:
        raise NotImplementedError(
            "annual_report_service.discover_ar_url: BSE/NSE filings "
            "index scraping is a Phase-2 task. Inject an HTTP client "
            "(or a mock in tests) to use the discovery path."
        )
    # Phase-2 implementation will go here.
    raise NotImplementedError("Phase-2: BSE filings index discovery")


def download_ar_pdf(
    url: str,
    client: Optional[Any] = None,
) -> bytes:
    """Download an AR PDF and return its bytes.

    Phase-1 scaffold. Phase-2 will:
      * GET the URL with a sensible UA and retry policy
      * Verify content-type is application/pdf
      * Cap size (annual reports are typically 5-30 MB)
      * Return the raw bytes (sha256 is computed by the caller)

    Args:
        url: HTTPS URL to the AR PDF.
        client: Optional HTTP client (httpx-like). Phase-2 will
            default to a module-level client with timeouts.

    Raises:
        NotImplementedError: until Phase-2 implements the fetch.
    """
    if client is None:
        raise NotImplementedError(
            "annual_report_service.download_ar_pdf: HTTP fetch is a "
            "Phase-2 task. Inject an HTTP client (or a mock in tests)."
        )
    raise NotImplementedError("Phase-2: PDF download")


# -- Extraction (Phase-2 stub) ----------------------------------

def extract_ar_structured_data(
    pdf_bytes: bytes,
    ticker: str,
    fiscal_year: int,
    anthropic_client: Optional[Any] = None,
) -> dict:
    """Extract structured data from an AR PDF using Claude Sonnet.

    Phase-1 scaffold. The real implementation (Phase 2) will:
      1. Upload the PDF via the Anthropic Files API (or inline if
         small enough).
      2. Call ``anthropic_client.messages.create(...)`` with a
         system prompt that embeds the schema above and uses
         prompt caching for the schema portion.
      3. Parse + validate the JSON tool-use payload.
      4. Return the dict in the documented shape.

    Args:
        pdf_bytes: Raw PDF bytes.
        ticker: NSE/BSE ticker symbol.
        fiscal_year: Fiscal year (e.g. 2024 for FY24).
        anthropic_client: An anthropic.Anthropic-compatible client.
            If None, the call raises NotImplementedError. Tests
            should inject a Mock client. We refuse to silently
            run so misconfigured code paths never hit the live
            API by accident.

    Returns:
        dict matching the schema documented at module level.

    Raises:
        NotImplementedError: if no anthropic_client supplied.
        ValueError: invalid inputs.
    """
    if anthropic_client is None:
        raise NotImplementedError(
            "annual_report_service.extract_ar_structured_data: live "
            "Anthropic client wiring is a Phase-2 task. Inject a "
            "client (or a mock in tests) to use the parsing path."
        )

    if not ticker or not isinstance(ticker, str):
        raise ValueError("ticker must be a non-empty string")
    if not isinstance(fiscal_year, int) or fiscal_year < 1990:
        raise ValueError("fiscal_year must be a sensible int year")
    if not pdf_bytes or len(pdf_bytes) < 1024:
        raise ValueError(
            "pdf_bytes too small (<1KB) -- pass real AR PDF bytes."
        )

    # Phase-2 will go here. For now the stub just refuses, so even
    # a test that injects a client but expects real extraction will
    # need to land alongside the Phase-2 prompt + parsing work.
    raise NotImplementedError(
        "Phase-2: implement Claude Sonnet extraction over PDF bytes."
    )


# -- DB persistence ---------------------------------------------

def _connect():
    """Open a psycopg2 connection. Returns None if DATABASE_URL is
    unset or the connect fails -- callers must handle the None.
    Same pattern as backend/services/concall_intel_service.py."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(url)
    except Exception as exc:
        logger.debug("annual_report: psycopg2.connect failed (%s)", exc)
        return None


_ALLOWED_SOURCES = {"bse", "nse", "company_website", "manual"}


def _validate_extracted(extracted: dict) -> None:
    """Lightweight schema check on the extracted payload before insert.

    We intentionally do NOT enforce every nested field -- the JSONB
    columns are meant to evolve. We only validate the top-level
    shape so a typo in a key name (e.g. "segments" vs "segment_data")
    fails fast instead of silently writing into the wrong column.
    """
    if not isinstance(extracted, dict):
        raise ValueError("extracted must be a dict")

    list_keys = (
        "segment_data",
        "capex_commitments",
        "auditor_flags",
        "contingent_liabilities",
        "related_party_transactions",
    )
    for key in list_keys:
        val = extracted.get(key)
        if val is not None and not isinstance(val, list):
            raise ValueError(f"extracted[{key!r}] must be a list or None")

    mda = extracted.get("mda_summary")
    if mda is not None and not isinstance(mda, str):
        raise ValueError("extracted['mda_summary'] must be a string or None")


def save_ar_data(
    ticker: str,
    fiscal_year: int,
    ar_url: Optional[str],
    extracted: dict,
    source: str = "bse",
    ar_pdf_sha256: Optional[str] = None,
    published_at: Optional[str] = None,
) -> bool:
    """UPSERT a company_annual_reports row for (ticker, fiscal_year).

    Returns True on success, False if the DB is unreachable. Does
    not raise on DB errors -- callers can decide whether to retry.

    Args:
        ticker: NSE/BSE ticker symbol.
        fiscal_year: e.g. 2024 for FY24.
        ar_url: HTTPS URL the PDF was fetched from (may be None
            for source='manual').
        extracted: dict matching the schema documented at module
            level. Validated by _validate_extracted before insert.
        source: 'bse' | 'nse' | 'company_website' | 'manual'.
        ar_pdf_sha256: hex sha256 of the downloaded PDF bytes
            (None for source='manual' if not computed).
        published_at: ISO date string (YYYY-MM-DD) of AR publish.

    Raises:
        ValueError: invalid inputs or extracted schema.
    """
    if not ticker or not isinstance(ticker, str):
        raise ValueError("ticker must be a non-empty string")
    if not isinstance(fiscal_year, int) or fiscal_year < 1990:
        raise ValueError("fiscal_year must be a sensible int year")
    if source not in _ALLOWED_SOURCES:
        raise ValueError(
            f"source must be one of {sorted(_ALLOWED_SOURCES)}, got {source!r}"
        )
    _validate_extracted(extracted)

    conn = _connect()
    if conn is None:
        logger.info(
            "save_ar_data: no DATABASE_URL -- skipping persist for %s FY%s",
            ticker, fiscal_year,
        )
        return False

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO company_annual_reports (
                        ticker, fiscal_year, ar_url, ar_pdf_sha256,
                        source, published_at,
                        segment_data, capex_commitments, auditor_flags,
                        contingent_liabilities, related_party_transactions,
                        mda_summary, extractor_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (ticker, fiscal_year) DO UPDATE SET
                        ar_url                       = EXCLUDED.ar_url,
                        ar_pdf_sha256                = EXCLUDED.ar_pdf_sha256,
                        source                       = EXCLUDED.source,
                        published_at                 = EXCLUDED.published_at,
                        segment_data                 = EXCLUDED.segment_data,
                        capex_commitments            = EXCLUDED.capex_commitments,
                        auditor_flags                = EXCLUDED.auditor_flags,
                        contingent_liabilities       = EXCLUDED.contingent_liabilities,
                        related_party_transactions   = EXCLUDED.related_party_transactions,
                        mda_summary                  = EXCLUDED.mda_summary,
                        ingested_at                  = now(),
                        extractor_version            = EXCLUDED.extractor_version
                    """,
                    (
                        ticker,
                        fiscal_year,
                        ar_url,
                        ar_pdf_sha256,
                        source,
                        published_at,
                        json.dumps(extracted.get("segment_data") or []),
                        json.dumps(extracted.get("capex_commitments") or []),
                        json.dumps(extracted.get("auditor_flags") or []),
                        json.dumps(extracted.get("contingent_liabilities") or []),
                        json.dumps(extracted.get("related_party_transactions") or []),
                        extracted.get("mda_summary"),
                        extracted.get("extractor_version", EXTRACTOR_VERSION),
                    ),
                )
        return True
    except Exception as exc:
        logger.warning("save_ar_data UPSERT failed: %s", exc)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_ar_for_ticker(
    ticker: str,
    fiscal_year: Optional[int] = None,
) -> Optional[dict]:
    """Read path used by the (Phase-3) analysis service.

    If fiscal_year is provided, returns that specific AR row.
    Otherwise returns the most recent AR available for the ticker.

    Returns None if:
      * DATABASE_URL is unset / connect fails (logged at debug),
      * No matching row exists.

    The returned dict mirrors the company_annual_reports row plus
    parsed JSONB values (so callers don't have to json.loads).
    """
    if not ticker or not isinstance(ticker, str):
        raise ValueError("ticker must be a non-empty string")

    conn = _connect()
    if conn is None:
        return None

    try:
        with conn:
            with conn.cursor() as cur:
                if fiscal_year is not None:
                    cur.execute(
                        """
                        SELECT ticker, fiscal_year, ar_url, ar_pdf_sha256,
                               source, published_at, ingested_at,
                               segment_data, capex_commitments, auditor_flags,
                               contingent_liabilities,
                               related_party_transactions,
                               mda_summary, extractor_version
                        FROM company_annual_reports
                        WHERE ticker = %s AND fiscal_year = %s
                        LIMIT 1
                        """,
                        (ticker, fiscal_year),
                    )
                else:
                    cur.execute(
                        """
                        SELECT ticker, fiscal_year, ar_url, ar_pdf_sha256,
                               source, published_at, ingested_at,
                               segment_data, capex_commitments, auditor_flags,
                               contingent_liabilities,
                               related_party_transactions,
                               mda_summary, extractor_version
                        FROM company_annual_reports
                        WHERE ticker = %s
                        ORDER BY fiscal_year DESC
                        LIMIT 1
                        """,
                        (ticker,),
                    )
                row = cur.fetchone()
                if row is None:
                    return None
                cols = [
                    "ticker", "fiscal_year", "ar_url", "ar_pdf_sha256",
                    "source", "published_at", "ingested_at",
                    "segment_data", "capex_commitments", "auditor_flags",
                    "contingent_liabilities", "related_party_transactions",
                    "mda_summary", "extractor_version",
                ]
                return dict(zip(cols, row))
    except Exception as exc:
        logger.debug("get_ar_for_ticker query failed: %s", exc)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass
