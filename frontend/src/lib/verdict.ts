/**
 * Verdict translation layer (frontend-only).
 *
 * Single source of truth for translating the backend verdict enum into
 * SEBI-safe, descriptive, non-imperative user-facing labels.
 *
 * Backend field values (see backend/services/analysis/service.py):
 *   undervalued | fairly_valued | overvalued | data_limited | avoid |
 *   unavailable | under_review
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
 * Map backend verdict → user-facing label. Purely descriptive — never
 * imperative (no "Buy" / "Sell"), as YieldIQ is not a SEBI-registered
 * investment adviser.
 */
export function verdictLabel(v: RawVerdict | null | undefined): string {
  if (!v) return ""
  const key = String(v).toLowerCase().replace(/\s+/g, "_")
  switch (key) {
    case "undervalued":   return "Undervalued"
    case "overvalued":    return "Overvalued"
    case "fairly_valued": return "Fairly Valued"
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
 * Undervalued → positive (green), Overvalued → negative (red),
 * Fairly Valued → neutral, anything model-cautious → warn.
 */
export function verdictTone(v: RawVerdict | null | undefined): VerdictTone {
  if (!v) return "neutral"
  const key = String(v).toLowerCase().replace(/\s+/g, "_")
  switch (key) {
    case "undervalued":   return "positive"
    case "overvalued":    return "negative"
    case "fairly_valued": return "neutral"
    case "data_limited":
    case "under_review":
    case "unavailable":
    case "avoid":         return "warn"
    default:              return "neutral"
  }
}
