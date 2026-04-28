"""sebi_filings_crawler.py — SCAFFOLDING for automated SEBI quarterly-
results ingestion.

This is the foundation only. The real BSE/NSE corporate-filings crawler
needs:

* Robust cookie priming + residential proxies (NSE has Cloudflare and
  aggressive rate limits — see backend/services/sebi_sast_service.py
  for the cookie-prime pattern we already use).
* A dedupe key tighter than (ticker, filing_type, fiscal_period,
  exchange) — some companies file partial / revised disclosures that
  share that tuple but differ by SEQ_ID.
* Retry with exponential backoff and a dead-letter handoff when
  retry_count > 3.
* Cache invalidation hook (see open question 4 in the design doc).

The discover_new_filings / process_pending functions in this module
are STUBS that exercise the data model without hitting the network.

Source endpoints (documented for the real implementation):

  BSE corporate filings JSON
    https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w
    ?strCat=Result&strPrevDate=YYYYMMDD&strToDate=YYYYMMDD&strScrip=&strSearch=P
    Attachment URL pattern:
    https://www.bseindia.com/xml-data/corpfiling/AttachLive/<UUID>.pdf

  NSE corporate financial results
    https://www.nseindia.com/api/corporates-financial-results
    ?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY&period=Quarterly
    XBRL URL is in the `xbrl` field of each row.

Recommended cron:
    */30 *  * * 1-6   discover (lookback_hours=2)
    */10 *  * * 1-6   process_pending (limit=50)

Never run discover with an unbounded lookback in production — it will
hammer BSE/NSE and trip Cloudflare.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

logger = logging.getLogger("yieldiq.workers.sebi_filings_crawler")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Endpoint templates (kept here so the real fetcher has one place to look)
# ---------------------------------------------------------------------------

_BSE_HOME = "https://www.bseindia.com/"
_BSE_ANNOUNCEMENTS_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
    "?strCat=Result&strPrevDate={from_d}&strToDate={to_d}"
    "&strScrip=&strSearch=P"
)
_BSE_ATTACH_URL = (
    "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attachment_id}"
)

_NSE_HOME = "https://www.nseindia.com/"
_NSE_FINANCIALS_URL = (
    "https://www.nseindia.com/api/corporates-financial-results"
    "?index=equities&from_date={from_d}&to_date={to_d}&period={period}"
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; YieldIQ/1.0)",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

VALID_FILING_TYPES = {
    "quarterly_results",
    "annual_report",
    "investor_presentation",
    "press_release",
    "corporate_action",
    "other",
}

VALID_EXCHANGES = {"BSE", "NSE"}

VALID_STATUSES = {
    "pending", "downloaded", "parsed", "ingested", "failed", "skipped",
}


@dataclass
class FilingMetadata:
    ticker: str
    filing_type: str
    filing_date: date
    source_exchange: str
    source_url: str
    fiscal_period: Optional[str] = None
    pdf_url: Optional[str] = None
    xbrl_url: Optional[str] = None

    def __post_init__(self) -> None:
        self.ticker = (self.ticker or "").upper().strip()
        if self.filing_type not in VALID_FILING_TYPES:
            raise ValueError(f"invalid filing_type {self.filing_type!r}")
        if self.source_exchange not in VALID_EXCHANGES:
            raise ValueError(f"invalid exchange {self.source_exchange!r}")
        if isinstance(self.filing_date, datetime):
            self.filing_date = self.filing_date.date()


# ---------------------------------------------------------------------------
# Discover (STUB — does not hit network)
# ---------------------------------------------------------------------------

def discover_new_filings(lookback_hours: int = 24) -> list[FilingMetadata]:
    """Return new filings detected on BSE / NSE in the last `lookback_hours`.

    SCAFFOLDING: this stub returns an empty list. The real implementation
    will:

    1. Prime NSE/BSE cookies (see backend/services/sebi_sast_service.py).
    2. GET both endpoints for the date window.
    3. Map rows -> FilingMetadata using a per-exchange normaliser.
    4. Filter to tickers tracked in `tickers` table.

    Until then, callers should rely on enqueue_filing() with externally
    sourced metadata (e.g. a one-off backfill JSON).
    """
    if lookback_hours <= 0:
        raise ValueError("lookback_hours must be positive")
    logger.info(
        "discover_new_filings STUB called (lookback_hours=%d). "
        "No network calls — returning [].",
        lookback_hours,
    )
    return []


def _bse_url_for(from_d: date, to_d: date) -> str:
    return _BSE_ANNOUNCEMENTS_URL.format(
        from_d=from_d.strftime("%Y%m%d"),
        to_d=to_d.strftime("%Y%m%d"),
    )


def _nse_url_for(from_d: date, to_d: date, period: str = "Quarterly") -> str:
    return _NSE_FINANCIALS_URL.format(
        from_d=from_d.strftime("%d-%m-%Y"),
        to_d=to_d.strftime("%d-%m-%Y"),
        period=period,
    )


# ---------------------------------------------------------------------------
# Enqueue (idempotent UPSERT)
# ---------------------------------------------------------------------------

def enqueue_filing(metadata: FilingMetadata, *, conn=None) -> Optional[int]:
    """Idempotent UPSERT into sebi_filings_queue.

    Returns the row id, or None if no DB connection is available
    (dev / test env without DATABASE_URL).

    A `conn` may be passed for tests; otherwise a fresh connection is
    grabbed from data_pipeline.db.engine.
    """
    own_conn = False
    cur = None
    try:
        if conn is None:
            try:
                from data_pipeline.db import engine
            except Exception as exc:
                logger.warning("enqueue_filing: pipeline engine import failed: %s", exc)
                return None
            if engine is None:
                return None
            conn = engine.raw_connection()
            own_conn = True

        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO sebi_filings_queue (
              ticker, filing_type, fiscal_period, filing_date,
              source_exchange, source_url, pdf_url, xbrl_url, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            ON CONFLICT (ticker, filing_type, fiscal_period, source_exchange)
              DO UPDATE SET
                filing_date = EXCLUDED.filing_date,
                source_url  = EXCLUDED.source_url,
                pdf_url     = COALESCE(EXCLUDED.pdf_url, sebi_filings_queue.pdf_url),
                xbrl_url    = COALESCE(EXCLUDED.xbrl_url, sebi_filings_queue.xbrl_url)
            RETURNING id
            """,
            (
                metadata.ticker,
                metadata.filing_type,
                metadata.fiscal_period,
                metadata.filing_date,
                metadata.source_exchange,
                metadata.source_url,
                metadata.pdf_url,
                metadata.xbrl_url,
            ),
        )
        row = cur.fetchone()
        if own_conn:
            conn.commit()
        return int(row[0]) if row else None
    except Exception:
        if own_conn and conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Process pending (STUB hand-off to existing parsers)
# ---------------------------------------------------------------------------

def _mark(conn, row_id: int, status: str, *, error: Optional[str] = None,
          ingested: bool = False) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE sebi_filings_queue
               SET status = %s,
                   error_message = %s,
                   retry_count = retry_count + CASE WHEN %s = 'failed' THEN 1 ELSE 0 END,
                   ingested_at = CASE WHEN %s THEN NOW() ELSE ingested_at END
             WHERE id = %s
            """,
            (status, error, status, ingested, row_id),
        )
    finally:
        cur.close()


def process_pending(limit: int = 50, *, conn=None, dry_run: bool = False) -> dict:
    """Walk pending filings and transition them through the lifecycle.

    SCAFFOLDING: this only walks state. The real implementation should:

    * Download xbrl_url and hand to data_pipeline.sources.nse_xbrl_fundamentals
      (specifically the parse helper inside that module — extract a public
      `parse_xbrl_bytes()` first so this module doesn't import URL fetchers).
    * For PDF-only filings, route to the LLM extractor (see open question 3).
    * On parsed → ingested, call filing_alert_service.notify_users_of_new_quarterly.
    * Bump analysis_cache for that ticker (see open question 4).

    Returns counters: {processed, ingested, failed, skipped}.
    """
    out = {"processed": 0, "ingested": 0, "failed": 0, "skipped": 0}

    own_conn = False
    if conn is None:
        try:
            from data_pipeline.db import engine
        except Exception as exc:
            logger.warning("process_pending: pipeline engine import failed: %s", exc)
            return out
        if engine is None:
            return out
        conn = engine.raw_connection()
        own_conn = True

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, ticker, filing_type, fiscal_period,
                   pdf_url, xbrl_url, retry_count
              FROM sebi_filings_queue
             WHERE status = 'pending'
             ORDER BY detected_at ASC
             LIMIT %s
            """,
            (int(limit),),
        )
        rows = cur.fetchall()
        cur.close()

        for row in rows:
            row_id, ticker, ftype, period, pdf_url, xbrl_url, retries = row
            out["processed"] += 1
            if dry_run:
                logger.info("DRY-RUN: would process id=%s %s %s", row_id, ticker, period)
                continue

            try:
                # STUB: real path is download → parse → ingest.
                if xbrl_url:
                    # data_pipeline.sources.nse_xbrl_fundamentals.parse_xbrl_bytes(...)
                    _mark(conn, row_id, "ingested", ingested=True)
                    out["ingested"] += 1
                elif pdf_url:
                    # PDF path — LLM extraction not implemented (see design doc Q3).
                    _mark(conn, row_id, "skipped", error="pdf_path_not_implemented")
                    out["skipped"] += 1
                else:
                    _mark(conn, row_id, "skipped", error="no_xbrl_no_pdf")
                    out["skipped"] += 1
            except Exception as exc:
                logger.exception("process_pending: row %s failed: %s", row_id, exc)
                _mark(conn, row_id, "failed", error=str(exc)[:500])
                out["failed"] += 1

        if own_conn:
            conn.commit()
    except Exception:
        if own_conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if own_conn:
            try:
                conn.close()
            except Exception:
                pass

    logger.info("process_pending complete: %s", out)
    return out


# ---------------------------------------------------------------------------
# Retry helper (used by the cron driver)
# ---------------------------------------------------------------------------

def with_backoff(fn, *args, attempts: int = 3, base_delay: float = 2.0, **kwargs):
    """Run `fn` with exponential backoff. Pattern matches sebi_sast_service."""
    last_exc: Optional[Exception] = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            time.sleep(base_delay * (2 ** i))
    if last_exc is not None:
        raise last_exc
    return None
