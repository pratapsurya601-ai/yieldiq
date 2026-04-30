# data_pipeline/sources/nse_flows_deals.py
# Fetches NSE bulk deals, block deals, and FII/DII daily flow snapshot.
#
# NSE has no historical archive for any of these — only current-day
# snapshots. The companion daily cron .github/workflows/nse_flows_daily.yml
# self-archives by running shortly after market close (19:00 IST).
#
# Endpoints (verified):
#   - https://www.nseindia.com/api/snapshot-capital-market-largedeal
#       returns BULK_DEALS_DATA + BLOCK_DEALS_DATA in one call.
#   - https://archives.nseindia.com/content/equities/bulk.csv
#   - https://archives.nseindia.com/content/equities/block.csv
#       rolling current-day CSV fallbacks (~10KB).
#   - https://www.nseindia.com/api/fiidiiTradeReact
#       FII + DII buy/sell/net for current trading day.
#
# Anti-bot: NSE blocks plain requests. Use curl_cffi with chrome
# impersonation; warm cookies via homepage GET first.
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

NSE_HOME = "https://www.nseindia.com"
NSE_LARGEDEAL_URL = (
    "https://www.nseindia.com/api/snapshot-capital-market-largedeal"
)
NSE_FII_DII_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
NSE_BULK_CSV = "https://archives.nseindia.com/content/equities/bulk.csv"
NSE_BLOCK_CSV = "https://archives.nseindia.com/content/equities/block.csv"


def _get_session():
    """curl_cffi chrome-impersonating session with warmed NSE cookies."""
    from curl_cffi import requests as cffi
    s = cffi.Session(impersonate="chrome")
    s.get(NSE_HOME, timeout=30)
    return s


def _to_int(v: Any) -> int:
    if v is None:
        return 0
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (ValueError, TypeError):
        return 0


def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _norm_buy_sell(v: Any) -> str:
    s = str(v or "").strip().upper()
    if s in ("BUY", "B"):
        return "B"
    if s in ("SELL", "S"):
        return "S"
    return s[:1] if s else ""


def _parse_deal_row(item: dict, deal_type: str) -> dict | None:
    """Normalize one bulk/block deal row to the bulk_block_deals schema."""
    ticker = str(item.get("symbol") or item.get("BD_SYMBOL") or "").strip()
    if not ticker:
        return None

    raw_date = (
        item.get("date")
        or item.get("BD_DT_DATE")
        or item.get("dealDate")
    )
    try:
        deal_date = pd.to_datetime(raw_date, dayfirst=True).date()
    except Exception:
        deal_date = date.today()

    client = str(
        item.get("clientName")
        or item.get("BD_CLIENT_NAME")
        or ""
    ).strip()

    bs = _norm_buy_sell(
        item.get("buySell")
        or item.get("BD_BUY_SELL")
    )
    if bs not in ("B", "S"):
        return None

    qty = _to_int(
        item.get("quantity")
        or item.get("qty")
        or item.get("BD_QTY_TRD")
    )
    price = _to_float(
        item.get("watp")
        or item.get("avgPrice")
        or item.get("BD_TP_WATP")
        or item.get("weightedAvgPrice")
    )

    return {
        "ticker": ticker,
        "deal_date": deal_date,
        "deal_type": deal_type,
        "client_name": client[:200],
        "buy_sell": bs,
        "quantity": qty,
        "price": price,
        "exchange": "NSE",
    }


def _fetch_csv_fallback(session, url: str, deal_type: str) -> list[dict]:
    """Fallback to archives.nseindia.com CSV when JSON API is empty/blocked."""
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            logger.warning("CSV %s returned HTTP %s", url, resp.status_code)
            return []
        text = resp.text or ""
        if not text.strip():
            return []
        reader = csv.DictReader(io.StringIO(text))
        rows: list[dict] = []
        for raw in reader:
            # Normalize keys (CSV headers may have spaces / case quirks)
            norm = {k.strip().lower().replace(" ", "_"): v for k, v in raw.items() if k}
            item = {
                "symbol": norm.get("symbol"),
                "date": norm.get("date"),
                "clientName": norm.get("client_name"),
                "buySell": norm.get("buy/sell") or norm.get("buy_/_sell"),
                "quantity": (
                    norm.get("quantity_traded")
                    or norm.get("qty")
                    or norm.get("quantity")
                ),
                "watp": (
                    norm.get("trade_price_/_wght._avg._price")
                    or norm.get("trade_price")
                    or norm.get("price")
                    or norm.get("wap")
                ),
            }
            parsed = _parse_deal_row(item, deal_type)
            if parsed:
                rows.append(parsed)
        return rows
    except Exception as exc:
        logger.warning("CSV fallback failed for %s: %s", url, exc)
        return []


def fetch_bulk_deals_today() -> list[dict]:
    """Returns bulk-deal rows shaped for bulk_block_deals."""
    session = _get_session()
    rows: list[dict] = []
    try:
        resp = session.get(NSE_LARGEDEAL_URL, timeout=30)
        if resp.status_code == 200:
            data = resp.json() or {}
            for item in data.get("BULK_DEALS_DATA", []) or []:
                parsed = _parse_deal_row(item, "bulk")
                if parsed:
                    rows.append(parsed)
        else:
            logger.warning("largedeal API HTTP %s", resp.status_code)
    except Exception as exc:
        logger.warning("largedeal API failed: %s", exc)

    if not rows:
        rows = _fetch_csv_fallback(session, NSE_BULK_CSV, "bulk")

    logger.info("fetch_bulk_deals_today: %d rows", len(rows))
    return rows


def fetch_block_deals_today() -> list[dict]:
    """Returns block-deal rows shaped for bulk_block_deals."""
    session = _get_session()
    rows: list[dict] = []
    try:
        resp = session.get(NSE_LARGEDEAL_URL, timeout=30)
        if resp.status_code == 200:
            data = resp.json() or {}
            for item in data.get("BLOCK_DEALS_DATA", []) or []:
                parsed = _parse_deal_row(item, "block")
                if parsed:
                    rows.append(parsed)
        else:
            logger.warning("largedeal API HTTP %s", resp.status_code)
    except Exception as exc:
        logger.warning("largedeal API failed: %s", exc)

    if not rows:
        rows = _fetch_csv_fallback(session, NSE_BLOCK_CSV, "block")

    logger.info("fetch_block_deals_today: %d rows", len(rows))
    return rows


def fetch_fii_dii_today() -> list[dict]:
    """Returns rows shaped for fii_dii_flows: trade_date, category, buy/sell/net."""
    session = _get_session()
    rows: list[dict] = []
    try:
        resp = session.get(NSE_FII_DII_URL, timeout=30)
        if resp.status_code != 200:
            logger.warning("fiidiiTradeReact HTTP %s", resp.status_code)
            return rows
        data = resp.json() or []
    except Exception as exc:
        logger.error("fiidiiTradeReact failed: %s", exc)
        return rows

    for item in data:
        cat = (item.get("category") or "").strip().upper()
        if cat.startswith("FII") or cat.startswith("FPI"):
            category = "FII"
        elif cat.startswith("DII"):
            category = "DII"
        else:
            continue

        raw_date = item.get("date")
        try:
            trade_date = pd.to_datetime(raw_date, dayfirst=True).date()
        except Exception:
            trade_date = date.today()

        rows.append({
            "trade_date": trade_date,
            "category": category,
            "buy_value_cr": _to_float(item.get("buyValue")),
            "sell_value_cr": _to_float(item.get("sellValue")),
            "net_value_cr": _to_float(item.get("netValue")),
        })

    logger.info("fetch_fii_dii_today: %d rows", len(rows))
    return rows


# --------------------------------------------------------------------------
# UPSERTs — psycopg2 path, used by the daily GH-Actions cron.
# --------------------------------------------------------------------------

UPSERT_DEAL_SQL = """
INSERT INTO bulk_block_deals
    (ticker, deal_date, deal_type, client_name, buy_sell,
     quantity, price, exchange)
VALUES
    (%(ticker)s, %(deal_date)s, %(deal_type)s, %(client_name)s, %(buy_sell)s,
     %(quantity)s, %(price)s, %(exchange)s)
ON CONFLICT ON CONSTRAINT uq_bulk_block_deal DO UPDATE SET
    price = EXCLUDED.price,
    fetched_at = NOW();
"""

UPSERT_FLOW_SQL = """
INSERT INTO fii_dii_flows
    (trade_date, category, buy_value_cr, sell_value_cr, net_value_cr)
VALUES
    (%(trade_date)s, %(category)s, %(buy_value_cr)s,
     %(sell_value_cr)s, %(net_value_cr)s)
ON CONFLICT ON CONSTRAINT uq_fii_dii_day DO UPDATE SET
    buy_value_cr = EXCLUDED.buy_value_cr,
    sell_value_cr = EXCLUDED.sell_value_cr,
    net_value_cr = EXCLUDED.net_value_cr;
"""


def upsert_deals(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(UPSERT_DEAL_SQL, rows)
    conn.commit()
    return len(rows)


def upsert_flows(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(UPSERT_FLOW_SQL, rows)
    conn.commit()
    return len(rows)


def run_daily(dsn: str | None = None) -> dict:
    """Top-level entrypoint used by the daily GH-Actions cron."""
    import os
    import psycopg2

    url = dsn or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    bulk = fetch_bulk_deals_today()
    block = fetch_block_deals_today()
    flows = fetch_fii_dii_today()

    conn = psycopg2.connect(url)
    try:
        n_bulk = upsert_deals(conn, bulk)
        n_block = upsert_deals(conn, block)
        n_flow = upsert_flows(conn, flows)
    finally:
        conn.close()

    return {
        "bulk_upserted": n_bulk,
        "block_upserted": n_block,
        "flows_upserted": n_flow,
        "ran_at": datetime.utcnow().isoformat(),
    }


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_daily(), indent=2, default=str))
