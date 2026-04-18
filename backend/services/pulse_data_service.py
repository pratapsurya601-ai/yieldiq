"""
pulse_data_service.py — Pulse axis data aggregator (Agent D).

The 6th axis of the YieldIQ Hex combines market/behavioral signals:
  - promoter stake changes (QoQ)
  - insider trading (net 30d, INR Cr)
  - analyst estimate revisions (30d)
  - pledged shares delta (QoQ)
  - institutional bulk/block flow (30d, INR Cr)

Every source is optional: if it fails, we log and skip — the pulse_raw
score is computed from whatever inputs we have. This service is called
by `backend/scripts/pulse_daily.py` from a GitHub Actions cron. It is
NOT intended to run on Railway (we have a single-worker constraint).

Nothing here constitutes investment advice — these are raw signals
that feed into the Hex score.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger("yieldiq.pulse")
if not logger.handlers:
    # Ensure something comes out even if the caller hasn't configured logging.
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# DB session bootstrapping
# ---------------------------------------------------------------------------

def _get_session_factory():
    """Return the SQLAlchemy Session factory from data_pipeline.db.

    Handles sys.path setup so this works from both backend/ and script
    contexts. Returns None if DATABASE_URL is not configured.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from data_pipeline.db import Session  # type: ignore
        return Session
    except Exception as exc:  # pragma: no cover
        logger.warning("PULSE: could not import data_pipeline.db.Session: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Table bootstrap (idempotent backup so service works even without migration)
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hex_pulse_inputs (
  ticker TEXT PRIMARY KEY,
  promoter_delta_qoq NUMERIC,
  insider_net_30d NUMERIC,
  estimate_revision_30d NUMERIC,
  pledged_pct_delta NUMERIC,
  institutional_flow_30d NUMERIC,
  pulse_raw NUMERIC,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sources_used JSONB
);
CREATE INDEX IF NOT EXISTS idx_hex_pulse_inputs_computed
  ON hex_pulse_inputs (computed_at);
"""


def ensure_table() -> bool:
    """Create hex_pulse_inputs if missing. Returns True on success."""
    Session = _get_session_factory()
    if Session is None:
        return False
    from sqlalchemy import text as _t  # local import
    try:
        sess = Session()
        try:
            for stmt in _CREATE_TABLE_SQL.strip().split(";"):
                s = stmt.strip()
                if s:
                    sess.execute(_t(s))
            sess.commit()
            return True
        finally:
            sess.close()
    except Exception as exc:
        logger.warning("PULSE: ensure_table failed: %s", exc)
        return False


# Run on import as a safety net. Silently no-ops if DB unavailable
# (e.g. during unit tests without DATABASE_URL).
try:
    ensure_table()
except Exception:
    pass


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def clamp(x: float, lo: float, hi: float) -> float:
    if x is None:
        return 0.0
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return 0.0


def sign_sqrt(x: float) -> float:
    """Signed square root — compresses magnitude without losing direction."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v == 0:
        return 0.0
    return math.copysign(math.sqrt(abs(v)), v)


# ---------------------------------------------------------------------------
# HTTP helper (shared UA, retry)
# ---------------------------------------------------------------------------

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (YieldIQ Pulse Pipeline; +https://yieldiq.in) "
        "Python/requests"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _http_get(url: str, *, headers: Optional[Dict[str, str]] = None,
              timeout: int = 30, retries: int = 1) -> Optional[bytes]:
    """GET with a realistic UA and one retry on 403/5xx. Returns body or None."""
    import requests  # local import so unit tests don't need it
    merged = dict(_DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    last_err: Optional[str] = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=merged, timeout=timeout)
            if resp.status_code == 200:
                return resp.content
            if resp.status_code in (403, 429) or 500 <= resp.status_code < 600:
                last_err = f"HTTP {resp.status_code}"
                time.sleep(1.5 * (attempt + 1))
                continue
            last_err = f"HTTP {resp.status_code}"
            break
        except Exception as exc:
            last_err = str(exc)
            time.sleep(1.5 * (attempt + 1))
    logger.info("PULSE: GET %s failed (%s)", url, last_err)
    return None


# ---------------------------------------------------------------------------
# Source 1 — yfinance analyst estimate revisions
# ---------------------------------------------------------------------------

def fetch_yf_estimate_revisions(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """Returns {ticker: {"revision_score": float in [-1,+1], "raw": {...}}}.

    Uses `.recommendations` dataframe if available; counts rows within
    the last 30 days and bucketizes "To Grade" into up/down/flat. Falls
    back to `.upgrades_downgrades` if the new yfinance surface is present.
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("PULSE: yfinance unavailable (%s)", exc)
        return out

    up_words = {"buy", "strong buy", "outperform", "overweight",
                "accumulate", "add", "positive", "upgrade"}
    down_words = {"sell", "strong sell", "underperform", "underweight",
                  "reduce", "negative", "downgrade"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    for t in tickers:
        yf_symbol = t if "." in t else f"{t}.NS"
        try:
            tk = yf.Ticker(yf_symbol)
            df = None
            # Prefer the newer upgrades_downgrades dataframe when present.
            for attr in ("upgrades_downgrades", "recommendations"):
                try:
                    df = getattr(tk, attr)
                except Exception:
                    df = None
                if df is not None and hasattr(df, "empty") and not df.empty:
                    break

            if df is None or not hasattr(df, "empty") or df.empty:
                continue

            ups = downs = total = 0
            # Normalise dataframe — index may be DatetimeIndex, or "Date"
            # column; action column may be "To Grade" / "ToGrade" / "Action".
            try:
                idx = df.index
                rows = []
                for i in range(len(df)):
                    row = df.iloc[i]
                    try:
                        date = idx[i]
                        if hasattr(date, "to_pydatetime"):
                            date = date.to_pydatetime()
                        if date.tzinfo is None:
                            date = date.replace(tzinfo=timezone.utc)
                    except Exception:
                        date = None
                    if date is not None and date < cutoff:
                        continue
                    grade = None
                    for col in ("ToGrade", "To Grade", "toGrade", "Action", "action"):
                        if col in df.columns:
                            val = row.get(col)
                            if val:
                                grade = str(val).strip().lower()
                                break
                    rows.append(grade)

                for g in rows:
                    total += 1
                    if not g:
                        continue
                    if any(w in g for w in up_words):
                        ups += 1
                    elif any(w in g for w in down_words):
                        downs += 1
            except Exception as exc:
                logger.debug("PULSE: %s revision parse error: %s", t, exc)
                continue

            if total <= 0:
                continue
            score = (ups - downs) / max(total, 1)
            out[t] = {
                "revision_score": float(score),
                "raw": {"ups": ups, "downs": downs, "total": total},
            }
        except Exception as exc:
            logger.debug("PULSE: yf revisions failed for %s: %s", t, exc)
            continue

    logger.info("PULSE: yf_estimate_revisions got %d/%d tickers", len(out), len(tickers))
    return out


# ---------------------------------------------------------------------------
# Source 2 — NSE bulk + block deals (last 30 days)
# ---------------------------------------------------------------------------

_NSE_BULK_URL = "https://archives.nseindia.com/products/content/equities/bulk_deals/bulk.csv"
_NSE_BLOCK_URL = "https://archives.nseindia.com/products/content/equities/block_deals/block.csv"


def _parse_nse_deals_csv(body: bytes) -> List[Dict[str, Any]]:
    """Parse NSE bulk/block CSV. Columns vary slightly between feeds but
    include Date, Symbol, Client Name, Buy/Sell, Quantity, Trade Price."""
    import csv
    rows: List[Dict[str, Any]] = []
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        return rows
    try:
        reader = csv.DictReader(io.StringIO(text))
        for r in reader:
            rows.append(r)
    except Exception as exc:
        logger.info("PULSE: NSE CSV parse error: %s", exc)
    return rows


def fetch_nse_deals(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """Returns {ticker: {"flow_cr": float, "raw": {...}}}.

    Bulk + block deals summed over last 30 days. Each deal contributes
    `quantity × price / 1e7` crore, signed by Buy/Sell.
    """
    out: Dict[str, Dict[str, Any]] = {}
    ticker_set = {t.upper() for t in tickers}

    combined_rows: List[Dict[str, Any]] = []
    for url in (_NSE_BULK_URL, _NSE_BLOCK_URL):
        body = _http_get(url, headers={"Referer": "https://www.nseindia.com/"}, retries=1)
        if not body:
            continue
        combined_rows.extend(_parse_nse_deals_csv(body))

    if not combined_rows:
        logger.info("PULSE: NSE deals — no rows fetched")
        return out

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)

    def _pick(d: Dict[str, Any], *keys: str) -> Optional[str]:
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return str(d[k]).strip()
            # case-insensitive fallback
            for kk in d.keys():
                if kk and kk.strip().lower() == k.lower():
                    v = d[kk]
                    if v not in (None, ""):
                        return str(v).strip()
        return None

    agg: Dict[str, Dict[str, float]] = {}
    for r in combined_rows:
        sym = _pick(r, "Symbol", "SYMBOL")
        if not sym:
            continue
        sym = sym.upper()
        if sym not in ticker_set:
            continue

        date_str = _pick(r, "Date", "DATE")
        if date_str:
            parsed = None
            for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                try:
                    parsed = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            if parsed and parsed < cutoff:
                continue

        buy_sell = (_pick(r, "Buy/Sell", "BUY / SELL", "BUY/SELL") or "").upper()
        qty_s = _pick(r, "Quantity Traded", "Quantity", "QTY")
        px_s = _pick(r, "Trade Price / Wght. Avg. Price", "Trade Price", "Price")
        try:
            qty = float((qty_s or "0").replace(",", ""))
            px = float((px_s or "0").replace(",", ""))
        except ValueError:
            continue
        value_cr = qty * px / 1e7
        sign = 1.0 if buy_sell.startswith("B") else (-1.0 if buy_sell.startswith("S") else 0.0)
        if sign == 0:
            continue

        bucket = agg.setdefault(sym, {"flow_cr": 0.0, "count": 0})
        bucket["flow_cr"] += sign * value_cr
        bucket["count"] += 1

    for sym, data in agg.items():
        out[sym] = {
            "flow_cr": round(data["flow_cr"], 3),
            "raw": {"deal_count": data["count"]},
        }
    logger.info("PULSE: NSE deals matched %d/%d tickers", len(out), len(tickers))
    return out


# ---------------------------------------------------------------------------
# Source 3 — BSE shareholding pattern (promoter %, pledged %)
# ---------------------------------------------------------------------------
# Skipped for v1: stocks table has no bse_code column. Placeholder kept so
# future wiring is trivial.

def fetch_bse_shareholding(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """Returns {ticker: {"promoter_delta_qoq": float, "pledged_pct_delta": float}}.

    v1 STUB: stocks table lacks a bse_code mapping. When bse_code is added,
    fetch https://api.bseindia.com/BseIndiaAPI/api/ShareholdingPattern/w?scripcode={code}
    and diff the two most-recent quarters for promoter % and pledged %.
    """
    logger.info("PULSE: bse_shareholding — not implemented (no bse_code mapping); skipping")
    return {}


# ---------------------------------------------------------------------------
# Source 4 — SEBI SAST / insider trading disclosures
# ---------------------------------------------------------------------------

def fetch_sebi_insider(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """Returns {ticker: {"insider_net_cr": float}}.

    v1 STUB: SEBI search is too brittle for a cron. Disclosures (Reg 7(2))
    live at https://www.sebi.gov.in/ — on next iteration, ingest via the
    official XBRL filings rather than scraping the search UI.
    """
    logger.info("PULSE: sebi_insider — not implemented; skipping")
    return {}


# ---------------------------------------------------------------------------
# Pulse score
# ---------------------------------------------------------------------------

def compute_pulse_raw(inputs: Dict[str, Any]) -> float:
    """Combine the signals into a -10..+10 raw score. Missing signals
    simply do not contribute."""
    score = 0.0
    if inputs.get("promoter_delta_qoq") is not None:
        score += 2.0 * clamp(inputs["promoter_delta_qoq"], -5, 5)
    if inputs.get("insider_net_30d") is not None:
        score += 1.5 * sign_sqrt(inputs["insider_net_30d"] / 100.0)
    if inputs.get("estimate_revision_30d") is not None:
        score += 3.0 * clamp(inputs["estimate_revision_30d"], -1, 1)
    if inputs.get("pledged_pct_delta") is not None:
        score -= 1.5 * clamp(inputs["pledged_pct_delta"], -10, 10)
    if inputs.get("institutional_flow_30d") is not None:
        score += 1.0 * sign_sqrt(inputs["institutional_flow_30d"] / 100.0)
    return clamp(score, -10, 10)


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT INTO hex_pulse_inputs (
    ticker, promoter_delta_qoq, insider_net_30d, estimate_revision_30d,
    pledged_pct_delta, institutional_flow_30d, pulse_raw,
    computed_at, sources_used
) VALUES (
    :ticker, :promoter_delta_qoq, :insider_net_30d, :estimate_revision_30d,
    :pledged_pct_delta, :institutional_flow_30d, :pulse_raw,
    now(), CAST(:sources_used AS JSONB)
)
ON CONFLICT (ticker) DO UPDATE SET
    promoter_delta_qoq     = EXCLUDED.promoter_delta_qoq,
    insider_net_30d        = EXCLUDED.insider_net_30d,
    estimate_revision_30d  = EXCLUDED.estimate_revision_30d,
    pledged_pct_delta      = EXCLUDED.pledged_pct_delta,
    institutional_flow_30d = EXCLUDED.institutional_flow_30d,
    pulse_raw              = EXCLUDED.pulse_raw,
    computed_at            = now(),
    sources_used           = EXCLUDED.sources_used
"""


def upsert_pulse_row(session, row: Dict[str, Any]) -> None:
    from sqlalchemy import text as _t
    params = {
        "ticker": row["ticker"],
        "promoter_delta_qoq": row.get("promoter_delta_qoq"),
        "insider_net_30d": row.get("insider_net_30d"),
        "estimate_revision_30d": row.get("estimate_revision_30d"),
        "pledged_pct_delta": row.get("pledged_pct_delta"),
        "institutional_flow_30d": row.get("institutional_flow_30d"),
        "pulse_raw": row.get("pulse_raw"),
        "sources_used": json.dumps(row.get("sources_used") or {}),
    }
    session.execute(_t(_UPSERT_SQL), params)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def load_top_tickers(limit: int = 500) -> List[str]:
    """Top-N tickers by market_cap_cr from market_metrics, active only."""
    Session = _get_session_factory()
    if Session is None:
        logger.warning("PULSE: no DB session; load_top_tickers returning []")
        return []
    from sqlalchemy import text as _t
    sess = Session()
    try:
        rows = sess.execute(_t(
            "SELECT s.ticker "
            "FROM stocks s "
            "LEFT JOIN market_metrics mm ON mm.ticker = s.ticker "
            "WHERE s.is_active = TRUE "
            "ORDER BY COALESCE(mm.market_cap_cr, 0) DESC "
            "LIMIT :lim"
        ), {"lim": int(limit)}).fetchall()
        return [r[0] for r in rows if r and r[0]]
    finally:
        sess.close()


def run_pulse_refresh(limit: int = 500) -> Dict[str, Any]:
    """Top-level entry. Fetch all sources, compute pulse_raw, upsert rows.

    Returns a summary dict for logging.
    """
    started = time.time()
    ensure_table()

    tickers = load_top_tickers(limit=limit)
    if not tickers:
        logger.warning("PULSE: no tickers loaded; aborting")
        return {"tickers": 0, "updated": 0, "sources": {}, "elapsed_s": 0.0}
    logger.info("PULSE: running refresh on %d tickers", len(tickers))

    source_results: Dict[str, Dict[str, Any]] = {}
    source_status: Dict[str, bool] = {}

    def _safe(name: str, fn: Callable[[List[str]], Dict[str, Any]]):
        try:
            res = fn(tickers) or {}
            source_results[name] = res
            source_status[name] = bool(res)
            logger.info("PULSE: source %s → %d hits", name, len(res))
        except Exception as exc:
            logger.exception("PULSE: source %s failed: %s", name, exc)
            source_results[name] = {}
            source_status[name] = False

    # Serial: each source has its own rate limiting and the ticker count
    # is small enough that parallelism isn't worth the complexity.
    _safe("yf_estimate_revisions", fetch_yf_estimate_revisions)
    _safe("nse_deals", fetch_nse_deals)
    _safe("bse_shareholding", fetch_bse_shareholding)
    _safe("sebi_insider", fetch_sebi_insider)

    Session = _get_session_factory()
    if Session is None:
        logger.warning("PULSE: no DB session; skipping upserts")
        return {
            "tickers": len(tickers),
            "updated": 0,
            "sources": source_status,
            "elapsed_s": time.time() - started,
        }

    updated = 0
    sess = Session()
    try:
        for t in tickers:
            inputs: Dict[str, Any] = {
                "ticker": t,
                "promoter_delta_qoq": None,
                "insider_net_30d": None,
                "estimate_revision_30d": None,
                "pledged_pct_delta": None,
                "institutional_flow_30d": None,
            }
            used: Dict[str, bool] = {}

            yf_hit = source_results.get("yf_estimate_revisions", {}).get(t)
            if yf_hit:
                inputs["estimate_revision_30d"] = yf_hit.get("revision_score")
                used["yf_estimate_revisions"] = True

            deals_hit = source_results.get("nse_deals", {}).get(t)
            if deals_hit:
                inputs["institutional_flow_30d"] = deals_hit.get("flow_cr")
                used["nse_deals"] = True

            bse_hit = source_results.get("bse_shareholding", {}).get(t)
            if bse_hit:
                if bse_hit.get("promoter_delta_qoq") is not None:
                    inputs["promoter_delta_qoq"] = bse_hit["promoter_delta_qoq"]
                if bse_hit.get("pledged_pct_delta") is not None:
                    inputs["pledged_pct_delta"] = bse_hit["pledged_pct_delta"]
                used["bse_shareholding"] = True

            sebi_hit = source_results.get("sebi_insider", {}).get(t)
            if sebi_hit and sebi_hit.get("insider_net_cr") is not None:
                inputs["insider_net_30d"] = sebi_hit["insider_net_cr"]
                used["sebi_insider"] = True

            # Skip rows with nothing to write — no source matched.
            if not used:
                continue

            inputs["pulse_raw"] = compute_pulse_raw(inputs)
            inputs["sources_used"] = used

            try:
                upsert_pulse_row(sess, inputs)
                updated += 1
            except Exception as exc:
                logger.warning("PULSE: upsert failed for %s: %s", t, exc)
                sess.rollback()

        sess.commit()
    finally:
        sess.close()

    elapsed = time.time() - started
    summary = {
        "tickers": len(tickers),
        "updated": updated,
        "sources": source_status,
        "elapsed_s": round(elapsed, 2),
    }
    logger.info("PULSE: done — %s", summary)
    return summary
