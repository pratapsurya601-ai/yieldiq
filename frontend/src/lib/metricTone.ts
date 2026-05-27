/**
 * metricTone.ts — canonical traffic-light tone helper for metric VALUES.
 *
 * Tickertape deep walk (.audit/tickertape-deep-walk-2026-05-27.md) trick #4:
 * Tickertape colors ~700 elements on the page; YieldIQ colored ~12. The eye
 * picks up "good/bad" instantly without reading prose.
 *
 * This helper returns a 4-tier MetricTone for a given metric+value (and
 * optional sector-median benchmark when the metric is relative). Callers
 * map the tone to a Tailwind text-color class via `metricToneTextClass`.
 *
 * SEBI lens (CRITICAL):
 *   The tone describes the NUMBER'S QUALITY vs benchmark or historical
 *   norm. It does NOT carry investment merit. Worked examples:
 *     OK: Payout 104% -> 'bad' (unsustainable cash flow)
 *     OK: ROE 45% -> 'good' (top quartile within most cohorts)
 *     NOT OK: MoS +50% -> 'good' (implies action)
 *     NOT OK: P/E 17x -> 'good' without a sector benchmark
 *
 *   Margin of Safety is intentionally NOT handled here. MoS direction is
 *   already colored in EditorialHero via text-success/text-danger as a
 *   sign-of-discount affordance; routing it through this helper would
 *   risk reading as a directional tier.
 *
 * Tailwind utility classes (already in design tokens):
 *   good    -> text-green-600  / dark:text-green-400
 *   neutral -> text-slate-700  / dark:text-slate-300
 *   warn    -> text-amber-600  / dark:text-amber-400
 *   bad     -> text-red-600    / dark:text-red-400
 *
 * Per-metric scoring rules (calibrated against the Indian large-cap cohort
 * and the existing per-component thresholds in QualityRatios.tsx /
 * InsightCards.tsx so this helper does not contradict the rest of the app):
 *
 *   pe (relative, requires sectorMedian):
 *     <  60% of sector  -> good
 *     <  90% of sector  -> neutral
 *     < 110% of sector  -> warn
 *     >=110% of sector  -> bad
 *     missing sectorMedian -> neutral (we will not call a P/E good or bad
 *     in absolute terms; that's the SEBI-risky path)
 *
 *   pb (relative, requires sectorMedian): same bands as pe.
 *
 *   roe (absolute, percent units, e.g. 45.9 means 45.9%):
 *     >= 20  -> good
 *     >= 12  -> neutral
 *     >=  5  -> warn
 *     else   -> bad
 *
 *   div_yield (absolute, percent units):
 *     >= 4   -> good
 *     >= 2   -> neutral
 *     >  0   -> warn
 *     else   -> bad   (zero or negative -> no live payout)
 *
 *   payout (absolute, percent units, payout ratio):
 *     >= 30 AND <= 70 -> good     (healthy distribution band)
 *     >  0  AND <  30 -> neutral  (lean payout, plenty of retention)
 *     >  70 AND <=100 -> warn     (rich payout, less retained capital)
 *     > 100           -> bad      (paying out more than earnings - unsustainable)
 *     <= 0            -> neutral  (not paying / data missing)
 *
 *   fscore (Piotroski 0-9):
 *     >= 8 -> good
 *     >= 6 -> neutral
 *     >= 4 -> warn
 *     else -> bad
 *
 *   worry (0-100, lower is calmer):
 *     <  30 -> good
 *     <  50 -> neutral
 *     <  70 -> warn
 *     else  -> bad
 *
 *   debt_equity (absolute multiple, e.g. 0.4):
 *     <  0.5 -> good
 *     <  1.0 -> neutral
 *     <  2.0 -> warn
 *     else   -> bad
 *
 *   op_margin (absolute, percent units):
 *     >= 20 -> good
 *     >= 12 -> neutral
 *     >=  5 -> warn
 *     else  -> bad
 *
 * Callers must treat the returned tone as presentation styling only and
 * MUST still render the underlying number / unit; never collapse the tone
 * into the only signal (a colorblind user must still get the same info).
 */

export type MetricTone = "good" | "neutral" | "warn" | "bad"

export type MetricKind =
  | "pe"
  | "pb"
  | "roe"
  | "div_yield"
  | "payout"
  | "fscore"
  | "worry"
  | "debt_equity"
  | "op_margin"

export interface MetricToneArgs {
  metric: MetricKind
  value: number | null | undefined
  /** Sector median for relative metrics (pe, pb). Required for those metrics
   *  to return anything other than 'neutral'. */
  sectorMedian?: number | null
}

/** Tailwind text-color classes (light + dark) for each tone. Kept as
 *  literal strings so the Tailwind JIT compiler can statically extract
 *  them. Do NOT build these by string concatenation. */
const TONE_TEXT_CLASS: Record<MetricTone, string> = {
  good: "text-green-600 dark:text-green-400",
  neutral: "text-slate-700 dark:text-slate-300",
  warn: "text-amber-600 dark:text-amber-400",
  bad: "text-red-600 dark:text-red-400",
}

/** Returns the Tailwind text-color class string for a MetricTone. */
export function metricToneTextClass(tone: MetricTone): string {
  return TONE_TEXT_CLASS[tone]
}

function isFinite(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v)
}

function relativeTone(
  value: number,
  sectorMedian: number | null | undefined,
  /** When true, LOWER is better (e.g. P/E, P/B). */
  lowerIsBetter: boolean,
): MetricTone {
  if (!isFinite(sectorMedian) || sectorMedian <= 0) return "neutral"
  const ratio = value / sectorMedian
  if (lowerIsBetter) {
    if (ratio < 0.6) return "good"
    if (ratio < 0.9) return "neutral"
    if (ratio < 1.1) return "warn"
    return "bad"
  }
  // higherIsBetter (currently unused but kept for symmetry)
  if (ratio > 1.5) return "good"
  if (ratio > 1.1) return "neutral"
  if (ratio > 0.9) return "warn"
  return "bad"
}

export function metricTone(args: MetricToneArgs): MetricTone {
  const { metric, value, sectorMedian } = args
  if (!isFinite(value)) return "neutral"

  switch (metric) {
    case "pe":
    case "pb": {
      // P/E and P/B are only meaningful against a cohort benchmark. Without
      // one we will not call them good or bad — the SEBI-risky path is to
      // imply a directional verdict on a raw absolute multiple.
      if (value <= 0) return "neutral"
      return relativeTone(value, sectorMedian, true)
    }

    case "roe": {
      if (value >= 20) return "good"
      if (value >= 12) return "neutral"
      if (value >= 5) return "warn"
      return "bad"
    }

    case "div_yield": {
      if (value >= 4) return "good"
      if (value >= 2) return "neutral"
      if (value > 0) return "warn"
      return "bad"
    }

    case "payout": {
      if (value <= 0) return "neutral"
      if (value > 100) return "bad"
      if (value > 70) return "warn"
      if (value >= 30) return "good"
      return "neutral"
    }

    case "fscore": {
      if (value >= 8) return "good"
      if (value >= 6) return "neutral"
      if (value >= 4) return "warn"
      return "bad"
    }

    case "worry": {
      if (value < 30) return "good"
      if (value < 50) return "neutral"
      if (value < 70) return "warn"
      return "bad"
    }

    case "debt_equity": {
      if (value < 0.5) return "good"
      if (value < 1.0) return "neutral"
      if (value < 2.0) return "warn"
      return "bad"
    }

    case "op_margin": {
      if (value >= 20) return "good"
      if (value >= 12) return "neutral"
      if (value >= 5) return "warn"
      return "bad"
    }

    default: {
      // Exhaustiveness guard. New MetricKind entries must add a case above.
      const _exhaustive: never = metric
      void _exhaustive
      return "neutral"
    }
  }
}

/** Convenience: compute tone + return its Tailwind class in one call. */
export function metricToneClass(args: MetricToneArgs): string {
  return metricToneTextClass(metricTone(args))
}
