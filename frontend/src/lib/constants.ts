// Single source of truth for colors — matches verdict_colors.py

export const VERDICT_COLORS = {
  undervalued: { bg: "bg-blue-50", text: "text-blue-800", border: "border-blue-200", hex: "#185FA5" },
  fairly_valued: { bg: "bg-gray-100", text: "text-gray-700", border: "border-gray-200", hex: "#475569" },
  overvalued: { bg: "bg-amber-50", text: "text-amber-800", border: "border-amber-200", hex: "#B45309" },
  avoid: { bg: "bg-red-50", text: "text-red-800", border: "border-red-200", hex: "#DC2626" },
  data_limited: { bg: "bg-gray-100", text: "text-gray-600", border: "border-gray-300", hex: "#6B7280" },
  unavailable: { bg: "bg-gray-100", text: "text-gray-500", border: "border-gray-300", hex: "#9CA3AF" },
  // Day-61 (2026-05-21): low_confidence is rendered neutral-slate so a
  // sub-50% confidence reading never reads as a confident undervalued /
  // overvalued call. The hero hint surfaces the actual MoS sign so the
  // user can see whether the underlying model leans cheap or expensive
  // --- the pill itself simply refuses to amplify the signal.
  low_confidence: { bg: "bg-slate-100", text: "text-slate-700", border: "border-slate-300", hex: "#64748B" },
} as const

export const TIER_LIMITS = { free: 5, starter: Infinity, pro: Infinity, analyst: Infinity } as const

export const SCORE_COLOR = (score: number): string => {
  if (score >= 75) return "#185FA5"
  if (score >= 55) return "#B45309"
  return "#DC2626"
}

export const SCORE_GRADE = (score: number): string => {
  if (score >= 75) return "A"
  if (score >= 55) return "B"
  if (score >= 35) return "C"
  if (score >= 20) return "D"
  return "F"
}

// ─────────────────────────────────────────────────────────────────
// Day-34 (2026-05-20): canonical class helpers for verdict / MoS /
// sentiment rendering. Before Day-34, 5+ components duplicated the
// same `bg-X-50 text-X-800 border-X-200` patterns inline — diverging
// when one was updated without the others (e.g. PeerComparisonCard
// used green for undervalued, VerdictChip used VERDICT_COLORS blue).
//
// All chip / pill / badge components should now go through these
// helpers instead of hand-rolling tailwind classes.
// ─────────────────────────────────────────────────────────────────

export type VerdictKey = keyof typeof VERDICT_COLORS

/**
 * Static dark-mode counterpart classes for each verdict. STATIC strings
 * are required so Tailwind's purge step can detect them at build time —
 * any form of interpolated dark-mode class name would be stripped from
 * the production CSS and the dark-mode variants would silently 404.
 */
const VERDICT_DARK_CLASSES: Record<VerdictKey, string> = {
  undervalued:    "dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-900",
  fairly_valued:  "dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700",
  overvalued:     "dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900",
  avoid:          "dark:bg-red-950/40 dark:text-red-300 dark:border-red-900",
  data_limited:   "dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700",
  unavailable:    "dark:bg-gray-800 dark:text-gray-500 dark:border-gray-700",
  low_confidence: "dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700",
}

/**
 * Returns the canonical bg + text + border + dark-mode variant
 * classes for a verdict chip. Pulls hue from VERDICT_COLORS so the
 * single source of truth stays in one place.
 *
 * Usage:
 *   <span className={verdictClassesWithDark("undervalued")}>...
 */
export function verdictClassesWithDark(
  v: VerdictKey | string | null | undefined,
): string {
  const key = (v ?? "").toString().toLowerCase().replace(/\s+/g, "_")
  const isKnown = (key in VERDICT_COLORS) as boolean
  const verdictKey: VerdictKey = isKnown
    ? (key as VerdictKey)
    : "unavailable"
  const c = VERDICT_COLORS[verdictKey]
  return [c.bg, c.text, c.border, VERDICT_DARK_CLASSES[verdictKey]].join(" ")
}

/**
 * MoS sign → tone class. Positive (cheap) gets the undervalued hue,
 * negative gets overvalued / avoid hue, neutral gets fairly_valued.
 * Keeps the MoS coloring consistent with the verdict chip palette
 * across hero, peer card, action bar, etc.
 *
 * Usage:
 *   <span className={mosToneClass(mos_pct)}>...
 */
export function mosToneClass(
  mosPct: number | null | undefined,
): string {
  if (mosPct === null || mosPct === undefined || !Number.isFinite(mosPct)) {
    return verdictClassesWithDark("data_limited")
  }
  if (mosPct >= 15) return verdictClassesWithDark("undervalued")
  if (mosPct <= -15) return verdictClassesWithDark("overvalued")
  return verdictClassesWithDark("fairly_valued")
}

/**
 * Concall transcript sentiment → tone class. Sentiment is a
 * different semantic from verdict — "positive" management commentary
 * gets the undervalued hue (good news), "negative" gets avoid,
 * "cautious" gets overvalued / amber.
 */
export function sentimentToneClass(
  sentiment: string | null | undefined,
): string {
  const s = (sentiment ?? "").toLowerCase()
  if (s === "positive") return verdictClassesWithDark("undervalued")
  if (s === "negative") return verdictClassesWithDark("avoid")
  if (s === "cautious") return verdictClassesWithDark("overvalued")
  return verdictClassesWithDark("fairly_valued")
}
