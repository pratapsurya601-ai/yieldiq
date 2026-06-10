"use client"

/**
 * TaxEfficiencyCalculator — Valuation-tab interactive tile.
 *
 * Goal: let a user feel the kink at 12 months. Indian listed equity is
 * taxed at 15% under STCG (<12 months held) and at 10% above the
 * ₹1L annual exemption under LTCG (≥12 months held). The difference
 * shows up most starkly in the post-tax effective return, and most
 * users do not internalise it until they see two columns side-by-side.
 *
 * Inputs:
 *   - Entry price per share (defaults to engine's `entryDefault`).
 *   - Exit price per share  (defaults to current price).
 *   - Quantity              (defaults to 100 — clean per-100-share math).
 *   - Holding period slider (0–36 months, step 1).
 *
 * Outputs (live, no submit button):
 *   - Pre-tax return % and ₹ on the assumed position.
 *   - Post-tax return %, tax owed ₹, effective tax rate.
 *   - STCG path and LTCG path always rendered side-by-side, with the
 *     active regime highlighted by the slider position.
 *   - Annualised post-tax return (only when ≥1 month held).
 *
 * SEBI lens: every visible string is descriptive. The component never
 * recommends an action — it surfaces the math of two tax regimes. The
 * inline footnote reminds users this is a tax-math illustration, not
 * tax advice. The regulator-banned vocabulary (b-u-y / s-e-l-l /
 * h-o-l-d / etc.) is asserted absent in __tests__/TaxEfficiencyCalculator.
 *
 * Mount site: Valuation tab, below ValuationMethodsPanel block.
 *
 * Math lives in `@/lib/tax-india` (pure helpers, also unit-tested) so
 * this component stays a thin presentation layer.
 */

import * as React from "react"

import { SummaryCard } from "@/components/cards"
import {
  computeCapitalGainsTax,
  preTaxReturn,
  postTaxReturn,
  annualiseReturn,
  formatRate,
  LTCG_THRESHOLD_MONTHS,
  LTCG_ANNUAL_EXEMPTION_INR,
  STCG_RATE,
  LTCG_RATE,
  CESS_RATE,
  type HoldingRegime,
} from "@/lib/tax-india"
import { cn, formatCurrency } from "@/lib/utils"

/* ─── props ─────────────────────────────────────────────────────────── */

export interface TaxEfficiencyCalculatorProps {
  /** Bare or .NS-suffixed ticker; only used in the descriptive header. */
  ticker: string
  /** Currency from `company.currency`; forwarded to formatCurrency. */
  currency?: string | null
  /**
   * Default entry price (₹). Falls back to the current price when not
   * supplied — most users want to model "what if I exit at current
   * price after N months from today's purchase".
   */
  entryDefault?: number | null
  /**
   * Default exit / current price (₹). Used both as the exit-input
   * default and as the entry default fallback.
   */
  currentPrice?: number | null
  /** Optional className for layout overrides at the call site. */
  className?: string
}

/* ─── slider config ─────────────────────────────────────────────────── */

const MONTHS_MIN = 0
const MONTHS_MAX = 36
const MONTHS_STEP = 1
const DEFAULT_MONTHS = 18

const QTY_MIN = 1
const QTY_MAX = 100_000

/* ─── helpers (component-local) ─────────────────────────────────────── */

function regimeLabel(regime: HoldingRegime): string {
  return regime === "stcg" ? "Short-term (STCG)" : "Long-term (LTCG)"
}

function regimeDescription(regime: HoldingRegime): string {
  return regime === "stcg"
    ? "Held under 12 months — 15% on the gain, plus 4% cess."
    : "Held 12 months or more — 10% on the gain above the ₹1L annual exemption, plus 4% cess."
}

function parsePositiveNumber(raw: string): number {
  const n = Number(raw.replace(/,/g, ""))
  return Number.isFinite(n) && n >= 0 ? n : 0
}

/* ─── component ─────────────────────────────────────────────────────── */

export default function TaxEfficiencyCalculator({
  ticker,
  currency,
  entryDefault,
  currentPrice,
  className,
}: TaxEfficiencyCalculatorProps) {
  const entrySeed = React.useMemo(() => {
    if (typeof entryDefault === "number" && entryDefault > 0) return entryDefault
    if (typeof currentPrice === "number" && currentPrice > 0) return currentPrice
    return 100
  }, [entryDefault, currentPrice])

  const exitSeed = React.useMemo(() => {
    if (typeof currentPrice === "number" && currentPrice > 0) return currentPrice
    return entrySeed * 1.2
  }, [currentPrice, entrySeed])

  const [entry, setEntry] = React.useState<string>(entrySeed.toFixed(2))
  const [exit, setExit] = React.useState<string>(exitSeed.toFixed(2))
  const [qty, setQty] = React.useState<string>("100")
  const [months, setMonths] = React.useState<number>(DEFAULT_MONTHS)

  // Reseed inputs when the underlying engine props change (e.g. user
  // navigates ticker → ticker via Next router). We compare against the
  // current value rather than uncritically overwriting so an in-flight
  // edit is preserved when the prop matches.
  React.useEffect(() => {
    setEntry((prev) =>
      Number(prev) === entrySeed ? prev : entrySeed.toFixed(2),
    )
    setExit((prev) =>
      Number(prev) === exitSeed ? prev : exitSeed.toFixed(2),
    )
  }, [entrySeed, exitSeed])

  const entryPrice = parsePositiveNumber(entry)
  const exitPrice = parsePositiveNumber(exit)
  const quantity = Math.max(QTY_MIN, Math.min(QTY_MAX, parsePositiveNumber(qty) || 1))

  const entryValue = entryPrice * quantity
  const exitValue = exitPrice * quantity

  // Two parallel computations: STCG (clamp months <12) and LTCG (clamp
  // months ≥12). The visible "active" regime tracks the slider; the
  // side-by-side card always shows BOTH so the user can compare the
  // bill at 11 months vs 12 months without dragging the slider back
  // and forth.
  const stcg = React.useMemo(
    () => computeCapitalGainsTax(entryValue, exitValue, 6),
    [entryValue, exitValue],
  )
  const ltcg = React.useMemo(
    () => computeCapitalGainsTax(entryValue, exitValue, 18),
    [entryValue, exitValue],
  )

  // Active regime — what the slider currently points at.
  const active = React.useMemo(
    () => computeCapitalGainsTax(entryValue, exitValue, months),
    [entryValue, exitValue, months],
  )

  const preR = preTaxReturn(entryValue, exitValue)
  const postR = postTaxReturn(entryValue, exitValue, months)
  const annualisedPost = annualiseReturn(postR, months)

  const displayTicker = ticker?.replace(/\.NS$|\.BO$/i, "") || "this position"

  const activeRegime = active.regime
  const isLtcg = activeRegime === "ltcg"
  const monthsToLtcg = Math.max(0, LTCG_THRESHOLD_MONTHS - months)

  // Direction class for the post-tax delta vs pre-tax.
  const taxDragPct = preR - postR // always ≥ 0 when there is a gain
  const dragClass =
    taxDragPct <= 0
      ? "text-ink"
      : "text-rose-600 dark:text-rose-400"

  const hasGain = active.gain > 0
  const hasLoss = active.gain < 0
  const hasInputs = entryPrice > 0 && exitPrice > 0

  return (
    <SummaryCard
      data-testid="tax-efficiency-calculator"
      className={cn("gap-4", className)}
    >
      <details className="group" open>
        <summary
          className="flex cursor-pointer items-center justify-between gap-3 list-none select-none"
          data-testid="tax-efficiency-toggle"
        >
          <div className="flex flex-col gap-0.5">
            <h2 className="text-lg font-bold text-ink">
              Tax efficiency by holding period
            </h2>
            <p className="text-xs text-caption leading-snug">
              See how the 12-month STCG-to-LTCG kink reshapes the
              post-tax return on {displayTicker}. Indian listed-equity
              rates.
            </p>
          </div>
          <span
            aria-hidden
            className="text-xs text-caption transition-transform group-open:rotate-180"
          >
            ▾
          </span>
        </summary>

        <div className="mt-4 flex flex-col gap-4">
          {/* ── Inputs row ─────────────────────────────────────────── */}
          <div
            className="grid grid-cols-1 gap-3 sm:grid-cols-3"
            data-testid="tax-efficiency-inputs"
          >
            <label className="flex flex-col gap-1 text-xs">
              <span className="uppercase tracking-wide text-caption">
                Entry price (₹/share)
              </span>
              <input
                data-testid="tax-entry-input"
                type="text"
                inputMode="decimal"
                value={entry}
                onChange={(e) => setEntry(e.target.value)}
                className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-indigo-500/40 num"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="uppercase tracking-wide text-caption">
                Exit price (₹/share)
              </span>
              <input
                data-testid="tax-exit-input"
                type="text"
                inputMode="decimal"
                value={exit}
                onChange={(e) => setExit(e.target.value)}
                className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-indigo-500/40 num"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="uppercase tracking-wide text-caption">
                Quantity
              </span>
              <input
                data-testid="tax-qty-input"
                type="text"
                inputMode="numeric"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-indigo-500/40 num"
              />
            </label>
          </div>

          {/* ── Holding-period slider ──────────────────────────────── */}
          <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[11px] uppercase tracking-wide text-caption">
                Holding period
              </span>
              <span
                className="text-sm font-semibold text-ink num"
                data-testid="tax-months-readout"
              >
                {months} {months === 1 ? "month" : "months"}
              </span>
            </div>
            <input
              data-testid="tax-months-slider"
              type="range"
              min={MONTHS_MIN}
              max={MONTHS_MAX}
              step={MONTHS_STEP}
              value={months}
              onChange={(e) => setMonths(Number(e.target.value))}
              className="w-full accent-indigo-600 dark:accent-indigo-400"
              aria-label="Holding period in months"
            />
            <div className="flex justify-between text-[10px] text-caption">
              <span>0 mo</span>
              <span className="font-medium">
                12 mo · LTCG threshold
              </span>
              <span>36 mo</span>
            </div>
            <div
              className={cn(
                "rounded-md border border-border bg-surface px-3 py-2 text-xs",
                isLtcg
                  ? "text-emerald-700 dark:text-emerald-300"
                  : "text-ink",
              )}
              data-testid="tax-regime-banner"
            >
              <span className="font-semibold">{regimeLabel(activeRegime)}</span>
              {": "}
              {regimeDescription(activeRegime)}
              {!isLtcg && monthsToLtcg > 0 ? (
                <>
                  {" "}
                  <span className="text-caption">
                    ({monthsToLtcg} more {monthsToLtcg === 1 ? "month" : "months"} until LTCG.)
                  </span>
                </>
              ) : null}
            </div>
          </div>

          {/* ── Pre-tax / post-tax headline ────────────────────────── */}
          <div
            className="grid grid-cols-1 gap-3 rounded-lg border border-border bg-surface p-3 sm:grid-cols-3"
            data-testid="tax-efficiency-headline"
          >
            <MetricBlock
              label="Pre-tax return"
              value={hasInputs ? formatRate(preR) : "—"}
              detail={hasInputs ? formatCurrency(active.gain, currency, ticker) : null}
              testId="tax-pretax-return"
            />
            <MetricBlock
              label="Post-tax return"
              value={hasInputs ? formatRate(postR) : "—"}
              detail={
                hasInputs
                  ? formatCurrency(active.netGain, currency, ticker)
                  : null
              }
              valueClassName={dragClass}
              testId="tax-posttax-return"
            />
            <MetricBlock
              label={
                months > 0
                  ? "Post-tax CAGR (annualised)"
                  : "Post-tax CAGR"
              }
              value={
                hasInputs && months > 0 ? formatRate(annualisedPost) : "—"
              }
              detail={
                hasInputs && months > 0
                  ? `over ${months} ${months === 1 ? "month" : "months"}`
                  : "set holding period above zero"
              }
              testId="tax-annualised-post"
            />
          </div>

          {/* ── Side-by-side STCG vs LTCG ──────────────────────────── */}
          <div
            className="grid grid-cols-1 gap-3 sm:grid-cols-2"
            data-testid="tax-side-by-side"
          >
            <RegimeCard
              regime="stcg"
              isActive={!isLtcg}
              entryValue={entryValue}
              exitValue={exitValue}
              ticker={ticker}
              currency={currency}
              breakdown={stcg}
            />
            <RegimeCard
              regime="ltcg"
              isActive={isLtcg}
              entryValue={entryValue}
              exitValue={exitValue}
              ticker={ticker}
              currency={currency}
              breakdown={ltcg}
            />
          </div>

          {hasLoss ? (
            <p
              className="text-xs text-caption"
              data-testid="tax-loss-note"
            >
              Capital loss — no tax payable. Losses may offset other
              capital gains under separate set-off and carry-forward
              rules; that allocation lives outside this calculator.
            </p>
          ) : null}

          {/* ── Methodology footnote ───────────────────────────────── */}
          <p
            className="text-[11px] leading-snug text-caption"
            data-testid="tax-efficiency-footnote"
          >
            Illustration only — assumes listed equity / equity-oriented
            mutual fund taxation under current Indian rules: {(STCG_RATE * 100).toFixed(0)}% STCG,{" "}
            {(LTCG_RATE * 100).toFixed(0)}% LTCG above ₹
            {(LTCG_ANNUAL_EXEMPTION_INR / 1000).toFixed(0)}k annual
            exemption, plus {(CESS_RATE * 100).toFixed(0)}% cess on tax.
            Surcharge tiers, slab-rate items, and per-portfolio
            exemption allocation are not modelled. Not tax advice;
            consult a qualified professional for your situation.
          </p>
        </div>
      </details>
    </SummaryCard>
  )
}

/* ─── sub-components ────────────────────────────────────────────────── */

interface MetricBlockProps {
  label: string
  value: string
  detail?: string | null
  valueClassName?: string
  testId?: string
}

function MetricBlock({ label, value, detail, valueClassName, testId }: MetricBlockProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] uppercase tracking-wide text-caption">
        {label}
      </span>
      <span
        className={cn("text-lg font-bold text-ink num", valueClassName)}
        data-testid={testId}
      >
        {value}
      </span>
      {detail ? (
        <span className="text-[11px] text-caption num">{detail}</span>
      ) : null}
    </div>
  )
}

interface RegimeCardProps {
  regime: HoldingRegime
  isActive: boolean
  entryValue: number
  exitValue: number
  ticker: string
  currency?: string | null
  breakdown: ReturnType<typeof computeCapitalGainsTax>
}

function RegimeCard({
  regime,
  isActive,
  entryValue,
  ticker,
  currency,
  breakdown,
}: RegimeCardProps) {
  const hasInputs = entryValue > 0
  const effective = breakdown.gain > 0 ? breakdown.effectiveRate : 0
  const postR = entryValue > 0 ? breakdown.netGain / entryValue : 0

  return (
    <div
      data-testid={`tax-regime-card-${regime}`}
      data-active={isActive ? "true" : "false"}
      className={cn(
        "flex flex-col gap-2 rounded-lg border bg-surface p-3 transition-colors",
        isActive
          ? "border-indigo-500/60 ring-1 ring-indigo-500/20"
          : "border-border opacity-90",
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-ink">
          {regimeLabel(regime)}
        </span>
        {isActive ? (
          <span className="text-[10px] font-semibold uppercase tracking-wide text-indigo-600 dark:text-indigo-400">
            active
          </span>
        ) : null}
      </div>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <dt className="text-caption">Tax owed</dt>
        <dd
          className="text-right font-semibold text-ink num"
          data-testid={`tax-${regime}-owed`}
        >
          {hasInputs ? formatCurrency(breakdown.totalTax, currency, ticker) : "—"}
        </dd>

        <dt className="text-caption">Effective rate on gain</dt>
        <dd
          className="text-right font-semibold text-ink num"
          data-testid={`tax-${regime}-eff`}
        >
          {hasInputs && breakdown.gain > 0 ? formatRate(effective) : "—"}
        </dd>

        <dt className="text-caption">Net proceeds</dt>
        <dd
          className="text-right font-semibold text-ink num"
          data-testid={`tax-${regime}-net`}
        >
          {hasInputs
            ? formatCurrency(entryValue + breakdown.netGain, currency, ticker)
            : "—"}
        </dd>

        <dt className="text-caption">Post-tax return</dt>
        <dd
          className="text-right font-semibold text-ink num"
          data-testid={`tax-${regime}-post`}
        >
          {hasInputs ? formatRate(postR) : "—"}
        </dd>
      </dl>
    </div>
  )
}
