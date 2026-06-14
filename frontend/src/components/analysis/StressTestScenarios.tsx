"use client"

/**
 * StressTestScenarios — historical-scenario what-if calculator.
 *
 * Pure-frontend companion to EarningsImpactSimulator. Where the simulator
 * lets users drag arbitrary levers, this panel applies *pre-baked
 * historical extreme regimes* (2008 GFC, 2020 pandemic, 2013 taper
 * tantrum) plus a free-form Custom slot. Three numbers come out the
 * other side:
 *
 *   Stressed price = currentPrice * sectorMultiplier(scenario, sector)
 *   Stressed FV    = baseFairValue * (1 + growthShockPp/100
 *                                       - waccShockBps/10000)
 *   Stressed MoS   = (stressedFv - stressedPrice) / stressedPrice * 100
 *
 * The sector-multiplier table is intentionally coarse and additive — a
 * single descriptive "what if the macro regime of 2008 recurred today?"
 * lens, not a per-company scenario engine. The caveat strip says so.
 *
 * Sector lookup falls through `normalizeSector` so callers can pass the
 * raw company.sector string (e.g. "Private Bank", "Banking", "IT
 * Services"). Sectors absent from a scenario fall back to a scenario-
 * specific default multiplier (the median sector shock for that crash).
 *
 * Mount site: Valuation tab on the analysis page, immediately below
 * `EarningsImpactSimulator`. Collapsible via <details>, default closed
 * so it doesn't dominate the tab on first paint.
 *
 * SEBI lens: every visible string is descriptive. No imperative
 * vocabulary from scripts/check_sebi_words.py. Words like "stressed",
 * "scenario", "historical", "extreme", "approximate" all pass.
 */

import * as React from "react"

import { SummaryCard } from "@/components/cards"
import { normalizeSector } from "@/lib/sector-taxonomy"
import { cn, computeTrueMos, formatCurrency, formatPct } from "@/lib/utils"

/* ─── scenario catalog ────────────────────────────────────────────── */

/**
 * Per-sector price multipliers reflect peak-to-trough drawdowns for
 * the matching crisis, sourced from Nifty sector index data. Numbers
 * are intentionally rounded to the nearest 5% — this is an order-of-
 * magnitude regime lens, not a per-day backtest replay.
 *
 * `defaultMultiplier` handles sectors not enumerated for a scenario
 * (e.g. Real Estate during taper tantrum). It's the rough median
 * shock across the enumerated sectors.
 */
interface StressScenario {
  id: string
  name: string
  description: string
  /** Optional — Custom scenario has no fixed multipliers. */
  multipliers?: Record<string, number>
  /** Fallback price multiplier when sector is unmapped. */
  defaultMultiplier?: number
  /** WACC shock in basis points (positive = higher discount rate). */
  waccShockBps: number
  /** Terminal-growth shock in percentage points. */
  growthShockPp: number
  /** Calendar year of the historical event — purely descriptive. */
  era: string
}

export const SCENARIOS: StressScenario[] = [
  {
    id: "2008_gfc",
    name: "2008 Global Financial Crisis",
    description:
      "Bank credit freeze, IT services demand collapse, metals -55% as commodity super-cycle ended. Nifty fell ~60% peak to trough.",
    multipliers: {
      Bank: 0.4,
      "Private Bank": 0.45,
      "PSU Bank": 0.35,
      "Financial Services": 0.5,
      "IT Services": 0.6,
      FMCG: 0.8,
      Metal: 0.45,
      Auto: 0.55,
      Energy: 0.5,
      Pharma: 0.75,
      "Real Estate": 0.3,
      "Consumer Durables": 0.55,
      Media: 0.5,
    },
    defaultMultiplier: 0.55,
    waccShockBps: 200,
    growthShockPp: -3,
    era: "Oct 2008",
  },
  {
    id: "2020_pandemic",
    name: "2020 COVID Pandemic",
    description:
      "Banks took credit-cost hit, hospitality and discretionary cratered, FMCG and pharma held up. Nifty fell ~38% in March 2020 then recovered.",
    multipliers: {
      Bank: 0.55,
      "Private Bank": 0.55,
      "PSU Bank": 0.45,
      "Financial Services": 0.5,
      "IT Services": 0.75,
      FMCG: 1.1,
      Pharma: 1.25,
      Metal: 0.65,
      Auto: 0.6,
      Energy: 0.6,
      "Real Estate": 0.55,
      "Consumer Durables": 0.6,
      Media: 0.5,
    },
    defaultMultiplier: 0.65,
    waccShockBps: 100,
    growthShockPp: -2,
    era: "Mar 2020",
  },
  {
    id: "2013_taper",
    name: "2013 Taper Tantrum",
    description:
      "FII outflows on Fed tapering hints, rupee fell 20%, FX-sensitive sectors compressed. IT services benefited from a softer INR.",
    multipliers: {
      Bank: 0.8,
      "Private Bank": 0.82,
      "PSU Bank": 0.7,
      "Financial Services": 0.78,
      "IT Services": 1.05,
      FMCG: 0.85,
      Pharma: 1.0,
      Metal: 0.85,
      Auto: 0.85,
      Energy: 0.9,
      "Real Estate": 0.75,
      "Consumer Durables": 0.85,
      Media: 0.85,
    },
    defaultMultiplier: 0.85,
    waccShockBps: 150,
    growthShockPp: -1,
    era: "Jun 2013",
  },
  {
    id: "custom",
    name: "Custom scenario",
    description:
      "Define a free-form price shock and WACC change. Useful when none of the historical regimes fit the macro question you have in mind.",
    waccShockBps: 0,
    growthShockPp: 0,
    era: "User-defined",
  },
]

/* ─── props ───────────────────────────────────────────────────────── */

export interface StressTestScenariosProps {
  /** Bare or .NS-suffixed ticker. Used inside descriptive helper text
   * and forwarded to `formatCurrency` for ADR cross-listings. */
  ticker: string
  /** Raw sector string from `company.sector`. Normalized internally
   * via `normalizeSector` before lookup in the multiplier table. */
  sector?: string | null
  /** Currency from `company.currency`. Forwarded to `formatCurrency`
   * so ADRs render in dollars rather than rupees. */
  currency?: string | null
  /** Current market price (₹ per share). Anchor for the stressed-
   * price calc. Required and must be > 0 for the panel to render
   * numeric outputs; otherwise we show a no-data state. */
  currentPrice: number
  /** Current DCF Fair Value (₹ per share). The anchor for the
   * stressed-FV calc. */
  baseFairValue: number
  /** Engine WACC, in percentage points. Captioned, not used in math. */
  baseWacc?: number | null
  /** Engine terminal growth rate, in percent. Captioned only. */
  baseGrowth?: number | null
  /** Optional className for layout overrides at the call site. */
  className?: string
}

/* ─── slider ranges for the custom scenario ───────────────────────── */

const CUSTOM_PRICE_PCT_MIN = -80
const CUSTOM_PRICE_PCT_MAX = 40
const CUSTOM_PRICE_PCT_STEP = 5

const CUSTOM_WACC_BPS_MIN = -200
const CUSTOM_WACC_BPS_MAX = 400
const CUSTOM_WACC_BPS_STEP = 25

const CUSTOM_GROWTH_PP_MIN = -5
const CUSTOM_GROWTH_PP_MAX = 2
const CUSTOM_GROWTH_PP_STEP = 0.5

/* ─── component ───────────────────────────────────────────────────── */

export default function StressTestScenarios({
  ticker,
  sector,
  currency,
  currentPrice,
  baseFairValue,
  baseWacc,
  baseGrowth,
  className,
}: StressTestScenariosProps) {
  const [activeId, setActiveId] = React.useState<string>("2008_gfc")
  const [customPricePct, setCustomPricePct] = React.useState(-30)
  const [customWaccBps, setCustomWaccBps] = React.useState(150)
  const [customGrowthPp, setCustomGrowthPp] = React.useState(-1)

  const activeScenario =
    SCENARIOS.find((s) => s.id === activeId) ?? SCENARIOS[0]

  const isCustom = activeScenario.id === "custom"
  const normalizedSector = normalizeSector(sector ?? "") || ""

  // Sector lookup tries normalized first, then raw, then default.
  const sectorMultiplier = React.useMemo(() => {
    if (isCustom) {
      return 1 + customPricePct / 100
    }
    const table = activeScenario.multipliers ?? {}
    const fromNormalized = table[normalizedSector]
    if (typeof fromNormalized === "number") {
      return fromNormalized
    }
    if (sector && typeof table[sector] === "number") {
      return table[sector]
    }
    return activeScenario.defaultMultiplier ?? 0.7
  }, [
    activeScenario,
    customPricePct,
    isCustom,
    normalizedSector,
    sector,
  ])

  const effectiveWaccBps = isCustom
    ? customWaccBps
    : activeScenario.waccShockBps
  const effectiveGrowthPp = isCustom
    ? customGrowthPp
    : activeScenario.growthShockPp

  const priceOk = Number.isFinite(currentPrice) && currentPrice > 0
  const fvOk = Number.isFinite(baseFairValue) && baseFairValue > 0

  const stressedPrice = priceOk ? currentPrice * sectorMultiplier : null

  // Linear FV sensitivity around the published Fair Value. Higher WACC
  // compresses; lower growth compresses.
  const stressedFv = React.useMemo(() => {
    if (!fvOk) {
      return null
    }
    const waccImpact = -(effectiveWaccBps / 10000)
    const growthImpact = effectiveGrowthPp / 100
    return baseFairValue * (1 + waccImpact + growthImpact)
  }, [baseFairValue, effectiveGrowthPp, effectiveWaccBps, fvOk])

  // stressedMosPct = implied upside % = (FV - price) / price * 100 (now secondary)
  const stressedMosPct =
    stressedPrice !== null &&
    stressedFv !== null &&
    stressedPrice > 0
      ? ((stressedFv - stressedPrice) / stressedPrice) * 100
      : null

  // stressedTrueMos = Buffett MoS = (1 - price/FV) * 100 (headline value)
  const stressedTrueMos =
    stressedFv !== null && stressedPrice !== null
      ? computeTrueMos(stressedFv, stressedPrice)
      : null

  const priceDeltaPct =
    stressedPrice !== null && priceOk
      ? (stressedPrice / currentPrice - 1) * 100
      : null

  const fvDeltaPct =
    stressedFv !== null && fvOk
      ? (stressedFv / baseFairValue - 1) * 100
      : null

  const displayTicker = ticker?.replace(/\.NS$|\.BO$/i, "") || "this ticker"

  const sectorCaption =
    normalizedSector && !isCustom
      ? `${normalizedSector} sector multiplier applied`
      : isCustom
      ? "User-defined price shock applied"
      : "Default cross-sector multiplier applied"

  return (
    <SummaryCard
      data-testid="stress-test-scenarios"
      className={cn("gap-4", className)}
    >
      <details className="group">
        <summary
          className="flex cursor-pointer items-center justify-between gap-3 list-none select-none"
          data-testid="stress-test-toggle"
        >
          <div className="flex flex-col gap-0.5">
            <h2 className="text-lg font-bold text-ink">
              Stress test scenarios
            </h2>
            <p className="text-xs text-caption leading-snug">
              Historical extreme regimes applied to {displayTicker}'s
              current price and Fair Value.
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
          <ScenarioSelector
            scenarios={SCENARIOS}
            activeId={activeId}
            onChange={setActiveId}
          />

          <div
            className="rounded-lg border border-border bg-surface p-3"
            data-testid="stress-test-scenario-detail"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-sm font-bold text-ink">
                {activeScenario.name}
              </span>
              <span className="text-[11px] uppercase tracking-wide text-caption">
                {activeScenario.era}
              </span>
            </div>
            <p
              className="mt-1 text-xs text-caption leading-snug"
              data-testid="stress-test-scenario-description"
            >
              {activeScenario.description}
            </p>
          </div>

          {isCustom ? (
            <div
              className="grid grid-cols-1 gap-4 md:grid-cols-3"
              data-testid="stress-test-custom-sliders"
            >
              <CustomSlider
                label="Price shock"
                testId="custom-price-slider"
                value={customPricePct}
                setValue={setCustomPricePct}
                min={CUSTOM_PRICE_PCT_MIN}
                max={CUSTOM_PRICE_PCT_MAX}
                step={CUSTOM_PRICE_PCT_STEP}
                unit="%"
                caption="vs current price"
              />
              <CustomSlider
                label="WACC shock"
                testId="custom-wacc-slider"
                value={customWaccBps}
                setValue={setCustomWaccBps}
                min={CUSTOM_WACC_BPS_MIN}
                max={CUSTOM_WACC_BPS_MAX}
                step={CUSTOM_WACC_BPS_STEP}
                unit="bps"
                caption={
                  typeof baseWacc === "number" && Number.isFinite(baseWacc)
                    ? `engine WACC: ${baseWacc.toFixed(1)}%`
                    : "discount-rate delta"
                }
              />
              <CustomSlider
                label="Growth shock"
                testId="custom-growth-slider"
                value={customGrowthPp}
                setValue={setCustomGrowthPp}
                min={CUSTOM_GROWTH_PP_MIN}
                max={CUSTOM_GROWTH_PP_MAX}
                step={CUSTOM_GROWTH_PP_STEP}
                unit="pp"
                precision={1}
                caption={
                  typeof baseGrowth === "number" &&
                  Number.isFinite(baseGrowth)
                    ? `engine terminal growth: ${baseGrowth.toFixed(1)}%`
                    : "terminal-growth delta"
                }
              />
            </div>
          ) : null}

          <div
            className="grid grid-cols-1 gap-3 rounded-lg border border-border bg-surface p-3 md:grid-cols-3"
            data-testid="stress-test-results"
          >
            <ResultCard
              label="Stressed price"
              testId="stress-test-price"
              value={
                stressedPrice !== null
                  ? formatCurrency(stressedPrice, currency, ticker)
                  : "—"
              }
              deltaPct={priceDeltaPct}
              caption={sectorCaption}
            />
            <ResultCard
              label="Stressed Fair Value"
              testId="stress-test-fv"
              value={
                stressedFv !== null
                  ? formatCurrency(stressedFv, currency, ticker)
                  : "—"
              }
              deltaPct={fvDeltaPct}
              caption={`+${effectiveWaccBps} bps WACC / ${
                effectiveGrowthPp >= 0 ? "+" : ""
              }${effectiveGrowthPp.toFixed(1)} pp growth`}
            />
            <ResultCard
              label="Stressed Margin of Safety"
              testId="stress-test-mos"
              value={
                stressedTrueMos !== null
                  ? `${stressedTrueMos >= 0 ? "+" : ""}${stressedTrueMos.toFixed(1)}%`
                  : stressedMosPct !== null
                  ? `${stressedMosPct >= 0 ? "+" : ""}${stressedMosPct.toFixed(1)}%`
                  : "—"
              }
              deltaPct={null}
              caption="(1 - price/FV) × 100"
              secondaryCaption={
                stressedMosPct !== null
                  ? `Implied upside: ${formatPct(stressedMosPct)}`
                  : undefined
              }
              valueColored
              rawValue={stressedTrueMos ?? stressedMosPct}
            />
          </div>

          <p
            className="text-[11px] text-caption leading-snug max-w-[72ch]"
            data-testid="stress-test-caveat"
          >
            Historical scenarios are approximate. Sector multipliers are
            order-of-magnitude regime estimates, not per-day backtest
            replays. Actual outcomes depend on company-specific factors
            (balance-sheet quality, cash runway, management response)
            that no scenario table captures.
          </p>
        </div>
      </details>
    </SummaryCard>
  )
}

/* ─── scenario selector ───────────────────────────────────────────── */

interface ScenarioSelectorProps {
  scenarios: StressScenario[]
  activeId: string
  onChange: (id: string) => void
}

function ScenarioSelector({
  scenarios,
  activeId,
  onChange,
}: ScenarioSelectorProps) {
  return (
    <div
      className="flex flex-wrap gap-2"
      role="tablist"
      aria-label="Stress test scenarios"
      data-testid="stress-test-selector"
    >
      {scenarios.map((s) => {
        const isActive = s.id === activeId
        return (
          <button
            key={s.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            data-testid={`stress-test-tab-${s.id}`}
            onClick={() => onChange(s.id)}
            className={cn(
              "rounded border px-2.5 py-1 text-xs font-semibold transition-colors",
              isActive
                ? "border-[var(--color-accent,#2563eb)] bg-[var(--color-accent,#2563eb)] text-white"
                : "border-border bg-raised text-ink hover:bg-surface",
            )}
          >
            {s.name}
          </button>
        )
      })}
    </div>
  )
}

/* ─── result card ─────────────────────────────────────────────────── */

interface ResultCardProps {
  label: string
  testId: string
  value: string
  deltaPct: number | null
  caption?: string
  /** Small secondary line below caption — used for the implied upside sub-label. */
  secondaryCaption?: string
  /** Color the value by sign — used for the MoS readout. */
  valueColored?: boolean
  /** Raw numeric for color decision when valueColored=true. */
  rawValue?: number | null
}

function ResultCard({
  label,
  testId,
  value,
  deltaPct,
  caption,
  secondaryCaption,
  valueColored,
  rawValue,
}: ResultCardProps) {
  const colorTarget = valueColored
    ? rawValue ?? null
    : deltaPct

  const directionClass =
    colorTarget === null ||
    !Number.isFinite(colorTarget) ||
    Math.abs(colorTarget) < 0.05
      ? "text-ink"
      : colorTarget > 0
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-rose-600 dark:text-rose-400"

  return (
    <div className="flex flex-col gap-0.5" data-testid={testId}>
      <span className="text-[11px] uppercase tracking-wide text-caption">
        {label}
      </span>
      <span
        className={cn("text-lg font-bold num tabular-nums", directionClass)}
        data-testid={`${testId}-value`}
      >
        {value}
        {!valueColored && deltaPct !== null && Number.isFinite(deltaPct) ? (
          <span
            className="ml-2 text-xs font-semibold"
            data-testid={`${testId}-delta`}
          >
            ({deltaPct >= 0 ? "+" : ""}
            {deltaPct.toFixed(1)}%)
          </span>
        ) : null}
      </span>
      {caption ? (
        <span className="text-[10px] text-caption leading-tight">
          {caption}
        </span>
      ) : null}
      {secondaryCaption ? (
        <span className="text-[10px] text-caption leading-tight">
          {secondaryCaption}
        </span>
      ) : null}
    </div>
  )
}

/* ─── custom slider ───────────────────────────────────────────────── */

interface CustomSliderProps {
  label: string
  testId: string
  value: number
  setValue: (v: number) => void
  min: number
  max: number
  step: number
  unit: string
  caption?: string
  precision?: number
}

function CustomSlider({
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
}: CustomSliderProps) {
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
      {caption ? (
        <span className="text-[10px] text-caption leading-tight">
          {caption}
        </span>
      ) : null}
    </div>
  )
}
