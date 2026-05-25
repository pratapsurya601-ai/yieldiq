// frontend/src/lib/prismNarrative.ts
// ═══════════════════════════════════════════════════════════════════
// P0 #3 (competitor design spec, SWS-inspired) — one-sentence narrative
// caption rendered beneath the Prism on every analysis page. Tells the
// user what to think about the shape they're seeing.
//
// SEBI-safe by construction: copy is purely factual and describes the
// numeric pillar configuration. No banned words from
// backend/services/analysis/sebi_filter.py (no "strong", "weak",
// "cheap", "expensive", "buy", "sell", "should", "appears", "concern",
// "strength", "weakness", "attractive", "poor", "outperform", etc).
// Frames are limited to numeric descriptions ("Quality and value
// pillars both score above 7", "Safety pillar is below 4"), which
// stays inside SEBI IA's factual-description carve-out.
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
  void pulse // pulse intentionally unused in copy — pace, not shape

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

  return "A balanced profile across the six pillars."
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
