"use client"

/**
 * InteractiveDcfPlayground — v_interactive_dcf_playground_2026_06_10.
 *
 * AlphaSpread-parity killer feature.
 *
 * Why this exists
 * ───────────────
 * AlphaSpread's defining moment is the interactive DCF + Reverse-DCF
 * playground: three sliders (WACC / Terminal Growth / FCF Growth) that
 * recompute Fair Value live, plus a Reverse-DCF mode that locks the
 * price and solves for the growth rate the market is implying.
 *
 * Every other competitor surface (M-Star research notes, Tickertape
 * scorecards, Trendlyne checklists) is static — text + a verdict pill.
 * The playground is the one surface where the user does the modelling
 * and sees the answer move. Adding it closes the largest visible
 * parity gap with one component.
 *
 * Math
 * ────
 * The 5-year + terminal DCF is a closed form:
 *
 *   FCF_t = FCF_0 * (1 + g)^t                        (years 1..5)
 *   PV(FCFs) = Σ_{t=1..5} FCF_t / (1 + WACC)^t
 *   TV = FCF_5 * (1 + g_T) / (WACC − g_T)
 *   PV(TV) = TV / (1 + WACC)^5
 *   FV/share = (PV(FCFs) + PV(TV) − debt + cash) / shares
 *
 * On the analysis payload we don't get FCF_0 directly, but we DO get
 * `valuation.pv_fcfs` and `valuation.pv_terminal` from the engine — so
 * we recover the equivalent FCF_0 from the engine's PV(FCFs) by
 * inverting the geometric series at the engine's published WACC and
 * growth rate. That gives us a base-year FCF anchored to whatever
 * cohort logic the engine ran (TTM, normalized, capex-adjusted), so
 * the sliders snap to the engine's actual numbers on first paint.
 *
 *   FCF_0 = PV(FCFs) / Σ_{t=1..5} ((1+g)/(1+w))^t
 *
 * Reverse-DCF
 * ───────────
 * Solve for `g` that makes equityFv(WACC, g, g_T, FCF_0) == price.
 * Bisection over g in [-15%, 35%] — the same bounds the backend
 * reverse_dcf service uses. Up to 60 iterations, 1e-4 tolerance.
 *
 * Bank / NBFC / insurance cohorts
 * ───────────────────────────────
 * For pure banks (per `isPureBank`) FCF is not meaningful — net
 * interest income, provisioning, and capital-adequacy cycles dominate.
 * Render a single caption pointing the user to the Composite
 * Composition breakdown above instead of a misleading FCF slider.
 *
 * SEBI vocabulary
 * ───────────────
 * Every caption describes the COMPUTATION ("Fair Value", "Implied FCF
 * growth", "Margin of Safety vs current price"). No verdict-class
 * vocabulary. No imperative language.
 */

import * as React from "react"

import { SummaryCard } from "@/components/cards"
import { isPureBank } from "@/lib/bankTickers"
import { cn, formatCurrency } from "@/lib/utils"

/* ─── public API types ────────────────────────────────────────────── */

/**
 * Engine anchors for the playground. Mirrors the subset of
 * `valuation` plus a small slice of `company` the playground reads.
 * Numbers arrive in the same units the analysis payload uses:
 *   - wacc, terminalGrowth, fcfGrowthRate: percentage points
 *     (e.g. 11.5 means 11.5%)
 *   - pvFcfs, pvTerminal, debt, cash: absolute INR
 *   - currentPrice, fairValue: INR/share
 *   - shares: absolute (e.g. 7.6e9 shares outstanding)
 */
export interface InteractiveDcfPlaygroundProps {
  ticker: string
  currency?: string | null
  /** Pure-bank cohort — when true, render the bank caption. */
  isBank?: boolean
  /** Engine-published Fair Value, INR/share. The anchor for MoS. */
  baseFairValue: number
  /** Engine-published price, INR/share. Locked in Reverse-DCF mode. */
  currentPrice: number
  /** Engine WACC, in percentage points. */
  baseWacc: number
  /** Engine terminal growth rate, in percentage points. */
  baseTerminalGrowth: number
  /** Engine 5y FCF growth rate, in percentage points. */
  baseFcfGrowthRate: number
  /** Sum of Σ_{t=1..5} discounted FCFs, absolute INR. */
  basePvFcfs: number
  /** Discounted terminal value, absolute INR. */
  basePvTerminal: number
  /** Net debt (debt − cash), absolute INR. The engine subtracts this
   * from enterprise value to get equity. Falls back to 0 when the
   * payload does not split debt/cash. */
  netDebt: number
  /** Shares outstanding, absolute. */
  shares: number
  /** Historical CAGRs for the reference panel (optional). */
  fcfGrowthHistoricalAvg?: number | null
  revenueCagr3y?: number | null
  revenueCagr5y?: number | null
  revenueCagr10y?: number | null
  className?: string
}

/* ─── slider ranges ───────────────────────────────────────────────── */

const WACC_MIN_PCT = 5
const WACC_MAX_PCT = 18
const WACC_STEP = 0.1

const TGR_MIN_PCT = 0
const TGR_MAX_PCT = 7
const TGR_STEP = 0.1

const GROWTH_MIN_PCT = -10
const GROWTH_MAX_PCT = 25
const GROWTH_STEP = 0.5

const WACC_TGR_BUFFER_PCT = 0.5 // WACC must exceed TGR by ≥0.5pp

const PROJECTION_YEARS = 5

const STORAGE_KEY = "yq:dcf-playground:scenarios"

/* ─── math primitives ─────────────────────────────────────────────── */

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v)
}

/**
 * Recover the implied base-year FCF from the engine's discounted-FCFs
 * sum, holding the engine's published WACC and growth rate constant.
 *
 *   PV(FCFs) = Σ_{t=1..5} FCF_0 * ((1+g)/(1+w))^t
 *           = FCF_0 * Σ_{t=1..5} r^t            where r = (1+g)/(1+w)
 *
 * If g == w the closed-form is FCF_0 * 5. If pvFcfs is non-positive
 * the playground falls back to deriving an FCF from the FV gap (last
 * resort — keeps the UI populated for legacy cached payloads).
 */
export function deriveBaseYearFcf(
  pvFcfs: number,
  waccPct: number,
  growthPct: number,
): number {
  if (!isFiniteNumber(pvFcfs) || pvFcfs <= 0) return 0
  const w = waccPct / 100
  const g = growthPct / 100
  if (Math.abs(w - g) < 1e-6) {
    return pvFcfs / PROJECTION_YEARS
  }
  const r = (1 + g) / (1 + w)
  let series = 0
  for (let t = 1; t <= PROJECTION_YEARS; t++) {
    series += Math.pow(r, t)
  }
  if (series <= 0) return 0
  return pvFcfs / series
}

/**
 * Pure-function DCF. Returns equity FV per share given fcf_0 and the
 * three sliders. Returns 0 when WACC ≤ terminalGrowth (caller checks
 * the clamp message before reading the value).
 */
export function dcfPerShare(
  fcf0: number,
  waccPct: number,
  growthPct: number,
  terminalGrowthPct: number,
  netDebt: number,
  shares: number,
): number {
  if (!isFiniteNumber(fcf0) || fcf0 <= 0) return 0
  if (!isFiniteNumber(shares) || shares <= 0) return 0
  const w = waccPct / 100
  const g = growthPct / 100
  const gT = terminalGrowthPct / 100
  if (w <= gT) return 0
  let pvFcfs = 0
  let fcf = fcf0
  for (let t = 1; t <= PROJECTION_YEARS; t++) {
    fcf = fcf0 * Math.pow(1 + g, t)
    pvFcfs += fcf / Math.pow(1 + w, t)
  }
  const fcf5 = fcf // last value from the loop
  const tv = (fcf5 * (1 + gT)) / (w - gT)
  const pvTv = tv / Math.pow(1 + w, PROJECTION_YEARS)
  const ev = pvFcfs + pvTv
  const equity = ev - (netDebt || 0)
  if (equity <= 0) return 0
  return equity / shares
}

/**
 * Bisect for the FCF growth rate (in percent) that makes
 * dcfPerShare(...) equal the supplied target price. Returns a tuple
 * (growthPct, converged). Bounds match the backend reverse-DCF
 * service: [-15%, 35%].
 */
export function solveImpliedGrowthPct(
  targetPrice: number,
  fcf0: number,
  waccPct: number,
  terminalGrowthPct: number,
  netDebt: number,
  shares: number,
): { growthPct: number; converged: boolean; pegged: "low" | "high" | null } {
  const LO = -15
  const HI = 35
  const f = (g: number) =>
    dcfPerShare(fcf0, waccPct, g, terminalGrowthPct, netDebt, shares)
  const fLo = f(LO)
  const fHi = f(HI)
  if (!isFiniteNumber(targetPrice) || targetPrice <= 0) {
    return { growthPct: 0, converged: false, pegged: null }
  }
  if (targetPrice <= fLo) {
    return { growthPct: LO, converged: false, pegged: "low" }
  }
  if (targetPrice >= fHi) {
    return { growthPct: HI, converged: false, pegged: "high" }
  }
  let a = LO
  let b = HI
  let mid = 0.5 * (a + b)
  for (let i = 0; i < 60; i++) {
    mid = 0.5 * (a + b)
    const fMid = f(mid)
    if (Math.abs(fMid - targetPrice) / Math.max(Math.abs(targetPrice), 1e-9) < 1e-4) {
      return { growthPct: mid, converged: true, pegged: null }
    }
    if (fMid < targetPrice) a = mid
    else b = mid
  }
  return { growthPct: mid, converged: false, pegged: null }
}

/* ─── scenario persistence ────────────────────────────────────────── */

export interface SavedScenario {
  name: string
  ticker: string
  waccPct: number
  terminalGrowthPct: number
  fcfGrowthPct: number
  savedAt: number
}

function readScenarios(ticker: string): SavedScenario[] {
  if (typeof window === "undefined") return []
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (s: SavedScenario) =>
        s &&
        typeof s.name === "string" &&
        s.ticker === ticker &&
        isFiniteNumber(s.waccPct) &&
        isFiniteNumber(s.terminalGrowthPct) &&
        isFiniteNumber(s.fcfGrowthPct),
    )
  } catch {
    return []
  }
}

function writeScenarios(scenarios: SavedScenario[]): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(scenarios))
  } catch {
    // localStorage quota / private mode — saving is optional.
  }
}

/* ─── component ───────────────────────────────────────────────────── */

export default function InteractiveDcfPlayground({
  ticker,
  currency,
  isBank,
  baseFairValue,
  currentPrice,
  baseWacc,
  baseTerminalGrowth,
  baseFcfGrowthRate,
  basePvFcfs,
  // basePvTerminal is accepted on the props bag for forward compat —
  // the live playground recomputes the terminal value directly from
  // FCF_5 / WACC / terminal growth so we don't read this default.
  basePvTerminal: _basePvTerminal,
  netDebt,
  shares,
  fcfGrowthHistoricalAvg,
  revenueCagr3y,
  revenueCagr5y,
  revenueCagr10y,
  className,
}: InteractiveDcfPlaygroundProps) {
  // ─── cohort gate ────────────────────────────────────────────────
  // Pure banks: render a single caption pointing back at the composite
  // breakdown above. We deliberately render SOMETHING so users who
  // followed the section anchor here aren't dropped into a void.
  const isBankCohort = isBank ?? isPureBank(ticker)

  // ─── inputs gate ────────────────────────────────────────────────
  // Derive the implied base-year FCF from the engine's PV(FCFs). When
  // the engine didn't populate pv_fcfs (legacy cache, data_limited),
  // hide the playground — the math has no anchor.
  const baseYearFcf = React.useMemo(() => {
    return deriveBaseYearFcf(basePvFcfs, baseWacc, baseFcfGrowthRate)
  }, [basePvFcfs, baseWacc, baseFcfGrowthRate])

  const hasInputs =
    isFiniteNumber(baseFairValue) &&
    baseFairValue > 0 &&
    isFiniteNumber(currentPrice) &&
    currentPrice > 0 &&
    isFiniteNumber(shares) &&
    shares > 0 &&
    baseYearFcf > 0

  // ─── slider state ───────────────────────────────────────────────
  const defaultWacc = Math.max(WACC_MIN_PCT, Math.min(WACC_MAX_PCT, baseWacc))
  const defaultTgr = Math.max(
    TGR_MIN_PCT,
    Math.min(TGR_MAX_PCT, baseTerminalGrowth),
  )
  const defaultGrowth = Math.max(
    GROWTH_MIN_PCT,
    Math.min(GROWTH_MAX_PCT, baseFcfGrowthRate),
  )

  const [waccPct, setWaccPct] = React.useState(defaultWacc)
  const [tgrPct, setTgrPct] = React.useState(defaultTgr)
  const [growthPct, setGrowthPct] = React.useState(defaultGrowth)
  const [mode, setMode] = React.useState<"forward" | "reverse">("forward")

  // ─── scenario persistence ───────────────────────────────────────
  const [scenarios, setScenarios] = React.useState<SavedScenario[]>([])
  const [scenarioName, setScenarioName] = React.useState("")
  React.useEffect(() => {
    setScenarios(readScenarios(ticker))
  }, [ticker])

  const saveScenario = () => {
    const trimmed = scenarioName.trim()
    if (!trimmed) return
    const entry: SavedScenario = {
      name: trimmed.slice(0, 40),
      ticker,
      waccPct,
      terminalGrowthPct: tgrPct,
      fcfGrowthPct: growthPct,
      savedAt: Date.now(),
    }
    // Replace existing scenario with same name to avoid duplicates,
    // preserve cross-ticker entries so the user's HDFCBANK scenarios
    // stay around when they save a TCS one.
    let crossTicker: SavedScenario[] = []
    if (typeof window !== "undefined") {
      try {
        const raw = window.localStorage.getItem(STORAGE_KEY)
        const parsed = raw ? JSON.parse(raw) : []
        if (Array.isArray(parsed)) {
          crossTicker = parsed.filter(
            (s: SavedScenario) =>
              s && typeof s === "object" && s.ticker !== ticker,
          )
        }
      } catch {
        crossTicker = []
      }
    }
    const existing = readScenarios(ticker).filter(
      (s) => s.name !== entry.name,
    )
    const next = [entry, ...existing].slice(0, 8)
    writeScenarios([...next, ...crossTicker])
    setScenarios(next)
    setScenarioName("")
  }

  const restoreScenario = (s: SavedScenario) => {
    setWaccPct(s.waccPct)
    setTgrPct(s.terminalGrowthPct)
    setGrowthPct(s.fcfGrowthPct)
  }

  const resetDefaults = () => {
    setWaccPct(defaultWacc)
    setTgrPct(defaultTgr)
    setGrowthPct(defaultGrowth)
  }

  // ─── live FV / MoS computation ──────────────────────────────────
  // WACC must exceed terminal growth by the buffer; otherwise the
  // terminal-value denominator collapses. We still render the slider
  // values but suppress the FV number and surface a clamp caption.
  const waccTgrClamp = waccPct <= tgrPct + WACC_TGR_BUFFER_PCT

  const liveFv = React.useMemo(() => {
    if (!hasInputs) return 0
    if (waccTgrClamp) return 0
    return dcfPerShare(
      baseYearFcf,
      waccPct,
      growthPct,
      tgrPct,
      netDebt,
      shares,
    )
  }, [
    hasInputs,
    waccTgrClamp,
    baseYearFcf,
    waccPct,
    growthPct,
    tgrPct,
    netDebt,
    shares,
  ])

  const liveMosPct = React.useMemo(() => {
    if (!isFiniteNumber(liveFv) || liveFv <= 0) return null
    if (!isFiniteNumber(currentPrice) || currentPrice <= 0) return null
    return ((liveFv - currentPrice) / currentPrice) * 100
  }, [liveFv, currentPrice])

  // ─── reverse-DCF computation ────────────────────────────────────
  const reverseSolution = React.useMemo(() => {
    if (mode !== "reverse" || !hasInputs) return null
    if (waccTgrClamp) return null
    return solveImpliedGrowthPct(
      currentPrice,
      baseYearFcf,
      waccPct,
      tgrPct,
      netDebt,
      shares,
    )
  }, [
    mode,
    hasInputs,
    waccTgrClamp,
    currentPrice,
    baseYearFcf,
    waccPct,
    tgrPct,
    netDebt,
    shares,
  ])

  // ─── projected FCF series for the mini chart ────────────────────
  const fcfSeries = React.useMemo(() => {
    if (!hasInputs) return []
    const g = mode === "reverse" && reverseSolution
      ? reverseSolution.growthPct / 100
      : growthPct / 100
    const out: { year: number; fcf: number }[] = []
    for (let t = 1; t <= PROJECTION_YEARS; t++) {
      out.push({ year: t, fcf: baseYearFcf * Math.pow(1 + g, t) })
    }
    return out
  }, [hasInputs, mode, reverseSolution, growthPct, baseYearFcf])

  // ─── render: bank cohort caption ────────────────────────────────
  if (isBankCohort) {
    return (
      <SummaryCard
        data-testid="interactive-dcf-playground-bank"
        className={cn("gap-3", className)}
      >
        <div className="flex flex-col gap-1">
          <h2 className="text-base font-bold text-ink">
            Interactive DCF Playground
          </h2>
          <p className="text-[12px] text-caption leading-snug">
            Free cash flow projections are not the primary lever for
            banks, NBFCs, and insurers — net interest income, provisioning,
            and capital adequacy dominate the valuation. The Composite
            Composition breakdown above shows the bank-appropriate
            estimators (residual income, P/B, deposit franchise) that
            drive the headline number for this ticker.
          </p>
        </div>
      </SummaryCard>
    )
  }

  // ─── render: missing inputs ─────────────────────────────────────
  if (!hasInputs) {
    return (
      <SummaryCard
        data-testid="interactive-dcf-playground-empty"
        className={cn("gap-3", className)}
      >
        <div className="flex flex-col gap-1">
          <h2 className="text-base font-bold text-ink">
            Interactive DCF Playground
          </h2>
          <p className="text-[12px] text-caption leading-snug">
            The playground needs an engine-published DCF anchor (Fair
            Value, WACC, terminal growth, base-year free cash flow). The
            data feed for this ticker hasn&rsquo;t populated all of the
            required fields. The Composite Composition panel above still
            shows the surviving estimators that drove the headline.
          </p>
        </div>
      </SummaryCard>
    )
  }

  // ─── render: main playground ────────────────────────────────────
  const liveFvDisplay = liveFv > 0
    ? formatCurrency(liveFv, currency ?? undefined, ticker)
    : "—"
  const priceDisplay = formatCurrency(currentPrice, currency ?? undefined, ticker)
  const baseFvDisplay = formatCurrency(
    baseFairValue,
    currency ?? undefined,
    ticker,
  )

  const mosTone =
    liveMosPct === null
      ? "text-caption"
      : liveMosPct >= 25
        ? "text-emerald-700 dark:text-emerald-300"
        : liveMosPct >= 0
          ? "text-ink"
          : "text-rose-700 dark:text-rose-300"

  // Bar chart geometry — derive max once so the bars share a scale.
  const fcfMax = Math.max(...fcfSeries.map((p) => p.fcf), 1)

  return (
    <SummaryCard
      data-testid="interactive-dcf-playground"
      className={cn("gap-4", className)}
    >
      <details
        className="group"
        data-testid="interactive-dcf-playground-details"
      >
        <summary
          className="flex cursor-pointer items-start justify-between gap-3 list-none [&::-webkit-details-marker]:hidden"
          data-testid="interactive-dcf-playground-summary"
        >
          <div className="flex flex-col gap-1 min-w-0">
            <h2 className="text-base font-bold text-ink">
              Interactive DCF Playground
            </h2>
            <p className="text-[12px] text-caption leading-snug">
              Drag WACC, terminal growth, and 5-year free cash flow growth
              to see how Fair Value moves. Engine defaults: WACC{" "}
              <span className="tabular-nums font-medium text-ink">
                {defaultWacc.toFixed(1)}%
              </span>{" "}
              · Terminal growth{" "}
              <span className="tabular-nums font-medium text-ink">
                {defaultTgr.toFixed(1)}%
              </span>{" "}
              · FCF growth{" "}
              <span className="tabular-nums font-medium text-ink">
                {defaultGrowth.toFixed(1)}%
              </span>{" "}
              → Fair Value{" "}
              <span className="tabular-nums font-medium text-ink">
                {baseFvDisplay}
              </span>
              .
            </p>
          </div>
          <span
            aria-hidden="true"
            className="shrink-0 text-caption text-xs group-open:rotate-180 transition-transform"
          >
            ▾
          </span>
        </summary>

        <div className="mt-4 flex flex-col gap-4">
          {/* mode toggle + reset */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div
              role="tablist"
              aria-label="Playground mode"
              className="inline-flex rounded-full border border-border bg-surface p-0.5 text-[11px]"
            >
              <button
                type="button"
                role="tab"
                aria-selected={mode === "forward"}
                data-testid="playground-mode-forward"
                onClick={() => setMode("forward")}
                className={cn(
                  "px-3 py-1 rounded-full transition",
                  mode === "forward"
                    ? "bg-bg text-ink shadow-sm"
                    : "text-caption hover:text-ink",
                )}
              >
                DCF
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "reverse"}
                data-testid="playground-mode-reverse"
                onClick={() => setMode("reverse")}
                className={cn(
                  "px-3 py-1 rounded-full transition",
                  mode === "reverse"
                    ? "bg-bg text-ink shadow-sm"
                    : "text-caption hover:text-ink",
                )}
              >
                Reverse-DCF
              </button>
            </div>
            <button
              type="button"
              data-testid="playground-reset"
              onClick={resetDefaults}
              className="text-[11px] text-caption hover:text-ink underline decoration-dotted underline-offset-2"
            >
              Reset to engine defaults
            </button>
          </div>

          {/* sliders + output two-column on >= md */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* sliders column */}
            <div className="flex flex-col gap-3">
              <SliderRow
                label="WACC"
                testId="slider-wacc"
                value={waccPct}
                min={WACC_MIN_PCT}
                max={WACC_MAX_PCT}
                step={WACC_STEP}
                unit="%"
                onChange={setWaccPct}
                hint={`Engine: ${defaultWacc.toFixed(1)}%`}
              />
              <SliderRow
                label="Terminal growth"
                testId="slider-tgr"
                value={tgrPct}
                min={TGR_MIN_PCT}
                max={TGR_MAX_PCT}
                step={TGR_STEP}
                unit="%"
                onChange={setTgrPct}
                hint={`Engine: ${defaultTgr.toFixed(1)}%`}
              />
              {mode === "forward" && (
                <SliderRow
                  label="FCF growth (5y)"
                  testId="slider-growth"
                  value={growthPct}
                  min={GROWTH_MIN_PCT}
                  max={GROWTH_MAX_PCT}
                  step={GROWTH_STEP}
                  unit="%"
                  onChange={setGrowthPct}
                  hint={`Engine: ${defaultGrowth.toFixed(1)}%`}
                />
              )}
              {waccTgrClamp && (
                <p
                  data-testid="playground-wacc-tgr-clamp"
                  className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
                >
                  WACC must exceed terminal growth by at least{" "}
                  {WACC_TGR_BUFFER_PCT.toFixed(1)} percentage points for
                  the terminal value to converge. Raise WACC or lower
                  terminal growth.
                </p>
              )}
            </div>

            {/* output column */}
            <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-3">
              {mode === "forward" ? (
                <>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.1em] text-caption">
                      Fair Value
                    </p>
                    <p
                      data-testid="playground-fv"
                      className="font-display text-2xl font-bold tabular-nums text-ink"
                    >
                      {liveFvDisplay}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.1em] text-caption">
                      Margin of Safety vs current price
                    </p>
                    <p
                      data-testid="playground-mos"
                      className={cn("text-sm font-semibold tabular-nums", mosTone)}
                    >
                      {liveMosPct === null
                        ? "—"
                        : `${liveMosPct >= 0 ? "+" : ""}${liveMosPct.toFixed(1)}%`}
                    </p>
                    <p className="text-[11px] text-caption mt-0.5">
                      Current price: {priceDisplay}
                    </p>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.1em] text-caption">
                      Locked price
                    </p>
                    <p className="font-display text-2xl font-bold tabular-nums text-ink">
                      {priceDisplay}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.1em] text-caption">
                      Implied FCF growth over {PROJECTION_YEARS} years
                    </p>
                    <p
                      data-testid="playground-reverse-growth"
                      className="text-sm font-semibold tabular-nums text-ink"
                    >
                      {reverseSolution === null
                        ? "—"
                        : `${reverseSolution.growthPct.toFixed(2)}%`}
                      {reverseSolution?.pegged === "high" && (
                        <span className="ml-1 text-[10px] uppercase tracking-[0.1em] text-amber-700 dark:text-amber-300">
                          {" "}
                          at upper bound
                        </span>
                      )}
                      {reverseSolution?.pegged === "low" && (
                        <span className="ml-1 text-[10px] uppercase tracking-[0.1em] text-amber-700 dark:text-amber-300">
                          {" "}
                          at lower bound
                        </span>
                      )}
                    </p>
                    <p className="text-[11px] text-caption mt-0.5">
                      This is the growth rate the current price embeds
                      under the WACC and terminal growth you set.
                    </p>
                  </div>
                  {(fcfGrowthHistoricalAvg != null ||
                    revenueCagr3y != null ||
                    revenueCagr5y != null ||
                    revenueCagr10y != null) && (
                    <div
                      data-testid="playground-historical-context"
                      className="border-t border-border pt-2 mt-1"
                    >
                      <p className="text-[10px] uppercase tracking-[0.1em] text-caption mb-1">
                        Historical reference
                      </p>
                      <ul className="text-[11px] text-body space-y-0.5">
                        {fcfGrowthHistoricalAvg != null && (
                          <li className="flex justify-between">
                            <span>FCF growth (engine baseline)</span>
                            <span className="tabular-nums">
                              {fcfGrowthHistoricalAvg.toFixed(1)}%
                            </span>
                          </li>
                        )}
                        {revenueCagr3y != null && (
                          <li className="flex justify-between">
                            <span>Revenue CAGR (3y)</span>
                            <span className="tabular-nums">
                              {revenueCagr3y.toFixed(1)}%
                            </span>
                          </li>
                        )}
                        {revenueCagr5y != null && (
                          <li className="flex justify-between">
                            <span>Revenue CAGR (5y)</span>
                            <span className="tabular-nums">
                              {revenueCagr5y.toFixed(1)}%
                            </span>
                          </li>
                        )}
                        {revenueCagr10y != null && (
                          <li className="flex justify-between">
                            <span>Revenue CAGR (10y)</span>
                            <span className="tabular-nums">
                              {revenueCagr10y.toFixed(1)}%
                            </span>
                          </li>
                        )}
                      </ul>
                    </div>
                  )}
                </>
              )}

              {/* projected FCF mini bar chart */}
              {fcfSeries.length > 0 && !waccTgrClamp && (
                <div
                  data-testid="playground-fcf-bars"
                  aria-label="Projected free cash flow over 5 years"
                >
                  <p className="text-[10px] uppercase tracking-[0.1em] text-caption mb-1">
                    Projected free cash flow
                  </p>
                  <div className="flex items-end gap-1 h-14">
                    {fcfSeries.map((p) => {
                      const heightPct = Math.max(
                        4,
                        Math.min(100, (p.fcf / fcfMax) * 100),
                      )
                      return (
                        <div
                          key={p.year}
                          className="flex-1 flex flex-col items-center gap-0.5"
                        >
                          <div
                            className="w-full rounded-t bg-brand/70"
                            style={{ height: `${heightPct}%` }}
                            data-testid={`playground-fcf-bar-${p.year}`}
                            data-fcf={p.fcf}
                          />
                          <span className="text-[9px] text-caption tabular-nums">
                            Y{p.year}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* scenarios */}
          <div className="flex flex-col gap-2 border-t border-border pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="text"
                aria-label="Scenario name"
                placeholder='Name this scenario (e.g. "Conservative")'
                value={scenarioName}
                onChange={(e) => setScenarioName(e.target.value)}
                data-testid="playground-scenario-input"
                className="flex-1 min-w-[180px] rounded-md border border-border bg-bg px-2 py-1 text-[12px] text-ink placeholder:text-caption focus:outline-none focus:ring-1 focus:ring-brand"
                maxLength={40}
              />
              <button
                type="button"
                data-testid="playground-save-scenario"
                onClick={saveScenario}
                disabled={!scenarioName.trim()}
                className="rounded-md border border-border bg-bg px-3 py-1 text-[12px] font-medium text-ink hover:bg-surface disabled:opacity-50 disabled:cursor-not-allowed transition"
              >
                Save scenario
              </button>
            </div>
            {scenarios.length > 0 && (
              <div
                data-testid="playground-scenario-chips"
                className="flex flex-wrap gap-1.5"
              >
                {scenarios.map((s) => (
                  <button
                    key={s.name}
                    type="button"
                    onClick={() => restoreScenario(s)}
                    data-testid={`playground-scenario-chip-${s.name}`}
                    className="rounded-full border border-border bg-bg px-2.5 py-0.5 text-[11px] text-ink hover:bg-surface transition"
                    title={`WACC ${s.waccPct.toFixed(1)}% · Terminal ${s.terminalGrowthPct.toFixed(1)}% · Growth ${s.fcfGrowthPct.toFixed(1)}%`}
                  >
                    {s.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          <p className="text-[11px] text-caption leading-snug">
            Playground math runs in your browser using the engine&rsquo;s
            published WACC, terminal growth, and discounted-FCF anchors.
            No round-trip required. The model is a 5-year explicit + Gordon
            terminal DCF; cohort-specific overrides (cyclical normalization,
            three-stage growth, bank residual income) are reflected in the
            engine&rsquo;s default slider positions, not in the slider math
            itself.
          </p>
        </div>
      </details>
    </SummaryCard>
  )
}

/* ─── slider sub-component ────────────────────────────────────────── */

interface SliderRowProps {
  label: string
  testId: string
  value: number
  min: number
  max: number
  step: number
  unit: string
  onChange: (next: number) => void
  hint?: string
}

function SliderRow({
  label,
  testId,
  value,
  min,
  max,
  step,
  unit,
  onChange,
  hint,
}: SliderRowProps) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <label
          htmlFor={`${testId}-input`}
          className="text-[12px] font-medium text-ink"
        >
          {label}
        </label>
        <span
          data-testid={`${testId}-value`}
          className="text-[12px] tabular-nums text-ink font-semibold"
        >
          {value.toFixed(1)}
          {unit}
        </span>
      </div>
      <input
        id={`${testId}-input`}
        type="range"
        data-testid={testId}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-2 accent-brand"
        aria-label={`${label} slider`}
      />
      <div className="flex justify-between text-[10px] text-caption tabular-nums">
        <span>
          {min.toFixed(0)}
          {unit}
        </span>
        {hint && <span>{hint}</span>}
        <span>
          {max.toFixed(0)}
          {unit}
        </span>
      </div>
    </div>
  )
}
