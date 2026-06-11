"use client"

/**
 * HonestHero — spec §1 / §1.1.
 *
 * The single hero region above the fold. Carries, in spec-priority order:
 *   1. Verdict pill (gated through shouldGateVerdict)
 *   2. Fair Value figure + confidence note (clamp pill when clamped)
 *   3. Discount-to-FV (or <DegradedScenarioCard> in the WIPRO clamp case)
 *   4. Worry signal (in the side rail)
 *   5. One-line caveat row (value-trap / data-limited / clamp note)
 *   6. Honest Card teaser slot (collapsed by default on desktop)
 *
 * One-rail invariant (spec §1 Fold 1 + agent-dispatch standing rule 3):
 *   THIS IS THE ONLY sticky scorecard-class surface on the analysis page.
 *   The retired surfaces (StickyScorecard, ScoreCard standalone mount)
 *   absorbed into this rail. Do NOT add a second `position: sticky` to
 *   any other component touching verdict / FV / discount / worry / score
 *   data; the rail is single-pinned by design.
 *
 * Layout:
 *   ≥1024  → 2-column flex: main column 1fr + sticky side rail 320px.
 *            Rail uses `lg:sticky lg:top-20 lg:self-start lg:w-[320px]`.
 *   <1024  → side rail collapses; <MobileScoreStrip> handles the mobile
 *            condensation in its own component (separate render site in
 *            AnalysisBody).
 *
 * Composes PR-B card primitives — <NarrativeCard> for the main panel,
 * <DataCard hover={false}> for the side-rail tiles. No raw div surfaces.
 *
 * SEBI lens: all labels descriptive (Verdict / Fair Value / Discount
 * to FV / Worry / Moat / Red flags). The verdict pill's user-facing
 * label is owned by `verdictTierLabel`. No imperative verbs anywhere.
 *
 * Distress-flag grade-cap (DISTRESS_FLAGS / capGrade) carried over from
 * the retired ScoreCard so the rail cannot render "Grade A" while the
 * page also lists "Consecutive Losses" / "Declining Revenue". Defence-
 * in-depth label-only correction; underlying score is untouched.
 */

import * as React from "react"
import Link from "next/link"

import { NarrativeCard, DataCard } from "@/components/cards"
import DegradedScenarioCard from "@/components/analysis/DegradedScenarioCard"
import IntrinsicValueSection from "@/components/analysis/IntrinsicValueSection"
import MetricTooltip from "@/components/common/MetricTooltip"
import { cn, formatCurrency } from "@/lib/utils"
import { formatMarketCap } from "@/lib/formatters"
import {
  VERDICT_COLORS,
  verdictTierFromMos,
  verdictTierLabel,
  type VerdictTier,
} from "@/lib/verdict-colors"
import type { HeroSignals } from "@/lib/useHeroSignals"
import type { AnalysisResponse } from "@/types/api"

/* ------------------------------------------------------------------ */
/*  Distress-flag grade cap (preserved verbatim from ScoreCard.tsx)   */
/* ------------------------------------------------------------------ */

const DISTRESS_FLAGS: ReadonlySet<string> = new Set([
  "loss_making",
  "negative_equity",
  "declining_revenue",
  "high_debt",
])

function hasDistressFlag(
  flags: ReadonlyArray<{ flag: string; severity?: string }> | undefined,
): boolean {
  if (!flags || flags.length === 0) return false
  return flags.some((f) => DISTRESS_FLAGS.has(f.flag))
}

function capGrade(grade: string | null, distress: boolean): string {
  if (!grade) return "—"
  if (!distress) return grade
  const g = grade.toUpperCase()
  if (g.startsWith("A")) return "B"
  return grade
}

/* ------------------------------------------------------------------ */

export interface HonestHeroProps {
  ticker: string
  displayTicker: string
  companyName: string
  currency: string
  signals: HeroSignals
  /** Used to detect the value-trap flag for the caveat row. */
  payload: AnalysisResponse
  /**
   * Raw (unclamped) fair value to pass into the DegradedScenarioCard
   * when the degraded state fires. Optional; the card omits the Rs.{raw}
   * reference when null.
   */
  rawFairValue?: number | null
  /** Two-line preview of the Honest Card body for the rail teaser. */
  honestCardTeaser?: string | null
  /** Optional "Tell me the story" CTA handler (rail bottom). */
  onTellStory?: () => void
}

export default function HonestHero({
  ticker,
  displayTicker,
  companyName,
  currency,
  signals,
  payload,
  rawFairValue,
  honestCardTeaser,
  onTellStory,
}: HonestHeroProps) {
  const tier: VerdictTier = signals.dataLimited
    ? "data_limited"
    : verdictTierFromMos(signals.discount, signals.verdict)
  const palette = VERDICT_COLORS[tier]
  const verdictLabel = signals.verdictGated
    ? "Under Review"
    : verdictTierLabel(tier)

  const redFlagList = payload.insights?.red_flags_structured ?? []
  const valueTrap = redFlagList.some((f) => f?.flag === "value_trap")
  const distress = hasDistressFlag(redFlagList)

  // ROOT CAUSE #1 (2026-06-10): single source of truth for the
  // headline FV. Reads from the resolver's `signals.headlineFairValue`
  // — which prefers the backend-stamped `headline_fair_value` field
  // (composite-IV-preferred), falling back to composite_intrinsic_value
  // and finally signals.fairValue (DCF) for legacy cached payloads.
  //
  // Background: T1.1 closed the ~40% HDFCBANK-class gap vs AlphaSpread
  // by computing a composite IV. Phase C switched the verdict gate to
  // the composite, but the hero headline figure (and every other
  // user-visible "Fair Value" pill on the page) was still reading
  // `valuation.fair_value` (DCF-only) — producing 3+ different numbers
  // on the same page. The canonical-headline contract makes the hero,
  // caveat, side-rail, FAQ, AI Why, peer table, and SEO surfaces all
  // read the SAME number. The DCF stays visible inside the "Based on
  // N methods" DCF row below, so users still see both estimators —
  // only every SINGLE headline figure reads the canonical number.
  const headlineFv = signals.headlineFairValue
  const currentPrice = payload.valuation?.current_price
  const safeCurrentPrice =
    typeof currentPrice === "number" &&
    Number.isFinite(currentPrice) &&
    currentPrice > 0
      ? currentPrice
      : null

  // DCF METHOD ROW ONLY — the "Based on N methods" breakdown inside
  // IntrinsicValueSection legitimately surfaces the DCF-specific
  // estimate NEXT TO the canonical headline IV (same exemption class
  // as DcfMultiplesChip / ValuationMethodsPanel). Every headline
  // figure in this file reads signals.headlineFairValue.
  // eslint-disable-next-line no-restricted-syntax -- headline-fv-allow: DCF method row inside IntrinsicValueSection
  const dcfMethodValue = signals.fairValue

  const fvDisplay =
    headlineFv != null
      ? formatCurrency(headlineFv, currency, ticker)
      : "—"

  const confNote =
    signals.confidence != null && !signals.dataLimited
      ? `conf ${Math.round(signals.confidence)}%`
      : null

  const showClampNote = signals.fairValueClamped && !signals.dataLimited

  const showValueTrapPara =
    valueTrap || (redFlagList.length >= 3 && signals.moat === "None")

  return (
    <section
      className="flex flex-col lg:flex-row lg:items-start lg:gap-6"
      aria-labelledby="honest-hero-heading"
    >
      {/* ── Main column (verdict + FV + discount/degraded + caveat) ── */}
      <div className="flex-1 min-w-0">
        <NarrativeCard className="border-l-4" style={{ borderLeftColor: "transparent" }}>
          {/* Verdict colour bar — saturated cascade carries the tier */}
          <span aria-hidden className={cn("block h-1 -mt-6 md:-mt-8 -mx-6 md:-mx-8 mb-4 rounded-t-2xl", palette.bar)} />

          {/* "1. INTRINSIC VALUE" — the AlphaSpread-style first numbered
              section REPLACES the legacy FV/Discount dl grid + the
              DcfMultiplesChip pill row (feat/alphaspread-style-opening).
              Centered numbered heading, SEBI-templated narrative with
              the canonical headline IV, "Based on N methods" rows (DCF /
              Peer Multiples / sector estimator), italic reconciliation
              note, and the right-hand IV card (huge figure + Discount /
              Premium badge + IV-vs-price bars). The verdict pill rides
              the headingExtra slot so it stays the single above-the-fold
              verdict surface. Degraded (WIPRO-clamp) payloads keep the
              clamped-FV + DegradedScenarioCard treatment via
              degradedContent — heading stays, so numbering never gaps. */}
          <IntrinsicValueSection
            ticker={ticker}
            displayTicker={displayTicker}
            companyName={companyName}
            currency={currency}
            intrinsicValue={headlineFv}
            currentPrice={safeCurrentPrice}
            dcfValue={dcfMethodValue}
            multiplesValue={payload.multiples_based_fv ?? null}
            multiplesMethod={payload.multiples_method ?? null}
            sectorSpecificValue={payload.sector_specific_fv ?? null}
            sectorSpecificLabel={payload.sector_specific_label ?? null}
            dataLimited={signals.dataLimited}
            degraded={signals.degraded}
            headingExtra={
              <>
                <span
                  id="honest-hero-heading"
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] font-semibold",
                    pillClasses(tier),
                  )}
                >
                  <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", dotForTier(tier))} />
                  {verdictLabel}
                </span>
                {confNote && (
                  <span className="text-[11px] text-caption">{confNote}</span>
                )}
              </>
            }
            degradedContent={
              <div className="mt-2">
                <p className="text-[10px] uppercase tracking-[0.15em] text-caption">
                  Fair Value
                </p>
                <p className="font-mono tabular-nums text-2xl font-semibold text-ink mt-0.5">
                  {fvDisplay}
                  {showClampNote && (
                    <span className="ml-2 inline-flex items-center rounded-full border border-amber-300 bg-tone-warn-bg px-1.5 py-0 text-[10px] font-medium text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200 align-middle">
                      clamp
                    </span>
                  )}
                </p>
                <div className="mt-4">
                  <DegradedScenarioCard
                    ticker={ticker}
                    currency={currency}
                    rawFairValue={rawFairValue}
                    showValueTrapPara={showValueTrapPara}
                    redFlagCount={signals.redFlags ?? null}
                    moat={signals.moat ?? null}
                  />
                </div>
              </div>
            }
          />

          {/* One-line caveat row — value-trap / data-limited / clamp.
              Spec §1 priority 5. Single most factual line; never directive. */}
          {!signals.degraded && (valueTrap || signals.dataLimited || showClampNote) && (
            <div
              role="note"
              className="mt-4 flex items-start gap-2 rounded-lg border border-amber-300 bg-tone-warn-bg dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200 px-3 py-2 text-[12px] leading-snug text-amber-900"
            >
              <span aria-hidden className="mt-0.5">⚠</span>
              <span>
                {signals.dataLimited
                  ? "Under Review — not enough reliable data to publish a fair value or discount-to-FV yet."
                  : valueTrap
                    ? "Possible value trap: the discount pairs with limited quality or no durable moat — read the Honest Card before acting on the headline figure."
                    : "Fair value clamped to a plausible display bound. See valuation notes below."}
              </span>
            </div>
          )}

          {/* Honest Card teaser (2-line preview) */}
          {honestCardTeaser && (
            <p className="mt-4 text-[13px] text-body leading-snug line-clamp-2">
              {honestCardTeaser}
            </p>
          )}
        </NarrativeCard>
      </div>

      {/* ── Side rail (≥1024 sticky). Hidden below lg; MobileScoreStrip
            renders separately. THE sole position:sticky surface among
            analysis scorecard-class components. ── */}
      <aside
        className="hidden lg:block lg:sticky lg:top-20 lg:self-start lg:w-[320px] lg:shrink-0 mt-4 lg:mt-0"
        aria-label={`${displayTicker} side rail`}
      >
        <DataCard hover={false} className="flex flex-col gap-3">
          {/* Premium Feel R2 — every metric on the rail is hover-explained.
              MetricTooltip wraps the value with a subtle dotted underline;
              hovering opens an explainer popover sourced from
              metric-explainers.ts. */}
          {/* 2026-06-09 fix/analysis-ux-fixbatch: each side-rail tile
              now passes an explicit `ariaValueText` so the trigger's
              aria-label reads e.g. "YieldIQ Score: 64 / 100" instead
              of the previous "YieldIQ Score: YieldIQ Score" (the
              fallback that fired whenever `value` was a JSX node and
              not a plain string). Chrome MCP audit on
              /analysis/HDFCBANK (2026-06-09) flagged all five tiles
              as label-only to assistive tech. */}
          {(() => {
            const scoreText =
              signals.score != null ? `${Math.round(signals.score)} / 100` : "—"
            return (
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
                  YieldIQ Score
                </span>
                <MetricTooltip
                  metric="yieldiq_score"
                  label="YieldIQ Score"
                  showLabel={false}
                  ariaValueText={scoreText}
                  value={
                    <span className="font-mono tabular-nums text-base text-ink">
                      {scoreText}
                    </span>
                  }
                />
              </div>
            )
          })()}
          {(() => {
            const gradeText = capGrade(signals.grade, distress)
            return (
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
                  Grade
                </span>
                <MetricTooltip
                  label="Grade"
                  showLabel={false}
                  title="Grade"
                  description="A letter shorthand (A/B/C/D/F) mapped from the YieldIQ Score so the rail can be scanned at a glance."
                  threshold="A: top decile across pillars. B: healthy composite. C: mixed with trade-offs. D/F: one or more pillars failing badly."
                  caveat="A grade is a label, not a verdict. Distress-flag businesses are capped at B regardless of the underlying score."
                  ariaValueText={gradeText}
                  value={
                    <span className="font-mono tabular-nums text-base text-ink">
                      {gradeText}
                    </span>
                  }
                />
              </div>
            )
          })()}
          {(() => {
            const moatText = signals.moat ?? "—"
            return (
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
                  Moat
                </span>
                <MetricTooltip
                  label="Moat"
                  showLabel={false}
                  title="Moat"
                  description="How durable the firm's competitive advantage looks — whether it can defend profit margins from rivals over the next 5-10 years."
                  threshold="Wide: pricing power proven over a full cycle. Moderate: some defenses. Narrow: limited and eroding. None: commodity-like economics."
                  ariaValueText={moatText}
                  value={
                    <span className="text-[13px] text-ink">{moatText}</span>
                  }
                />
              </div>
            )
          })()}
          {(() => {
            const redFlagsText =
              signals.redFlags != null ? String(signals.redFlags) : "—"
            return (
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
                  Red flags
                </span>
                <MetricTooltip
                  label="Red flags"
                  showLabel={false}
                  title="Red flags"
                  description="Count of structured red-flag signals raised by our quality engine — governance, accounting, leverage, and operating-trend issues."
                  caveat="A non-zero count means the engine raised at least one flag; the Risk and Quality deep-dive below explains each one in plain English."
                  ariaValueText={redFlagsText}
                  value={
                    <span className="font-mono tabular-nums text-[13px] text-ink">
                      {redFlagsText}
                    </span>
                  }
                />
              </div>
            )
          })()}
          {(() => {
            const worryText = worryRailLabel(signals.worry)
            return (
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
                  Worry
                </span>
                <MetricTooltip
                  label="Worry"
                  showLabel={false}
                  title="Worry signal"
                  description="Our holder-experience tier — translates a basket of volatility, drawdown, and quality inputs into a one-line owner-of-this-stock label."
                  threshold="Sleep well: low realized volatility, durable fundamentals. Watch closely: meaningful flags or volatility. Read bears: read the bear case before adding."
                  caveat="A label, not a forecast. The tier reflects historical risk-of-experience, not the next move in the price."
                  ariaValueText={worryText}
                  value={
                    <span className="text-[13px] text-ink">{worryText}</span>
                  }
                />
              </div>
            )
          })()}
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
              Market cap
            </span>
            <span className="font-mono tabular-nums text-[13px] text-ink">
              {signals.marketCapCr != null ? formatMarketCap(signals.marketCapCr) : "—"}
            </span>
          </div>

          <div className="border-t border-border pt-3 flex flex-col gap-2">
            {onTellStory ? (
              <button
                type="button"
                onClick={onTellStory}
                className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-brand text-white text-xs font-semibold px-3 py-2 min-h-[36px] hover:opacity-90 active:scale-[0.98] transition"
              >
                Tell me the story
              </button>
            ) : (
              <Link
                href={`/report/${ticker}`}
                className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-brand text-white text-xs font-semibold px-3 py-2 min-h-[36px] hover:opacity-90 active:scale-[0.98] transition"
              >
                Tell me the story
              </Link>
            )}
            <Link
              href={`/analysis/${encodeURIComponent(ticker)}/playground`}
              className="text-[11px] text-brand hover:underline text-center"
            >
              Reverse-DCF →
            </Link>
          </div>
        </DataCard>
      </aside>
    </section>
  )
}

function pillClasses(tier: VerdictTier): string {
  switch (tier) {
    case "undervalued":
      return "bg-tone-good-bg text-tone-good-fg border-tone-good-bd"
    case "overvalued":
      return "bg-rose-50 text-rose-700 border-rose-200"
    case "fairly_valued":
      return "bg-tone-neutral-bg text-slate-700 border-tone-neutral-bd"
    default:
      return "bg-tone-warn-bg text-amber-900 border-amber-300 dark:bg-amber-950/30 dark:text-amber-200 dark:border-amber-900"
  }
}

function dotForTier(tier: VerdictTier): string {
  switch (tier) {
    case "undervalued":
      return "bg-emerald-500"
    case "overvalued":
      return "bg-rose-500"
    case "fairly_valued":
      return "bg-slate-400"
    default:
      return "bg-amber-500"
  }
}

function worryRailLabel(tier: HeroSignals["worry"] | null | undefined): string {
  switch (tier) {
    case "sleep_well":
      return "Sleep well"
    case "normal":
      return "Normal"
    case "watch_closely":
      return "Watch closely"
    case "read_bears":
      return "Read bears"
    case "significant_concerns":
      return "High"
    default:
      return "—"
  }
}

// formatMarketCapCr (the "Rs.X L Cr" jargon-style private duplicate)
// is deleted — the rail now renders via the canonical
// formatMarketCap() from @/lib/formatters ("₹X.XX Lakh Cr").
