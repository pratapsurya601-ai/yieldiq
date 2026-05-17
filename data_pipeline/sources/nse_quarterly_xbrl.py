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
import os
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


# ───────────────────────────────────────────────────────────────────────
# NEW (2026-05): integrated-filing-results endpoint
#
# NSE replaced /api/corporates-financial-results with /api/integrated-
# filing-results during the SEBI Integrated Filing (Financials +
# Governance) rollout (effective from quarters ending 31-MAR-2025
# onwards). The legacy endpoint still serves historical filings but no
# longer publishes the newest XBRLs. Schema changes:
#
#   * Listing shape:   list[filing]  ->  {"data": [...], "size", "page",
#                                          "totalCount"}
#   * Field names:     toDate -> qe_Date,  broadcastDate -> broadcast_Date,
#                      xbrl URL prefix changed:
#                          BANKING_<seq>_<ts>.xml     -> INTEGRATED_FILING_BANKING_<seq>_<ts>.xml
#                          NBFC_INDAS_<seq>_<ts>.xml  -> INTEGRATED_FILING_INDAS_<seq>_<ts>.xml
#                          INSURANCE listings still under LI_/GI_ prefix
#                          (handled by existing detect_schema).
#   * `type` discriminator: each filing is now one of
#         "Integrated Filing- Financials"  (carries the financial XBRL)
#         "Integrated Filing- Governance"  (carries the GCG XBRL — not
#                                            for our pipeline)
#     We filter to *Financials* before yielding to the parser.
#   * `consolidated` field is a STRING ("Consolidated"/"Standalone")
#     instead of a bool.
#
# Taxonomy (the XBRL itself):
#   The financial XBRL now uses the unified `in-capmkt:` namespace for
#   ALL schemas (industrial, banking, insurance). The tag *local names*
#   are unchanged from the legacy `in-bse-fin:` / `in-bse-fin-bnk:`
#   schemas, so INDUSTRIAL_QUARTERLY_TAGS / BANK_QUARTERLY_TAGS resolve
#   100% against the integrated XBRL with no edits. Schema detection
#   keys off the URL prefix (`INTEGRATED_FILING_BANKING_*`) plus a new
#   namespace-URI fallback (the URI now contains the substring
#   `IntegratedFinance_Banking` instead of the `-bnk` suffix).
# ───────────────────────────────────────────────────────────────────────

USE_INTEGRATED_FILING_API = os.getenv(
    "USE_INTEGRATED_FILING_API", "1"
).strip().lower() not in ("0", "false", "no", "off", "")


def _adapt_integrated_filing(rec: dict[str, Any]) -> dict[str, Any]:
    """Adapt one /integrated-filing-results record to the legacy shape.

    Legacy keys the downstream code reads:
        toDate, broadcastDate, xbrl, consolidated (bool), audited (bool),
        symbol, type
    Integrated-filing keys: qe_Date, broadcast_Date, xbrl, consolidated
        (str), audited (str), symbol, type.

    The original record is kept under "_raw_integrated" so debug
    logging / provenance can recover the full row.
    """
    cons_raw = (rec.get("consolidated") or "").strip()
    if cons_raw.lower() == "consolidated":
        cons_bool: bool | None = True
    elif cons_raw.lower() == "standalone":
        cons_bool = False
    else:
        cons_bool = None
    aud_raw = (rec.get("audited") or "").strip().lower()
    aud_bool = aud_raw.startswith("audited") if aud_raw else None
    return {
        # Legacy aliases (read by fetch_and_parse and parsers)
        "toDate": rec.get("qe_Date"),
        "broadcastDate": rec.get("broadcast_Date"),
        "xbrl": rec.get("xbrl"),
        "consolidated": cons_bool,
        "audited": aud_bool,
        "symbol": rec.get("symbol"),
        "type": rec.get("type"),
        # New keys kept verbatim for any caller that wants them
        "qe_Date": rec.get("qe_Date"),
        "broadcast_Date": rec.get("broadcast_Date"),
        "audited_str": rec.get("audited"),
        "consolidated_str": rec.get("consolidated"),
        "type_Sub": rec.get("type_Sub"),
        "_raw_integrated": rec,
    }


def _fetch_integrated_filings(
    symbol: str,
    index: str = "equities",
    session=None,
    period: str = "Quarterly",
    page_size: int = 20,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    """Fetch + paginate the /api/integrated-filing-results endpoint.

    Returns a list of *adapted* filing dicts (legacy shape) FILTERED to
    `type == "Integrated Filing- Financials"`. Governance XBRLs are
    dropped because they don't carry P&L / balance-sheet facts.

    Pagination: continues while `len(collected) < totalCount` and the
    response has at least one row, capped at `max_pages` for safety.
    """
    from data_pipeline.sources.nse_xbrl_fundamentals import (
        NSE_API_BASE, NSE_WARMUP,
    )

    if session is None:
        session = _get_session()

    # Per-symbol cookie warmup (same pattern as _fetch_filings_index).
    try:
        session.get(NSE_WARMUP.format(symbol=symbol), timeout=10)
    except Exception:
        pass

    collected: list[dict[str, Any]] = []
    seen_seq: set[str] = set()
    total: int | None = None

    for page_idx in range(max_pages):
        url = (
            f"{NSE_API_BASE}/integrated-filing-results"
            f"?index={index}&symbol={symbol}&period={period}"
            f"&size={page_size}&page={page_idx + 1}"
        )
        try:
            r = session.get(
                url, timeout=20, headers={"Accept": "application/json"},
            )
        except Exception as exc:
            logger.info(
                "integrated-filing fetch error page=%d index=%s symbol=%s: %s",
                page_idx, index, symbol, exc,
            )
            break
        if r.status_code != 200:
            # 404 on unknown symbol is expected; only log other codes.
            if r.status_code not in (404, 400):
                logger.info(
                    "integrated-filing HTTP %d page=%d symbol=%s",
                    r.status_code, page_idx, symbol,
                )
            break
        try:
            payload = r.json()
        except Exception:
            break

        # Endpoint returns either a dict envelope or a bare list. Handle both.
        if isinstance(payload, dict):
            rows = payload.get("data") or []
            if total is None:
                tc = payload.get("totalCount")
                total = int(tc) if isinstance(tc, (int, str)) and str(tc).isdigit() else None
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []

        if not rows:
            break

        new_added = 0
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            seq = str(rec.get("seq_Id") or rec.get("seq_id") or "")
            if seq and seq in seen_seq:
                continue
            if seq:
                seen_seq.add(seq)
            collected.append(rec)
            new_added += 1

        if new_added == 0:
            break
        if total is not None and len(collected) >= total:
            break
        # If we got fewer than page_size rows on a page, assume last page.
        if len(rows) < page_size:
            break

    # Filter to Financials only; adapt to legacy shape.
    out: list[dict[str, Any]] = []
    for rec in collected:
        ftype = (rec.get("type") or "").strip()
        if ftype != "Integrated Filing- Financials":
            continue
        out.append(_adapt_integrated_filing(rec))
    return out


def _legacy_fetch_filings_index(
    symbol: str, index: str, session, period: str = "Quarterly",
) -> list[dict[str, Any]]:
    """Alias of _fetch_filings_index kept for clarity in the new flow.

    The legacy endpoint still serves historical (pre-FY26) filings, so we
    keep it as a fallback when the integrated API returns zero rows.
    """
    return _fetch_filings_index(symbol, index, session=session, period=period)


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

    # Default: equities / main-board.
    #
    # Strategy (post-2026-05 integrated-filing rollout):
    #   1. If USE_INTEGRATED_FILING_API is on (default), prefer the new
    #      endpoint. It returns the newest FY26 + Q4 FY25 filings the
    #      legacy endpoint no longer publishes.
    #   2. Merge with legacy listing results to cover historical (pre-
    #      FY25) filings — the new endpoint does NOT serve them. Dedup
    #      by xbrl URL.
    #   3. If the integrated endpoint is disabled or both empty, fall
    #      through with the legacy-only result (prior behaviour).
    for alias in aliases:
        for index in ("equities", "insurance", "debt"):
            integrated_rows: list[dict[str, Any]] = []
            legacy_rows: list[dict[str, Any]] = []

            if USE_INTEGRATED_FILING_API and index == "equities":
                try:
                    integrated_rows = _fetch_integrated_filings(
                        alias, index=index, session=session, period="Quarterly",
                    )
                except Exception as exc:
                    logger.info(
                        "integrated fetch failed alias=%s index=%s: %s",
                        alias, index, exc,
                    )

            try:
                if index == "equities":
                    legacy_rows = fetch_filings_list(
                        alias, "Quarterly", session=session,
                    )
                else:
                    legacy_rows = _legacy_fetch_filings_index(
                        alias, index, session=session,
                    )
            except Exception as exc:
                logger.info(
                    "legacy fetch failed alias=%s index=%s: %s",
                    alias, index, exc,
                )

            # Merge: integrated first (newest), then legacy fallbacks not
            # already covered by xbrl URL.
            seen_urls: set[str] = set()
            merged: list[dict[str, Any]] = []
            for f in integrated_rows:
                u = (f.get("xbrl") or "").strip()
                if u and u in seen_urls:
                    continue
                if u:
                    seen_urls.add(u)
                merged.append(f)
            for f in legacy_rows:
                u = (f.get("xbrl") or "").strip()
                if u and u in seen_urls:
                    continue
                if u:
                    seen_urls.add(u)
                merged.append(f)

            if merged:
                if alias != symbol or index != "equities":
                    logger.info(
                        "resolved %s via alias=%s index=%s (%d integrated + %d legacy)",
                        symbol, alias, index,
                        len(integrated_rows), len(legacy_rows),
                    )
                return alias, [("Quarterly", f) for f in merged]
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
    "rounding": ["LevelOfRoundingUsedInFinancialStatements", "LevelOfRounding"],
    "has_cashflow_str": ["WhetherCashFlowStatementIsApplicableOnCompany"],
}


# ───────────────────────────────────────────────────────────────────────
# Cash-flow tags — present only on H1 (Q2/Sep) and H2 (Q4/Mar) filings.
#
# Under SEBI LODR Reg 33, listed entities must publish a cash-flow
# statement only half-yearly. Q1 (Jun) and Q3 (Dec) quarterly XBRL
# filings carry `WhetherCashFlowStatementIsApplicableOnCompany=false`
# and zero cash-flow facts.
#
# The values are YTD cumulative (Apr→period_end) and live in the
# `FourD` context (Ind-AS year-to-date convention — see
# `_detect_period_type_from_contexts` in nse_xbrl_fundamentals.py).
# A Q2 filing's FourD CFO is H1 YTD (6 months). A Q4 filing's FourD
# CFO is the FULL FY YTD (12 months). The caller stores both alongside
# `cashflow_period_months` ∈ {6, 12} so the TTM aggregator can stitch
# H1 + previous-FY-H2 = trailing twelve months.
#
# Tag spellings observed in production NSE quarterly filings
# (verified against INFY Q2/Q4 FY24-FY25, RELIANCE Q2 FY25,
# HDFCBANK Q2 FY25, HINDUNILVR Q4 FY24). The
# `*ClassifiedAsInvestingActivities` suffix on capex is specific to
# the quarterly schema — the annual XBRL uses the shorter form, hence
# the dual mapping in nse_xbrl_fundamentals.py::_FIELD_TAGS["capex"].
# ───────────────────────────────────────────────────────────────────────

QUARTERLY_CASHFLOW_TAGS: dict[str, list[str]] = {
    "cfo_cr": [
        "CashFlowsFromUsedInOperatingActivities",
        "NetCashFlowFromOperatingActivities",
        "NetCashGeneratedFromOperatingActivities",
        "CashFlowsFromUsedInOperatingActivitiesTotal",
        "NetCashFlowsFromUsedInOperatingActivities",
        "CashFlowsFromUsedInOperations",
        "NetCashFromUsedInOperatingActivities",
    ],
    "cfi_cr": [
        "CashFlowsFromUsedInInvestingActivities",
        "NetCashFlowFromInvestingActivities",
        "CashFlowsFromUsedInInvestingActivitiesTotal",
        "NetCashUsedInInvestingActivities",
        "NetCashFromUsedInInvestingActivities",
    ],
    "cff_cr": [
        "CashFlowsFromUsedInFinancingActivities",
        "NetCashFlowFromFinancingActivities",
        "CashFlowsFromUsedInFinancingActivitiesTotal",
        "NetCashUsedInFinancingActivities",
        "NetCashFromUsedInFinancingActivities",
    ],
    "capex_cr": [
        # Quarterly schema spelling (the `ClassifiedAs...` suffix is
        # added to disambiguate investing-section facts from
        # balance-sheet PP&E movement).
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssetsClassifiedAsInvestingActivities",
        "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
        # Annual-style fallbacks for cross-schema robustness
        "PurchaseOfPropertyPlantAndEquipment",
        "PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssets",
        "PurchaseOfFixedAssets",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForPropertyPlantAndEquipment",
        "AdditionsToPropertyPlantAndEquipment",
        "CapitalExpenditure",
    ],
}


# ───────────────────────────────────────────────────────────────────────
# Schema detection
# ───────────────────────────────────────────────────────────────────────

def detect_schema(xbrl_url: str | None, xml_bytes: bytes | None) -> str:
    """Return one of 'banking' | 'insurance' | 'industrial'.

    Priority:
      1. URL keyword (BANKING_, INSURANCE_, INTEGRATED_FILING_BANKING_,
         INTEGRATED_FILING_INSURANCE_) — cheap, no XML parse needed
      2. XML namespace map (suffix '-bnk' / '-ins' OR new integrated-
         filing URI substrings `IntegratedFinance_Banking` /
         `IntegratedFinance_Insurance`)
      3. Default: 'industrial'

    The `INTEGRATED_FILING_*` URL prefixes were introduced by NSE in
    the SEBI Integrated Filing rollout (2026). The financial XBRL now
    uses the unified `in-capmkt:` namespace for all schemas, with the
    industry split encoded in the namespace *URI* path (e.g.
    `http://.../IntegratedFinance_Banking/.../in-capmkt/in-capmkt-ent`).
    Both filename and URI matches are needed because we sometimes hold
    the bytes without the URL (parser unit-tests) or vice versa.
    """
    if xbrl_url:
        u = xbrl_url.upper()
        # The "BANKING_" check naturally subsumes "INTEGRATED_FILING_BANKING_".
        if "BANKING_" in u or "/BANK/" in u:
            return "banking"
        # Insurance — INTEGRATED_FILING_INSURANCE_ + legacy LI_/GI_ filename
        # prefixes. Match on the filename segment so we don't false-positive
        # on '/LI/' in other path components.
        last = u.rsplit("/", 1)[-1]
        if (
            last.startswith("LI_")
            or last.startswith("GI_")
            or "INSURANCE_" in u
        ):
            return "insurance"

    if xml_bytes:
        try:
            from lxml import etree

            root = etree.fromstring(xml_bytes)
            for _prefix, uri in (root.nsmap or {}).items():
                if not uri:
                    continue
                low = uri.lower()
                # Legacy in-bse-fin-bnk / -ins suffixes.
                if low.endswith("-bnk") or "-bnk/" in low or "-bnk-" in low:
                    return "banking"
                if low.endswith("-ins") or "-ins/" in low or "-ins-" in low:
                    return "insurance"
                if "/insurance/" in low:
                    return "insurance"
                # New 2026 integrated-filing URI segments.
                if "integratedfinance_banking" in low:
                    return "banking"
                if "integratedfinance_insurance" in low:
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
        # Millions declared but values look like raw INR. Affects
        # BHARTIARTL / MARUTI / SUNPHARMA Q2 FY25 among others: declared
        # 'Millions' (divisor=10) but rev_raw is in raw rupees, producing
        # cfo_cr off by 1e6. Same ₹10-trillion sanity threshold as the
        # 'Crores' bypass above (raw/10 > 1e10 => declared Mn cannot be
        # right; treat as raw INR).
        if declared == 0.1 and revenue_raw is not None and abs(revenue_raw) > 1e10:
            return 1e7
        # General post-compute sanity guard: regardless of declared scale,
        # if the resulting value_in_cr would exceed ₹10 trillion (1e6 Cr)
        # the file is almost certainly a raw-INR template mis-tag — no
        # Indian filer reports a quarter that large. Fall back to raw-INR
        # divisor 1e7.
        if revenue_raw is not None:
            divisor_candidate = {
                "crores": 1.0,
                "lakhs": 100.0,
                "millions": 10.0,
                "thousands": 1e5,
                "hundreds": 1e6,
                "actual": 1e7,
            }.get(rounding)
            if divisor_candidate is not None and divisor_candidate < 1e7:
                if abs(revenue_raw) / divisor_candidate > 1e6:
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


def _pick_ytd_cashflow_fact(
    facts: dict[str, list[tuple[float, str]]],
    contexts: dict[str, dict[str, Any]],
    local_names: list[str],
    period_end: date,
) -> float | None:
    """Pick a YTD cumulative cash-flow fact ending on `period_end`.

    Cash-flow values in NSE quarterly XBRL live in a `Four`-prefixed
    duration context (Ind-AS YTD convention). The context's printed
    <startDate>/<endDate> can be misleading — it sometimes spans only
    the final quarter even when the value is the full YTD cumulative
    (this is the same OneD/FourD quirk that motivated the annual
    period-detection fix in `_detect_period_type_from_contexts`).

    Resolution order:
      1. A context whose ID starts with "Four" AND whose endDate
         matches `period_end` (the canonical YTD context).
      2. Any context whose endDate matches `period_end` and whose
         duration is >= 60 days (covers companies whose template
         puts cash flow into the OneD = quarter context, with the
         YTD cumulative still inside it — observed on a handful
         of PSU filings).
      3. None — fact is genuinely absent.
    """
    period_end_s = period_end.isoformat()
    for ln in local_names:
        candidates = facts.get(ln, [])
        if not candidates:
            continue
        # Prefer Four-prefixed (canonical YTD)
        for val, ctx in candidates:
            ci = contexts.get(ctx, {})
            if ci.get("end") != period_end_s:
                continue
            if isinstance(ctx, str) and ctx.startswith("Four"):
                return val
        # Fallback: any duration context ending on period_end
        for val, ctx in candidates:
            ci = contexts.get(ctx, {})
            if ci.get("end") != period_end_s:
                continue
            start_s = ci.get("start")
            if not start_s:
                continue
            try:
                start_d = datetime.strptime(start_s, "%Y-%m-%d").date()
            except Exception:
                continue
            if (period_end - start_d).days >= 60:
                return val
    return None


def _cashflow_period_months(period_end: date) -> int:
    """Return 6 for H1 (Q2/Sep), 12 for H2/FY (Q4/Mar), else 0.

    SEBI LODR cash flow is published only at H1 (Sep) and Q4 (Mar).
    A Q4 (Mar) filing's FourD context carries the FULL FY YTD value
    (12 months), not just H2 — so 12 is correct, not 6.
    """
    m = period_end.month
    if m == 9:
        return 6
    if m == 3:
        return 12
    return 0


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

    # Cash-flow extraction — only populated on H1 (Sep) and FY (Mar)
    # period_ends per SEBI LODR Reg 33. We still attempt the parse on
    # Q1/Q3 in case a filer included it voluntarily; the values will
    # simply come back None and the row carries cfo_cr = None.
    has_cf_str = (_pick_string(sfacts, META_TAGS["has_cashflow_str"]) or "").strip().lower()
    has_cashflow_statement: bool | None
    if has_cf_str in ("true", "yes", "1"):
        has_cashflow_statement = True
    elif has_cf_str in ("false", "no", "0"):
        has_cashflow_statement = False
    else:
        has_cashflow_statement = None

    def cf_num(name: str) -> float | None:
        tag_list = QUARTERLY_CASHFLOW_TAGS.get(name) or []
        v = _pick_ytd_cashflow_fact(facts, contexts, tag_list, period_end)
        return None if v is None else round(v / scale, 2)

    cfo_cr = cf_num("cfo_cr")
    cfi_cr = cf_num("cfi_cr")
    cff_cr = cf_num("cff_cr")
    capex_cr = cf_num("capex_cr")
    # If any cash-flow value parsed, record the YTD period length so
    # the TTM aggregator downstream can stitch H1 + previous-FY-H2.
    if cfo_cr is not None or cfi_cr is not None or cff_cr is not None:
        cashflow_period_months: int | None = _cashflow_period_months(period_end) or None
    else:
        cashflow_period_months = None

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
        # Cash flow (H1/H2 YTD cumulative — see QUARTERLY_CASHFLOW_TAGS
        # docstring and migration 034 for unit / period semantics).
        # NULL on Q1/Q3 filings; capex omitted on services-heavy filers
        # whose investing section is dominated by financial-asset moves.
        "cfo_cr": cfo_cr,
        "cfi_cr": cfi_cr,
        "cff_cr": cff_cr,
        "capex_cr": capex_cr,
        "cashflow_period_months": cashflow_period_months,
        "has_cashflow_statement": has_cashflow_statement,
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
