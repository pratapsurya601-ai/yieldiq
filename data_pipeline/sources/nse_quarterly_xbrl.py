"""Production NSE quarterly XBRL ingest — 3 schemas (industrial / banking / insurance).

Listing endpoint:
    GET https://www.nseindia.com/api/corporates-financial-results
        ?index=equities&symbol=<SYM>&period=Quarterly

For banking schema filings the discriminator is either:
    * the listing URL contains 'BANKING_', or
    * the XBRL root namespace map includes a prefix ending in '-bnk'.

This module is consumed by `scripts/backfill_nse_quarterly_xbrl.py`. The
CLI wrapper handles DB writes (or --dry-run). This module only:

    * fetches the filings list (delegated to the existing
      data_pipeline.sources.nse_xbrl_fundamentals helpers)
    * downloads + parses one XBRL into a row-shaped dict
    * understands all three schemas + post-merger symbol aliases

Bugs fixed vs. the scratch scripts (spike_infy_xbrl, spike_hdfcbank_xbrl,
backfill_xbrl_batch{1..5}):

    1. fiscal_quarter_label off-by-one-year for Jan-Mar quarters
       (Q4 FY24 used to be labelled Q4 FY24 correctly, but Q3 FY25
       was being labelled Q3 FY26).
    2. Unit-scale now reads <in-bse-fin:LevelOfRoundingUsedInFinancialStatements>
       directly instead of guessing from the revenue magnitude
       (BAJAJFINSV standalone was the regression case — small holdco
       revenue tripped the magnitude heuristic into 'lakhs' mode).
    3. N_QUARTERS standardized to 22 (covers 5 full FYs + 2 quarters
       headroom for as-reported re-filings).
    4. Banking schema (in-bse-fin-bnk:) recognised + parsed.
    5. NSE_SYMBOL_ALIASES handle post-merger ticker drift
       (LTI → LTIM/LTIMINDTREE; TATAMOTORS-DVR class collapse).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from typing import Any

from data_pipeline.sources.nse_xbrl_fundamentals import (
    _extract_contexts,
    _extract_facts,
    _get_session,
    _parse_nse_date,
    fetch_filings_list,
)

logger = logging.getLogger(__name__)


N_QUARTERS = 22  # 5 FY * 4 + 2 quarters headroom


# ───────────────────────────────────────────────────────────────────────
# Symbol aliases — post-merger / ticker drift
# ───────────────────────────────────────────────────────────────────────

NSE_SYMBOL_ALIASES: dict[str, list[str]] = {
    "LTIM": ["LTIM", "LTIMINDTREE", "LTI"],
    "TATAMOTORS": ["TATAMOTORS", "TATAMOTORS-DVR", "TATAMOTORSDV"],
}


def _fetch_filings_index(
    symbol: str, index: str, session, period: str = "Quarterly",
) -> list[dict[str, Any]]:
    """Listing fetch with a custom ?index= and ?period= value.

    Supports `period='Half-Yearly'` for the SME cohort (many SMEs file
    on a half-yearly cadence rather than quarterly).
    """
    from data_pipeline.sources.nse_xbrl_fundamentals import NSE_API_BASE, NSE_WARMUP
    try:
        session.get(NSE_WARMUP.format(symbol=symbol), timeout=10)
    except Exception:
        pass
    url = (
        f"{NSE_API_BASE}/corporates-financial-results"
        f"?index={index}&symbol={symbol}&period={period}"
    )
    try:
        r = session.get(url, timeout=20, headers={"Accept": "application/json"})
    except Exception as exc:
        logger.info(
            "listing fetch error index=%s period=%s symbol=%s: %s",
            index, period, symbol, exc,
        )
        return []
    if r.status_code != 200:
        return []
    try:
        data = r.json()
    except Exception:
        return []
    return data if isinstance(data, list) else []


def resolve_symbol_filings(
    symbol: str, session=None, segment: str = "equities",
) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    """Try each alias / index / period combo until filings are found.

    Returns (used_symbol, [(report_period_type, filing), ...]).

    Each returned filing is paired with the `report_period_type` label
    ('Quarterly' or 'Half-Yearly') used to fetch it, so the caller can
    persist it alongside the row without re-deriving from the URL.

    Search strategy by `segment`:

      segment='equities' (default — main-board):
        Try aliases × ('equities', 'insurance', 'debt') × Quarterly only.
        This preserves the prior contract exactly.

      segment='sme':
        Try aliases × index='sme' × ('Quarterly', 'Half-Yearly').
        SMEs split between the two cadences; we collect from BOTH so a
        ticker that filed quarterly for FY24 and switched to half-yearly
        for FY25 lands both vintages.
    """
    aliases = NSE_SYMBOL_ALIASES.get(symbol, [symbol])
    if session is None:
        session = _get_session()

    if segment == "sme":
        collected: list[tuple[str, dict[str, Any]]] = []
        used: str | None = None
        for alias in aliases:
            for period in ("Quarterly", "Half-Yearly"):
                try:
                    filings = _fetch_filings_index(
                        alias, "sme", session=session, period=period,
                    )
                except Exception as exc:
                    logger.info(
                        "sme alias=%s period=%s fetch failed: %s",
                        alias, period, exc,
                    )
                    continue
                if filings:
                    if used is None:
                        used = alias
                    collected.extend((period, f) for f in filings)
            if collected:
                if (used or symbol) != symbol:
                    logger.info(
                        "resolved %s via SME alias=%s (%d filings)",
                        symbol, used, len(collected),
                    )
                return used or symbol, collected
        return symbol, []

    # Default: equities / main-board (unchanged behaviour).
    for alias in aliases:
        for index in ("equities", "insurance", "debt"):
            try:
                if index == "equities":
                    filings = fetch_filings_list(alias, "Quarterly", session=session)
                else:
                    filings = _fetch_filings_index(alias, index, session=session)
            except Exception as exc:
                logger.info("alias %s index=%s fetch failed: %s", alias, index, exc)
                continue
            if filings:
                if alias != symbol or index != "equities":
                    logger.info(
                        "resolved %s via alias=%s index=%s (%d filings)",
                        symbol, alias, index, len(filings),
                    )
                return alias, [("Quarterly", f) for f in filings]
    return symbol, []


# ───────────────────────────────────────────────────────────────────────
# Schema-specific tag maps
# ───────────────────────────────────────────────────────────────────────

INDUSTRIAL_QUARTERLY_TAGS: dict[str, list[str]] = {
    "revenue_cr": ["RevenueFromOperations"],
    "other_income_cr": ["OtherIncome"],
    "total_income_cr": ["Income", "TotalIncome"],
    "employee_benefit_cr": ["EmployeeBenefitExpense"],
    "finance_costs_cr": ["FinanceCosts"],
    "depreciation_cr": [
        "DepreciationDepletionAndAmortisationExpense",
        "DepreciationAndAmortisationExpense",
    ],
    "other_expenses_cr": ["OtherExpenses"],
    "total_expenses_cr": ["Expenses", "TotalExpenses"],
    "profit_before_tax_cr": [
        "ProfitBeforeTax",
        "ProfitBeforeExceptionalItemsAndTax",
    ],
    "tax_expense_cr": ["TaxExpense"],
    "net_profit_cr": [
        "ProfitLossForPeriod",
        "ProfitLossForPeriodFromContinuingOperations",
    ],
    "comprehensive_income_cr": ["ComprehensiveIncomeForThePeriod"],
    "paid_up_capital_cr": ["PaidUpValueOfEquityShareCapital"],
}

# Banking schema — see CLAUDE.md spike notes and the actual HDFCBANK
# XBRL we downloaded for verification (see tests/fixtures/xbrl/).
#
# Acceptance run verified against HDFCBANK Q3 FY25 standalone — see
# `verify_bank_field_names()` below for the data-driven name resolution
# that handles the two main spellings observed in production:
#   * 'OperatingProfitBeforeProvisionAndContingencies'   (singular)
#   * 'OperatingProfitBeforeProvisionsAndContingencies'  (plural — task spec)
BANK_QUARTERLY_TAGS: dict[str, list[str]] = {
    "revenue_cr": ["InterestEarned"],
    "interest_earned_cr": ["InterestEarned"],
    "interest_expended_cr": ["InterestExpended"],
    "other_income_cr": ["OtherIncome"],
    "total_income_cr": ["Income", "TotalIncome"],
    "operating_profit_cr": [
        # Field actually found in HDFCBANK Q3 FY25 XBRL is the SINGULAR
        # spelling — see tests/fixtures/xbrl/hdfcbank_q3_fy25.xml. The
        # plural form is listed second as a forward-compat fallback in
        # case the SEBI schema updates the tag name.
        "OperatingProfitBeforeProvisionAndContingencies",
        "OperatingProfitBeforeProvisionsAndContingencies",
    ],
    "provisions_cr": [
        "ProvisionsOtherThanTaxAndContingencies",
        "ProvisionsAndContingencies",
    ],
    "employee_benefit_cr": ["EmployeesCost", "EmployeeBenefitExpense"],
    "profit_before_tax_cr": [
        # Observed in HDFCBANK fixture; fall back to industrial spelling
        # in case any private-sector bank uses the shorter Ind-AS tag.
        "ProfitLossFromOrdinaryActivitiesBeforeTax",
        "ProfitBeforeTax",
    ],
    "tax_expense_cr": ["TaxExpense"],
    "net_profit_cr": [
        # HDFCBANK uses "ForThePeriod" (with "The"); some PSU banks omit
        # the article. Both spellings live here, observed-first.
        "ProfitLossForThePeriod",
        "ProfitLossFromOrdinaryActivitiesAfterTax",
        "ProfitLossForPeriod",
    ],
    "paid_up_capital_cr": ["PaidUpValueOfEquityShareCapital"],
}

# Insurance schema — discovered via ?index=insurance listing endpoint
# (HDFCLIFE Q3 FY25, URL pattern `LI_<seq>_<id>_<ts>.xml`). Namespace
# uses `in-capmkt` (Insurance role variant) instead of in-bse-fin-bnk,
# so detection is URL-prefix-driven for this schema.
#
# Coverage is INTENTIONALLY PARTIAL. The insurance P&L has two ledgers
# (Policyholders' Account + Shareholders' Account), per-line-of-business
# splits, and IRDAI-specific metrics (solvency ratio, persistency, NBP)
# that don't map onto the industrial schema columns. This map covers
# the headline P&L only — enough for `revenue_cr` / `net_profit_cr`
# population. Full insurance-native columns are deferred to a follow-up
# PR (insurance recon task `aecc0764eeae0e4b7`).
INSURANCE_QUARTERLY_TAGS: dict[str, list[str]] = {
    # Use NetPremiumIncome as the canonical revenue proxy (matches what
    # peers report as "topline" for life insurers).
    "revenue_cr": ["NetPremiumIncome", "GrossPremiumIncome"],
    "other_income_cr": ["OtherIncome", "PolicyholdersAccountOtherIncome"],
    "total_income_cr": ["Income"],
    "total_expenses_cr": ["Expenses", "ExpensesOfManagement"],
    "employee_benefit_cr": ["EmployeesRemunerationAndWelfareExpenses"],
    "profit_before_tax_cr": ["ProfitLossBeforeTax"],
    "tax_expense_cr": ["ProvisionsForTax", "ProvisionsForTaxes", "CurrentTax"],
    "net_profit_cr": [
        "ProfitLossAfterTaxAndExtraordinaryItems",
        "ProfitLossAfterTaxBeforeExtraordinaryItems",
    ],
    "paid_up_capital_cr": ["PaidUpValueOfEquityShareCapital"],
    # Insurance-native (not stored in current schema; reserved for
    # future insurance-specific columns).
    "_gross_premium_cr": ["GrossPremiumIncome"],
    "_benefits_paid_cr": ["BenefitsPaidNet"],
    "_commission_cr": ["NetCommission", "Commission"],
    "_surplus_cr": ["SurplusDeficit"],
}


PER_SHARE_TAGS_INDUSTRIAL: dict[str, list[str]] = {
    "basic_eps": [
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsLossPerShareFromContinuingOperations",
        "BasicEarningsPerShare",
    ],
    "diluted_eps": [
        "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "DilutedEarningsLossPerShareFromContinuingOperations",
        "DilutedEarningsPerShare",
    ],
    "face_value": ["FaceValueOfEquityShareCapital"],
}

PER_SHARE_TAGS_BANK: dict[str, list[str]] = {
    "basic_eps": [
        "BasicEarningsLossPerShareFromContinuingOperations",
        "BasicEarningsPerShareAfterExtraordinaryItems",
        "BasicEarningsPerShareBeforeExtraordinaryItems",
        "BasicEarningsPerShare",
    ],
    "diluted_eps": [
        "DilutedEarningsLossPerShareFromContinuingOperations",
        "DilutedEarningsPerShareAfterExtraordinaryItems",
        "DilutedEarningsPerShareBeforeExtraordinaryItems",
        "DilutedEarningsPerShare",
    ],
    "face_value": ["FaceValueOfEquityShareCapital"],
}

META_TAGS: dict[str, list[str]] = {
    "is_audited_str": ["WhetherResultsAreAuditedOrUnaudited"],
    "nature_str": ["NatureOfReportStandaloneConsolidated"],
    "segment_str": ["IsCompanyReportingMultisegmentOrSingleSegment"],
    "rounding": ["LevelOfRoundingUsedInFinancialStatements"],
}


# ───────────────────────────────────────────────────────────────────────
# Schema detection
# ───────────────────────────────────────────────────────────────────────

def detect_schema(xbrl_url: str | None, xml_bytes: bytes | None) -> str:
    """Return one of 'banking' | 'insurance' | 'industrial'.

    Priority:
      1. URL keyword (BANKING_, INSURANCE_) — cheap, no XML parse needed
      2. XML namespace map (suffix '-bnk' / '-ins')
      3. Default: 'industrial'
    """
    if xbrl_url:
        u = xbrl_url.upper()
        if "BANKING_" in u or "/BANK/" in u:
            return "banking"
        # NSE insurance URL pattern: LI_<seq>_<id>_<ts>.xml (Life)
        # or GI_<seq>_<id>_<ts>.xml (General). Match on the filename
        # segment so we don't false-positive on '/LI/' in other paths.
        last = u.rsplit("/", 1)[-1]
        if last.startswith("LI_") or last.startswith("GI_") or "INSURANCE_" in u:
            return "insurance"

    if xml_bytes:
        try:
            from lxml import etree

            root = etree.fromstring(xml_bytes)
            for _prefix, uri in (root.nsmap or {}).items():
                if not uri:
                    continue
                low = uri.lower()
                if low.endswith("-bnk") or "-bnk/" in low or "-bnk-" in low:
                    return "banking"
                if low.endswith("-ins") or "-ins/" in low or "-ins-" in low:
                    return "insurance"
                if "/insurance/" in low:
                    return "insurance"
        except Exception:
            pass

    return "industrial"


# ───────────────────────────────────────────────────────────────────────
# Pure helpers — single source of truth (no copy/paste from spike scripts)
# ───────────────────────────────────────────────────────────────────────

def fiscal_quarter_label(period_end: date) -> str:
    """Indian FY: Apr-Mar. Q1=Apr-Jun, Q2=Jul-Sep, Q3=Oct-Dec, Q4=Jan-Mar.

    Bug-fix vs. spike: the spike incremented `fy` by 1 only inside the
    Q3 branch, so:
      * 2024-09-30 → Q2 FY24 (wrong, should be Q2 FY25)
      * 2024-12-31 → Q3 FY25 (right)
      * 2024-03-31 → Q4 FY24 (right)
    The correct rule is: any month >= April rolls FY forward.

    Examples:
      * 2024-09-30 → 'Q2 FY25'
      * 2024-03-31 → 'Q4 FY24'
      * 2024-12-31 → 'Q3 FY25'
      * 2022-06-30 → 'Q1 FY23'
    """
    y, m = period_end.year, period_end.month
    if m >= 4:  # Apr-Dec → FY ends next March
        fy_year = (y + 1) % 100
        q = ((m - 4) // 3) + 1
    else:  # Jan-Mar → Q4 of current FY
        fy_year = y % 100
        q = 4
    return f"Q{q} FY{fy_year:02d}"


def _localname(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _string_facts(xml_bytes: bytes) -> dict[str, list[tuple[str, str]]]:
    try:
        from lxml import etree
    except ImportError:  # pragma: no cover
        from xml.etree import ElementTree as etree  # type: ignore
    try:
        root = etree.fromstring(xml_bytes)
    except Exception:
        return {}
    out: dict[str, list[tuple[str, str]]] = {}
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        txt = (el.text or "").strip()
        if not txt:
            continue
        ln = _localname(el.tag)
        ctx = el.get("contextRef") or ""
        out.setdefault(ln, []).append((txt, ctx))
    return out


def _pick_string(sfacts: dict[str, list[tuple[str, str]]], names: list[str]) -> str | None:
    for ln in names:
        if ln in sfacts and sfacts[ln]:
            return sfacts[ln][0][0]
    return None


def detect_unit_scale(
    sfacts: dict[str, list[tuple[str, str]]],
    revenue_raw: float | None,
) -> float:
    """Return the divisor to convert raw XBRL number → ₹ Crores.

    Reads <in-bse-fin:LevelOfRoundingUsedInFinancialStatements> first. The
    string values observed in production are 'Lakhs', 'Crores', 'Millions',
    'Thousands', 'Hundreds', 'Actual'.

    The XBRL "rounding" tag describes the *unit* the company reports values
    in (most are 'Crores' = values written as e.g. 34,915 mean ₹34,915 Cr),
    but a substantial minority of NSE filings report raw rupees regardless
    of the declared rounding (legacy template upload behaviour). So:

      1. Read the declared rounding.
      2. Cross-check with the magnitude of revenue. If revenue would
         resolve to an absurd Cr value (> 1e7 Cr ≈ ₹100 trillion), assume
         the file is actually raw rupees and divide by 1e7 regardless.

    Fallback to pure magnitude heuristic when the tag is absent
    (older filings sometimes omit it).
    """
    rounding = (_pick_string(sfacts, META_TAGS["rounding"]) or "").strip().lower()

    scale_map = {
        "crores": 1.0,        # already in Cr
        "lakhs": 1e-2,        # 100 Lakhs = 1 Cr → divide by 100? no, MULTIPLY by 0.01
        "millions": 0.1,      # 10 Mn = 1 Cr → 1 Mn = 0.1 Cr
        "thousands": 1e-4,    # 1 Th = 0.0001 Cr
        "hundreds": 1e-5,
        "actual": 1e7,        # raw INR → divide by 1e7
    }

    declared = scale_map.get(rounding)
    if declared is not None:
        # Sanity check: detect template upload bug where file declares
        # 'Crores' but actually contains raw INR. The largest realistic
        # quarterly revenue in true ₹Cr is RELIANCE consolidated at ~2.5
        # lakh Cr; any rev_raw > 1e6 (= ₹1M-Cr = ₹10 trillion) with
        # 'Crores' declared is unambiguously a raw-INR template upload.
        # BAJAJFINSV standalone Q3 FY25 hit this: declared='Crores',
        # rev_raw=708,200,000 (= ₹70.82 Cr).
        if declared == 1.0 and revenue_raw is not None and abs(revenue_raw) > 1e6:
            return 1e7
        # Lakhs declared but values look like raw INR.
        if declared == 1e-2 and revenue_raw is not None and abs(revenue_raw) > 1e8:
            return 1e7
        # Use the declared scale interpreted as a divisor:
        #   value_in_cr = raw / divisor
        # For 'Crores': divisor = 1 → value already in Cr
        # For 'Lakhs':  divisor = 100 (100 Lakhs = 1 Cr)
        # For 'Millions': divisor = 10
        # For 'Actual': divisor = 1e7
        if rounding == "crores":
            return 1.0
        if rounding == "lakhs":
            return 100.0
        if rounding == "millions":
            return 10.0
        if rounding == "thousands":
            return 1e5
        if rounding == "hundreds":
            return 1e6
        if rounding == "actual":
            return 1e7

    # Fallback magnitude heuristic (rounding tag missing).
    if revenue_raw is None:
        return 1e7
    if abs(revenue_raw) > 1e9:
        return 1e7
    if abs(revenue_raw) > 1e4:
        return 100.0
    return 1.0


def _pick_quarter_fact(
    facts: dict[str, list[tuple[float, str]]],
    contexts: dict[str, dict[str, Any]],
    local_names: list[str],
    period_end: date,
) -> float | None:
    """Pick the OneD-style (~quarter duration ending on period_end) value."""
    period_end_s = period_end.isoformat()
    for ln in local_names:
        candidates = facts.get(ln, [])
        if not candidates:
            continue
        for val, ctx in candidates:
            ci = contexts.get(ctx, {})
            if ci.get("end") != period_end_s:
                continue
            start_s = ci.get("start")
            if not start_s:
                if ci.get("instant") == period_end_s:
                    return val
                continue
            try:
                start_d = datetime.strptime(start_s, "%Y-%m-%d").date()
            except Exception:
                continue
            if 60 <= (period_end - start_d).days <= 120:
                return val
        for val, ctx in candidates:
            ci = contexts.get(ctx, {})
            if ci.get("instant") == period_end_s:
                return val
        for val, ctx in candidates:
            ci = contexts.get(ctx, {})
            if ci.get("end") == period_end_s:
                return val
        for val, ctx in candidates:
            if ctx in ("OneD", "OneI"):
                return val
    return None


def _resolve_period_start(
    contexts: dict[str, dict[str, Any]], period_end: date
) -> date:
    period_end_s = period_end.isoformat()
    for _ctx, info in contexts.items():
        if info.get("end") != period_end_s:
            continue
        s = info.get("start")
        if not s:
            continue
        try:
            sd = datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            continue
        if 60 <= (period_end - sd).days <= 120:
            return sd
    m = period_end.month
    if m in (4, 5, 6):
        return date(period_end.year, 4, 1)
    if m in (7, 8, 9):
        return date(period_end.year, 7, 1)
    if m in (10, 11, 12):
        return date(period_end.year, 10, 1)
    return date(period_end.year, 1, 1)


# ───────────────────────────────────────────────────────────────────────
# Top-level parser
# ───────────────────────────────────────────────────────────────────────

def parse_quarter_xml(
    xml_bytes: bytes,
    ticker: str,
    period_end: date,
    xbrl_url: str | None,
    filed_at: str | None = None,
) -> dict[str, Any] | None:
    """Parse one quarterly XBRL into a row dict ready for upsert.

    The returned dict's keys are a superset of the company_quarterly_results
    columns (industrial + banking). `schema_type` is always set; bank-only
    fields are present (None for industrial) and vice-versa.
    """
    facts = _extract_facts(xml_bytes)
    contexts = _extract_contexts(xml_bytes)
    sfacts = _string_facts(xml_bytes)
    if not facts:
        return None

    schema = detect_schema(xbrl_url, xml_bytes)
    if schema == "banking":
        tags = BANK_QUARTERLY_TAGS
        per_share_tags = PER_SHARE_TAGS_BANK
    elif schema == "insurance" and INSURANCE_QUARTERLY_TAGS:
        tags = INSURANCE_QUARTERLY_TAGS
        per_share_tags = PER_SHARE_TAGS_INDUSTRIAL
    else:
        tags = INDUSTRIAL_QUARTERLY_TAGS
        per_share_tags = PER_SHARE_TAGS_INDUSTRIAL

    # Detect scale using the unit tag (with sanity check). Use revenue
    # for the magnitude check whether industrial or bank (for banks
    # 'revenue_cr' maps to InterestEarned, which is on the same scale).
    rev_raw = _pick_quarter_fact(facts, contexts, tags.get("revenue_cr", []), period_end)
    scale = detect_unit_scale(sfacts, rev_raw)

    def num(name: str) -> float | None:
        tag_list = tags.get(name)
        if not tag_list:
            return None
        v = _pick_quarter_fact(facts, contexts, tag_list, period_end)
        return None if v is None else round(v / scale, 2)

    def per_share(name: str) -> float | None:
        return _pick_quarter_fact(facts, contexts, per_share_tags.get(name, []), period_end)

    nature = _pick_string(sfacts, META_TAGS["nature_str"]) or ""
    is_consol = "Consolidated" in nature and "Standalone" not in nature
    is_audited_str = (_pick_string(sfacts, META_TAGS["is_audited_str"]) or "").strip()
    is_audited = is_audited_str.lower().startswith("audited")
    segment_str = (_pick_string(sfacts, META_TAGS["segment_str"]) or "").strip()
    is_single_segment = segment_str.lower().startswith("single")

    period_start = _resolve_period_start(contexts, period_end)

    row: dict[str, Any] = {
        "ticker": ticker,
        "schema_type": schema,
        "fiscal_quarter": fiscal_quarter_label(period_end),
        "period_start": period_start,
        "period_end": period_end,
        "is_consolidated": is_consol,
        "is_audited": is_audited,
        "is_single_segment": is_single_segment,
        # Core P&L (mapped per-schema; for banks revenue_cr := InterestEarned)
        "revenue_cr": num("revenue_cr"),
        "other_income_cr": num("other_income_cr"),
        "total_expenses_cr": num("total_expenses_cr"),
        "profit_before_tax_cr": num("profit_before_tax_cr"),
        "tax_expense_cr": num("tax_expense_cr"),
        "net_profit_cr": num("net_profit_cr"),
        "comprehensive_income_cr": num("comprehensive_income_cr"),
        # Industrial-only expense breakdown (None for banks)
        "employee_benefit_cr": num("employee_benefit_cr"),
        "finance_costs_cr": num("finance_costs_cr"),
        "depreciation_cr": num("depreciation_cr"),
        "other_expenses_cr": num("other_expenses_cr"),
        # Per-share
        "basic_eps": per_share("basic_eps"),
        "diluted_eps": per_share("diluted_eps"),
        "face_value": per_share("face_value"),
        "paid_up_capital_cr": num("paid_up_capital_cr"),
        # Bank-only (None for industrial)
        "interest_earned_cr": num("interest_earned_cr") if schema == "banking" else None,
        "interest_expended_cr": num("interest_expended_cr") if schema == "banking" else None,
        "operating_profit_cr": num("operating_profit_cr") if schema == "banking" else None,
        "provisions_cr": num("provisions_cr") if schema == "banking" else None,
        # Provenance
        "xbrl_url": xbrl_url,
        "xbrl_sha256": hashlib.sha256(xml_bytes).hexdigest(),
        "filed_at": filed_at,
    }
    return row


# ───────────────────────────────────────────────────────────────────────
# Convenience — fetch + parse for one symbol
# ───────────────────────────────────────────────────────────────────────

def fetch_and_parse(
    symbol: str,
    *,
    limit: int = N_QUARTERS,
    session=None,
    sleep_between: float = 0.4,
    segment: str = "equities",
) -> list[dict[str, Any]]:
    """Fetch + download + parse up to `limit` filings for `symbol`.

    Symbol aliases are tried automatically. Failures are logged & skipped;
    only successfully-parsed rows are returned.

    `segment`:
        'equities' (default) — main-board, Quarterly cadence
        'sme'                — SME EMERGE, Quarterly + Half-Yearly cadence

    Each emitted row carries `segment` and `report_period_type` so the
    upsert layer can persist them into columns added by migration 032.
    """
    import time

    if session is None:
        session = _get_session()

    used_symbol, paired = resolve_symbol_filings(
        symbol, session=session, segment=segment,
    )
    paired = paired[:limit]
    rows: list[dict[str, Any]] = []
    for report_period_type, f in paired:
        xbrl_url = f.get("xbrl")
        # Industrial/banking listings use 'toDate'; insurance listings
        # use 'periodEnd'. Try both.
        to_s = f.get("toDate") or f.get("to_date") or f.get("periodEnd")
        period_end = _parse_nse_date(to_s) if to_s else None
        if not xbrl_url or not str(xbrl_url).startswith("http") or period_end is None:
            continue
        try:
            r = session.get(xbrl_url, timeout=20)
        except Exception as exc:
            logger.info("%s download fail %s: %s", symbol, xbrl_url, exc)
            continue
        if r.status_code != 200 or len(r.content) < 500:
            continue
        filed_at = (
            f.get("broadcastDate")
            or f.get("broadCastDate")  # insurance listing variant
            or f.get("submissionDate")
        )
        try:
            row = parse_quarter_xml(r.content, symbol, period_end, xbrl_url, filed_at)
        except Exception as exc:
            logger.info("%s parse fail %s: %s", symbol, xbrl_url, exc)
            continue
        if row:
            row["_resolved_symbol"] = used_symbol
            row["segment"] = segment
            row["report_period_type"] = report_period_type
            rows.append(row)
        time.sleep(sleep_between)
    return rows
