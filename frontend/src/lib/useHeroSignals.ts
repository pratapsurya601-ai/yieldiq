/**
 * useHeroSignals(payload) — single source of truth for the resolved
 * hero signals consumed by BOTH <HonestHero> (desktop side rail) AND
 * <MobileScoreStrip> (the 4-tile mobile strip).
 *
 * Spec ref: redesign/spec.md §1 Fold 1 ("Mobile fallback (<=768): the
 * side rail collapses INTO MobileScoreStrip ... reads from the SAME
 * source-of-truth resolver so desktop and mobile cannot drift").
 *
 * This is a pure resolver — memoised via useMemo so it does not re-cost
 * on every render. It does NOT subscribe to React Query, does NOT touch
 * localStorage, does NOT introspect window. Inputs in, signals out.
 *
 * NO backend changes were made for this hook. Where a field is not yet
 * threaded on `AnalysisResponse` today (specifically `compounded_growth`
 * — currently only on `StockSummary` per `lib/api.ts`), we read through
 * a defensive cast and return `null`. The half-armed state is documented
 * inline so a future agent threading the field on AnalysisResponse
 * (Agent B's contract change — NOT this PR's scope) lights up the
 * signal without touching this file.
 */

import { useMemo } from "react"

import type { AnalysisResponse, MoatGrade, Verdict } from "@/types/api"
import { isDegradedScenario, isFairValueClamped } from "@/lib/scenarios"
import { shouldGateVerdict } from "@/lib/utils"

/**
 * The flat bag of resolved signals the hero surfaces (desktop side rail
 * AND mobile strip) read from. Fields are nullable when the underlying
 * payload field is missing or non-finite — every consumer is expected
 * to render `—` for null rather than fabricate a value.
 *
 * NOT exported as a wire format; this is purely UI plumbing.
 */
export interface HeroSignals {
  /** Raw backend verdict enum — for callers that want to drive their own labels. */
  verdict: Verdict | null
  /** True when the verdict pill must collapse to "Under Review" (sub-50% conf, wide band, etc.). */
  verdictGated: boolean
  /**
   * DCF-only fair value (mirrors `valuation.fair_value`). Kept for
   * surfaces that LEGITIMATELY need the DCF number specifically —
   * `DcfMultiplesChip` (which compares DCF vs Multiples by definition)
   * and `ValuationMethodsPanel` (which breaks out per-engine values).
   *
   * Every OTHER hero / caveat / FAQ / AI-Why / OG / JSON-LD / peer
   * surface MUST read `headlineFairValue` below — that is the single
   * canonical number every user-visible FV pill agrees on. The
   * ESLint rule in `frontend/.eslintrc.cjs` enforces this invariant.
   */
  fairValue: number | null
  /**
   * Canonical headline Fair Value — composite IV when present + > 0,
   * else the DCF `fairValue` above, else null. SINGLE source of truth
   * for the hero pill, caveat line, side-rail summary, AI Why
   * paragraph, FAQ Q1/Q2, peer comparison table, Prism Price ladder,
   * History tab legend, and every SEO surface (OG card, JSON-LD,
   * Twitter card).
   *
   * Background (ROOT CAUSE #1, 2026-06-10): a prod audit of the
   * HDFCBANK analysis page found 8+ surfaces reading from 3
   * different fields and producing 3 different visible numbers:
   *   - Hero pill          → composite_intrinsic_value (₹1,147.77)
   *   - Caveat line below  → signals.fairValue / DCF      (₹1,142)
   *   - Side-rail summary  → signals.fairValue / DCF      (₹1,141.82)
   *   - Price ladder       → valuation.fair_value         (₹1,141.82)
   *   - AI Why paragraph   → valuation.fair_value         (₹1,142)
   *   - Quality FAQ Q1/Q2  → valuation.fair_value         (₹1,141.82)
   *   - Peer table         → peer-endpoint fair_value     (₹1,129)
   *   - History legend     → inconsistent label
   *
   * The architectural fix is this field. Every consumer reads
   * `signals.headlineFairValue`; only DcfMultiplesChip /
   * ValuationMethodsPanel may keep reading `signals.fairValue`.
   */
  headlineFairValue: number | null
  /**
   * Source of the headline FV — "composite" when composite_intrinsic_value
   * drove the number, "dcf" when fallback to valuation.fair_value, null
   * when neither was usable (data-limited path).
   */
  headlineFairValueMethod: "composite" | "dcf" | null
  /** Whether the headline FV is sitting at the +/-200% display clamp. */
  fairValueClamped: boolean
  /** Signed discount-to-FV percent (MoS), clamped to the backend's display range. Null when unreliable. */
  discount: number | null
  /** Worry-Index tier label (sleep_well / normal / watch_closely / read_bears / significant_concerns). */
  worry: WorryTier | null
  /** Composite 0-100 score (yieldiq_score). */
  score: number | null
  /** A-F grade letter. */
  grade: string | null
  /** Moat label as emitted by the backend (preserves "N/A (Financial)" for banks). */
  moat: MoatGrade | null
  /** Count of structured red flags. */
  redFlags: number | null
  /** 0-1 Refraction Index (kept null until backend re-calibrates — see ScoreCard comment). */
  refraction: number | null
  /** Market cap in crores. */
  marketCapCr: number | null
  /** Monthly score series, oldest first. Empty when not yet backfilled. */
  trend12m: number[]
  /** Model confidence 0-100. Null when unreliable. */
  confidence: number | null
  /** True when the WIPRO-class degraded-scenario state has fired (spec §2.1). */
  degraded: boolean
  /** True when the page is in the data-limited / under-review branch. */
  dataLimited: boolean
}

export type WorryTier =
  | "sleep_well"
  | "normal"
  | "watch_closely"
  | "read_bears"
  | "significant_concerns"

/**
 * Resolve the bag once. Same payload → same bag (referentially equal
 * within a render thanks to useMemo). Pass null when the upstream
 * AnalysisResponse query is still loading; consumers get an "all-null"
 * signal bag they can render skeletons against.
 */
export function useHeroSignals(
  payload: AnalysisResponse | null | undefined,
): HeroSignals {
  return useMemo(() => resolveHeroSignals(payload), [payload])
}

/**
 * Pure resolver — exported separately so unit tests can drive it without
 * a React renderer. `useHeroSignals` is a thin useMemo wrapper.
 */
export function resolveHeroSignals(
  payload: AnalysisResponse | null | undefined,
): HeroSignals {
  if (!payload) {
    return EMPTY
  }
  const v = payload.valuation
  const q = payload.quality
  const i = payload.insights
  const w = payload.worry_index ?? null

  const verdictLower = (v.verdict || "").toString().toLowerCase()
  const dataLimited =
    verdictLower === "data_limited" ||
    verdictLower === "under_review" ||
    verdictLower === "under review" ||
    verdictLower === "unavailable" ||
    (q.yieldiq_score ?? 0) <= 0 ||
    v.fair_value === 0

  const verdictGated = shouldGateVerdict({
    dataLimited,
    confidence: v.confidence_score,
    currentPrice: v.current_price,
    bullCase: v.bull_case,
    bearCase: v.bear_case,
    marginOfSafety: v.margin_of_safety,
  })

  const fairValueClamped = isFairValueClamped(payload)

  const fairValue =
    !dataLimited && v.fair_value > 0 && Number.isFinite(v.fair_value)
      ? v.fair_value
      : null

  // Canonical headline FV resolver (ROOT CAUSE #1, 2026-06-10).
  //
  // Prefer the backend-stamped `headline_fair_value` field when
  // present (populated by routers/analysis.py
  // `_inject_headline_fair_value_*` on every response). Fall back to
  // the same composite-IV-or-DCF chain client-side so legacy cached
  // payloads — which predate the backend field — still surface a
  // coherent number on every consumer (hero, FAQ, AI Why, peer
  // table, OG/JSON-LD). Returns null only when neither composite IV
  // nor the DCF FV is usable, mirroring the `fairValue` null branch
  // above.
  const headlinePayload = payload as unknown as {
    headline_fair_value?: number | null
    headline_fair_value_method?: "composite" | "dcf" | null
    composite_intrinsic_value?: number | null
  }
  const backendHeadline = headlinePayload.headline_fair_value
  const compositeIv = headlinePayload.composite_intrinsic_value
  let headlineFairValue: number | null
  let headlineFairValueMethod: "composite" | "dcf" | null
  if (
    typeof backendHeadline === "number" &&
    Number.isFinite(backendHeadline) &&
    backendHeadline > 0 &&
    !dataLimited
  ) {
    headlineFairValue = backendHeadline
    headlineFairValueMethod =
      headlinePayload.headline_fair_value_method === "composite" ||
      headlinePayload.headline_fair_value_method === "dcf"
        ? headlinePayload.headline_fair_value_method
        : // When the backend stamped a value but no method (legacy
          // half-armed payload), infer from whether the composite slot
          // matches the headline within the 2dp rounding the backend
          // applies before serialising.
          typeof compositeIv === "number" &&
            Number.isFinite(compositeIv) &&
            compositeIv > 0 &&
            Math.abs(compositeIv - backendHeadline) < 0.5
          ? "composite"
          : "dcf"
  } else if (
    typeof compositeIv === "number" &&
    Number.isFinite(compositeIv) &&
    compositeIv > 0 &&
    !dataLimited
  ) {
    headlineFairValue = compositeIv
    headlineFairValueMethod = "composite"
  } else if (fairValue != null) {
    headlineFairValue = fairValue
    headlineFairValueMethod = "dcf"
  } else {
    headlineFairValue = null
    headlineFairValueMethod = null
  }

  const discount =
    !dataLimited && Number.isFinite(v.margin_of_safety)
      ? v.margin_of_safety
      : null

  // Refraction lives on the Prism payload (not AnalysisResponse). Until
  // we thread a "compactRefraction" off Prism into this hook, leave it
  // null and let the side rail read from prismResolved directly when it
  // needs to. We surface the key on the bag so the rail does not need
  // a parallel resolver.
  const refraction: number | null = null

  // 12M trend lives on the Prism payload too; same plumbing posture.
  const trend12m: number[] = []

  const marketCapCr =
    payload.company.market_cap && payload.company.market_cap > 0
      ? payload.company.market_cap / 1e7
      : null

  return {
    verdict: v.verdict ?? null,
    verdictGated,
    fairValue,
    headlineFairValue,
    headlineFairValueMethod,
    fairValueClamped,
    discount,
    worry: (w?.tier as WorryTier | undefined) ?? null,
    score: Number.isFinite(q.yieldiq_score) ? q.yieldiq_score : null,
    grade: q.grade ?? null,
    moat: (q.moat ?? null) as MoatGrade | null,
    redFlags: i?.red_flags_structured?.length ?? null,
    refraction,
    marketCapCr,
    trend12m,
    confidence: Number.isFinite(v.confidence_score) ? v.confidence_score : null,
    degraded: isDegradedScenario(payload),
    dataLimited,
  }
}

const EMPTY: HeroSignals = {
  verdict: null,
  verdictGated: false,
  fairValue: null,
  headlineFairValue: null,
  headlineFairValueMethod: null,
  fairValueClamped: false,
  discount: null,
  worry: null,
  score: null,
  grade: null,
  moat: null,
  redFlags: null,
  refraction: null,
  marketCapCr: null,
  trend12m: [],
  confidence: null,
  degraded: false,
  dataLimited: false,
}
