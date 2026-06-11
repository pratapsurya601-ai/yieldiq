/**
 * formatNumbers.ts — canonical number-comprehension formatters.
 *
 * Page-wide number standard (2026-06-11): every number on the analysis
 * page must be instantly understandable — consistent formatting,
 * explicit units, Indian digit grouping, and a single em-dash ("—")
 * fallback for missing/unusable values.
 *
 * This module is the ONE source of truth for:
 *   - per-share rupee amounts        → formatINR(1147.77)          = "₹1,147.77"
 *   - compact rupee amounts          → formatINR(1.15e13, compact) = "₹11.50 Lakh Cr"
 *   - crore-denominated amounts      → formatCrore(62227)          = "₹62,227 Cr"
 *   - percentages (signed/unsigned)  → formatPct(53.7, signed)     = "+53.7%"
 *   - valuation multiples            → formatMultiple(16.7)        = "16.7x"
 *   - plain counts                   → formatCompactCount(13982)   = "13,982"
 *
 * Conventions locked here (do not fork in panel-local helpers):
 *   - Em-dash "—" for null / undefined / NaN / Infinity. Never "--",
 *     never "N/A", never an empty string.
 *   - Indian digit grouping via toLocaleString("en-IN") (1,23,456).
 *   - Large-cap unit is "Lakh Cr" (newspaper convention), never the
 *     "L Cr" shorthand — see lib/formatters.ts for the rationale.
 *   - Crore compaction thresholds: >= 1,00,000 Cr → "X.XX Lakh Cr";
 *     >= 1,000 Cr → whole-rupee Indian grouping; >= 1 Cr → 1 decimal;
 *     < 1 Cr → 2 decimals.
 *   - Signed percentages always carry an explicit "+" on >= 0 (deltas,
 *     MoS, YoY); ratios like payout stay unsigned.
 *
 * Existing canonical helpers are re-exported below so call sites can
 * import everything number-related from this one module:
 *   - formatCurrency (lib/utils)    — currency-aware rupee/foreign path
 *   - formatMarketCap (lib/formatters) — market-cap specific (>0 only)
 */

export { formatCurrency } from "./utils"
export { formatMarketCap } from "./formatters"

const EM_DASH = "—"

/** True when the value is a finite number we can format. */
function usable(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v)
}

export interface FormatINROptions {
  /**
   * Compact large rupee amounts: >= ₹1 Cr → Cr / Lakh Cr scale,
   * >= ₹1 Lakh → "₹X.XX L". Per-share prices stay non-compact.
   */
  compact?: boolean
  /** Max fraction digits on the non-compact path (default 2). */
  decimals?: number
}

/**
 * Format an ABSOLUTE-RUPEE amount.
 *
 *   formatINR(1147.77)                  → "₹1,147.77"
 *   formatINR(-980.5)                   → "-₹980.5" (sign before ₹)
 *   formatINR(1.15e13, {compact: true}) → "₹11.50 Lakh Cr"
 *   formatINR(250_000, {compact: true}) → "₹2.50 L"
 *   formatINR(null)                     → "—"
 */
export function formatINR(
  value: number | null | undefined,
  opts: FormatINROptions = {},
): string {
  if (!usable(value)) return EM_DASH
  const { compact = false, decimals = 2 } = opts
  const sign = value < 0 ? "-" : ""
  const abs = Math.abs(value)
  if (compact) {
    if (abs >= 1e7) return `${sign}${formatCrore(abs / 1e7)}`
    if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`
  }
  return `${sign}₹${abs.toLocaleString("en-IN", {
    maximumFractionDigits: decimals,
  })}`
}

/**
 * Format a CRORE-DENOMINATED amount (₹1 Cr = 1e7 rupees). This is the
 * unit the backend uses for market caps and financial-statement rows.
 *
 *   formatCrore(1_150_000) → "₹11.50 Lakh Cr"
 *   formatCrore(62_227)    → "₹62,227 Cr"
 *   formatCrore(850.4)     → "₹850.4 Cr"
 *   formatCrore(0.42)      → "₹0.42 Cr"
 *   formatCrore(-14_400)   → "-₹14,400 Cr"
 *   formatCrore(NaN)       → "—"
 */
export function formatCrore(cr: number | null | undefined): string {
  if (!usable(cr)) return EM_DASH
  const sign = cr < 0 ? "-" : ""
  const abs = Math.abs(cr)
  if (abs >= 100_000) {
    // Two decimals so "1.44" never rounds to "1.4"; threshold keeps the
    // unit >= 1.00 Lakh Cr (mid-caps stay on the plain-Cr path).
    return `${sign}₹${(abs / 100_000).toFixed(2)} Lakh Cr`
  }
  if (abs >= 1_000) {
    return `${sign}₹${Math.round(abs).toLocaleString("en-IN")} Cr`
  }
  if (abs >= 1) return `${sign}₹${abs.toFixed(1)} Cr`
  return `${sign}₹${abs.toFixed(2)} Cr`
}

export interface FormatPctOptions {
  /**
   * Explicit "+" on values >= 0. Use for deltas (MoS, YoY, CAGR,
   * discount-to-FV). Ratios like payout or ROE stay unsigned.
   */
  signed?: boolean
  /** Fraction digits (default 1 — the page-wide percentage standard). */
  decimals?: number
}

/**
 * Format a value ALREADY IN PERCENT UNITS (53.7 means 53.7%).
 *
 *   formatPct(53.7, {signed: true})  → "+53.7%"
 *   formatPct(-12.34, {signed: true})→ "-12.3%"
 *   formatPct(26.0)                  → "26.0%"
 *   formatPct(26, {decimals: 0})     → "26%"
 *   formatPct(null)                  → "—"
 */
export function formatPct(
  value: number | null | undefined,
  opts: FormatPctOptions = {},
): string {
  if (!usable(value)) return EM_DASH
  const { signed = false, decimals = 1 } = opts
  const prefix = signed && value >= 0 ? "+" : ""
  return `${prefix}${value.toFixed(decimals)}%`
}

/**
 * Format a valuation multiple ("x" suffix).
 *
 *   formatMultiple(16.7)  → "16.7x"
 *   formatMultiple(0)     → "0.0x"
 *   formatMultiple(null)  → "—"
 */
export function formatMultiple(
  value: number | null | undefined,
  decimals = 1,
): string {
  if (!usable(value)) return EM_DASH
  return `${value.toFixed(decimals)}x`
}

/**
 * Format a plain count with Indian digit grouping, no unit.
 *
 *   formatCompactCount(13982)   → "13,982"
 *   formatCompactCount(123456)  → "1,23,456"
 *   formatCompactCount(12.7)    → "13"
 *   formatCompactCount(null)    → "—"
 */
export function formatCompactCount(value: number | null | undefined): string {
  if (!usable(value)) return EM_DASH
  return Math.round(value).toLocaleString("en-IN")
}
