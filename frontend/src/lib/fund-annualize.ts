/**
 * fund-annualize — trailing-return annualization for the /funds screener.
 *
 * The funds API returns trailing returns as CUMULATIVE decimal fractions
 * over the window (e.g. ret_3y = 0.77 means the NAV grew 77% across the
 * full three years, NOT 77% per year). Global research tables
 * (Morningstar, Yahoo Finance) quote multi-year trailing returns
 * ANNUALIZED — the compound annual growth rate (CAGR p.a.) — so a 3Y of
 * 0.77 reads as ≈21.0% p.a. This module is the single source of truth
 * for that conversion and its display formatting.
 *
 * Unit contract (mirrors models/fund.py FundListItem):
 *   • ret_1y / ret_3y / ret_5y / ret_10y are CUMULATIVE decimal fractions.
 *   • The 1Y window is already a one-year figure, so it is NOT
 *     de-compounded — annualized(0.088, 1) === 8.8.
 *   • For n > 1 the annualized rate is ((1 + cumulative)^(1/n) − 1) × 100.
 *
 * Guards (return null → the cell renders "—"):
 *   • null / undefined / non-finite input.
 *   • (1 + cumulative) <= 0 — a total loss ≥ 100% would make the n-th
 *     root of a non-positive number NaN/imaginary, which is meaningless
 *     to display; we suppress rather than print "NaN%".
 *
 * Pure functions only (no React, no DOM) so they are unit-testable in
 * isolation — see __tests__/fundAnnualize.test.ts.
 */

/** Number of compounding years for each trailing-return window. */
export const RETURN_WINDOW_YEARS = { ret_1y: 1, ret_3y: 3, ret_5y: 5, ret_10y: 10 } as const

/**
 * Annualize a cumulative trailing return to a percent-per-annum figure.
 *
 * @param cumulative CUMULATIVE decimal fraction over the window
 *   (0.77 = +77% total). May be null/undefined.
 * @param years      length of the window in years (1, 3, 5, 10).
 * @returns annualized return as a PERCENT number (21.0), or null when the
 *   input is missing or (1 + cumulative) <= 0.
 *
 * Examples:
 *   annualizeReturn(0.088, 1)  → 8.8     (1Y passes through, ×100)
 *   annualizeReturn(0.77, 3)   → ~21.0   ((1.77)^(1/3) − 1) × 100
 *   annualizeReturn(-1, 5)     → null    (1 + (−1) = 0, not positive)
 *   annualizeReturn(null, 3)   → null
 */
export function annualizeReturn(
  cumulative: number | null | undefined,
  years: number,
): number | null {
  if (cumulative === null || cumulative === undefined) return null
  if (!Number.isFinite(cumulative)) return null
  // The 1Y window is already a one-year return — no de-compounding.
  if (years <= 1) return cumulative * 100
  const growth = 1 + cumulative
  // n-th root of a non-positive number is undefined for display purposes.
  if (growth <= 0) return null
  const annual = Math.pow(growth, 1 / years) - 1
  if (!Number.isFinite(annual)) return null
  return annual * 100
}

/**
 * Format an annualized return PERCENT for a table cell.
 *
 * @param pct annualized percent (from annualizeReturn), or null.
 * @returns a one-decimal signed percent string ("+21.0%", "−4.3%"), or
 *   "—" for a null/missing value. Uses a real minus sign (U+2212) so
 *   negatives align under positives in a tabular-figures column.
 */
export function formatAnnualizedPct(pct: number | null): string {
  if (pct === null || !Number.isFinite(pct)) return "—"
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : ""
  return `${sign}${Math.abs(pct).toFixed(1)}%`
}

/**
 * Convenience: annualize then format in one call for a given window.
 *
 *   formatTrailingReturn(0.77, 3) → "+21.0%"
 *   formatTrailingReturn(null, 5) → "—"
 */
export function formatTrailingReturn(
  cumulative: number | null | undefined,
  years: number,
): string {
  return formatAnnualizedPct(annualizeReturn(cumulative, years))
}
