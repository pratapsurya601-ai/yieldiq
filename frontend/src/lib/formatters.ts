/**
 * Display formatters for monetary values. Kept separate from `utils.ts`
 * so callers that only need a market-cap helper don't transitively pull
 * in company-name lookup tables.
 *
 * All helpers accept values in Crore (₹1 Cr = 10,000,000). Backend
 * consistently returns `market_cap_cr` in this unit for INR tickers.
 */

/**
 * Format a market cap expressed in Crore (₹Cr) into a compact Indian
 * display string.
 *
 *   ≥ 10,000 Cr  → "₹1.44 Lakh Cr" (1 Lakh Cr = 100,000 Cr)
 *   ≥ 1,000 Cr   → "₹14,400 Cr"    (Indian grouping)
 *   < 1,000 Cr   → "₹850 Cr"
 *
 * Rationale: the older `₹1.44L Cr` shorthand reads awkwardly to most
 * Indian readers — "L Cr" is jargon. "Lakh Cr" is the newspaper
 * convention and matches how Moneycontrol/ET quote large caps.
 */
export function formatMarketCap(cr: number): string {
  if (!Number.isFinite(cr) || cr <= 0) return "\u2014"
  if (cr >= 10_000) {
    // 1 Lakh Cr = 100,000 Cr. Two decimals so "1.44" doesn't round to "1.4".
    return `\u20b9${(cr / 100_000).toFixed(2)} Lakh Cr`
  }
  if (cr >= 1_000) {
    // Indian digit grouping: 14,400 not 14400.
    const whole = Math.round(cr)
    return `\u20b9${whole.toLocaleString("en-IN")} Cr`
  }
  return `\u20b9${cr.toFixed(0)} Cr`
}
