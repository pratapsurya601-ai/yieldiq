"use client"

/**
 * ReverseDcfPanel — "what is the market pricing in?"
 *
 * Reads /api/v1/public/reverse-dcf/{ticker} (anonymous-accessible).
 * The endpoint returns the implied FCF growth + implied FCF margin
 * the current price embeds, plus a 3-point iso-FV curve and a plain-
 * English summary. When the backend returns null (loss-makers, data-
 * limited tickers, cache miss) the component renders nothing — this
 * is purely additive UI sitting below the scenario card.
 *
 * Day-87: wire the three new fields shipped by Day-76 backend:
 *   • applicable=false + category=bank_like → small "not applicable"
 *     card instead of hiding the panel.
 *   • growth_off_scale=true → headline becomes a >= / <= bound with
 *     an amber caveat note (summary text is already bound-qualified
 *     server-side; we surface it verbatim).
 *
 * No reuse from the existing /stocks/[ticker]/reverse-dcf page (which
 * hits the older authed endpoint with a different shape) — that path
 * is verdict-centric, this panel is implied-axis-centric.
 */

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"

// Mirror of backend models/forecaster.py constants. Kept in sync manually
// (constants haven't changed in 18 months and any change would require a
// CACHE_VERSION bump which is a coordinated release). If they drift the
// slider's implied-growth read will diverge from the static headline by
// at most ~0.5pp at extreme settings — visible but not catastrophic.
const TERMINAL_FADE_G = 0.04
const FADE_K = 0.25

function expFade(t: number, g0: number, gT: number): number {
  return gT + (g0 - gT) * Math.exp(-FADE_K * t)
}

// Two-stage faded DCF, equity-per-share. Direct port of
// reverse_dcf_service._dcf_per_share so the slider's iso-curve is
// directly comparable to the static summary the backend ships.
function dcfPerShare(
  fcfBase: number,
  growthRate: number,
  wacc: number,
  terminalG: number,
  years: number,
  totalDebt: number,
  totalCash: number,
  shares: number,
): number {
  if (!(fcfBase > 0) || !(shares > 0)) return 0
  if (wacc <= terminalG) return 0
  let fcf = fcfBase
  let pv = 0
  let last = fcf
  for (let t = 1; t <= years; t++) {
    let g = expFade(t, growthRate, terminalG)
    if (g < -0.15) g = -0.15
    if (g > 0.35) g = 0.35
    fcf = fcf * (1 + g)
    pv += fcf / Math.pow(1 + wacc, t)
    last = fcf
  }
  const tv = (last * (1 + terminalG)) / (wacc - terminalG)
  const pvTv = tv / Math.pow(1 + wacc, years)
  const ev = pv + pvTv
  const equity = ev - (totalDebt || 0) + (totalCash || 0)
  if (equity <= 0) return 0
  return equity / shares
}

// Bisect for the FCF growth rate that makes dcfPerShare === targetPrice,
// holding margin (and therefore fcfBase) fixed. Mirrors
// reverse_dcf_service._binary_search on growth.
function solveImpliedGrowth(
  targetPrice: number,
  fcfBase: number,
  wacc: number,
  terminalG: number,
  years: number,
  totalDebt: number,
  totalCash: number,
  shares: number,
): { growth: number; converged: boolean; pegged: "high" | "low" | null } {
  const LO = -0.05
  const HI = 0.5
  const f = (g: number) =>
    dcfPerShare(fcfBase, g, wacc, terminalG, years, totalDebt, totalCash, shares)
  const fLo = f(LO)
  const fHi = f(HI)
  if (targetPrice <= fLo) return { growth: LO, converged: false, pegged: "low" }
  if (targetPrice >= fHi) return { growth: HI, converged: false, pegged: "high" }
  let a = LO
  let b = HI
  let mid = 0.5 * (a + b)
  for (let i = 0; i < 80; i++) {
    mid = 0.5 * (a + b)
    const fMid = f(mid)
    if (Math.abs(fMid - targetPrice) / Math.max(Math.abs(targetPrice), 1e-9) < 1e-3) {
      return { growth: mid, converged: true, pegged: null }
    }
    if (fMid < targetPrice) a = mid
    else b = mid
  }
  return { growth: mid, converged: false, pegged: null }
}

// Extract trailing 5y revenue CAGR from sanity_check_lines[0]. The
// backend formats it as "trailing 5y revenue CAGR X.X%" and we surface
// that as a side-by-side comparator on the slider readout.
function parseTrailing5yCagr(lines: string[] | undefined | null): number | null {
  if (!lines || lines.length === 0) return null
  for (const line of lines) {
    const m = line.match(/trailing 5y revenue CAGR\s+(-?\d+(?:\.\d+)?)%/i)
    if (m) {
      const pct = parseFloat(m[1])
      if (Number.isFinite(pct)) return pct / 100
    }
  }
  return null
}

interface IsoFvPoint {
  growth: number
  margin: number
}

interface ReverseDcfInputs {
  current_price: number
  wacc: number
  terminal_g: number
  current_fcf: number
  current_margin: number
  current_revenue: number
  consensus_growth: number
  total_debt: number
  total_cash: number
  shares: number
  years: number
}

interface ReverseDcfPayload {
  ticker: string
  implied_growth_pct: number
  implied_margin_pct: number
  iso_fv_curve: IsoFvPoint[]
  current_market_implied_summary: string
  sanity_check_lines: string[]
  converged: boolean
  inputs: ReverseDcfInputs
  // Day-87: Day-76 backend additions ---------------------------------
  applicable?: boolean
  reason?: string
  category?: string
  growth_off_scale?: boolean
  growth_pegged_high?: boolean
  growth_pegged_low?: boolean
}

async function fetchReverseDcf(ticker: string): Promise<ReverseDcfPayload | null> {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  try {
    const res = await fetch(`${base}/api/v1/public/reverse-dcf/${ticker}`, {
      next: { revalidate: 600 },
    })
    if (!res.ok) return null
    const data = await res.json()
    if (!data || typeof data !== "object") return null
    // Day-87: accept the bank-skip payload shape (no implied_growth_pct).
    if (data.applicable === false) {
      return data as ReverseDcfPayload
    }
    if (!("implied_growth_pct" in data)) {
      return null
    }
    return data as ReverseDcfPayload
  } catch {
    return null
  }
}

function formatPct(decimal: number, digits = 1): string {
  if (!Number.isFinite(decimal)) return "—"
  return `${(decimal * 100).toFixed(digits)}%`
}

interface Props {
  ticker: string
}

export default function ReverseDcfPanel({ ticker }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["public-reverse-dcf", ticker],
    queryFn: () => fetchReverseDcf(ticker),
    enabled: !!ticker,
    staleTime: 10 * 60 * 1000,
    retry: 1,
  })

  if (isLoading || !data) {
    // Still hide on null/error — only the bank-skip payload renders.
    return null
  }

  // Day-87: bank-skip card. Banks / NBFCs / insurers do not admit an
  // FCF-based reverse-DCF — Day-76 returns a structured non-applicable
  // payload and we surface a small explanatory card so the absence is
  // legible rather than mysteriously missing.
  if (data.applicable === false) {
    return (
      <section
        aria-label="Reverse DCF — not applicable"
        className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
      >
        <header className="mb-1">
          <h2 className="text-sm font-semibold text-ink tracking-tight uppercase">
            Reverse-DCF
          </h2>
        </header>
        <p className="text-caption text-xs leading-relaxed">
          <span className="font-bold text-ink">Not applicable for banks.</span>{" "}
          Banks, NBFCs and insurers use ROE / RoA / NIM instead of FCF-based
          valuation. See the Quality panel for those metrics.
        </p>
      </section>
    )
  }

  const {
    implied_growth_pct: impliedG,
    implied_margin_pct: impliedM,
    iso_fv_curve: iso,
    current_market_implied_summary: summary,
    sanity_check_lines: sanity,
    inputs,
    growth_off_scale: offScale,
    growth_pegged_high: peggedHigh,
    growth_pegged_low: peggedLow,
  } = data

  // Day-87: off-scale headline. When the bisector pegs at the search
  // boundary we surface the number as a bound (>= / <=) plus a short
  // caveat. The backend `summary` field is already bound-qualified so
  // we render it verbatim and tag it with the amber note below.
  const offScalePrefix = peggedHigh ? "≥" : peggedLow ? "≤" : null
  const offScaleCaveat = peggedHigh
    ? "off-scale — likely trough-margin distortion"
    : peggedLow
      ? "off-scale — likely balance-sheet event distortion"
      : null

  const trailing5yCagr = parseTrailing5yCagr(sanity)

  return (
    <section
      aria-label="Reverse DCF"
      className="bg-bg rounded-2xl border border-border p-5"
    >
      <header className="mb-3">
        <h2 className="text-sm font-semibold text-ink tracking-tight uppercase">
          Reverse-DCF — what&rsquo;s the market pricing in?
        </h2>
        <p className="text-xs text-caption mt-1">
          Holding today&rsquo;s price as the target, the assumptions a 10-year
          two-stage DCF must adopt to match it.
        </p>
      </header>

      <ReverseDcfSliders
        inputs={inputs}
        trailing5yCagr={trailing5yCagr}
      />

      <p className="mt-4 pt-4 border-t border-border text-xs uppercase tracking-wider text-caption mb-1">
        Snapshot at backend defaults
      </p>
      <p className="text-sm text-body leading-relaxed">{summary}</p>

      {offScale && offScaleCaveat && (
        <p className="mt-2 text-xs leading-relaxed rounded-md border border-amber-300/40 bg-amber-50 dark:bg-amber-950/20 text-amber-900 dark:text-amber-200 px-3 py-2">
          <span className="font-bold">Note:</span> {offScaleCaveat}. The
          implied-growth figure above is a bound, not a point estimate.
        </p>
      )}

      <ul className="mt-4 space-y-2 text-sm">
        <li className="flex items-baseline gap-2">
          <span aria-hidden className="text-caption">&bull;</span>
          <span>
            Implied FCF growth at current{" "}
            <span className="font-mono tabular-nums">
              {formatPct(inputs.current_margin)}
            </span>{" "}
            margins:{" "}
            <span className="font-semibold font-mono tabular-nums text-ink">
              {offScalePrefix ? `${offScalePrefix} ` : ""}
              {formatPct(impliedG)}
            </span>
            {offScale && (
              <span className="ml-1 text-caption text-xs">(off-scale)</span>
            )}
          </span>
        </li>
        <li className="flex items-baseline gap-2">
          <span aria-hidden className="text-caption">&bull;</span>
          <span>
            Implied FCF margin at consensus{" "}
            <span className="font-mono tabular-nums">
              {formatPct(inputs.consensus_growth)}
            </span>{" "}
            growth:{" "}
            <span className="font-semibold font-mono tabular-nums text-ink">
              {formatPct(impliedM)}
            </span>
          </span>
        </li>
        {iso && iso.length > 0 && (
          <li className="flex items-baseline gap-2">
            <span aria-hidden className="text-caption">&bull;</span>
            <span>
              Iso-FV curve:{" "}
              <span className="font-mono tabular-nums">
                {iso.map((p, i) => (
                  <span key={i}>
                    {i > 0 ? "  /  " : ""}
                    {formatPct(p.growth)} g &amp; {formatPct(p.margin)} m
                  </span>
                ))}
              </span>
            </span>
          </li>
        )}
      </ul>

      {sanity && sanity.length > 0 && (
        <footer className="mt-4 pt-3 border-t border-border">
          <p className="text-[11px] uppercase tracking-wider text-caption mb-1">
            Sanity check vs trailing 5y actuals
          </p>
          <ul className="space-y-1">
            {sanity.map((line, i) => (
              <li key={i} className="text-xs text-caption leading-relaxed">
                {line}
              </li>
            ))}
          </ul>
        </footer>
      )}
    </section>
  )
}

// ─────────────────────────────────────────────────────────────────
// Interactive WACC / terminal-growth sliders. Reuses the backend
// `inputs` snapshot (current FCF, debt, cash, shares, price, etc.)
// and re-solves the bisector client-side on every slider tick.
// Pure-additive: the static summary above still renders untouched.
// ─────────────────────────────────────────────────────────────────
interface SlidersProps {
  inputs: ReverseDcfInputs
  trailing5yCagr: number | null
}

const WACC_MIN = 0.07
const WACC_MAX = 0.16
const TG_MIN = 0.0
const TG_MAX = 0.08
const STEP = 0.001

function clamp(x: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, x))
}

function ReverseDcfSliders({ inputs, trailing5yCagr }: SlidersProps) {
  const defaultWacc = clamp(inputs.wacc, WACC_MIN, WACC_MAX)
  const defaultTg = clamp(inputs.terminal_g, TG_MIN, TG_MAX)
  const [wacc, setWacc] = useState<number>(defaultWacc)
  const [tg, setTg] = useState<number>(defaultTg)

  // Guard: terminal growth must be strictly below WACC for Gordon to
  // resolve. If the user drags TG above WACC we visually clamp TG to
  // WACC - 0.5pp so the readout stays finite.
  const effectiveTg = tg >= wacc ? Math.max(0, wacc - 0.005) : tg

  const result = useMemo(() => {
    return solveImpliedGrowth(
      inputs.current_price,
      inputs.current_fcf,
      wacc,
      effectiveTg,
      inputs.current_fcf > 0 ? inputs.years : 10,
      inputs.total_debt,
      inputs.total_cash,
      inputs.shares,
    )
  }, [
    inputs.current_price,
    inputs.current_fcf,
    inputs.years,
    inputs.total_debt,
    inputs.total_cash,
    inputs.shares,
    wacc,
    effectiveTg,
  ])

  const reset = () => {
    setWacc(defaultWacc)
    setTg(defaultTg)
  }
  const dirty =
    Math.abs(wacc - defaultWacc) > 1e-9 || Math.abs(tg - defaultTg) > 1e-9

  const growthPct = (result.growth * 100).toFixed(1)
  const sign = result.pegged === "high" ? "≥ " : result.pegged === "low" ? "≤ " : ""

  return (
    <div className="mt-3 mb-1 rounded-xl border border-border bg-surface/40 p-4">
      <div className="flex items-baseline justify-between mb-3 gap-2 flex-wrap">
        <div className="flex items-center gap-1.5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-caption">
            Interactive — drag to test assumptions
          </h3>
          <span
            aria-label="Solves implied FCF growth client-side from the same two-stage faded DCF the backend uses"
            title="Solves implied FCF growth client-side from the same two-stage faded DCF the backend uses."
            className="text-caption cursor-help text-xs"
          >
            &#9432;
          </span>
        </div>
        {dirty && (
          <button
            type="button"
            onClick={reset}
            className="text-[11px] uppercase tracking-wider text-caption hover:text-ink underline-offset-2 hover:underline"
          >
            Reset
          </button>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <SliderRow
          label="WACC"
          value={wacc}
          min={WACC_MIN}
          max={WACC_MAX}
          step={STEP}
          defaultValue={defaultWacc}
          onChange={setWacc}
        />
        <SliderRow
          label="Terminal growth"
          value={tg}
          min={TG_MIN}
          max={TG_MAX}
          step={STEP}
          defaultValue={defaultTg}
          onChange={setTg}
        />
      </div>

      <div className="mt-4 rounded-lg bg-bg border border-border px-4 py-3">
        <p className="text-sm text-body leading-relaxed">
          At WACC{" "}
          <span className="font-mono tabular-nums font-semibold text-ink">
            {(wacc * 100).toFixed(1)}%
          </span>{" "}
          and terminal growth{" "}
          <span className="font-mono tabular-nums font-semibold text-ink">
            {(effectiveTg * 100).toFixed(1)}%
          </span>
          , the market is pricing in an implied FCF growth rate of{" "}
          <span className="font-mono tabular-nums font-semibold text-ink">
            {sign}
            {growthPct}%
          </span>
          {trailing5yCagr !== null ? (
            <>
              {" "}
              (vs trailing 5y revenue CAGR{" "}
              <span className="font-mono tabular-nums">
                {(trailing5yCagr * 100).toFixed(1)}%
              </span>
              ).
            </>
          ) : (
            "."
          )}
        </p>
        {result.pegged !== null && (
          <p className="mt-2 text-xs leading-relaxed text-amber-700 dark:text-amber-300">
            Off-scale — the implied growth is outside the [−5%, +50%] search
            window, so the figure above is a bound rather than a point estimate.
          </p>
        )}
        {tg >= wacc && (
          <p className="mt-2 text-xs leading-relaxed text-amber-700 dark:text-amber-300">
            Terminal growth cannot equal or exceed WACC — clamped to{" "}
            {(effectiveTg * 100).toFixed(1)}% for this readout.
          </p>
        )}
      </div>
    </div>
  )
}

interface SliderRowProps {
  label: string
  value: number
  min: number
  max: number
  step: number
  defaultValue: number
  onChange: (v: number) => void
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  defaultValue,
  onChange,
}: SliderRowProps) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <label className="text-xs text-caption">{label}</label>
        <span className="text-sm font-mono tabular-nums font-semibold text-ink">
          {(value * 100).toFixed(1)}%
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        aria-label={`${label} — current ${(value * 100).toFixed(1)} percent, default ${(defaultValue * 100).toFixed(1)} percent`}
        className="w-full accent-ink cursor-pointer"
      />
      <div className="flex justify-between text-[10px] text-caption mt-0.5 font-mono tabular-nums">
        <span>{(min * 100).toFixed(0)}%</span>
        <span>default {(defaultValue * 100).toFixed(1)}%</span>
        <span>{(max * 100).toFixed(0)}%</span>
      </div>
    </div>
  )
}
