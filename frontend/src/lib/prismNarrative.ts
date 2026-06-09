// frontend/src/lib/prismNarrative.ts
// ═══════════════════════════════════════════════════════════════════
// P0 #3 (competitor design spec, SWS-inspired) — one-sentence narrative
// caption rendered beneath the Prism on every analysis page. Tells the
// user what to think about the shape they're seeing.
//
// SEBI-safe by construction: copy is purely factual and describes the
// numeric pillar configuration. The banned-vocabulary list lives in
// backend/services/analysis/sebi_filter.py — no token from that list
// is emitted by any output string produced by this module. Frames are
// limited to numeric descriptions ("Quality and value pillars both
// score above 7", "Safety pillar is at or below 3"), which stays
// inside SEBI IA's factual-description carve-out.
//
// Pure function — no React, no fetch, deterministic, trivially testable.
// ═══════════════════════════════════════════════════════════════════

export interface PrismAxes {
  pulse: number
  quality: number
  moat: number
  safety: number
  growth: number
  value: number
}

// Display label for each axis key. Kept inside this module so the
// narrative copy stays self-contained — Prism callers already deal
// with their own labels at render time.
const PILLAR_DISPLAY: Record<keyof PrismAxes, string> = {
  pulse:   "Pulse",
  quality: "Quality",
  moat:    "Moat",
  safety:  "Safety",
  growth:  "Growth",
  value:   "Value",
}

// Bug 8 (P2, 2026-06-09): the original fall-through "A balanced
// profile across the six pillars." copy fired indiscriminately when
// none of the explicit threshold rules above matched — even when the
// underlying pillars ran from 2 to 8 (clearly not balanced).
//
// We re-derive the fall-through with three sub-cases keyed off the
// max-min RANGE across the six axes:
//
//   range < 1.5   "Tightly balanced — every pillar within 1.5 of the others."
//   range < 3.0   "Mostly balanced — {top} leads at X.X, {bottom} trails at Y.Y."
//   range >= 3.0  "{top} leads (X.X) while {bottom} lags (Y.Y) — uneven across pillars."
//
// SEBI-safe: "leads", "trails", "lags", "uneven", "balanced" are
// purely descriptive — none on the banned-vocab list. The threshold
// at 1.5 is the same units the YieldIQ Prism pillar scoring uses
// (0..10 scale, one decimal place), so "within 1.5" is meaningful.
function fallbackBalancedNarrative(axes: PrismAxes): string {
  // Six axes the Prism actually draws — Pulse is intentionally
  // excluded from the explicit rules above ("pace, not shape") but
  // it IS one of the six pillars the original copy referenced, so
  // include it in the variance check.
  const entries = (Object.keys(axes) as (keyof PrismAxes)[]).map((k) => ({
    key: k,
    score: axes[k],
  }))
  let topIdx = 0
  let botIdx = 0
  for (let i = 1; i < entries.length; i++) {
    if (entries[i].score > entries[topIdx].score) topIdx = i
    if (entries[i].score < entries[botIdx].score) botIdx = i
  }
  const top = entries[topIdx]
  const bot = entries[botIdx]
  const range = top.score - bot.score

  if (range < 1.5) {
    return "Tightly balanced — every pillar within 1.5 of the others."
  }
  const topName = PILLAR_DISPLAY[top.key]
  const botName = PILLAR_DISPLAY[bot.key]
  const topStr = top.score.toFixed(1)
  const botStr = bot.score.toFixed(1)
  if (range < 3.0) {
    return `Mostly balanced — ${topName} leads at ${topStr}, ${botName} trails at ${botStr}.`
  }
  return `${topName} leads (${topStr}) while ${botName} lags (${botStr}) — uneven across pillars.`
}

/**
 * Build the one-sentence narrative caption for a Prism shape. Rules
 * are evaluated in priority order (first match wins) so the most
 * informative framing surfaces even when several thresholds overlap.
 *
 * All scores are 0..10. Nulls are coerced to 5 (neutral) by the caller
 * — this function expects a fully-populated axes object.
 */
export function generatePrismNarrative(axes: PrismAxes): string {
  const { pulse, quality, moat, safety, growth, value } = axes
  void pulse // pulse intentionally unused in the explicit threshold
  // rules below — it's pace, not shape — but it IS factored into the
  // fall-through variance check (Bug 8 fix).

  if (quality >= 7 && value >= 7) {
    return "Quality and value pillars both score above 7."
  }
  if (quality >= 7 && growth >= 7) {
    return "Quality and growth pillars both score above 7."
  }
  if (growth >= 7 && value <= 4) {
    return "Growth scores above 7 while value sits at or below 4."
  }
  if (moat >= 7 && safety >= 7) {
    return "Moat and safety pillars both score above 7."
  }
  if (quality >= 7 && value <= 4) {
    return "Quality scores above 7 while value sits at or below 4."
  }
  if (value >= 7 && quality <= 4) {
    return "Value scores above 7 while quality sits at or below 4."
  }
  if (safety <= 4 && growth >= 6) {
    return "Growth is above 6 while safety sits at or below 4."
  }
  if (safety <= 3) {
    return "Safety pillar is at or below 3 — review the risks below."
  }
  if (growth <= 3 && value >= 6) {
    return "Value is above 6 while growth sits at or below 3."
  }

  // Bug 8 fix: discriminate the fall-through by max-min variance so
  // genuinely uneven pillar configurations stop reading as "balanced".
  return fallbackBalancedNarrative(axes)
}

/**
 * Helper to convert the PrismData.pillars array shape into the
 * axes object this generator consumes. Null scores are mapped to 5
 * (neutral) so a data-limited pillar can't tip the rule cascade.
 */
export function axesFromPillars(
  pillars: ReadonlyArray<{ key: string; score: number | null }>,
): PrismAxes {
  const get = (k: string): number => {
    const p = pillars.find((x) => x.key === k)
    if (!p || p.score == null || !Number.isFinite(p.score)) return 5
    return p.score as number
  }
  return {
    pulse: get("pulse"),
    quality: get("quality"),
    moat: get("moat"),
    safety: get("safety"),
    growth: get("growth"),
    value: get("value"),
  }
}
