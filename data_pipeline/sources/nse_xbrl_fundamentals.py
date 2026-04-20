"""Fundamentals source via NSE's corporate-financial-results API.

NSE publishes the same SEBI-mandated XBRL that BSE does, but serves it
openly at ``nsearchives.nseindia.com`` (no Akamai wall). The filings-
index endpoint ``/api/corporates-financial-results`` returns 20+ years
of annual + quarterly records per ticker, each with a direct ``xbrl``
URL.

Pipeline
--------
1. Fetch list of filings: ``/api/corporates-financial-results?
   symbol=RELIANCE&period=Annual`` (also ``Quarterly``)
2. For each filing, download the XBRL XML from the ``xbrl`` field
3. Parse with lxml, extracting key in-bse-fin tags by local-name
   (namespace-agnostic so IGAAP 2011, Ind-AS 2016, Ind-AS 2020 all
   map cleanly to the same canonical fields).
4. Return rows in the same shape as bse_xbrl.fetch_historical_financials
   so store_financials() works unchanged.

Per ticker: 1 master call + 10-40 XBRL downloads = ~8s serial budget.
With 5-shard matrix on GH Actions, 5,500 tickers ≈ 75 min.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)


NSE_API_BASE = "https://www.nseindia.com/api"
NSE_WARMUP = "https://www.nseindia.com/get-quotes/equity?symbol={symbol}"

# ── session helper ───────────────────────────────────────────────────

def _get_session():
    """curl_cffi Chrome-impersonate session (NSE blocks plain requests)."""
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        logger.error("curl_cffi required: pip install curl_cffi")
        raise
    s = cffi.Session(impersonate="chrome")
    try:
        s.get("https://www.nseindia.com/", timeout=15)
    except Exception:
        pass
    return s


# ── filings-list ─────────────────────────────────────────────────────

def fetch_filings_list(
    symbol: str, period: str = "Annual", session=None,
) -> list[dict[str, Any]]:
    """Return list of filing metadata dicts.

    period: 'Annual' or 'Quarterly'
    """
    if session is None:
        session = _get_session()
    # Warm symbol page for per-symbol cookies
    try:
        session.get(NSE_WARMUP.format(symbol=symbol), timeout=10)
    except Exception:
        pass
    url = (
        f"{NSE_API_BASE}/corporates-financial-results"
        f"?index=equities&symbol={symbol}&period={period}"
    )
    try:
        r = session.get(url, timeout=20, headers={"Accept": "application/json"})
    except Exception as exc:
        logger.info("nse filings list error %s: %s", symbol, exc)
        return []
    if r.status_code != 200:
        logger.info("nse filings list HTTP %d for %s", r.status_code, symbol)
        return []
    try:
        data = r.json()
    except Exception:
        return []
    return data if isinstance(data, list) else []


# ── XBRL parsing ─────────────────────────────────────────────────────

# Canonical-to-candidate tag map. Values are lists of XBRL element
# local-names we've seen populated for each canonical field. Priority
# order matters — first non-null wins.
_FIELD_TAGS = {
    "revenue": [
        "RevenueFromOperations",
        "RevenueFromOperationsTotal",
        "TotalRevenueFromOperations",
        "NetSalesOrRevenueFromOperations",
        "IncomeFromOperations",
    ],
    "total_income": [
        "TotalIncome",
        "TotalRevenue",
    ],
    "pat": [
        "ProfitLossForPeriod",
        "ProfitLossForThePeriod",
        "ProfitAfterTaxFromContinuingOperations",
        "NetProfit",
    ],
    "pbt": [
        "ProfitLossBeforeTaxFromContinuingOperations",
        "ProfitBeforeTax",
    ],
    "eps_diluted": [
        "DilutedEarningsPerShareAfterExtraordinaryItems",
        "DilutedEarningsPerShareBeforeExtraordinaryItems",
        "DilutedEarningsLossPerShareFromContinuingOperations",
        "DilutedEarningsPerShare",
        "BasicEarningsPerShareAfterExtraordinaryItems",
        "BasicEarningsPerShareBeforeExtraordinaryItems",
        "BasicEarningsLossPerShareFromContinuingOperations",
        "BasicEarningsPerShare",
        "DilutedEPS",
        "BasicEPS",
    ],
    "total_expenses": [
        "TotalExpenses",
        "Expenses",
    ],
    "depreciation": [
        "DepreciationDepletionAndAmortisationExpense",
        "DepreciationAndAmortisationExpense",
        "DepreciationAmortizationAndDepletionExpense",
    ],
    "finance_cost": [
        "FinanceCosts",
        "InterestExpense",
    ],
    # Balance sheet
    "total_debt": [
        "Borrowings",
        "LongTermBorrowings",
        "BorrowingsCurrent",
        "BorrowingsNonCurrent",
    ],
    "total_equity": [
        "EquityAttributableToOwnersOfParent",
        "Equity",
        "ShareholdersFunds",
        "TotalEquity",
    ],
    "cash": [
        "CashAndCashEquivalents",
        "CashAndBankBalances",
    ],
    # Cash flow
    "cfo": [
        "CashFlowsFromUsedInOperatingActivities",
        "NetCashFlowFromOperatingActivities",
    ],
    "capex": [
        "PurchaseOfPropertyPlantAndEquipment",
        "PurchaseOfFixedAssets",
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ],
}


def _localname(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _parse_num(txt: str | None) -> float | None:
    if txt is None:
        return None
    s = str(txt).strip()
    if not s or s.upper() in ("NIL", "NA", "-"):
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def _extract_facts(xml_bytes: bytes) -> dict[str, list[tuple[float, str]]]:
    """Return {localname: [(value, contextRef), ...]} for all numeric facts."""
    try:
        from lxml import etree
    except ImportError:
        from xml.etree import ElementTree as etree  # type: ignore

    try:
        root = etree.fromstring(xml_bytes)
    except Exception as exc:
        logger.debug("xbrl parse fail: %s", exc)
        return {}

    facts: dict[str, list[tuple[float, str]]] = {}
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        ln = _localname(el.tag)
        txt = (el.text or "").strip()
        if not txt:
            continue
        val = _parse_num(txt)
        if val is None:
            continue
        ctx = el.get("contextRef") or ""
        facts.setdefault(ln, []).append((val, ctx))
    return facts


def _extract_contexts(xml_bytes: bytes) -> dict[str, dict[str, Any]]:
    """Return {contextId: {start, end, instant, scenario}} for period resolution."""
    try:
        from lxml import etree
    except ImportError:
        from xml.etree import ElementTree as etree  # type: ignore
    try:
        root = etree.fromstring(xml_bytes)
    except Exception:
        return {}

    ctx_map: dict[str, dict[str, Any]] = {}
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if _localname(el.tag) != "context":
            continue
        cid = el.get("id")
        if not cid:
            continue
        info: dict[str, Any] = {}
        for child in el.iter():
            ln = _localname(child.tag)
            if ln == "startDate":
                info["start"] = (child.text or "").strip()
            elif ln == "endDate":
                info["end"] = (child.text or "").strip()
            elif ln == "instant":
                info["instant"] = (child.text or "").strip()
        ctx_map[cid] = info
    return ctx_map


def _pick_value(facts, contexts, local_names, period_end: date) -> float | None:
    """Pick the first non-null value whose context matches period_end."""
    period_end_s = period_end.isoformat()
    for ln in local_names:
        candidates = facts.get(ln, [])
        # First pass: exact end-date / instant match
        for val, ctx in candidates:
            ci = contexts.get(ctx, {})
            if ci.get("end") == period_end_s or ci.get("instant") == period_end_s:
                return val
        # Second pass: any match (take largest magnitude as a fallback for consolidated > standalone)
        if candidates:
            return max(candidates, key=lambda x: abs(x[0]))[0]
    return None


def parse_nse_xbrl(xml_bytes: bytes, ticker: str, period_end: date,
                    period_type: str = "annual") -> dict[str, Any] | None:
    """Parse one XBRL file into our canonical financials row shape."""
    facts = _extract_facts(xml_bytes)
    if not facts:
        return None
    contexts = _extract_contexts(xml_bytes)

    revenue = _pick_value(facts, contexts, _FIELD_TAGS["revenue"], period_end)
    if revenue is None:
        revenue = _pick_value(facts, contexts, _FIELD_TAGS["total_income"], period_end)
    pat = _pick_value(facts, contexts, _FIELD_TAGS["pat"], period_end)
    eps = _pick_value(facts, contexts, _FIELD_TAGS["eps_diluted"], period_end)
    depreciation = _pick_value(facts, contexts, _FIELD_TAGS["depreciation"], period_end)
    pbt = _pick_value(facts, contexts, _FIELD_TAGS["pbt"], period_end)
    total_debt = _pick_value(facts, contexts, _FIELD_TAGS["total_debt"], period_end)
    total_equity = _pick_value(facts, contexts, _FIELD_TAGS["total_equity"], period_end)
    cash = _pick_value(facts, contexts, _FIELD_TAGS["cash"], period_end)
    cfo = _pick_value(facts, contexts, _FIELD_TAGS["cfo"], period_end)
    capex = _pick_value(facts, contexts, _FIELD_TAGS["capex"], period_end)

    # XBRL values are in INR. Our DB stores in Crores (1 Cr = 1e7 INR).
    # Most NSE XBRLs file in actual INR; some file in Rs Crore already.
    # Heuristic: if revenue > 1e7 × 100 (i.e. >100 Cr in raw INR), scale down.
    def _to_cr(x):
        if x is None:
            return None
        if abs(x) > 1e9:  # > 100 Cr in raw INR
            return x / 1e7
        return x

    # EBITDA proxy: PBT + depreciation + finance cost
    finance_cost = _pick_value(facts, contexts, _FIELD_TAGS["finance_cost"], period_end)
    ebitda = None
    if pbt is not None:
        parts = [pbt]
        if depreciation is not None:
            parts.append(depreciation)
        if finance_cost is not None:
            parts.append(finance_cost)
        ebitda = sum(parts)

    return {
        "ticker": ticker,
        "period_end": period_end,
        "period_type": period_type,
        "revenue": _to_cr(revenue),
        "pat": _to_cr(pat),
        "ebitda": _to_cr(ebitda),
        "cfo": _to_cr(cfo),
        "capex": _to_cr(capex),
        "total_debt": _to_cr(total_debt),
        "total_equity": _to_cr(total_equity),
        "cash": _to_cr(cash),
        "eps_diluted": eps,  # already per-share rupees
        "source": "NSE_XBRL",
    }


# ── top-level ingest ─────────────────────────────────────────────────

_DATE_RE = re.compile(r"(\d{2})-(\w{3})-(\d{4})")
_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}


def _parse_nse_date(s: str) -> date | None:
    """'31-Mar-2024' -> date(2024,3,31); '01-APR-2023' -> date(2023,4,1)."""
    if not s:
        return None
    m = _DATE_RE.match(s.strip())
    if not m:
        return None
    d, mon_s, y = m.group(1), m.group(2).upper(), m.group(3)
    mon = _MONTHS.get(mon_s[:3])
    if not mon:
        return None
    try:
        return date(int(y), mon, int(d))
    except Exception:
        return None


def fetch_ticker_financials(
    symbol: str,
    session=None,
    max_annual: int = 15,
    max_quarterly: int = 40,
    sleep: float = 0.3,
) -> list[dict[str, Any]]:
    """Top-level: fetch ticker's filings list, download + parse each XBRL.

    Returns rows list (annual + quarterly) ready for store_financials().
    """
    if session is None:
        session = _get_session()

    all_rows: list[dict[str, Any]] = []

    for period, cap in (("Annual", max_annual), ("Quarterly", max_quarterly)):
        filings = fetch_filings_list(symbol, period, session=session)
        if not filings:
            continue
        # Keep the most recent `cap` filings (NSE returns newest first)
        filings = filings[:cap]

        seen_periods: set[date] = set()
        for f in filings:
            to_s = f.get("toDate") or f.get("to_date")
            period_end = _parse_nse_date(to_s) if to_s else None
            if period_end is None:
                continue
            if period_end in seen_periods:
                # Prefer earlier filing (first seen) which is usually the
                # most recent submission. NSE frequently has duplicates.
                continue
            seen_periods.add(period_end)

            xbrl_url = f.get("xbrl")
            if not xbrl_url or not xbrl_url.startswith("http"):
                continue

            try:
                r = session.get(xbrl_url, timeout=20)
            except Exception as exc:
                logger.debug("xbrl fetch fail %s: %s", xbrl_url, exc)
                continue
            if r.status_code != 200 or len(r.content) < 500:
                continue

            row = parse_nse_xbrl(
                r.content, symbol, period_end,
                period_type="annual" if period == "Annual" else "quarterly",
            )
            if row:
                all_rows.append(row)

            time.sleep(sleep)

    return all_rows
