"use client"

/**
 * ImpliedAssumptionsCard — Implied-Assumptions extension (2026-06-10).
 *
 * AlphaSpread-style "what does the market expect at the current
 * price?" card. Sits on the Valuation tab beneath the headline Fair
 * Value figure and provides a quick read of the gap between the
 * market-implied growth and the company's trailing realized growth /
 * analyst consensus, plus a plausibility meter.
 *
 * Rendering rules
 * ───────────────
 *   * `implied == null`                → render nothing (self-hide).
 *     Backwards-compatible with legacy cached payloads predating the
 *     v_implied_assumptions_extension_2026_06_10 manifest entry.
 *   * `implied_revenue_cagr_pct` is required (numeric) for the headline
 *     value; the surrounding context lines self-hide per-field when the
 *     corresponding nullable value is absent.
 *
 * SEBI lens — every visible string is observational and describes the
 * MARKET'S IMPLIED ASSUMPTION, not an opinion. The card never
 * names a verdict; the plausibility chip is a label of the implied
 * number's distance from history, not a directional call on the stock.
 * Vocabulary lint owned by scripts/check_sebi_words.py.
 *
 * Dark mode native — every colored slot uses tone-* design tokens so
 * the card reads identically across both themes. Plausibility meter
 * background uses neutral / brand tokens; the fill colour is driven
 * by the score band (>=70 emerald, 30-69 amber, <30 rose).
 *
 * Layout — single card. Top row: headline + chip. Middle row: two
 * comparison stats side-by-side (Consensus vs Trailing). Bottom row:
 * plausibility meter with the score readout and a one-line caption.
 * Wraps at narrow widths so it fits inside the existing Valuation tab
 * column without horizontal scroll.
 */

import * as React from "react"

import { cn } from "@/lib/utils"

/** Mirrors the backend ImpliedAssumptionsResult JSON shape. */
export interface ImpliedAssumptionsPayload {
  implied_revenue_cagr_pct: number
  implied_terminal_growth_pct: number
  implied_margin_expansion_bps: number | null
  implied_wacc_pct: number | null
  consensus_revenue_cagr_pct: number | null
  growth_gap_pp: number | null
  market_expectation_label: string
  plausibility_score: number
  headline: string
}

export interface ImpliedAssumptionsCardProps {
  implied: ImpliedAssumptionsPayload | null | undefined
  /**
   * Trailing 3y revenue CAGR sourced from the Quality block — used to
   * show the "vs trailing N% (3y)" line. Optional: when null the line
   * self-hides and the card falls back to the consensus-only view.
   */
  trailingRevenueCagr?: number | null
  /** Optional className for layout-side adjustments by the page. */
  className?: string
}

type ToneSlot = "emerald" | "amber" | "rose" | "neutral"

const LABEL_TONE: Record<string, ToneSlot> = {
  modest: "emerald",
  moderate: "amber",
  aggressive: "rose",
  extreme: "rose",
}

const TONE_CHIP_CLASS: Record<ToneSlot, string> = {
  emerald:
    "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200",
  amber:
    "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200",
  rose:
    "border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200",
  neutral:
    "border-slate-200 bg-slate-50 text-slate-800 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-200",
}

const TONE_BAR_CLASS: Record<ToneSlot, string> = {
  emerald: "bg-emerald-500 dark:bg-emerald-400",
  amber: "bg-amber-500 dark:bg-amber-400",
  rose: "bg-rose-500 dark:bg-rose-400",
  neutral: "bg-slate-400 dark:bg-slate-500",
}

function plausibilityTone(score: number): ToneSlot {
  if (score >= 70) return "emerald"
  if (score >= 30) return "amber"
  return "rose"
}

function plausibilityCaption(score: number): string {
  // Observational copy only — describes WHERE the implied number sits
  // relative to history, never asserts a directional opinion.
  if (score >= 90) return "Implied growth is close to the company's trailing 3-year history."
  if (score >= 70) return "Implied growth is a touch above the company's trailing 3-year history."
  if (score >= 50) return "Implied growth sits meaningfully above the trailing 3-year history."
  if (score >= 30) return "Implied growth sits well above the trailing 3-year history."
  return "Implied growth is far above the company's trailing 3-year history."
}

function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return "—"
  return `${value.toFixed(digits)}%`
}

function fmtPp(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return "—"
  const sign = value >= 0 ? "+" : ""
  return `${sign}${value.toFixed(digits)}pp`
}

export default function ImpliedAssumptionsCard({
  implied,
  trailingRevenueCagr,
  className,
}: ImpliedAssumptionsCardProps) {
  if (implied == null) {
    return null
  }
  if (
    typeof implied.implied_revenue_cagr_pct !== "number" ||
    !Number.isFinite(implied.implied_revenue_cagr_pct)
  ) {
    return null
  }

  const tone: ToneSlot =
    LABEL_TONE[implied.market_expectation_label?.toLowerCase?.() ?? ""] ?? "neutral"
  const score = Math.max(
    0,
    Math.min(100, Math.round(implied.plausibility_score ?? 0)),
  )
  const meterTone = plausibilityTone(score)

  const trailingPct =
    trailingRevenueCagr != null && Number.isFinite(trailingRevenueCagr)
      ? trailingRevenueCagr * 100
      : null

  return (
    <section
      data-testid="implied-assumptions-card"
      aria-label="Market-implied assumptions"
      className={cn(
        "rounded-2xl border border-slate-200 bg-white p-5 shadow-sm",
        "dark:border-slate-800 dark:bg-slate-950/40",
        className,
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.18em] text-caption">
            Market expects
          </p>
          <h3
            data-testid="implied-assumptions-headline-value"
            className="mt-1 font-display text-2xl font-semibold leading-tight tabular-nums"
          >
            {fmtPct(implied.implied_revenue_cagr_pct)} revenue CAGR
          </h3>
        </div>
        <span
          data-testid="implied-assumptions-chip"
          className={cn(
            "inline-flex items-center rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-wide",
            TONE_CHIP_CLASS[tone],
          )}
        >
          {implied.market_expectation_label}
        </span>
      </header>

      <p
        data-testid="implied-assumptions-headline"
        className="mt-2 text-sm text-caption leading-snug"
      >
        {implied.headline}
      </p>

      <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/40">
          <dt className="text-[10px] uppercase tracking-wider text-caption">
            vs Analyst consensus
          </dt>
          <dd
            data-testid="implied-assumptions-consensus"
            className="mt-1 font-mono text-sm tabular-nums"
          >
            {implied.consensus_revenue_cagr_pct != null ? (
              <>
                {fmtPct(implied.consensus_revenue_cagr_pct)}{" "}
                <span className="text-caption">
                  ({fmtPp(implied.growth_gap_pp)} gap)
                </span>
              </>
            ) : (
              <span className="text-caption">No analyst coverage</span>
            )}
          </dd>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/40">
          <dt className="text-[10px] uppercase tracking-wider text-caption">
            vs Trailing 3-year CAGR
          </dt>
          <dd
            data-testid="implied-assumptions-trailing"
            className="mt-1 font-mono text-sm tabular-nums"
          >
            {trailingPct != null ? (
              <>
                {fmtPct(trailingPct)}{" "}
                <span className="text-caption">
                  ({fmtPp(implied.implied_revenue_cagr_pct - trailingPct)} gap)
                </span>
              </>
            ) : (
              <span className="text-caption">Insufficient history</span>
            )}
          </dd>
        </div>
      </dl>

      {/* Solver assumption echo — small print so the card stays self-
          describing. Margin-expansion bps and implied WACC are
          additive context; each self-hides when its source is null. */}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-caption">
        {implied.implied_wacc_pct != null && (
          <span data-testid="implied-assumptions-wacc">
            WACC {fmtPct(implied.implied_wacc_pct)}
          </span>
        )}
        {Number.isFinite(implied.implied_terminal_growth_pct) && (
          <span data-testid="implied-assumptions-terminal">
            Terminal g {fmtPct(implied.implied_terminal_growth_pct)}
          </span>
        )}
        {implied.implied_margin_expansion_bps != null && (
          <span data-testid="implied-assumptions-margin-bps">
            Margin gap {implied.implied_margin_expansion_bps >= 0 ? "+" : ""}
            {Math.round(implied.implied_margin_expansion_bps)} bps
          </span>
        )}
      </div>

      {/* Plausibility meter — observational, never directional. */}
      <div className="mt-4">
        <div className="flex items-center justify-between text-[11px] text-caption">
          <span className="uppercase tracking-wider">Plausibility</span>
          <span
            data-testid="implied-assumptions-score"
            className={cn(
              "font-mono tabular-nums",
              TONE_CHIP_CLASS[meterTone].split(" ")[2], // text color
            )}
          >
            {score} / 100
          </span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={score}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Plausibility of implied growth vs history"
          className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
        >
          <div
            data-testid="implied-assumptions-meter-fill"
            className={cn("h-full transition-all", TONE_BAR_CLASS[meterTone])}
            style={{ width: `${score}%` }}
          />
        </div>
        <p
          data-testid="implied-assumptions-caption"
          className="mt-1.5 text-[12px] text-caption leading-snug"
        >
          {plausibilityCaption(score)}
        </p>
      </div>
    </section>
  )
}
