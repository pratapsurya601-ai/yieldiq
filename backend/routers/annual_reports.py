# backend/routers/annual_reports.py
# ═══════════════════════════════════════════════════════════════
# Phase H-frontend: public-read AR signal endpoints.
#
# Two endpoints, both no-auth and read-only against the ar_signals
# table populated by extract_ar_signals_batch.py (migration 060):
#
#   1. GET /api/v1/annual-reports/{ar_id}/signals
#        Returns the most-recent signals row for a specific
#        company_annual_reports.id. Useful for the operator
#        review surface and any per-AR drilldown.
#
#   2. GET /api/v1/annual-reports/signals/by-ticker/{ticker}/latest
#        Returns the most-recent (by published_at DESC,
#        fiscal_year DESC) signals row for a ticker. This is what
#        the public ARSignalsPanel on /analysis/[ticker] consumes.
#
# Both endpoints follow the same withheld-protocol used by the
# concall signals router: when quality_flag == 'sebi_withheld' we
# collapse the payload to {signals: null, withheld: true, ...}
# so the frontend never renders free-text content that the
# JSON-walking SEBI sanitizer flagged.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from backend.services.ar_segment_validator import validate_segment_rows

logger = logging.getLogger("yieldiq.annual_reports")

router = APIRouter(prefix="/api/v1/annual-reports", tags=["annual-reports"])


def _connect_signals():
    """Open a psycopg2 connection. Returns None on missing
    DATABASE_URL or driver-import failure so the endpoints can
    downgrade to a {signals: null} 200 response instead of 500-ing
    the analysis page.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(url)
    except Exception as exc:
        logger.debug("ar signals: psycopg2.connect failed (%s)", exc)
        return None


def _parse_jsonb(value: Any) -> Any:
    """psycopg2 returns JSONB as either dict/list (when the
    connection has the JSON adapter registered) or as a raw JSON
    string. Normalise to the Python object.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _row_to_payload(row: tuple) -> dict:
    """Convert a SELECTed row to the public JSON shape. Centralised
    so the two endpoints can't drift.

    Row layout MUST match _SIGNALS_SELECT below.
    """
    (
        signals_id,
        annual_report_id,
        segment_data,
        capex_commitments,
        related_party_transactions,
        auditor_flags,
        contingent_liabilities,
        management_outlook,
        quality_flag,
        model_version,
        prompt_version,
        extracted_at,
        ticker,
        fiscal_year,
        ar_url,
        published_at,
    ) = row

    base_envelope = {
        "ticker": ticker,
        "fiscal_year": int(fiscal_year) if fiscal_year is not None else None,
        "annual_report_id": int(annual_report_id),
        "quality_flag": quality_flag,
        "generated_at": extracted_at.isoformat() if extracted_at else None,
        "ar_url": ar_url,
        "published_at": published_at.isoformat() if published_at else None,
    }

    # SEBI-withheld rows return a neutral envelope. We expose
    # metadata so the operator review surface can find the row,
    # but the free-text signals are nulled.
    if (quality_flag or "").lower() == "sebi_withheld":
        return {**base_envelope, "signals": None, "withheld": True}

    # ROOT CAUSE #9 — stamp segment_data rows with unit_validated /
    # validation_reason so the frontend can hide rows flagged as
    # likely unit-misreads (e.g. HDFCBANK FY25 "Retail Banking —
    # Digital" Revenue ₹8.59 Cr). The validator is a pure
    # post-processor; we never mutate the underlying ar_signals
    # row. See backend/services/ar_segment_validator.py.
    raw_segments = _parse_jsonb(segment_data) or []
    stamped_segments = validate_segment_rows(raw_segments)
    return {
        **base_envelope,
        "withheld": False,
        "signals": {
            "segment_data": stamped_segments,
            "capex_commitments": _parse_jsonb(capex_commitments) or [],
            "related_party_transactions":
                _parse_jsonb(related_party_transactions) or [],
            "auditor_flags": _parse_jsonb(auditor_flags) or [],
            "contingent_liabilities":
                _parse_jsonb(contingent_liabilities) or [],
            "management_outlook": management_outlook,
            "model_version": model_version,
            "prompt_version":
                int(prompt_version) if prompt_version is not None else None,
        },
    }


# Joined SELECT against company_annual_reports so callers get the
# ticker / fiscal_year / ar_url metadata in a single round-trip.
_SIGNALS_SELECT = (
    "SELECT s.id, s.annual_report_id, "
    "s.segment_data, s.capex_commitments, "
    "s.related_party_transactions, s.auditor_flags, "
    "s.contingent_liabilities, s.management_outlook, "
    "s.quality_flag, s.model_version, s.prompt_version, s.extracted_at, "
    "car.ticker, car.fiscal_year, car.ar_url, car.published_at "
    "FROM ar_signals s "
    "JOIN company_annual_reports car ON car.id = s.annual_report_id "
)


def _empty_payload() -> dict:
    return {
        "signals": None,
        "withheld": False,
        "ticker": None,
        "fiscal_year": None,
        "annual_report_id": None,
        "quality_flag": None,
        "generated_at": None,
        "ar_url": None,
        "published_at": None,
    }


@router.get("/{ar_id}/signals")
async def get_signals_for_ar(ar_id: int):
    """Return the latest ar_signals row for a given AR.

    Many ARs will have only one row (single model_version /
    prompt_version), but the operator can re-extract at a bumped
    prompt; we return the most-recent by extracted_at. When no
    row exists, return a 200 with {signals: null} so the caller
    doesn't need a special 404 path.
    """
    if ar_id is None or ar_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="ar_id must be a positive integer",
        )
    conn = _connect_signals()
    if conn is None:
        return _empty_payload()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    _SIGNALS_SELECT
                    + "WHERE s.annual_report_id = %s "
                    "ORDER BY s.extracted_at DESC LIMIT 1",
                    (ar_id,),
                )
                row = cur.fetchone()
        if not row:
            return _empty_payload()
        return _row_to_payload(row)
    except Exception as exc:
        logger.warning("get_signals_for_ar(%s) failed: %s", ar_id, exc)
        return _empty_payload()
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/signals/by-ticker/{ticker}/latest")
async def get_latest_signals_for_ticker(ticker: str):
    """Return the most-recent ar_signals row for a ticker.

    Backs the public ARSignalsPanel. Strips .NS / .BO suffix so
    RELIANCE.NS and bare RELIANCE both match. Picks the row with
    the highest (published_at, fiscal_year) -- a fresh AR for the
    latest FY beats a re-extraction of an older one.
    """
    raw = (ticker or "").strip().upper()
    if not raw:
        raise HTTPException(status_code=400, detail="ticker required")
    bare = raw
    for suffix in (".NS", ".BO"):
        if bare.endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    conn = _connect_signals()
    if conn is None:
        return _empty_payload()
    try:
        with conn:
            with conn.cursor() as cur:
                # Match the bare ticker or the suffixed forms to
                # be defensive against historical writes that
                # included a suffix.
                cur.execute(
                    _SIGNALS_SELECT
                    + "WHERE car.ticker IN (%s, %s, %s) "
                    "ORDER BY car.published_at DESC NULLS LAST, "
                    "         car.fiscal_year DESC, "
                    "         s.extracted_at DESC "
                    "LIMIT 1",
                    (bare, f"{bare}.NS", f"{bare}.BO"),
                )
                row = cur.fetchone()
        if not row:
            return _empty_payload()
        return _row_to_payload(row)
    except Exception as exc:
        logger.warning(
            "get_latest_signals_for_ticker(%s) failed: %s", bare, exc,
        )
        return _empty_payload()
    finally:
        try:
            conn.close()
        except Exception:
            pass
