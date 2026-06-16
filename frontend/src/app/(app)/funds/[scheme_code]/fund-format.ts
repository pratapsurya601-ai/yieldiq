/**
 * fund-format — shared, framework-free formatting helpers for the
 * /funds/[scheme_code] Asset Page tabs.
 *
 * Kept deliberately tiny and pure so each tab (server- or client-side)
 * can import the same render path. UNIT conventions follow the backend
 * CONTRACT documented in types/api.ts:
 *   - ret_*, cagr_*, stdev_*, max_drawdown_*, alpha_*, *_excess_* are
 *     DECIMAL FRACTIONS → ×100 for a percent display.
 *   - sharpe / sortino / beta / info_ratio / capture are dimensionless.
 *   - ter_* and weight_pct are already in PERCENT.
 *   - category_percentile_3y is on a 0-100 scale.
 */

export const DASH = "—"

/** A value already in PERCENT (TER, weight) → "0.62%". */
export function pct(v: number | null | undefined, dp = 2): string {
  if (v == null || !Number.isFinite(v)) return DASH
  return `${v.toFixed(dp)}%`
}

/** A DECIMAL FRACTION (0.0884) → "8.84%". */
export function fracPct(v: number | null | undefined, dp = 2): string {
  if (v == null || !Number.isFinite(v)) return DASH
  return `${(v * 100).toFixed(dp)}%`
}

/** A dimensionless ratio (sharpe, beta) → "1.24". */
export function ratio(v: number | null | undefined, dp = 2): string {
  if (v == null || !Number.isFinite(v)) return DASH
  return v.toFixed(dp)
}

/** True only when a number is present and finite. */
export function present(v: number | null | undefined): v is number {
  return v != null && Number.isFinite(v)
}

/** Tone class for a signed delta — success on ≥0, warning below. */
export function signTone(v: number | null | undefined): string {
  if (!present(v)) return "text-caption"
  return v >= 0 ? "text-success" : "text-warning"
}
