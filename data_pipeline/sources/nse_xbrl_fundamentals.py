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
        # Seen on PSU oil marketers (BPCL/HPCL/IOC) Ind-AS filings where
        # the headline line is "Income from Operations" / gross revenue.
        "GrossRevenueFromOperations",
        "RevenueFromSaleOfProducts",
    ],
    "total_income": [
        "TotalIncome",
        "TotalRevenue",
        # Older IGAAP filings (pre-2016) used this alias.
        "TotalRevenueIncludingOtherIncome",
    ],
    "pat": [
        "ProfitLossForPeriod",
        "ProfitLossForThePeriod",
        "ProfitAfterTaxFromContinuingOperations",
        "NetProfit",
        # Ind-AS 2020 variant (seen on TCS/INFY/HDFCBANK).
        "ProfitLossAfterTax",
        "ProfitLossAttributableToOwnersOfParent",
    ],
    "pbt": [
        "ProfitLossBeforeTaxFromContinuingOperations",
        "ProfitBeforeTax",
        "ProfitLossBeforeTax",
        "ProfitLossBeforeExceptionalItemsAndTax",
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
        # Seen on ONGC / upstream oil filings.
        "DepreciationDepletionAmortisationAndImpairmentExpense",
    ],
    "finance_cost": [
        "FinanceCosts",
        "InterestExpense",
        "FinanceCost",
    ],
    # Operating profit / EBIT — needed for proper ROCE numerator.
    # First tag is the most common Ind-AS "profit from operations" line;
    # the explicit EBIT / EarningsBeforeInterestAndTax tags are rare
    # but worth checking before we fall back to derivation.
    "operating_profit": [
        "ProfitLossFromContinuingOperationsBeforeTax",
        "ProfitFromOperations",
        "ProfitLossFromOperatingActivities",
        "OperatingProfit",
        "EarningsBeforeInterestAndTax",
        "EBIT",
    ],
    # Balance sheet
    "total_assets": [
        "Assets",
        "TotalAssets",
        "AssetsTotal",
        "TotalOfAssets",
    ],
    "current_liabilities": [
        "CurrentLiabilities",
        "TotalCurrentLiabilities",
        "LiabilitiesCurrent",
        "CurrentLiabilitiesTotal",
    ],
    "total_debt": [
        "Borrowings",
        "LongTermBorrowings",
        "BorrowingsCurrent",
        "BorrowingsNonCurrent",
        # Ind-AS 2020 refinement seen on RELIANCE / ONGC.
        "BorrowingsNoncurrent",
        "NoncurrentBorrowings",
        "CurrentBorrowings",
    ],
    "total_equity": [
        "EquityAttributableToOwnersOfParent",
        "Equity",
        "ShareholdersFunds",
        "TotalEquity",
        # Banking schema (HDFCBANK etc.) splits capital + reserves;
        # we match on the combined roll-up when available.
        "EquityAttributableToOwnersOfTheParent",
    ],
    "cash": [
        "CashAndCashEquivalents",
        "CashAndBankBalances",
        "CashAndCashEquivalentsCashFlowStatement",
    ],
    # Cash flow
    "cfo": [
        "CashFlowsFromUsedInOperatingActivities",
        "NetCashFlowFromOperatingActivities",
        # Variants surfaced on BPCL + HPCL FY22-FY24 filings where the
        # narrower "generated" wording replaces "from/used in". Without
        # these, CFO parses as NULL and FCF breaks.
        "NetCashFlowsFromUsedInOperatingActivities",
        "CashFlowsFromUsedInOperatingActivitiesTotal",
        "CashGeneratedFromOperations",
        "NetCashGeneratedFromOperatingActivities",
        "NetCashFromUsedInOperatingActivities",
    ],
    "capex": [
        "PurchaseOfPropertyPlantAndEquipment",
        "PurchaseOfFixedAssets",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        # PSU oil/gas Ind-AS tag variants surfaced on BPCL / HPCL /
        # IOC / ONGC — parent agent's investigation found capex NULL
        # on every NSE_XBRL row for these tickers. These forms cover
        # the "property, plant, equipment and intangibles" roll-up and
        # the "cash outflow" wording used on investing-activities lines.
        "PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssets",
        "PurchaseOfPropertyPlantEquipmentAndIntangibleAssets",
        "PurchaseOfTangibleAssets",
        "AcquisitionOfPropertyPlantAndEquipment",
        "CashOutflowOnPurchaseOfPropertyPlantAndEquipment",
        "PaymentsForPropertyPlantAndEquipment",
        "AdditionsToPropertyPlantAndEquipment",
        "AdditionsToFixedAssets",
        # Oil & gas upstream capex (ONGC-specific).
        "CapitalExpenditure",
        "PurchaseOfIntangibleAssets",
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


def _detect_period_type_from_contexts(
    contexts: dict[str, dict[str, Any]],
    period_end: date,
) -> str | None:
    """Infer 'annual' vs 'quarterly' from the XBRL duration contexts.

    The `<context><period>` duration is the ground truth for a filing —
    the NSE endpoint label ("Annual"/"Quarterly") is only a hint and
    occasionally misclassifies (e.g. a Q4+FY combined filing tagged
    under the Annual endpoint carries a 90-day duration).

    Rules:
    - Find the duration context whose endDate matches period_end.
    - Compute (endDate - startDate) in days.
    - 300+ days → annual; 60-120 days → quarterly.
    - Return None if no duration context matches period_end (caller
      falls back to endpoint-based hint).
    """
    period_end_s = period_end.isoformat()
    best_days: int | None = None
    for _cid, info in contexts.items():
        if info.get("end") != period_end_s:
            continue
        start_s = info.get("start")
        if not start_s:
            continue
        try:
            start_d = datetime.strptime(start_s, "%Y-%m-%d").date()
        except Exception:
            continue
        days = (period_end - start_d).days
        if days <= 0:
            continue
        if best_days is None or days > best_days:
            best_days = days
    if best_days is None:
        return None
    if best_days >= 300:
        return "annual"
    if 60 <= best_days <= 120:
        return "quarterly"
    # Half-year or 9-month combined filings — treat as annual-adjacent
    # quarterly since our downstream ratios are annual-only anyway.
    # Returning None lets the endpoint hint win.
    return None


_CONSOLIDATED_KEYS = (
    "consolidated",
    "isConsolidated",
    "is_consolidated",
    "relatingTo",
    "relating_to",
    "nature",
    "reResType",
    "resultType",
    "result_type",
    "type",
)


def _filing_is_consolidated(filing: dict[str, Any]) -> bool | None:
    """Inspect a filing-index entry for its Consolidated/Standalone label.

    NSE's `corporates-financial-results` entries expose the distinction
    under a handful of keys depending on the endpoint version. Returns
    True for Consolidated, False for Standalone, None if undetermined.
    """
    for k in _CONSOLIDATED_KEYS:
        v = filing.get(k)
        if v is None:
            continue
        s = str(v).strip().lower()
        if not s:
            continue
        if "consolidated" in s and "non" not in s and "standalone" not in s:
            return True
        if "standalone" in s or s.startswith("non-consolidated") or s == "non consolidated":
            return False
    return None


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
    """Parse one XBRL file into our canonical financials row shape.

    `period_type` is the endpoint-based hint ('annual'/'quarterly'). If
    the XBRL contexts carry an unambiguous duration we prefer that over
    the hint — the endpoint occasionally misclassifies Q4+FY combined
    filings. See `_detect_period_type_from_contexts`.
    """
    facts = _extract_facts(xml_bytes)
    if not facts:
        return None
    contexts = _extract_contexts(xml_bytes)

    # Context-duration wins over endpoint hint when they disagree.
    inferred = _detect_period_type_from_contexts(contexts, period_end)
    if inferred and inferred != period_type:
        logger.info(
            "nse_xbrl period_type override for %s %s: endpoint=%s, context=%s",
            ticker, period_end.isoformat(), period_type, inferred,
        )
        period_type = inferred

    revenue = _pick_value(facts, contexts, _FIELD_TAGS["revenue"], period_end)
    if revenue is None:
        revenue = _pick_value(facts, contexts, _FIELD_TAGS["total_income"], period_end)
    pat = _pick_value(facts, contexts, _FIELD_TAGS["pat"], period_end)
    eps = _pick_value(facts, contexts, _FIELD_TAGS["eps_diluted"], period_end)
    depreciation = _pick_value(facts, contexts, _FIELD_TAGS["depreciation"], period_end)
    pbt = _pick_value(facts, contexts, _FIELD_TAGS["pbt"], period_end)
    total_assets = _pick_value(facts, contexts, _FIELD_TAGS["total_assets"], period_end)
    current_liabilities = _pick_value(
        facts, contexts, _FIELD_TAGS["current_liabilities"], period_end
    )
    total_debt = _pick_value(facts, contexts, _FIELD_TAGS["total_debt"], period_end)
    total_equity = _pick_value(facts, contexts, _FIELD_TAGS["total_equity"], period_end)
    cash = _pick_value(facts, contexts, _FIELD_TAGS["cash"], period_end)
    cfo = _pick_value(facts, contexts, _FIELD_TAGS["cfo"], period_end)
    capex = _pick_value(facts, contexts, _FIELD_TAGS["capex"], period_end)

    # Operating profit — the preferred EBIT source. If the filing
    # carries an explicit "Profit from operations" / EBIT tag we use
    # it directly; otherwise we reconstruct EBIT from PBT + finance
    # cost below.
    operating_profit = _pick_value(
        facts, contexts, _FIELD_TAGS["operating_profit"], period_end
    )
    finance_cost = _pick_value(facts, contexts, _FIELD_TAGS["finance_cost"], period_end)

    # EBIT = operating_profit from filing if present;
    # otherwise derive: EBIT = PBT + finance_cost (classic reconstruction).
    # EBITDA (below) = EBIT + depreciation.
    ebit = operating_profit
    if ebit is None and pbt is not None:
        fc = finance_cost or 0.0
        ebit = pbt + fc

    # EBITDA proxy: PBT + depreciation + finance cost
    ebitda = None
    if pbt is not None:
        parts = [pbt]
        if depreciation is not None:
            parts.append(depreciation)
        if finance_cost is not None:
            parts.append(finance_cost)
        ebitda = sum(parts)

    # Unit normalisation — per-filing, not per-field.
    #
    # Indian XBRL filings publish numbers in one of three unit scales:
    #   1. Absolute rupees (raw INR)      → typical revenue 1e11-1e14
    #   2. Lakhs (x 10^5)                 → typical revenue 1e4-1e7
    #   3. Crores (x 10^7, our DB unit)   → typical revenue 10-5e5
    #
    # The previous per-field heuristic compared each value against 1e9
    # independently — fine for large caps, catastrophic for small caps
    # where PAT is below the threshold while equity is already in Cr.
    # Example (HONDAPOWER seen in prod logs):
    #   pat = 158_000_000 (raw rupees, = 15.8 Cr)
    #   total_equity = 812.11 (already in Cr)
    #   per-field heuristic: both below 1e9, both left as-is
    #   → stored as pat=158M Cr, equity=812 Cr, ROE=(158M/812)*100
    #     = 19,455,549% — pure corruption.
    #
    # Fix: pick ONE scale per filing based on revenue magnitude (the
    # most reliable anchor — always the largest non-derivative number
    # in an income statement) and apply it uniformly to every field.
    # PAT, equity, cash, debt etc. all come from the SAME XBRL file,
    # so they share the filing's unit choice.
    if revenue is not None and revenue > 0:
        abs_rev = abs(revenue)
        if abs_rev > 1e11:           # raw rupees (e.g. Reliance ₹9L cr = 9e12)
            scale = 1e7
        elif abs_rev > 1e8:          # also raw rupees, smaller company
            scale = 1e7
        elif abs_rev > 1e4:          # lakhs (10^5 each = Cr when /100)
            scale = 1e2
        else:                        # already crores
            scale = 1.0
    else:
        # No revenue anchor — use a conservative field-by-field check
        # only on the flow-of-funds fields. Safer to null-out than guess.
        scale = None

    def _scale(x):
        if x is None:
            return None
        if scale is None:
            return None  # can't trust without an anchor
        return x / scale

    return {
        "ticker": ticker,
        "period_end": period_end,
        "period_type": period_type,
        "revenue": _scale(revenue),
        "pat": _scale(pat),
        "ebit": _scale(ebit),
        "ebitda": _scale(ebitda),
        "cfo": _scale(cfo),
        "capex": _scale(capex),
        "total_assets": _scale(total_assets),
        "current_liabilities": _scale(current_liabilities),
        "total_debt": _scale(total_debt),
        "total_equity": _scale(total_equity),
        "cash": _scale(cash),
        "eps_diluted": eps,  # per-share rupees, not scaled
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

        # ── Consolidated-preference grouping ──────────────────────────
        # For a given period_end, NSE may return both a Standalone and
        # a Consolidated filing. We want exactly one row per period:
        # prefer Consolidated; write Standalone only if that's all we
        # have. This matches the pattern yfinance uses and avoids
        # duplicate rows (one NULL-heavy standalone shadowing the
        # real consolidated numbers).
        grouped: dict[date, dict[str, dict[str, Any]]] = {}
        for f in filings:
            to_s = f.get("toDate") or f.get("to_date")
            period_end = _parse_nse_date(to_s) if to_s else None
            if period_end is None:
                continue
            xbrl_url = f.get("xbrl")
            if not xbrl_url or not xbrl_url.startswith("http"):
                continue
            is_consol = _filing_is_consolidated(f)
            # Bucket: "consolidated" | "standalone" | "unknown"
            if is_consol is True:
                bucket = "consolidated"
            elif is_consol is False:
                bucket = "standalone"
            else:
                bucket = "unknown"
            slot = grouped.setdefault(period_end, {})
            # Keep first-seen per bucket (NSE returns newest first).
            slot.setdefault(bucket, f)

        # Emit in (newest → oldest) order so caller-side logs stay
        # deterministic and match what was previously produced.
        for period_end in sorted(grouped.keys(), reverse=True):
            slot = grouped[period_end]
            if "consolidated" in slot:
                chosen = slot["consolidated"]
                source_label = "NSE_XBRL"
                if "standalone" in slot:
                    logger.info(
                        "nse_xbrl consolidated-preference: %s %s — "
                        "dropping standalone in favour of consolidated",
                        symbol, period_end.isoformat(),
                    )
            elif "unknown" in slot:
                # No explicit Consolidated/Standalone label — trust the
                # filing as-is (historical behaviour).
                chosen = slot["unknown"]
                source_label = "NSE_XBRL"
            else:
                # Only a Standalone exists. Per contract, write it but
                # tag the source so downstream can tell them apart.
                chosen = slot["standalone"]
                source_label = "NSE_XBRL_STANDALONE"
                logger.info(
                    "nse_xbrl standalone-only: %s %s — "
                    "writing standalone (no consolidated filing available)",
                    symbol, period_end.isoformat(),
                )

            xbrl_url = chosen.get("xbrl")
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
                row["source"] = source_label
                all_rows.append(row)

            time.sleep(sleep)

    return all_rows
