"use client"

/**
 * EarningsImpactSimulator — T6.4 (engine-refinement roadmap).
 *
 * A pure-frontend what-if calculator. Users drag four sliders
 * (revenue beat, margin shift, growth shift, WACC shift) and see how
 * the DCF Fair Value would move under a linear Gordon-style sensitivity
 * approximation:
 *
 *   ΔFV / FV  ≈  (ΔRev / Rev)
 *              + ΔMargin (pp)
 *              + ΔTerminalGrowth (pp)
 *              − ΔWACC (pp)
 *
 * That's a first-order Taylor expansion around the engine's published
 * Fair Value — it captures direction and magnitude for small shifts.
 * Extreme inputs (e.g. ±30% revenue beat alongside ±100 bps WACC) are
 * intentionally not modelled non-linearly: the panel ships a one-line
 * caveat noting that. We never re-run the DCF here; this is a "feel for
 * the lever" tool, not a replacement engine.
 *
 * Mount site: collapsible section on the Valuation tab below
 * ValuationMethodsPanel. Default collapsed via <details>.
 *
 * SEBI lens: every visible string is descriptive ("Simulated DCF Fair
 * Value", "Linear sensitivity approximation only"). No imperative
 * vocabulary from scripts/check_sebi_words.py.
 */

import * as React from "react"

import { SummaryCard } from "@/components/cards"
import { cn, formatCurrency } from "@/lib/utils"

/* ─── props ────────────────────────────────────────────────────────── */

export interface EarningsImpactSimulatorProps {
  /** Bare or .NS-suffixed ticker. Used only inside the descriptive
   * helper sentence — not re-emitted anywhere SEBI-sensitive. */
  ticker: string
  /** Currency from `company.currency`. Forwarded to `formatCurrency`
   * so ADR cross-listings render in dollars rather than rupees. */
  currency?: string | null
  /** Current DCF Fair Value (₹ per share). The anchor of the
   * linearisation — every simulated FV is a multiplicative shift on
   * this number. */
  baseFairValue: number
  /** Engine WACC, in percentage points (e.g. `12.5` for 12.5%). Used
   * only as a captioned reference under the WACC slider; we don't need
   * the raw value in the math because the slider is a ΔWACC delta. */
  baseWacc?: number | null
  /** Engine terminal growth rate, in percent. Captioned under the
   * growth slider. */
  baseTerminalGrowth?: number | null
  /** Optional className for layout overrides at the call site. */
  className?: string
}

/* ─── slider ranges (typed) ────────────────────────────────────────── */

const REV_BEAT_MIN = -30
const REV_BEAT_MAX = 30
const REV_BEAT_STEP = 1

const MARGIN_BPS_MIN = -300
const MARGIN_BPS_MAX = 300
const MARGIN_BPS_STEP = 25

const GROWTH_PP_MIN = -3
const GROWTH_PP_MAX = 3
const GROWTH_PP_STEP = 0.25

const WACC_BPS_MIN = -100
const WACC_BPS_MAX = 100
const WACC_BPS_STEP = 10

/* ─── component ───────────────────────────────────────────────────── */

export default function EarningsImpactSimulator({
  ticker,
  currency,
  baseFairValue,
  baseWacc,
  baseTerminalGrowth,
  className,
}: EarningsImpactSimulatorProps) {
  const [revBeatPct, setRevBeatPct] = React.useState(0)
  const [marginShiftBps, setMarginShiftBps] = React.useState(0)
  const [growthShiftPp, setGrowthShiftPp] = React.useState(0)
  const [waccShiftBps, setWaccShiftBps] = React.useState(0)

  // Gordon-style linear sensitivity. Each lever is a unitless decimal
  // fraction added to a 1.0 base, then multiplied through the engine
  // Fair Value. ΔWACC enters with a negative sign because a higher
  // discount rate compresses FV.
  const adjustedFv = React.useMemo(() => {
    if (!Number.isFinite(baseFairValue) || baseFairValue <= 0) {
      return baseFairValue
    }
    const revImpact = revBeatPct / 100
    const marginImpact = marginShiftBps / 10000
    const growthImpact = growthShiftPp / 100
    const waccImpact = -(waccShiftBps / 10000)
    const cumulativeImpact =
      revImpact + marginImpact + growthImpact + waccImpact
    return baseFairValue * (1 + cumulativeImpact)
  }, [baseFairValue, revBeatPct, marginShiftBps, growthShiftPp, waccShiftBps])

  const baseFvSafe =
    Number.isFinite(baseFairValue) && baseFairValue > 0
      ? baseFairValue
      : null

  const deltaPct =
    baseFvSafe !== null ? (adjustedFv / baseFvSafe - 1) * 100 : 0

  // Direction class — emerald when simulated > base, rose when <,
  // muted when equal. We intentionally avoid verdict-band copy.
  const directionClass =
    !Number.isFinite(deltaPct) || Math.abs(deltaPct) < 0.05
      ? "text-ink"
      : deltaPct > 0
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-rose-600 dark:text-rose-400"

  const resetAll = () => {
    setRevBeatPct(0)
    setMarginShiftBps(0)
    setGrowthShiftPp(0)
    setWaccShiftBps(0)
  }

  const displayTicker = ticker?.replace(/\.NS$|\.BO$/i, "") || "this ticker"

  // Engine WACC + terminal-g captions — gracefully degrade when the
  // engine fields are null (data-limited tickers).
  const waccCaption =
    typeof baseWacc === "number" && Number.isFinite(baseWacc)
      ? `engine WACC: ${baseWacc.toFixed(1)}%`
      : null
  const growthCaption =
    typeof baseTerminalGrowth === "number" &&
    Number.isFinite(baseTerminalGrowth)
      ? `engine terminal growth: ${baseTerminalGrowth.toFixed(1)}%`
      : null

  return (
    <SummaryCard
      data-testid="earnings-impact-simulator"
      className={cn("gap-4", className)}
    >
      <details className="group">
        <summary
          className="flex cursor-pointer items-center justify-between gap-3 list-none select-none"
          data-testid="earnings-impact-simulator-toggle"
        >
          <div className="flex flex-col gap-0.5">
            <h2 className="text-lg font-bold text-ink">
              Earnings Impact Simulator
            </h2>
            <p className="text-xs text-caption leading-snug">
              What if {displayTicker} prints differently versus current
              engine assumptions? Drag the levers below.
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
          <div
            className="grid grid-cols-1 gap-4 md:grid-cols-2"
            data-testid="earnings-impact-sliders"
          >
            <SliderControl
              label="Revenue beat"
              testId="rev-beat-slider"
              value={revBeatPct}
              setValue={setRevBeatPct}
              min={REV_BEAT_MIN}
              max={REV_BEAT_MAX}
              step={REV_BEAT_STEP}
              unit="%"
              caption="vs current 12m revenue"
            />
            <SliderControl
              label="Margin shift"
              testId="margin-shift-slider"
              value={marginShiftBps}
              setValue={setMarginShiftBps}
              min={MARGIN_BPS_MIN}
              max={MARGIN_BPS_MAX}
              step={MARGIN_BPS_STEP}
              unit="bps"
              caption="EBIT margin delta"
            />
            <SliderControl
              label="Growth shift"
              testId="growth-shift-slider"
              value={growthShiftPp}
              setValue={setGrowthShiftPp}
              min={GROWTH_PP_MIN}
              max={GROWTH_PP_MAX}
              step={GROWTH_PP_STEP}
              unit="pp"
              caption={growthCaption ?? "terminal growth delta"}
              precision={2}
            />
            <SliderControl
              label="WACC shift"
              testId="wacc-shift-slider"
              value={waccShiftBps}
              setValue={setWaccShiftBps}
              min={WACC_BPS_MIN}
              max={WACC_BPS_MAX}
              step={WACC_BPS_STEP}
              unit="bps"
              caption={waccCaption ?? "discount rate delta"}
            />
          </div>

          <div
            className="grid grid-cols-1 gap-3 rounded-lg border border-border bg-surface p-3 md:grid-cols-2"
            data-testid="earnings-impact-output"
          >
            <div className="flex flex-col gap-0.5">
              <span className="text-[11px] uppercase tracking-wide text-caption">
                Base DCF Fair Value
              </span>
              <span
                className="text-lg font-bold text-ink num"
                data-testid="earnings-impact-base-fv"
              >
                {baseFvSafe !== null
                  ? formatCurrency(baseFvSafe, currency, ticker)
                  : "—"}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-[11px] uppercase tracking-wide text-caption">
                Simulated DCF Fair Value
              </span>
              <span
                className={cn("text-lg font-bold num", directionClass)}
                data-testid="earnings-impact-simulated-fv"
              >
                {baseFvSafe !== null
                  ? formatCurrency(adjustedFv, currency, ticker)
                  : "—"}
                {baseFvSafe !== null && (
                  <span className="ml-2 text-xs font-semibold">
                    ({deltaPct >= 0 ? "+" : ""}
                    {deltaPct.toFixed(1)}%)
                  </span>
                )}
              </span>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <p
              className="text-[11px] text-caption leading-snug max-w-[60ch]"
              data-testid="earnings-impact-caveat"
            >
              Linear sensitivity approximation only. Actual model
              interactions are non-linear at extreme inputs — re-run the
              full engine for production estimates.
            </p>
            <button
              type="button"
              onClick={resetAll}
              className="rounded border border-border bg-raised px-2 py-1 text-[11px] font-semibold text-ink hover:bg-surface"
              data-testid="earnings-impact-reset"
            >
              Reset levers
            </button>
          </div>
        </div>
      </details>
    </SummaryCard>
  )
}

/* ─── slider control ──────────────────────────────────────────────── */

interface SliderControlProps {
  label: string
  testId: string
  value: number
  setValue: (v: number) => void
  min: number
  max: number
  step: number
  unit: string
  caption?: string | null
  precision?: number
}

function SliderControl({
  label,
  testId,
  value,
  setValue,
  min,
  max,
  step,
  unit,
  caption,
  precision = 0,
}: SliderControlProps) {
  const inputId = React.useId()
  const displayValue =
    precision > 0 ? value.toFixed(precision) : value.toString()
  const sign = value > 0 ? "+" : ""

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label
          htmlFor={inputId}
          className="text-xs font-semibold text-ink"
        >
          {label}
        </label>
        <span
          className="text-xs font-bold text-ink num tabular-nums"
          data-testid={`${testId}-value`}
        >
          {sign}
          {displayValue}
          {unit}
        </span>
      </div>
      <input
        id={inputId}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => setValue(Number(e.target.value))}
        className="w-full accent-[var(--color-accent,#2563eb)]"
        data-testid={testId}
        aria-label={label}
      />
      {caption && (
        <span className="text-[10px] text-caption leading-tight">
          {caption}
        </span>
      )}
    </div>
  )
}
