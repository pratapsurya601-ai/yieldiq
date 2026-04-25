"use client"

/**
 * EditorialHero — Morningstar-grade 3-column hero for /analysis/[ticker].
 *
 *   ┌─────────────────────┬──────────────────────┬─────────────┐
 *   │ Verdict narrative   │   THE PRISM          │  ScoreCard  │
 *   │ (4/12)              │   (5/12)             │  (3/12)     │
 *   └─────────────────────┴──────────────────────┴─────────────┘
 *
 * Receives ALL data as props — no client-side fetches here. Parent page
 * does one server-side fetch of /api/v1/prism/<ticker> so the entire
 * above-the-fold content renders SSR (protects LCP).
 *
 * The Prism component itself (owned by Agent Phi2) is imported lazily
 * with a skeleton fallback so this file keeps building even while that
 * component is in flight.
 */

import dynamic from "next/dynamic"
import { useMemo, useState } from "react"

import Prism from "@/components/prism/Prism"
import PillarExplainer from "@/components/prism/PillarExplainer"
import ScoreCard from "@/components/analysis/ScoreCard"
import MetricTooltip from "@/components/analysis/MetricTooltip"
import { verdictColor } from "@/lib/prism"
import { timeAgo } from "@/lib/dataFreshness"
import type {
  PillarKey,
  PrismData,
  PrismMode,
} from "@/components/prism/types"
import {
  formatCurrency,
  formatPct,
  verdictDisplayLabel,
  verdictRegion,
} from "@/lib/utils"
import type { Verdict } from "@/types/api"

// Lazy-load so visitors who never click "Tell me the story" don't pay
// the narrator's bundle cost.
const PrismNarrator = dynamic(
  () => import("@/components/prism/PrismNarrator"),
  { ssr: false },
)

export interface EditorialHeroProps {
  /** Prism payload — contains verdict, pillars, refraction. */
  data: PrismData
  /** Fair value in company currency. */
  fairValue: number
  /** Current price in company currency. */
  currentPrice: number
  /** Margin of safety (0-100, signed). */
  marginOfSafety: number
  /** Moat tier — "Wide" | "Narrow" | "None". */
  moat: string
  currency: string
  /** Legacy YieldIQ score 0-100. */
  score100: number
  grade: string
  /** Optional sector-rank pair for the ScoreCard bar. */
  sectorRank?: { rank: number; total: number } | null
  /** Monthly score trend, oldest first. */
  trend12m?: number[]
  /** Market cap in crores (INR). */
  marketCapCr?: number | null
  /** True when DCF inputs aren't reliable — shows a Data Limited banner instead of verdict. */
  dataLimited?: boolean
  /**
   * Canonical Verdict — drives the headline and small region caption.
   * Single source of truth across the analysis page (see RELIANCE
   * triple-contradiction bug postmortem). The hero MUST derive its
   * user-facing label from this field; verdictColor(data.verdict_band)
   * is geometric only (ring palette), not a label.
   */
  valuationVerdict: Verdict
  /**
   * Structured red-flag list from the backend insights payload. The
   * "Possible value trap" banner fires when — and ONLY when — this
   * array contains a ``value_trap`` entry. Backend /services/analysis
   * is the single source of truth; the banner used to recompute the
   * trigger from Prism pillars here, which drifted from the W8 rule
   * in ``backend/services/analysis/utils.py`` and produced the
   * ADSL-style "banner says trap, Red Flags list says None" contradiction
   * the external auditor flagged (B2 / P0-#8 follow-up, 2026-04-22).
   */
  redFlags?: Array<{ flag: string; severity?: string }>
}

// NOTE: bandCaption() and titleCase() were removed — both produced
// user-facing labels keyed off prism band/verdict_label, which drifted
// from the canonical valuation.verdict and caused the RELIANCE
// triple-contradiction bug. Headline and region caption now derive from
// the Verdict prop via verdictDisplayLabel/verdictRegion (lib/utils.ts).

/** The three cells share style; small helper keeps JSX flat. */
function Stat({
  label,
  value,
  metricKey,
}: {
  label: string
  value: string
  metricKey?: string
}) {
  const labelEl = (
    <dt className="text-[10px] uppercase tracking-[0.15em] text-caption">
      {label}
    </dt>
  )
  return (
    <div>
      {metricKey ? (
        <MetricTooltip metricKey={metricKey}>{labelEl}</MetricTooltip>
      ) : (
        labelEl
      )}
      <dd className="font-mono tabular-nums text-lg font-semibold text-ink">{value}</dd>
    </div>
  )
}

export default function EditorialHero({
  data,
  fairValue,
  currentPrice,
  marginOfSafety,
  moat,
  currency,
  score100,
  grade,
  sectorRank,
  trend12m,
  marketCapCr,
  dataLimited,
  redFlags,
  valuationVerdict,
}: EditorialHeroProps) {
  const defaultMode: PrismMode = "spectrum"
  const color = verdictColor(data.verdict_band)
  const [highlightedPillar, setHighlightedPillar] =
    useState<PillarKey | null>(null)
  // Tap-to-explain state — opens a PillarExplainer sheet with the
  // axis's factual `why` string. Separate from highlightedPillar
  // (which is narrator-driven glow) so users can tap without the
  // narrator fighting for control.
  const [explainerAxis, setExplainerAxis] = useState<PillarKey | null>(null)

  // Value-trap indicator — fires when the backend insights pipeline has
  // tagged this stock with the ``value_trap`` red flag. We intentionally
  // do NOT recompute the trigger from Prism pillars here: the previous
  // implementation (Value>=8 AND (Quality<5 OR Moat=None)) and the backend
  // W8 rule (mos_pct>30 AND (piotroski<=4 OR moat==None)) drifted apart
  // and produced the contradictory "Possible value trap" banner +
  // "Red Flags: None" state on ADSL. Single source of truth = backend
  // red_flags array; banner renders iff value_trap is present in it.
  // See backend/services/analysis/utils.py::_add_flags W8 rule.
  const valueTrap = useMemo(
    () => (redFlags ?? []).some((f) => f?.flag === "value_trap"),
    [redFlags],
  )

  return (
    <section
      className="bg-bg rounded-2xl border border-border p-5 md:p-6"
      aria-label="Valuation summary"
    >
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8">
        {/* ══════════════════════════════════════════════════════════
            Column 1 — Verdict narrative (mobile: 3rd)
            ══════════════════════════════════════════════════════════ */}
        <div className="lg:col-span-4 order-3 lg:order-1 flex flex-col gap-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-caption">
            YieldIQ Prism · Verdict
          </p>

          <div className="flex items-center gap-2">
            <span
              aria-hidden
              className="inline-block w-2.5 h-2.5 rounded-full"
              style={{ background: color }}
            />
            <MetricTooltip metricKey="verdict">
              <span className="text-[11px] uppercase tracking-[0.15em] text-body">
                {verdictRegion(valuationVerdict)}
              </span>
            </MetricTooltip>
          </div>

          {/* Value-trap indicator — factual warning when Value is maxed
              but Quality or Moat is weak. Classic "undervalued for a
              reason" pattern. Not a sell recommendation; just surfaces
              the tension so the user can factor it into their read. */}
          {valueTrap && (
            <div
              role="note"
              aria-label="Possible value trap"
              className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-[12px] leading-snug text-amber-900"
            >
              <svg className="w-4 h-4 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3m0 3.5h.01M10.29 3.86l-8.4 14.42A2 2 0 003.61 21h16.78a2 2 0 001.72-2.72L13.71 3.86a2 2 0 00-3.42 0z" />
              </svg>
              <span>
                <span className="font-semibold">Possible value trap.</span>{" "}
                Deep discount paired with limited quality or no durable moat —
                stocks below fair value often stay below fair value for a reason.
              </span>
            </div>
          )}

          {/* Serif headline — the verdict as an editorial title. We do NOT
              fabricate longer prose here (SEBI). The verdict label from the
              Prism payload is the canonical display string. */}
          <h2
            className="font-editorial text-3xl leading-tight text-ink font-semibold"
            style={{ fontVariationSettings: "'opsz' 48" }}
          >
            {verdictDisplayLabel(valuationVerdict)}
          </h2>

          {/* 2x2 metrics */}
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 mt-1">
            <Stat
              label="Fair Value"
              value={fairValue > 0 ? formatCurrency(fairValue, currency) : "Not reported"}
              metricKey="fair_value"
            />
            <Stat
              label="Current Price"
              value={currentPrice > 0 ? formatCurrency(currentPrice, currency) : "Awaiting data"}
              metricKey="current_price"
            />
            {!dataLimited && (
              <div>
                <MetricTooltip metricKey="mos">
                  <dt className="text-[10px] uppercase tracking-[0.15em] text-caption">
                    Margin of Safety
                  </dt>
                </MetricTooltip>
                <dd
                  className={`font-mono tabular-nums text-lg font-semibold ${
                    marginOfSafety >= 0 ? "text-success" : "text-danger"
                  }`}
                >
                  {
                    // Previous copy was "+80%+" which reads like a broken
                    // render. Show the real signed number; only if it's
                    // truly enormous (>200%) do we collapse to ">+200%"
                    // so the layout doesn't overflow.
                    marginOfSafety > 200
                      ? ">+200%"
                      : marginOfSafety < -200
                      ? "<-200%"
                      : formatPct(marginOfSafety)
                  }
                </dd>
              </div>
            )}
            <Stat label="Moat" value={moat || "Not rated"} metricKey="moat" />
          </dl>

          <p className="text-[11px] text-caption leading-relaxed mt-2">
            {data.disclaimer}
          </p>
        </div>

        {/* ══════════════════════════════════════════════════════════
            Column 2 — The Prism (mobile: 2nd)
            ══════════════════════════════════════════════════════════ */}
        <div className="lg:col-span-5 order-2 lg:order-2 flex flex-col items-center">
          {/* Responsive-safe wrapper: on phones the Prism caps at the
              device width (with a small gutter) rather than overflowing
              horizontally. Prism itself now uses width:100% + aspect
              ratio, so the max-width here defines the upper bound. */}
          <div className="relative w-full max-w-[340px] mx-auto">
            <Prism
              data={data}
              size={340}
              defaultMode={defaultMode}
              highlightedPillar={highlightedPillar}
              onPillarTap={setExplainerAxis}
            />
          </div>
          <p className="mt-3 text-[11px] text-caption leading-snug text-center max-w-[30ch]">
            Every stock has a Signature. Unfold it into a Spectrum to see how it
            refracts.
          </p>
          {/* Trust-Surface "last refresh" badge — only renders when the
              backend stamps the payload with computed_at. We deliberately
              omit the line rather than render a dash when missing so it
              never looks broken. */}
          {(() => {
            const ago = timeAgo(data.computed_at)
            if (!ago) return null
            return (
              <p className="mt-1.5 text-[10px] text-caption leading-snug text-center">
                Last refresh: {ago} &middot; Sources: NSE &middot; BSE &middot; SEBI
              </p>
            )
          })()}
          <div className="mt-4 w-full max-w-[34ch]">
            <PrismNarrator
              data={data}
              onHighlight={setHighlightedPillar}
            />
          </div>
        </div>

        {/* ══════════════════════════════════════════════════════════
            Column 3 — ScoreCard (mobile: 1st — most valuable at a glance)
            ══════════════════════════════════════════════════════════ */}
        <div className="lg:col-span-3 order-1 lg:order-3">
          <ScoreCard
            score100={score100}
            grade={grade}
            trend12m={trend12m}
            sectorRank={sectorRank ?? null}
            refractionIndex={data.refraction_index}
            marketCapCr={marketCapCr ?? null}
          />
        </div>
      </div>

      {/* Tap-to-explain sheet — rendered at section-level so its fixed
          positioning escapes the 3-column grid. Opens when the user
          clicks/taps a vertex in the Signature. */}
      <PillarExplainer
        open={explainerAxis !== null}
        axis={explainerAxis}
        data={data}
        onClose={() => setExplainerAxis(null)}
      />
    </section>
  )
}
