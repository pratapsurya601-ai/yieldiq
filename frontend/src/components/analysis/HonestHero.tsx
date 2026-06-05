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
import { cn, formatCurrency, formatPct } from "@/lib/utils"
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

  const fvDisplay =
    signals.fairValue != null
      ? formatCurrency(signals.fairValue, currency, ticker)
      : "—"

  const discountDisplay = (() => {
    if (signals.degraded) return "+200% (clamp)"
    if (signals.discount == null) return "—"
    return formatPct(signals.discount)
  })()

  const discountTone: "good" | "bad" | "neutral" =
    signals.discount == null || signals.dataLimited
      ? "neutral"
      : signals.discount >= 0
        ? "good"
        : "bad"

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

          {/* Ticker line */}
          <p className="text-[11px] text-caption uppercase tracking-[0.15em]">
            {displayTicker} · {companyName}
          </p>

          {/* Verdict pill */}
          <div className="mt-2 flex items-center gap-2 flex-wrap">
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
          </div>

          {/* Fair Value + Discount row (or DegradedScenarioCard) */}
          {signals.degraded ? (
            <div className="mt-4">
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
          ) : (
            <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3">
              <div>
                <dt className="text-[10px] uppercase tracking-[0.15em] text-caption">
                  Fair Value
                </dt>
                <dd className="font-mono tabular-nums text-2xl font-semibold text-ink mt-0.5">
                  {fvDisplay}
                  {showClampNote && (
                    <span className="ml-2 inline-flex items-center rounded-full border border-amber-300 bg-tone-warn-bg px-1.5 py-0 text-[10px] font-medium text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200 align-middle">
                      clamp
                    </span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase tracking-[0.15em] text-caption">
                  {signals.discount != null && signals.discount < 0
                    ? "Premium to FV"
                    : "Discount to FV"}
                </dt>
                <dd
                  className={cn(
                    "font-mono tabular-nums text-2xl font-semibold mt-0.5",
                    discountTone === "good"
                      ? "text-tone-good-fg"
                      : discountTone === "bad"
                        ? "text-rose-700"
                        : "text-ink",
                  )}
                >
                  {discountDisplay}
                </dd>
              </div>
            </dl>
          )}

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
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
              YieldIQ Score
            </span>
            <span className="font-mono tabular-nums text-base text-ink">
              {signals.score != null ? `${Math.round(signals.score)} / 100` : "—"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
              Grade
            </span>
            <span className="font-mono tabular-nums text-base text-ink">
              {capGrade(signals.grade, distress)}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
              Moat
            </span>
            <span className="text-[13px] text-ink">
              {signals.moat ?? "—"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
              Red flags
            </span>
            <span className="font-mono tabular-nums text-[13px] text-ink">
              {signals.redFlags != null ? signals.redFlags : "—"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
              Worry
            </span>
            <span className="text-[13px] text-ink">
              {worryRailLabel(signals.worry)}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
              Market cap
            </span>
            <span className="font-mono tabular-nums text-[13px] text-ink">
              {signals.marketCapCr != null ? formatMarketCapCr(signals.marketCapCr) : "—"}
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

function formatMarketCapCr(cr: number): string {
  if (cr >= 1e5) return `Rs.${(cr / 1e5).toFixed(2)} L Cr`
  if (cr >= 1e3) return `Rs.${(cr / 1e3).toFixed(1)}k Cr`
  return `Rs.${Math.round(cr)} Cr`
}
