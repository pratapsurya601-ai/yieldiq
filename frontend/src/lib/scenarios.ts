/**
 * scenarios.ts — TS port of the predicates spec'd in
 * `redesign/spec.md` §2.1 (degraded-scenario trigger) and §4.2
 * (healthy-spread + suspect-growth-inputs predicates).
 *
 * Single source of truth for two layout decisions on the analysis page:
 *   • Whether to render <DegradedScenarioCard> in place of FVProjectionFan
 *     (the WIPRO "+200% / +200% / +200%" clamp class — spec §2).
 *   • Whether to promote `scenarios` to numbered slot 1 (healthy spread)
 *     vs demote it to slot 4 (degenerate, spec §4.2 — cluster B reads).
 *
 * The previous redesign attempt let the `fair_value_clamped` flag + the
 * bear/base/bull spread carry the entire signal. WIPRO showed that those
 * same numbers can be COMPUTED FROM a suspect input (the -77.1% revenue
 * CAGR case — `_SANITY_ABS_CAP=100` admits it, no clamp fires, the
 * resulting spread can look healthy while being entirely artificial).
 * `has_suspect_growth_inputs` is the sign/magnitude-based sanity signal
 * the hero copy uses, applied here so scenario placement and hero copy
 * degrade in lockstep.
 *
 * NO backend changes were made for this file. The constants below
 * (`_NEAR_CAP_THRESHOLD = 75.0`, `_HEALTHY_SPREAD_MIN_PP = 15.0`) are
 * named exports so a future calibration task (spec §11.7) can be a
 * one-line change once the live distribution is observable.
 *
 * SEBI lens: no user-facing strings live here. All copy resolution
 * happens in HonestHero / DegradedScenarioCard / MobileScoreStrip.
 */

import type { AnalysisResponse, ScenariosOutput } from "@/types/api"

/**
 * Any growth percent whose magnitude is at or above this is treated as
 * brushing the backend `_SANITY_ABS_CAP=100` ceiling. Spec §4.2:
 *
 *   "A value at/near the cap is almost always a unit-bug / base-near-zero
 *    artifact, not a real move. Treat near-cap as IMPLICITLY clamped even
 *    when the backend has not set fair_value_clamped."
 *
 * Exported (rather than `const` only) so the calibration follow-up
 * (spec §11.7, post-launch) can be a one-line edit traceable in git
 * history. DO NOT inline the number elsewhere.
 */
export const _NEAR_CAP_THRESHOLD = 75.0

/**
 * Minimum bull-bear discount spread (percentage points) for a scenario
 * trio to count as "healthy" per spec §4.2. Below this threshold the
 * three tiles tell the same story dressed in three numbers — the
 * spec's "model overconfidence" failure mode.
 *
 * Operator-chosen floor (15pp) — calibration task in spec §11.7 will
 * revisit against the live ~250-name universe distribution.
 */
export const _HEALTHY_SPREAD_MIN_PP = 15.0

/**
 * Spec §2.1 trigger. Render <DegradedScenarioCard> in place of the
 * normal three-tile scenario row when ALL of the following are true:
 *
 *   clamped == true
 *   && bear_disc == base_disc == bull_disc   (arithmetic equality)
 *   && abs(bear_disc) >= 199.0               (at/above the ±200% display ceiling)
 *
 * Partial degradation (any two collapsing but not the third) falls back
 * to the legacy FVProjectionFan with an inline AnalyticalNotes caution
 * chip — that is cluster D's call, NOT ours; this predicate returns
 * `false` in that case so the legacy path renders.
 *
 * Source-of-clamp note: the backend's `valuation.fair_value_clamped` is
 * NOT exposed on the `ValuationOutput` type. The canonical signal today
 * is `data_issues.some(s => s.includes("Fair value clamped"))` (see
 * AnalysisBody.tsx fvClamped derivation). We accept that string-search
 * because (a) it is the same source-of-truth EditorialHero + the headline
 * MoS clamp use, and (b) it is the only signal exposed today. If the
 * backend later adds a typed flag (`valuation.fair_value_clamped:
 * boolean`), update the cast site — not the predicate logic.
 */
export function isDegradedScenario(payload: AnalysisResponse | null | undefined): boolean {
  if (!payload) return false
  const s: ScenariosOutput | null | undefined = payload.scenarios
  if (!s || !s.bear || !s.base || !s.bull) return false

  const clamped = isFairValueClamped(payload)
  if (!clamped) return false

  const bear = s.bear.mos_pct
  const base = s.base.mos_pct
  const bull = s.bull.mos_pct
  if (
    !Number.isFinite(bear) ||
    !Number.isFinite(base) ||
    !Number.isFinite(bull)
  ) {
    return false
  }

  // Arithmetic equality of three finite numbers, per spec. Float equality
  // is intentional — the backend emits identical clamped values bit-for-bit
  // when this state fires; introducing an epsilon would silently broaden
  // the predicate against the spec.
  if (bear !== base || base !== bull) return false

  if (Math.abs(bear) < 199.0) return false

  return true
}

/**
 * Spec §4.2 — implicit-clamp detector. A growth input is suspect when
 * at/near the backend sanity cap (spec: |pct| ≥ _NEAR_CAP_THRESHOLD).
 *
 * `compounded_growth` is NOT a field on `AnalysisResponse` today — it
 * lives on the separate `StockSummary` payload (lib/api.ts). Threading
 * it onto AnalysisResponse is Agent B's contract change, NOT ours.
 *
 * We read through a defensive cast so the redesign is half-armed: the
 * predicate degrades gracefully (returns false → "not suspect") when
 * compounded_growth is absent from the payload, which is the current
 * production state for AnalysisResponse. Once Agent B threads the
 * field, the predicate auto-arms — no edit needed here.
 */
export function has_suspect_growth_inputs(
  payload: AnalysisResponse | null | undefined,
): boolean {
  if (!payload) return false
  // Defensive cast — see jsdoc above. compounded_growth is NOT on
  // AnalysisResponse yet. Half-armed by design.
  const cg = (payload as unknown as {
    compounded_growth?: {
      revenue?: Record<string, number | null | undefined> | null
      eps?: Record<string, number | null | undefined> | null
      fcf?: Record<string, number | null | undefined> | null
    } | null
  }).compounded_growth
  if (!cg) return false
  for (const metric of ["revenue", "eps", "fcf"] as const) {
    const m = cg[metric]
    if (!m) continue
    for (const horizon of ["3y", "5y", "10y"] as const) {
      const pct = m[horizon]
      if (pct == null || !Number.isFinite(pct)) continue
      if (Math.abs(pct) >= _NEAR_CAP_THRESHOLD) return true
    }
  }
  return false
}

/**
 * Spec §4.2 — healthy-spread predicate. A scenario trio is healthy when:
 *   • all three discounts are finite, AND
 *   • backend has NOT set fair_value_clamped, AND
 *   • no suspect growth input (implicit clamp), AND
 *   • bear < base < bull, AND
 *   • (bull - bear) >= _HEALTHY_SPREAD_MIN_PP
 *
 * Used by cluster B (personalization §4.2) to splice `scenarios` from
 * slot 4 to slot 1 when healthy. Not consumed by HonestHero or the
 * degraded card directly — those use `isDegradedScenario` which is the
 * stricter (clamp + flat + at-ceiling) condition.
 */
export function isHealthyScenarioSpread(
  payload: AnalysisResponse | null | undefined,
): boolean {
  if (!payload) return false
  const s = payload.scenarios
  if (!s || !s.bear || !s.base || !s.bull) return false
  const bear = s.bear.mos_pct
  const base = s.base.mos_pct
  const bull = s.bull.mos_pct
  if (
    !Number.isFinite(bear) ||
    !Number.isFinite(base) ||
    !Number.isFinite(bull)
  ) {
    return false
  }
  if (isFairValueClamped(payload)) return false
  if (has_suspect_growth_inputs(payload)) return false
  if (!(bear < base && base < bull)) return false
  if (bull - bear < _HEALTHY_SPREAD_MIN_PP) return false
  return true
}

/**
 * Internal helper. The backend's clamp signal is not exposed as a typed
 * boolean on ValuationOutput today — `AnalysisBody.tsx` reads it from
 * `data_issues.includes("Fair value clamped")`. We mirror that read here
 * so the predicates use the same single source of truth as the headline
 * MoS clamp. Exported for tests so we can drive the predicates from
 * either side (typed cast or string-marker) once the backend types this.
 */
export function isFairValueClamped(
  payload: AnalysisResponse | null | undefined,
): boolean {
  if (!payload) return false
  // Future-proof: read a typed flag first when present.
  const typed = (payload.valuation as unknown as { fair_value_clamped?: boolean | null })
    ?.fair_value_clamped
  if (typed === true) return true
  const issues = payload.data_issues ?? []
  return issues.some(
    (s) => typeof s === "string" && s.includes("Fair value clamped"),
  )
}
