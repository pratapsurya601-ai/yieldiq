// frontend/src/lib/sectorFinancials.ts
// ═════════════════════════════════════════════════════════════════
// Sector-aware financial-field resolvers.
//
// Banks (and the financial cohorts that share the same schema —
// NBFCs, insurers) do NOT report `revenue` / `free_cash_flow` in
// the conventional sense. Their income statement is shaped around
// `interest_earned`, `net_interest_income`, and `total_income`;
// they do not run a meaningful FCF surface at all.
//
// Until this module landed, every chart and panel that read
// `financials.revenue` or `financials.fcf` directly would render
// flat-zero bars for HDFCBANK, SBIN, AXISBANK, etc., because the
// generic field is `null` for those tickers.
//
// The helpers below take the raw `Financials` row plus a
// best-effort sector / ticker hint and return the value that needs
// to be displayed.  Components stay simple — they call
// `getDisplayRevenue(...)` once and get back either a number or
// `null` — and the cohort decision is centralised here.
//
// SYNC RULE: `isBankSector` mirrors backend `_PURE_BANK_TICKERS_FOR_DE`
// plus the canonical "Bank" / "Private Bank" / "PSU Bank" sector
// strings used by `sector-taxonomy.ts`.  When the bank universe
// changes, update `bankTickers.ts` first, then re-verify this file
// against it.
// ═════════════════════════════════════════════════════════════════

import { isPureBank } from "@/lib/bankTickers"

/** Minimal interface satisfied by both `FinancialYear` (from
 * `@/lib/api`) and the loose `{revenue, fcf}` shape used by
 * `FinancialBars`. Field-additive — extra keys are ignored. */
export interface SectorAwareFinancials {
  revenue?: number | null
  free_cash_flow?: number | null
  fcf?: number | null
  // Bank / NBFC / Insurance schemas
  interest_earned?: number | null
  net_interest_income?: number | null
  total_income?: number | null
  net_income?: number | null
}

/** Lowercase tokens that identify a bank-cohort sector string. */
const BANK_SECTOR_TOKENS = new Set<string>([
  "bank",
  "banks",
  "banking",
  "private bank",
  "private banks",
  "private sector bank",
  "psu bank",
  "psu banks",
  "public sector bank",
])

const NBFC_SECTOR_TOKENS = new Set<string>([
  "nbfc",
  "non banking financial company",
  "non-banking financial company",
  "financial services",
  "finance",
  "diversified financials",
])

const INSURANCE_SECTOR_TOKENS = new Set<string>([
  "insurance",
  "life insurance",
  "general insurance",
])

function normToken(raw: string | null | undefined): string {
  return (raw ?? "").trim().toLowerCase()
}

/**
 * Treat as a bank when EITHER the sector string maps into the bank
 * cohort OR the ticker is in the canonical pure-bank list. The
 * latter rescues tickers whose `sector` field arrived as `null`
 * during cold-compute, which would otherwise leak the generic-
 * revenue path.
 */
export function isBankSector(sector: string | null | undefined, ticker?: string | null | undefined): boolean {
  if (isPureBank(ticker)) return true
  const t = normToken(sector)
  if (!t) return false
  return BANK_SECTOR_TOKENS.has(t)
}

/** NBFC cohort: separate from bank but shares the financial-schema
 * idiosyncrasies (interest income, no conventional FCF). */
export function isNBFCSector(sector: string | null | undefined): boolean {
  const t = normToken(sector)
  return NBFC_SECTOR_TOKENS.has(t)
}

export function isInsuranceSector(sector: string | null | undefined): boolean {
  const t = normToken(sector)
  return INSURANCE_SECTOR_TOKENS.has(t)
}

/** Convenience: returns true for any of the three financial cohorts
 * (bank / NBFC / insurance) that share the "interest income drives
 * the top line, FCF is not meaningful" pattern. */
export function isFinancialCohort(sector: string | null | undefined, ticker?: string | null | undefined): boolean {
  return isBankSector(sector, ticker) || isNBFCSector(sector) || isInsuranceSector(sector)
}

/**
 * Resolve the value that gets plotted on a "Revenue" axis for
 * THIS ticker / sector pair.
 *
 *   Generic    → financials.revenue
 *   Bank/NBFC  → interest_earned ?? net_interest_income ?? total_income
 *   Insurance  → total_income (premium-income proxy) ?? revenue
 *
 * Null when no sensible field exists.
 */
export function getDisplayRevenue(
  f: SectorAwareFinancials | null | undefined,
  sector: string | null | undefined,
  ticker?: string | null | undefined,
): number | null {
  if (!f) return null
  if (isBankSector(sector, ticker) || isNBFCSector(sector)) {
    return (
      _num(f.interest_earned) ??
      _num(f.net_interest_income) ??
      _num(f.total_income) ??
      _num(f.revenue)
    )
  }
  if (isInsuranceSector(sector)) {
    return _num(f.total_income) ?? _num(f.revenue)
  }
  return _num(f.revenue)
}

/**
 * Display label for the revenue axis. Used in chart headers so the
 * reader sees "Net Interest Income" instead of "Revenue" on a bank
 * page where the bars are actually NII.
 */
export function getDisplayRevenueLabel(
  sector: string | null | undefined,
  ticker?: string | null | undefined,
): string {
  if (isBankSector(sector, ticker) || isNBFCSector(sector)) return "Net Interest Income"
  if (isInsuranceSector(sector)) return "Net Premium Income"
  return "Revenue"
}

/**
 * FCF resolver. Banks / NBFCs / insurers DO NOT report a meaningful
 * Free Cash Flow figure — their cash cycle is the deposit-loan
 * spread, not capex-driven cash generation. Returning `null` here
 * makes the chart show its empty state with the not-applicable note
 * instead of stacking flat-zero bars.
 */
export function getDisplayFCF(
  f: SectorAwareFinancials | null | undefined,
  sector: string | null | undefined,
  ticker?: string | null | undefined,
): number | null {
  if (!f) return null
  if (isFinancialCohort(sector, ticker)) return null
  return _num(f.free_cash_flow) ?? _num(f.fcf)
}

/**
 * Display label for the FCF axis. On financial cohorts the chart
 * renders a "not meaningful" hint rather than a numeric label.
 */
export function getDisplayFCFLabel(
  sector: string | null | undefined,
  ticker?: string | null | undefined,
): string {
  if (isFinancialCohort(sector, ticker)) return "Free Cash Flow (n/a for banks)"
  return "Free Cash Flow"
}

/**
 * One-liner caption to show under an FCF chart that is hidden for
 * the cohort. Helps the reader understand WHY there's nothing there
 * — and points them at the bank-specific surfaces (NIM, CASA, loan
 * growth) that DO answer the underlying question.
 */
export function getFCFNotApplicableNote(
  sector: string | null | undefined,
  ticker?: string | null | undefined,
): string | null {
  if (isFinancialCohort(sector, ticker)) {
    return "Free cash flow is not meaningful for banks and NBFCs — see Net Interest Margin and loan-book growth instead."
  }
  return null
}

function _num(v: number | null | undefined): number | null {
  if (v === null || v === undefined) return null
  if (!Number.isFinite(v)) return null
  return v
}
