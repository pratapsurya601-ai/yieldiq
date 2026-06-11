/**
 * ValuationMethodsPanel — T5.10 (engine-refinement roadmap, trust +
 * transparency play).
 *
 * Surfaces EVERY valuation estimate the YieldIQ engine has produced for
 * the current ticker — Composite IV, DCF, Peer Multiples, Wall Street
 * consensus, plus the Phase B additions (Three-stage DCF, DDM, EPV,
 * Liquidation, Probability-weighted) once those land in the payload.
 *
 * Design intent:
 *   - Single grid. Each row carries: label, value (₹), gap-vs-price
 *     percent, method tag (when present), one-line description, a
 *     semantic badge (primary / supporting / floor / consensus).
 *   - Render only methods whose `value` is non-null. The rest collapse
 *     into a `<details>` footnote so the reader knows the engine
 *     considered them but they did not apply.
 *   - Empty state when ZERO methods have a value (warming cache / fresh
 *     listing / data-limited ticker).
 *
 * Composition:
 *   - Pure RSC-safe (no client hooks, no `"use client"`) — the
 *     component reads pre-fetched payload data only.
 *   - Reuses PR-B `SummaryCard` for the outer surface and
 *     `MetricTooltip` for hover-explainers on each method tag so the
 *     visual idiom matches HonestHero / ValuationGrid / TransparencyStrip.
 *
 * SEBI lens:
 *   - All copy is descriptive. The gap-vs-price line reads as
 *     "MoS +24% vs current price" (when FV > CP) or "-12% vs current
 *     price" (when FV < CP). No imperative verbs from the banned-
 *     vocabulary list in scripts/check_sebi_words.py.
 *   - The "not applicable" footnotes explain WHY each method was
 *     skipped (e.g. "DDM needs payout >= 30% and a 5+ year dividend
 *     streak") without implying directionality.
 */

import * as React from "react"

import { SummaryCard } from "@/components/cards"
import MetricTooltip from "@/components/common/MetricTooltip"
import { cn, formatCurrency } from "@/lib/utils"
import type { AnalysisResponse } from "@/types/api"

type BadgeKind = "primary" | "supporting" | "floor" | "consensus"

interface MethodEntry {
  key: string
  label: string
  value: number | null
  method?: string | null
  description: string
  badge: BadgeKind
  applicable: boolean
  reasonIfNotApplicable?: string
}

export interface ValuationMethodsPanelProps {
  data: AnalysisResponse
  className?: string
}

/* ─── public API ───────────────────────────────────────────────────── */

export default function ValuationMethodsPanel({
  data,
  className,
}: ValuationMethodsPanelProps) {
  const methods = buildMethodEntries(data)
  const applicableMethods = methods.filter((m) => m.applicable)
  const skippedMethods = methods.filter((m) => !m.applicable)

  // Empty-state: ZERO applicable methods means the panel sits on a
  // warming-cache / fresh-listing payload. Skipped rows alone are not
  // enough to render the surface meaningfully.
  if (applicableMethods.length === 0) {
    return (
      <SummaryCard
        data-testid="valuation-methods-panel-empty"
        className={cn("gap-3", className)}
      >
        <h2 className="text-lg font-bold text-ink">
          Valuation methods
        </h2>
        <p className="text-sm text-caption">
          Valuation methods are still computing for this ticker. Check
          back shortly.
        </p>
      </SummaryCard>
    )
  }

  const currentPrice =
    typeof data.valuation?.current_price === "number" &&
    Number.isFinite(data.valuation.current_price) &&
    data.valuation.current_price > 0
      ? data.valuation.current_price
      : null

  const currency = data.company?.currency ?? "INR"
  const ticker = data.company?.ticker ?? data.ticker ?? null
  const displayTicker = ticker ?? "this ticker"

  return (
    <SummaryCard
      data-testid="valuation-methods-panel"
      className={cn("gap-4", className)}
    >
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-bold text-ink">
          How we value {displayTicker}
        </h2>
        <p className="text-xs text-caption leading-snug">
          YieldIQ surfaces every independent estimator the engine
          considered. Methods that produced a value are shown first;
          methods that did not apply for this ticker are listed below
          with the reason so you can see the full coverage instead of
          a silent gap.
        </p>
      </div>

      <div
        role="list"
        className="grid grid-cols-1 md:grid-cols-2 gap-3"
        data-testid="valuation-methods-grid"
      >
        {applicableMethods.map((entry) => (
          <MethodRow
            key={entry.key}
            entry={entry}
            currentPrice={currentPrice}
            currency={currency}
            ticker={ticker}
          />
        ))}
      </div>

      {skippedMethods.length > 0 && (
        <div
          className="rounded-lg border border-border bg-surface p-3 flex flex-col gap-2"
          data-testid="valuation-methods-skipped"
        >
          <p className="text-[11px] uppercase tracking-[0.15em] text-caption">
            Not applicable for {displayTicker}
          </p>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[12px] text-body">
            {skippedMethods.map((m) => (
              <li
                key={m.key}
                data-testid={`valuation-method-${m.key}-skipped`}
                className="leading-snug rounded-md border border-border bg-bg px-2.5 py-2"
              >
                <span className="font-semibold text-ink">{m.label}</span>
                <span className="text-caption">
                  {" "}
                  — {m.reasonIfNotApplicable ?? "Data not available for this ticker."}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </SummaryCard>
  )
}

/* ─── method-entry construction ────────────────────────────────────── */

function buildMethodEntries(data: AnalysisResponse): MethodEntry[] {
  const compositeValue = numericOrNull(data.composite_intrinsic_value)
  const dcfValue = numericOrNull(data.valuation?.fair_value)
  const multiplesValue = numericOrNull(data.multiples_based_fv)
  const wallStreetValue =
    numericOrNull(data.analyst_consensus?.price_target?.mean) ??
    numericOrNull(data.insights?.wall_street_avg_target)
  const threeStageValue = numericOrNull(data.three_stage_fv)
  const ddmValue = numericOrNull(data.ddm_fv)
  const epvValue = numericOrNull(data.epv_per_share)
  const liquidationValue = numericOrNull(data.liquidation_per_share)
  const replacementValue = numericOrNull(data.replacement_per_share)
  const probValue = numericOrNull(data.probability_weighted_fv)
  const sectorSpecificValue = numericOrNull(data.sector_specific_fv)

  // v_fix_phase_b_estimator_coverage_2026_06_10:
  // backend now writes ``*_reason`` strings whenever an estimator is
  // null. Prefer those — they carry the dynamic, ticker-aware
  // explanation (e.g. "Not applicable for banks — the franchise is
  // the deposit base, not the rebuildable asset base"). Fall back to
  // the static copy below when the backend hasn't surfaced one
  // (legacy cached payloads).
  return [
    {
      key: "composite",
      label: "Composite Intrinsic Value",
      value: compositeValue,
      method: data.composite_components?.method ?? null,
      description:
        "Weighted average of DCF, Peer Multiples, Wall Street consensus, plus the standalone Phase-B estimators — the headline figure on the hero.",
      badge: "primary",
      applicable: compositeValue !== null,
      reasonIfNotApplicable:
        "Composite is unavailable until at least one underlying estimator computes.",
    },
    {
      key: "dcf",
      label: "DCF Fair Value",
      value: dcfValue,
      method: data.valuation?.valuation_engine_used ?? null,
      description:
        "Two-stage discounted cash flow — projects FCF for 5 years then a terminal value at the long-run growth rate. For banks the engine substitutes a P/B residual-income closed form.",
      badge: "supporting",
      applicable: dcfValue !== null && dcfValue > 0,
      reasonIfNotApplicable:
        "Headline DCF could not converge on a defensible per-share value.",
    },
    {
      key: "multiples",
      label: "Peer Multiples",
      value: multiplesValue,
      method: data.multiples_method ?? null,
      description:
        "Re-prices the stock at the sector-median PE / PB / EV-EBITDA — what would the price be at peer-typical multiples.",
      badge: "supporting",
      applicable: multiplesValue !== null && multiplesValue > 0,
      reasonIfNotApplicable:
        "Peer cohort lacks the breadth or quality to anchor a defensible peer-median multiple.",
    },
    {
      key: "wall_street",
      label: "Wall Street Consensus",
      value: wallStreetValue,
      method: null,
      description:
        "Mean of published analyst 12-month price targets (Finnhub feed). Third-party reference, not a YieldIQ model output.",
      badge: "consensus",
      applicable: wallStreetValue !== null && wallStreetValue > 0,
      reasonIfNotApplicable:
        "Coverage feed does not carry any published analyst targets for this ticker.",
    },
    {
      key: "sector_specific",
      label: prettifySectorLabel(data.sector_specific_label) ?? "Sector-specific FV",
      value: sectorSpecificValue,
      method: data.sector_specific_label ?? null,
      description:
        "Per-cohort primary engine — bank residual income, NBFC ROA tree, insurance EV+VNB, telecom ARPU DCF, holdco SOTP, oil & gas SOTP, auto OEM cycle, cement utilization, steel cost curve, RE NAV, etc. Sized to the cohort's value driver rather than a generic DCF.",
      badge: "primary",
      applicable: sectorSpecificValue !== null && sectorSpecificValue > 0,
      reasonIfNotApplicable:
        "No dedicated sector engine routes for this ticker — composite uses the headline DCF + Multiples + Wall St scheme.",
    },
    {
      key: "three_stage",
      label: "Three-stage Growth DCF",
      value: threeStageValue,
      method: data.three_stage_method ?? null,
      description:
        "Explicit high-growth phase, then a linear fade, then terminal — Damodaran framework. Useful when growth normalises gradually rather than abruptly.",
      badge: "supporting",
      applicable: threeStageValue !== null && threeStageValue > 0,
      reasonIfNotApplicable:
        data.three_stage_reason ??
        "Three-stage DCF activates for tickers with a credible multi-phase growth profile and a positive base-year FCF.",
    },
    {
      key: "ddm",
      label: "Dividend Discount Model",
      value: ddmValue,
      method: data.ddm_method ?? null,
      description:
        "Gordon, two-stage, or H-model — values the stock as the present value of expected future dividends. Built for high-payout businesses.",
      badge: "supporting",
      applicable: ddmValue !== null && ddmValue > 0,
      reasonIfNotApplicable:
        data.ddm_reason ??
        "DDM needs payout >= 30% and a 5+ year dividend streak. Skipped for non-dividend or low-payout businesses.",
    },
    {
      key: "epv",
      label: "Earnings Power Value",
      value: epvValue,
      method: null,
      description:
        "Greenwald no-growth baseline — capitalises normalised earnings without crediting any future growth. The gap to DCF is the value attributable to growth.",
      badge: "supporting",
      applicable: epvValue !== null && epvValue > 0,
      reasonIfNotApplicable:
        data.epv_reason ??
        "EPV needs 5+ years of stable EBIT to normalise the earnings base. Skipped when the operating history is too short, too volatile, or routed to a dedicated framework (banks, insurers, REITs).",
    },
    {
      key: "liquidation",
      label: "Liquidation Floor",
      value: liquidationValue,
      method: null,
      description:
        "Graham-style asset recovery floor — what each share would receive if the business wound up its operations and sold its assets. A bottom anchor, not a fair value.",
      badge: "floor",
      applicable: liquidationValue !== null && liquidationValue > 0,
      reasonIfNotApplicable:
        data.liquidation_reason ??
        "Liquidation framework not meaningful for asset-light or financial businesses where balance-sheet assets do not represent recoverable value.",
    },
    {
      key: "replacement",
      label: "Replacement Value",
      value: replacementValue,
      method: data.replacement_method ?? null,
      description:
        "Tobin-Q-style rebuild cost — what it would cost to recreate this business from scratch at today's input prices. An asset-rebuild ceiling that anchors the upper bound on the asset frame.",
      badge: "floor",
      applicable: replacementValue !== null && replacementValue > 0,
      reasonIfNotApplicable:
        data.replacement_reason ??
        "Replacement-cost framework not meaningful for banks / NBFCs / insurers (capital and deposit franchise are the value, not the asset base) or for asset-light cohorts.",
    },
    {
      key: "probability_weighted",
      label: "Probability-weighted FV",
      value: probValue,
      method: data.probability_weighted_method ?? null,
      description:
        "Bull, base, and bear scenarios combined with calibrated probabilities — captures the full distribution of outcomes rather than a single point estimate.",
      badge: "supporting",
      applicable: probValue !== null && probValue > 0,
      reasonIfNotApplicable:
        data.probability_weighted_reason ??
        "Probability-weighted FV activates when the three scenarios are individually credible and have a defensible probability mix.",
    },
  ]
}

/**
 * Prettify the sector-engine label for display
 * ("bank_residual_income_deepened" -> "Bank Residual Income").
 * Returns null when the input is null so the caller can fall back to
 * the default label.
 */
function prettifySectorLabel(label: string | null | undefined): string | null {
  if (!label) return null
  const map: Record<string, string> = {
    bank_residual_income_deepened: "Bank Residual Income",
    holdco_sotp: "Holdco SOTP",
    nbfc_roa: "NBFC ROA Tree",
    insurance_ev_vnb: "Insurance EV + VNB",
    pharma_pipeline: "Pharma Pipeline rNPV",
    telecom_arpu: "Telecom ARPU DCF",
    oil_gas: "Oil & Gas SOTP",
    auto_oem_cycle: "Auto OEM Cycle",
    cement_utilization: "Cement Utilization",
    steel_cost_curve: "Steel Cost Curve",
    re_developer_nav: "Real Estate NAV",
    consumer_durables_wc: "Consumer Durables WC",
    media_subscriber_ltv: "Media Subscriber LTV",
    logistics_freight: "Logistics Freight",
  }
  if (label in map) return map[label]
  // Generic fallback — turn snake_case into Title Case.
  return label
    .split("_")
    .map((word) => (word.length === 0 ? word : word[0].toUpperCase() + word.slice(1)))
    .join(" ")
}

/* ─── single method row ────────────────────────────────────────────── */

interface MethodRowProps {
  entry: MethodEntry
  currentPrice: number | null
  currency: string
  ticker: string | null
}

function MethodRow({
  entry,
  currentPrice,
  currency,
  ticker,
}: MethodRowProps) {
  const palette = BADGE_PALETTE[entry.badge]
  const valueText =
    entry.value != null
      ? formatCurrency(entry.value, currency, ticker)
      : "—"
  const gap = computeGapPct(entry.value, currentPrice)
  const gapText = formatGap(gap)
  const gapTone = toneForGap(gap)
  const methodTag = entry.method ? prettifyMethodTag(entry.method) : null

  return (
    <div
      role="listitem"
      data-testid={`valuation-method-${entry.key}`}
      className={cn(
        "rounded-xl border bg-bg p-3 flex flex-col gap-2",
        palette.border,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-[0.15em] text-caption">
            {palette.kicker}
          </p>
          <p className="text-sm font-semibold text-ink leading-tight mt-0.5">
            {entry.label}
          </p>
        </div>
        <span
          aria-label={`${palette.kicker} method`}
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap",
            palette.badge,
          )}
        >
          {palette.kicker}
        </span>
      </div>

      <div className="flex items-baseline justify-between gap-2">
        <MetricTooltip
          label={entry.label}
          showLabel={false}
          title={entry.label}
          description={entry.description}
          ariaValueText={valueText}
          value={
            <span
              className={cn(
                "font-mono tabular-nums text-xl font-semibold",
                palette.value,
              )}
            >
              {valueText}
            </span>
          }
        />
        {gapText && (
          <span
            data-testid={`valuation-method-${entry.key}-gap`}
            className={cn(
              "font-mono tabular-nums text-[12px]",
              gapTone,
            )}
          >
            {gapText}
          </span>
        )}
      </div>

      <p className="text-[12px] text-body leading-snug">{entry.description}</p>

      {methodTag && (
        <p
          data-testid={`valuation-method-${entry.key}-method-tag`}
          className="text-[11px] text-caption"
        >
          Method: <span className="font-mono">{methodTag}</span>
        </p>
      )}
    </div>
  )
}

/* ─── helpers ──────────────────────────────────────────────────────── */

const BADGE_PALETTE: Record<
  BadgeKind,
  { kicker: string; border: string; badge: string; value: string }
> = {
  primary: {
    kicker: "Primary",
    border: "border-tone-info-bd dark:border-blue-900",
    badge:
      "bg-tone-info-bg text-tone-info-fg border-tone-info-bd dark:bg-blue-950/40 dark:text-blue-200 dark:border-blue-900",
    value: "text-ink",
  },
  supporting: {
    kicker: "Supporting",
    border: "border-border",
    badge:
      "bg-tone-neutral-bg text-slate-700 border-tone-neutral-bd dark:bg-slate-800/60 dark:text-slate-200 dark:border-slate-700",
    value: "text-ink",
  },
  floor: {
    kicker: "Floor",
    border: "border-amber-300 dark:border-amber-900",
    badge:
      "bg-tone-warn-bg text-amber-900 border-amber-300 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-900",
    value: "text-amber-900 dark:text-amber-200",
  },
  consensus: {
    kicker: "Consensus",
    border: "border-tone-good-bd dark:border-emerald-900",
    badge:
      "bg-tone-good-bg text-tone-good-fg border-tone-good-bd dark:bg-emerald-950/40 dark:text-emerald-200 dark:border-emerald-900",
    value: "text-ink",
  },
}

function numericOrNull(value: unknown): number | null {
  if (typeof value !== "number") return null
  if (!Number.isFinite(value)) return null
  return value
}

function computeGapPct(value: number | null, currentPrice: number | null): number | null {
  if (value == null || currentPrice == null) return null
  if (!Number.isFinite(value) || !Number.isFinite(currentPrice)) return null
  if (currentPrice <= 0) return null
  return ((value - currentPrice) / currentPrice) * 100
}

/**
 * Descriptive gap line. Positive values frame as "MoS +N% vs current
 * price" (the engine's estimate sits above current); negative values
 * read as "-N% vs current price". Descriptive only — never imperative.
 */
function formatGap(gap: number | null): string | null {
  if (gap == null || !Number.isFinite(gap)) return null
  const rounded = Math.round(gap * 10) / 10
  if (rounded >= 0) {
    return `MoS +${rounded.toFixed(1)}% vs current price`
  }
  return `${rounded.toFixed(1)}% vs current price`
}

function toneForGap(gap: number | null): string {
  if (gap == null || !Number.isFinite(gap)) return "text-caption"
  if (gap >= 0) return "text-emerald-700 dark:text-emerald-300"
  return "text-rose-700 dark:text-rose-300"
}

/**
 * Map of engine method tags to human-readable labels. The engine emits
 * snake_case identifiers (e.g. "bank_composite_2_method"); rendering
 * those raw — or with underscores merely stripped — looks like a
 * leaked internal token. The override table below covers every known
 * engine tag with a hand-tuned label; anything not in the table falls
 * back to title-cased word-split so a newly added tag still reads as
 * "Some New Method" rather than "some new method".
 */
const METHOD_LABELS: Record<string, string> = {
  // multiples_method values ("pe" | "pb" | "ev_ebitda") previously fell
  // through to the title-case fallback and rendered as "Pe" / "Pb" /
  // "Ev Ebitda" — raw-field jargon in a visible label. Hand-tuned:
  pe: "P/E multiple",
  pb: "P/B multiple",
  ev_ebitda: "EV/EBITDA multiple",
  bank_composite_2_method: "Bank Composite (2-method)",
  bank_composite_residual_multiples_analyst:
    "Bank Composite (Residual Income × Multiples × Wall St)",
  bank_composite_residual_multiples:
    "Bank Composite (Residual Income × Multiples)",
  bank_residual_income: "Bank — Residual Income",
  pb_residual_income: "P/B Residual Income",
  composite_dcf_multiples_analyst:
    "Composite (DCF × Multiples × Wall St)",
  composite_dcf_multiples: "Composite (DCF × Multiples)",
  composite_dcf_analyst: "Composite (DCF × Wall St)",
  composite_multiples_analyst: "Composite (Multiples × Wall St)",
  holdco_dcf_only: "Holdco — DCF only (SOTP pending)",
  dcf_only: "DCF only",
  multiples_only: "Multiples only",
  analyst_only: "Wall Street consensus only",
  three_scenario: "Three-scenario weighted",
  four_scenario: "Four-scenario weighted",
  unavailable: "Unavailable",
}

function toTitleCase(s: string): string {
  return s
    .split(" ")
    .map((w) => (w.length === 0 ? w : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ")
}

function prettifyMethodTag(method: string): string {
  const known = METHOD_LABELS[method]
  if (known) return known
  // Fallback: replace underscores with spaces and title-case so an
  // unmapped tag like "explicit_fade" reads as "Explicit Fade" rather
  // than "explicit fade".
  return toTitleCase(method.replace(/_/g, " "))
}
