/**
 * YieldIQ is an India-only platform — every ticker is .NS or .BO.
 * Therefore the safe default is ₹ everywhere. $ should ONLY appear if
 * we explicitly know the value is non-INR (rare; e.g. ADR cross-listing).
 *
 * This module is the single source of truth for the currency symbol.
 * Replaces the previous `c === "INR" ? "₹" : "$"` strict-equality checks
 * scattered across components, which fell back to `$` on:
 *   - "USD" (the v50 yfinance currency-mistag bug for Indian listings)
 *   - "inr" lowercase
 *   - "" empty string
 *   - null / undefined
 *
 * Defensive note: the BACKEND occasionally tags currency='USD' for
 * Indian-listed stocks (the v50 mis-tag bug — partially patched in
 * PR #173). When `isIndianTicker(ticker)` is true and the currency
 * looks foreign, we log a console warning and still render ₹.
 */

const FOREIGN_CURRENCIES = new Set([
  "USD", "EUR", "GBP", "JPY", "CNY", "SGD", "HKD", "AUD", "CAD", "CHF",
])

const FOREIGN_SYMBOL: Record<string, string> = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  CNY: "¥",
  SGD: "S$",
  HKD: "HK$",
  AUD: "A$",
  CAD: "C$",
  CHF: "CHF ",
}

const RUPEE = "₹"

/** Indian listing heuristic — used to detect the v50 currency-mistag bug. */
export function isIndianTicker(ticker?: string | null, exchange?: string | null): boolean {
  if (ticker) {
    const t = ticker.toUpperCase()
    if (t.endsWith(".NS") || t.endsWith(".BO")) return true
  }
  if (exchange) {
    const ex = exchange.toUpperCase()
    if (ex === "NSE" || ex === "BSE") return true
  }
  return false
}

/**
 * Single source of truth for the currency symbol. Defaults to ₹ unless
 * an EXPLICIT, recognised foreign currency is provided.
 *
 * Optional `ticker` lets us catch the v50 yfinance mis-tag where an
 * Indian listing comes through with currency='USD'. We force ₹ in that
 * case and emit a console warning so the bug is visible in dev.
 */
export function currencySymbol(c?: string | null, ticker?: string | null): string {
  if (!c) return RUPEE
  const upper = c.toUpperCase().trim()
  if (upper === "INR" || upper === "RS" || upper === "RS.") return RUPEE
  if (FOREIGN_CURRENCIES.has(upper)) {
    if (isIndianTicker(ticker)) {
      // v50 currency-mistag bug — Indian ticker tagged as USD/etc.
      if (typeof console !== "undefined") {
        // Visible in dev console; in production this still helps support.
        console.warn(
          `[currency] Indian ticker ${ticker} tagged as ${upper}; ` +
          `forcing ₹ (v50 mis-tag bug, see PR #173).`
        )
      }
      return RUPEE
    }
    return FOREIGN_SYMBOL[upper] ?? upper + " "
  }
  // Anything unrecognised (empty, "inr" lowercase already handled, junk) → ₹
  return RUPEE
}

/** Locale matching `currencySymbol` — defaults to en-IN for ₹. */
export function currencyLocale(c?: string | null, ticker?: string | null): string {
  if (!c) return "en-IN"
  const upper = c.toUpperCase().trim()
  if (FOREIGN_CURRENCIES.has(upper) && !isIndianTicker(ticker)) {
    if (upper === "GBP") return "en-GB"
    if (upper === "EUR") return "de-DE"
    if (upper === "JPY") return "ja-JP"
    return "en-US"
  }
  return "en-IN"
}

/**
 * Convenience: format an amount as ₹X,XXX (en-IN). Pass `compact: true`
 * for ₹X.X Cr / ₹X.X L for large values. Use this when you need the
 * full `${symbol}${amount}` rendered with the right locale grouping.
 */
export function formatINR(
  amount: number,
  opts?: { decimals?: number; compact?: boolean }
): string {
  if (!Number.isFinite(amount)) return "—"
  const decimals = opts?.decimals ?? 2
  if (opts?.compact) {
    const abs = Math.abs(amount)
    if (abs >= 1e7) return `${RUPEE}${(amount / 1e7).toFixed(1)} Cr`
    if (abs >= 1e5) return `${RUPEE}${(amount / 1e5).toFixed(1)} L`
  }
  return `${RUPEE}${amount.toLocaleString("en-IN", { maximumFractionDigits: decimals })}`
}
