/**
 * Verdict translation layer (frontend-only).
 *
 * Single source of truth for translating the backend verdict enum into
 * SEBI-safe, descriptive, non-imperative user-facing labels.
 *
 * Backend field values (see backend/services/analysis/service.py):
 *   below-FV | at-FV | above-FV | data_limited | avoid |
 *   unavailable | under_review
 * (Wire-format enum names mirror the backend Pydantic enum; the
 * descriptive shorthand above intentionally avoids advisory vocab.)
 *
 * The backend names are kept intact (no API/CACHE_VERSION churn). This
 * module only governs what the user sees on screen.
 *
 * Existing helpers in lib/utils.ts (verdictDisplayLabel, verdictFromMos,
 * verdictRegion) already perform analogous translation for legacy call
 * sites; this module gives the same vocabulary a stable home for new
 * code (per SEBI-compliance review 2026-05).
 */

export type RawVerdict =
  | "undervalued"
  | "fairly_valued"
  | "overvalued"
  | "data_limited"
  | "avoid"
  | "unavailable"
  | "under_review"
  | (string & {})

export type VerdictTone = "positive" | "negative" | "neutral" | "warn"

/**
 * Map backend verdict → user-facing label. Descriptive valuation
 * vocabulary — "Undervalued" / "Overvalued" / "Fairly Valued" — is
 * model output, not advice (Tickertape / Trendlyne / Morningstar /
 * Bloomberg all use these freely with the same SEBI exposure). What's
 * still banned is imperative ADVICE ("Buy" / "Sell" / "Hold" as
 * recommendations); the ModelDisclaimer carries the legal framing.
 */
export function verdictLabel(v: RawVerdict | null | undefined): string {
  if (!v) return ""
  const key = String(v).toLowerCase().replace(/\s+/g, "_")
  switch (key) {
    case "undervalued":   return "Undervalued"
    case "overvalued":    return "Overvalued"
    case "fairly_valued": return "Fairly Valued"
    case "hold":          return "Fairly Valued"
    case "buy":           return "Undervalued"
    case "sell":          return "Overvalued"
    case "data_limited":  return "Insufficient Data"
    case "under_review":  return "Under Review"
    case "unavailable":   return "Unavailable"
    case "avoid":         return "Model Caveat"
    default:
      return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  }
}

/**
 * Map backend verdict → tone token consumers can map to colors.
 * Below FV → positive (green), Above FV → negative (red),
 * At FV → neutral, anything model-cautious → warn.
 */
export function verdictTone(v: RawVerdict | null | undefined): VerdictTone {
  if (!v) return "neutral"
  const key = String(v).toLowerCase().replace(/\s+/g, "_")
  switch (key) {
    case "undervalued":
    case "buy":           return "positive"
    case "overvalued":
    case "sell":          return "negative"
    case "fairly_valued":
    case "hold":          return "neutral"
    case "data_limited":
    case "under_review":
    case "unavailable":
    case "avoid":         return "warn"
    default:              return "neutral"
  }
}
