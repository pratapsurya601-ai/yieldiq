"use client"

/**
 * AnalysisBodyV2 — flag-gated SHADOW body for /analysis/[ticker].
 *
 * This is the v3-redesign analysis page being ported onto live data,
 * ONE build at a time. It is mounted ONLY for users holding the
 * `analysis_v2` feature flag (default OFF for everyone) — see the gate
 * in AnalysisAuthGate.tsx. The legacy <AnalysisBody/> is the live page
 * for every other user and is never edited by this work.
 *
 * Phase 0 (scaffold) + Phase 1 (the SPINE) are implemented here:
 *   - same useQuery(["analysis", ticker], getAnalysis) the live body uses
 *   - useHeroSignals(data) — the canonical FV/MoS/score/verdict resolver
 *   - ChromeHeaderV2 + JumpNavV2 + DecisionBoxV2 (with the Spectrum)
 *     ported from the locked demo, fed REAL props
 *   - every not-yet-built section is a titled placeholder so the scroll
 *     + JumpNav work end-to-end without any fake data
 *
 * The verdict layer (verdict pill + MoS hero + FV number + Spectrum
 * region text) is gated by the `verdict_layer_on` flag and falls back to
 * the codebase's SEBI-neutral Under-Review state when OFF. Story /
 * quality / financials / tools stay always-on (stubbed here).
 *
 * Query fan-out: only the base getAnalysis query fires on mount. The
 * deferred peers / financials / fv-history queries belong to their
 * sections and are NOT eagerly fired in this build.
 */

import { useQuery } from "@tanstack/react-query"

import { getAnalysis } from "@/lib/api"
import { useHeroSignals } from "@/lib/useHeroSignals"
import { useFeatureFlag } from "@/lib/useFeatureFlag"
import LoadingSteps from "@/components/ui/LoadingSteps"

import { DEMO_COLORS } from "@/app/demo/analysis-redesign/theme"
import { Muted } from "@/app/demo/analysis-redesign/ui"

import ChromeHeaderV2 from "./v2/ChromeHeaderV2"
import DecisionBoxV2 from "./v2/DecisionBoxV2"
import JumpNavV2, { type JumpNavItem } from "./v2/JumpNavV2"
import type { SpectrumAxisReal } from "./v2/SpectrumV2"
import SectionValuationV2 from "./v2/SectionValuationV2"
import SectionForecastV2 from "./v2/SectionForecastV2"
import SectionAnalystsV2 from "./v2/SectionAnalystsV2"

/* ------------------------------------------------------------------ */
/*  Axis derivation — mirrors backend/services/analysis/hex_axes.py    */
/*  (_to_score10 + the synthetic per-axis formulas) so the Spectrum    */
/*  bands match the engine's 0-10 scaling. The analysis payload does   */
/*  not carry the `hex` block, so we derive the six axes from the same */
/*  quality/valuation fields the backend's pure fallback path uses.    */
/* ------------------------------------------------------------------ */

/** Coerce any number to [0,10]; quality scores are 0-100 → divide-by-10. */
function toScore10(v: number | null | undefined, fallback = 5): number | null {
  if (v == null || !Number.isFinite(v)) return fallback === null ? null : fallback
  let x = v
  if (x > 10) x = x / 10
  return Math.max(0, Math.min(10, x))
}

/** Value axis from signed MoS percentage: 5 + mos/12.5, clamped. */
function valueAxis(mos: number | null): number | null {
  if (mos == null || !Number.isFinite(mos)) return null
  return Math.max(0, Math.min(10, 5 + mos / 12.5))
}

/** Growth axis from revenue_cagr_3y (DECIMAL, 0.15 = 15%). */
function growthAxis(cagr: number | null | undefined): number | null {
  if (cagr == null || !Number.isFinite(cagr)) return null
  if (cagr < 0) return Math.max(0, 3 + cagr * 30)
  return Math.min(10, 3 + cagr * 20)
}

/**
 * Safety axis from structured red flags (+ a CAR bonus for banks).
 * No red-flag data → neutral 5. More flags → lower. Healthy CAR (>=15%)
 * nudges up; thin CAR (<12%) nudges down. Real fields only.
 */
function safetyAxis(redFlags: number | null, car: number | null | undefined): number | null {
  let s: number
  if (redFlags == null) {
    s = 5
  } else if (redFlags === 0) {
    s = 8
  } else if (redFlags <= 1) {
    s = 6.5
  } else if (redFlags <= 3) {
    s = 5
  } else {
    s = 3
  }
  if (car != null && Number.isFinite(car)) {
    if (car >= 15) s = Math.min(10, s + 1)
    else if (car < 12) s = Math.max(0, s - 1.5)
  }
  return s
}

interface BuiltAxis extends SpectrumAxisReal {
  /** True when the axis fell back to the neutral 5.0 (no real input). */
  synthetic?: boolean
}

/** Build the six Spectrum axes from the resolved signals + payload. */
function buildAxes(
  quality: {
    moat_score?: number | null
    momentum_score?: number | null
    revenue_cagr_3y?: number | null
    yieldiq_score?: number | null
    car?: number | null
  },
  discount: number | null,
  redFlags: number | null,
): BuiltAxis[] {
  const pulse = toScore10(quality.momentum_score, 5)
  const qual = toScore10(quality.yieldiq_score, 5)
  const moat = toScore10(quality.moat_score, 5)
  const growth = growthAxis(quality.revenue_cagr_3y) ?? 5
  const value = valueAxis(discount) ?? 5
  const safety = safetyAxis(redFlags, quality.car) ?? 5

  // Order mirrors the locked demo (Pulse, Quality, Moat, Safety, Growth,
  // Value) so the VALUE band lands last and the auto-select highlights it.
  return [
    { k: "PULSE", s: pulse ?? 5, c: DEMO_COLORS.blue, d: DEMO_COLORS.blueDark },
    { k: "QUALITY", s: qual ?? 5, c: DEMO_COLORS.teal, d: DEMO_COLORS.tealDark },
    { k: "MOAT", s: moat ?? 5, c: DEMO_COLORS.tealLight, d: DEMO_COLORS.tealDeep },
    { k: "SAFETY", s: safety, c: DEMO_COLORS.blueLight, d: DEMO_COLORS.blueDeep },
    { k: "GROWTH", s: growth, c: DEMO_COLORS.amber, d: DEMO_COLORS.amberDark },
    { k: "VALUE", s: value, c: DEMO_COLORS.coral, d: DEMO_COLORS.coralDeep },
  ]
}

/* ------------------------------------------------------------------ */
/*  Stub section — a titled placeholder for a not-yet-built section.   */
/*  Keeps the single-scroll narrative + JumpNav working end-to-end     */
/*  without rendering any fabricated data.                             */
/* ------------------------------------------------------------------ */
function StubSection({ id, num, title }: { id: string; num: string; title: string }) {
  return (
    <section
      id={id}
      className="mb-3.5 scroll-mt-24 rounded-2xl border border-dashed border-border bg-surface px-4 py-6 md:px-5"
    >
      <div className="mb-2 flex items-center gap-2.5">
        <span className="flex h-[26px] min-w-[26px] items-center justify-center rounded-full bg-tone-info-bg px-2 text-[12px] text-tone-info-fg">
          {num}
        </span>
        <span className="text-[16px] font-medium text-ink">{title}</span>
      </div>
      <Muted>This section is coming in the next build.</Muted>
    </section>
  )
}

/**
 * Stub sections still awaiting their own build, split around the real v2
 * sections that DO exist. Valuation / Forecast / Analysts are now live
 * components (this build); the rest remain titled placeholders so the
 * single-scroll narrative + JumpNav keep working end-to-end.
 */
const STUBS_BEFORE_VALUATION: { id: string; num: string; title: string }[] = [
  { id: "sec-thesis", num: "02", title: "Thesis" },
  { id: "sec-business", num: "03", title: "Business" },
  { id: "sec-financials", num: "04", title: "Financials" },
]
const STUBS_AFTER_VALUATION: { id: string; num: string; title: string }[] = [
  { id: "sec-risk", num: "07", title: "Risk" },
  { id: "sec-ownership", num: "08", title: "Ownership" },
  { id: "sec-peers", num: "09", title: "Peers" },
]
const STUBS_AFTER_ANALYSTS: { id: string; num: string; title: string }[] = [
  { id: "sec-news", num: "11", title: "News" },
]

export default function AnalysisBodyV2({ ticker }: { ticker: string }) {
  const verdictLayerOn = useFeatureFlag("verdict_layer_on")

  // Same base query the live body uses — identical key + fn so the
  // React-Query cache is shared with any concurrent live-body mount.
  const { data, isLoading, error } = useQuery({
    queryKey: ["analysis", ticker],
    queryFn: () => getAnalysis(ticker),
    enabled: !!ticker,
    staleTime: 60_000,
    retry: (failureCount, err) => {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404 || status === 429) return false
      return failureCount < 1
    },
  })

  // Canonical resolver — runs above every early return so hook order is
  // stable across loading / error / success.
  const signals = useHeroSignals(data ?? null)

  if (isLoading) return <LoadingSteps />
  if (error || !data) {
    const display = ticker.replace(".NS", "").replace(".BO", "")
    return (
      <div className="mx-auto max-w-md px-4 py-16 text-center pb-20" role="alert" aria-live="polite">
        <p className="mb-2 text-lg font-semibold text-ink">Could not load {display}</p>
        <p className="mb-4 max-w-sm text-sm text-body">
          Data provider may be temporarily unavailable. Try again in a moment.
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 active:scale-[0.98]"
        >
          Try again
        </button>
      </div>
    )
  }

  const overall = signals.score != null ? Math.max(0, Math.min(10, signals.score / 10)) : null
  const axes = buildAxes(
    {
      moat_score: data.quality.moat_score,
      momentum_score: data.quality.momentum_score,
      revenue_cagr_3y: data.quality.revenue_cagr_3y,
      yieldiq_score: data.quality.yieldiq_score,
      car: data.quality.car,
    },
    signals.discount,
    signals.redFlags,
  )

  // JumpNav anchors — the spine "Answer" (Decision Box), then sections in
  // scroll order: the stubs + the three real v2 sections built here.
  const jumpItems: JumpNavItem[] = [
    { id: "sec-answer", label: "Answer" },
    ...STUBS_BEFORE_VALUATION.map((s) => ({ id: s.id, label: s.title })),
    { id: "sec-valuation", label: "Valuation" },
    { id: "sec-forecast", label: "Forecast" },
    ...STUBS_AFTER_VALUATION.map((s) => ({ id: s.id, label: s.title })),
    { id: "sec-analysts", label: "Analysts" },
    ...STUBS_AFTER_ANALYSTS.map((s) => ({ id: s.id, label: s.title })),
  ]

  return (
    <div className="mx-auto max-w-[1060px] px-3 pb-16 pt-3 md:px-5">
      <V2Styles />

      {/* Phase-0 build banner — honest about what is real vs stubbed. */}
      <div className="mb-3 mt-1 rounded-xl border border-tone-info-bd bg-tone-info-bg px-3.5 py-2 text-[12.5px] text-tone-info-fg">
        New analysis layout (preview) — the answer spine plus valuation,
        forecast and analyst coverage are live on real data; the remaining
        sections arrive in upcoming builds.
      </div>

      <ChromeHeaderV2 data={data} />
      <JumpNavV2 items={jumpItems} />
      <DecisionBoxV2
        data={data}
        signals={signals}
        axes={axes}
        overall={overall}
        verdictLayerOn={verdictLayerOn}
      />

      {STUBS_BEFORE_VALUATION.map((s) => (
        <StubSection key={s.id} id={s.id} num={s.num} title={s.title} />
      ))}

      <SectionValuationV2 data={data} signals={signals} verdictLayerOn={verdictLayerOn} />
      <SectionForecastV2 data={data} signals={signals} verdictLayerOn={verdictLayerOn} />

      {STUBS_AFTER_VALUATION.map((s) => (
        <StubSection key={s.id} id={s.id} num={s.num} title={s.title} />
      ))}

      <SectionAnalystsV2 data={data} signals={signals} verdictLayerOn={verdictLayerOn} />

      {STUBS_AFTER_ANALYSTS.map((s) => (
        <StubSection key={s.id} id={s.id} num={s.num} title={s.title} />
      ))}
    </div>
  )
}

/**
 * v2-scoped keyframes (live-pulse dot). Scoped class names so they do
 * not collide with the demo's `demo-*` classes. The global
 * prefers-reduced-motion kill-switch in globals.css applies; the media
 * block here doubles up for safety per the demo's pattern.
 */
function V2Styles() {
  return (
    <style>{`
@keyframes v2-live-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }
.v2-live-pulse { animation: v2-live-pulse 1.9s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .v2-live-pulse { animation: none !important; }
}
`}</style>
  )
}
