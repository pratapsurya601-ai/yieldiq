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
import ScoreBreakdownPanel from "@/components/analysis/ScoreBreakdownPanel"
import MetricTooltip from "@/components/analysis/MetricTooltip"
import FvConfidenceBand from "@/components/analysis/FvConfidenceBand"
import { verdictColor } from "@/lib/prism"
import { timeAgo } from "@/lib/dataFreshness"
import {
  axesFromPillars,
  generatePrismNarrative,
} from "@/lib/prismNarrative"
import type {
  PillarKey,
  PrismData,
  PrismMode,
} from "@/components/prism/types"
import {
  formatCurrency,
  formatPct,
  shouldGateVerdict,
  verdictDisplayLabel,
  verdictFromMos,
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
  /** Signed (FV-CP)/CP*100. Label renders as "Discount to FV" when >= 0, "Premium to FV" when < 0. */
  marginOfSafety: number
  /**
   * Step B (2026-05-17): true Buffett margin of safety = (FV-CP)/FV*100.
   * Optional/nullable for pre-PR cached payloads. When present AND
   * non-negative, render as a separate "Margin of Safety (Buffett)"
   * stat. Hidden for overvalued names (negative MoS confuses in chip form).
   */
  buffettMosPct?: number | null
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
  /**
   * DCF model confidence on a 0–100 scale (mirrors
   * `ValuationOutput.confidence_score`). Drives the ±band rendered
   * beneath the headline Fair Value. Null/undefined → band omitted.
   * Suppressed entirely when `dataLimited === true`, since a model that
   * failed its reliability gate has no meaningful confidence to report.
   */
  confidence?: number | null
  /**
   * True when backend clamped fair_value to a plausible bound (e.g.
   * computed FV > 3x current price). Headline verdict must NOT read as
   * positive "Notably Below Fair Value" when the underlying FV is
   * clamped — see MUTHOOTFIN P0 (2026-05-17): yellow "Under Review"
   * banner sat directly under a huge "Notably Below Fair Value" header
   * because the hero derived its label from MoS only, ignoring the
   * clamp + reliability signals.
   */
  fvClamped?: boolean
  /**
   * Day-91 (2026-05-22): scenario band gate inputs. When the bull/bear
   * band exceeds 25% of current price the headline collapses to "Under
   * Review" even when confidence reads >= 60. Optional/nullable for
   * legacy cached payloads.
   */
  bullCase?: number | null
  bearCase?: number | null
  /**
   * DCF reliability gate (mirrors ValuationOutput.dcf_reliable). When
   * false, the fair_value/MoS in the payload failed the backend's
   * reliability check and the hero must not present a positive verdict.
   */
  dcfReliable?: boolean
  /**
   * Backend data_confidence band ("high" | "medium" | "low" | "unusable").
   * "low" / "unusable" suppress positive verdict labels in the hero.
   */
  dataConfidence?: string | null
  /**
   * Single-primary-signal hierarchy (chassis 2026-05-26): when true, the
   * hero renders ONLY the headline triad — Verdict + Fair Value (with
   * confidence band) + Discount/Premium to FV. The ScoreCard column,
   * Buffett MoS chip, and Moat stat are hidden and instead surface
   * inside the "Confidence and methodology" disclosure below the hero
   * in AnalysisBody. Mirrors AlphaSpread's one-number + one-pill hero
   * pattern (see .audit/competitor-walk-hdfcbank-2026-05-26.md).
   */
  compactSummary?: boolean
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
  buffettMosPct,
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
  confidence,
  fvClamped,
  bullCase,
  bearCase,
  dcfReliable,
  dataConfidence,
  compactSummary = false,
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

  // ─────────────────────────────────────────────────────────────────
  // "Under Review" guard — MUTHOOTFIN P0 (2026-05-17).
  //
  // Before this guard, the headline was derived purely from MoS via
  // verdictFromMos(), so a ticker with a clamped FV (FV > 3x price),
  // a failed DCF reliability gate, OR a "low/unusable" data-confidence
  // band could still render a giant "Notably Below Fair Value" title —
  // directly above the yellow "Under Review — not enough reliable data"
  // banner and the "Fair value clamped" caution. Three contradictory
  // signals on one page = user confusion + SEBI risk (the positive
  // label reads as endorsement on a ticker the model itself flags as
  // unreliable).
  //
  // The fix collapses any of six unreliability signals into a single
  // "Under Review" headline that uses the warning tone. The existing
  // yellow banner + clamp caution stay as-is; they now reinforce the
  // header instead of contradicting it.
  //
  // Triggers (any one):
  //   1. valuationVerdict ∈ {data_limited, under_review, unavailable, avoid}
  //   2. dcfReliable === false  (backend reliability gate failed)
  //   3. dataConfidence ∈ {low, unusable}
  //   4. fvClamped === true  (FV clamped to plausible bound)
  //   5. dataLimited === true (parent's existing aggregate flag)
  //   6. score100 < 50  (composite below the unreliable-floor)
  // ─────────────────────────────────────────────────────────────────
  const verdictKey = String(valuationVerdict ?? "").toLowerCase().replace(/\s+/g, "_")
  const verdictUnreliable =
    verdictKey === "data_limited" ||
    verdictKey === "under_review" ||
    verdictKey === "unavailable" ||
    verdictKey === "avoid"
  const confidenceUnreliable =
    typeof dataConfidence === "string" &&
    (dataConfidence.toLowerCase() === "low" ||
      dataConfidence.toLowerCase() === "unusable")
  // Day-91 (2026-05-22): fold the shared confidence/band-ratio gate
  // into isUnreliable so the EditorialHero, AnalysisHero, tab title,
  // and PublicAnalysis pill agree. Was: score100 < 50 only — caught
  // RELIANCE/INDIGO by score but missed TCS (score 70, confidence 67,
  // wide scenario band) per audit #4.
  const verdictGated = shouldGateVerdict({
    dataLimited: false,
    confidence,
    currentPrice,
    bullCase,
    bearCase,
    marginOfSafety,
  })
  const isUnreliable =
    !!dataLimited ||
    verdictUnreliable ||
    dcfReliable === false ||
    confidenceUnreliable ||
    fvClamped === true ||
    verdictGated ||
    (typeof score100 === "number" && Number.isFinite(score100) && score100 < 50)

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
              <span
                data-testid="editorial-hero-region"
                className={`text-[11px] uppercase tracking-[0.15em] ${
                  isUnreliable ? "text-amber-700 dark:text-amber-300" : "text-body"
                }`}
              >
                {/* Single source of truth: derive verdict from MoS (the
                    same number rendered in the hero stats) via
                    verdictFromMos(). The backend verdict ENUM is only a
                    fallback when MoS is null/non-finite — it can drift
                    from MoS during cold-cache or stale-cache conditions
                    and produce SBIN/TCS-style tab-vs-body contradictions.
                    Postmortem: 2026-04-30 P0 — body said "Fair Value
                    Region" while tab said "Notably Above Fair Value"
                    on SBIN MoS -39.5%. When isUnreliable fires the
                    label collapses to "Under Review" (MUTHOOTFIN P0
                    2026-05-17) — see guard above. */}
                {isUnreliable
                  ? "Under Review"
                  : Number.isFinite(marginOfSafety) && marginOfSafety != null
                  ? verdictFromMos(marginOfSafety)
                  : verdictRegion(valuationVerdict)}
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
              className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200 px-3 py-2 text-[12px] leading-snug text-amber-900"
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
            data-testid="editorial-hero-headline"
            className={`font-editorial text-3xl leading-tight font-semibold ${
              isUnreliable ? "text-amber-800 dark:text-amber-200" : "text-ink"
            }`}
            style={{ fontVariationSettings: "'opsz' 48" }}
          >
            {/* Headline mirrors the small region caption above. Always
                derive from MoS so tab title and hero headline cannot
                disagree (see SBIN/TCS P0, 2026-04-30).

                When isUnreliable fires (clamped FV, failed DCF gate,
                low/unusable data_confidence, score < 50, or backend
                verdict ∈ {data_limited, under_review, unavailable,
                avoid}) the headline collapses to "Under Review" — no
                positive "Notably Below Fair Value" can sit above the
                yellow caution banner on tickers the model itself
                flags as unreliable. MUTHOOTFIN P0 (2026-05-17). */}
            {isUnreliable
              ? "Under Review"
              : Number.isFinite(marginOfSafety) && marginOfSafety != null
              ? verdictFromMos(marginOfSafety)
              : verdictDisplayLabel(valuationVerdict)}
          </h2>

          {/* When dataLimited, FV/MoS are unreliable — replace the headline
              metrics with an Under Review banner. Stale FV next to a tiny
              "Data Limited" chip reads as a real fair value. P0 fix
              2026-05-02 (ONGC canary). */}
          {dataLimited && (
            <div
              role="note"
              aria-label="Under Review"
              className="mt-1 rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200 px-3 py-2 text-[12px] leading-snug text-amber-900"
            >
              <span className="font-semibold">Under Review</span> &mdash; not enough
              reliable data to publish a fair value, margin of safety, or composite
              score for this ticker yet. Current price below for reference only.
              <dl className="mt-2 grid grid-cols-1 gap-y-1">
                <Stat
                  label="Current Price"
                  value={currentPrice > 0 ? formatCurrency(currentPrice, currency) : "Awaiting data"}
                  metricKey="current_price"
                />
              </dl>
            </div>
          )}

          {/* 2x2 metrics — only when we actually have a fair value to show. */}
          {!dataLimited && (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 mt-1">
            <div>
              <MetricTooltip metricKey="fair_value">
                <dt className="text-[10px] uppercase tracking-[0.15em] text-caption">
                  Fair Value
                </dt>
              </MetricTooltip>
              <dd className="font-mono tabular-nums text-lg font-semibold text-ink">
                {fairValue > 0 ? formatCurrency(fairValue, currency) : "Not reported"}
              </dd>
              {/* Confidence ±band — only when the DCF reliability gate
                  passed (dataLimited=false) and the backend supplied a
                  confidence_score. See FvConfidenceBand for math + amber
                  threshold. */}
              {fairValue > 0 && (
                <FvConfidenceBand
                  fairValue={fairValue}
                  confidence={confidence}
                  currency={currency}
                />
              )}
              {/* Reverse-DCF Playground entry — Week-2 manifesto. The
                  playground lives at /analysis/[ticker]/playground and
                  lets users drag sliders for the 5 key DCF inputs to
                  see fair value recompute live. Always visible (the
                  free tier only unlocks WACC inside; soft paywall on
                  the rest). */}
              {fairValue > 0 && data?.ticker && (
                <a
                  href={`/analysis/${encodeURIComponent(data.ticker)}/playground`}
                  className="mt-1 inline-block text-[11px] font-semibold text-emerald-700 hover:underline dark:text-emerald-300"
                >
                  &rarr; Adjust the assumptions
                </a>
              )}
            </div>
            <Stat
              label="Current Price"
              value={currentPrice > 0 ? formatCurrency(currentPrice, currency) : "Awaiting data"}
              metricKey="current_price"
            />
            <div>
              {/*
                Step C (2026-05-17): drop the "Upside / Downside" framing
                entirely. Label switches dynamically based on sign:
                  marginOfSafety >= 0  →  "Discount to FV"  (FV > price)
                  marginOfSafety  < 0  →  "Premium to FV"   (price > FV)
                The Buffett MoS chip below stays separate and is hidden
                for overvalued names (negative Buffett MoS is confusing
                in chip form — cleaner UX to just omit it).
              */}
              <MetricTooltip metricKey="mos">
                <dt
                  className="text-[10px] uppercase tracking-[0.15em] text-caption"
                  title="Discount or premium of current price relative to fair value. Computed as (Fair Value - Price) / Price × 100."
                >
                  {marginOfSafety >= 0 ? "Discount to FV" : "Premium to FV"}
                </dt>
              </MetricTooltip>
              <dd
                className={`font-mono tabular-nums text-lg font-semibold ${
                  marginOfSafety >= 0 ? "text-success" : "text-danger"
                }`}
              >
                {
                  // Show the magnitude as a positive number; the label
                  // ("Discount" vs "Premium") conveys direction. Caps at
                  // ±200% so the layout doesn't overflow.
                  (() => {
                    const mag = Math.abs(marginOfSafety)
                    if (marginOfSafety > 200) return ">200%"
                    if (marginOfSafety < -200) return ">200%"
                    return formatPct(mag)
                  })()
                }
              </dd>
            </div>
            {/* Buffett MoS + Moat — demoted from the headline grid into
                the "Confidence and methodology" disclosure rendered below
                the hero in AnalysisBody when `compactSummary` is on. This
                keeps the above-the-fold triad to Verdict + Fair Value +
                Discount-to-FV. See .audit/competitor-walk-hdfcbank-
                2026-05-26.md gap #2. */}
            {!compactSummary && buffettMosPct != null && Number.isFinite(buffettMosPct) && buffettMosPct >= 0 && (
              <div>
                <dt
                  className="text-[10px] uppercase tracking-[0.15em] text-caption"
                  title="How much room below current price the model says exists. Buffett-style: (Fair Value - Price) / Fair Value."
                >
                  Margin of Safety (Buffett)
                </dt>
                <dd
                  className="font-mono tabular-nums text-lg font-semibold text-success"
                >
                  {formatPct(buffettMosPct)}
                </dd>
              </div>
            )}
            {!compactSummary && (
              <Stat label="Moat" value={moat || "Not rated"} metricKey="moat" />
            )}
          </dl>
          )}

          <p className="text-[11px] text-caption leading-relaxed mt-2">
            {data.disclaimer}
          </p>
        </div>

        {/* ══════════════════════════════════════════════════════════
            Column 2 — The Prism (mobile: 2nd)
            ══════════════════════════════════════════════════════════ */}
        <div className={`${compactSummary ? "lg:col-span-8" : "lg:col-span-5"} order-2 lg:order-2 flex flex-col items-center`}>
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

          {/* P0 #3 (SWS-inspired) — one-sentence narrative caption that
              tells the user what to read into the Prism shape. Purely
              factual numeric description; SEBI-safe by construction
              (see lib/prismNarrative.ts header). */}
          {(() => {
            const narrative = generatePrismNarrative(
              axesFromPillars(data.pillars),
            )
            return (
              <p
                data-testid="prism-narrative-caption"
                className="mt-2 italic text-sm text-caption leading-snug text-center max-w-prose"
              >
                {narrative}
              </p>
            )
          })()}

          {/* Counter chips below the caption — derived from the SAME
              red_flags_structured array EditorialHero already consumes
              (severity==="info" → positive signal, otherwise → red flag),
              so these counts can't drift from the Red Flag Insights panel.
              Hidden when zero to keep the hero quiet on clean shapes. */}
          {(() => {
            const flags = redFlags ?? []
            const redFlagsCount = flags.filter(
              (f) => f && (f as { severity?: string }).severity !== "info",
            ).length
            const positivesCount = flags.filter(
              (f) => f && (f as { severity?: string }).severity === "info",
            ).length
            if (redFlagsCount === 0 && positivesCount === 0) return null
            return (
              <div
                data-testid="prism-counter-chips"
                className="mt-2 flex items-center justify-center gap-2"
                aria-label="Risk and positive-signal counts"
              >
                {redFlagsCount > 0 && (
                  <span
                    data-testid="prism-red-flag-chip"
                    className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
                    title={`${redFlagsCount} red flag${redFlagsCount === 1 ? "" : "s"}`}
                  >
                    <span aria-hidden>⚠</span>
                    {redFlagsCount}
                  </span>
                )}
                {positivesCount > 0 && (
                  <span
                    data-testid="prism-positive-chip"
                    className="inline-flex items-center gap-1 rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200"
                    title={`${positivesCount} positive signal${positivesCount === 1 ? "" : "s"}`}
                  >
                    <span aria-hidden>★</span>
                    {positivesCount}
                  </span>
                )}
              </div>
            )
          })()}
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
            Hidden when `compactSummary` is on. ScoreCard +
            ScoreBreakdownPanel are then rendered inside the
            "Confidence and methodology" disclosure below the hero in
            AnalysisBody so the above-the-fold view stays at one
            primary signal triad (Verdict + FV + MoS).
            ══════════════════════════════════════════════════════════ */}
        {!compactSummary && (
          <div className="lg:col-span-3 order-1 lg:order-3 flex flex-col gap-3">
            <ScoreCard
              score100={score100}
              grade={grade}
              trend12m={trend12m}
              sectorRank={sectorRank ?? null}
              refractionIndex={data.refraction_index}
              marketCapCr={marketCapCr ?? null}
              redFlags={redFlags}
            />
            {/* Phase C.3 — "Why this score?" transparency panel.
                Renders nothing when score_breakdown is absent. */}
            <ScoreBreakdownPanel
              breakdown={data.quality?.score_breakdown}
            />
          </div>
        )}
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
