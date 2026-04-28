"use client"

/* ------------------------------------------------------------------ *
 * SensitivityPanel — three sliders (WACC / 5y FCF growth / operating
 * margin) that drive a debounced POST to /analysis/{ticker}/recompute.
 * The headline FV + MoS render above the controls so the user sees
 * impact in real time. Backend tier-gates the endpoint to paid plans;
 * AnalysisBody wraps this component in <ProGate requiredTier="pro">,
 * so by the time we render here the user already has access.
 * ------------------------------------------------------------------ */

import { useEffect, useMemo, useRef, useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { recomputeDcf, type RecomputeResponse } from "@/lib/api"
import { formatCurrency, formatPct } from "@/lib/utils"

interface Props {
  ticker: string
  currency: string
  /** Default WACC from the canonical analysis (decimal, e.g. 0.12). */
  defaultWacc: number
  /** Default 5y growth from the canonical analysis (decimal). */
  defaultGrowth: number
  /** Default operating margin from the canonical analysis (decimal).
   *  May be 0/null for non-financials we couldn't compute — caller
   *  passes a sensible fallback (e.g. 0.15). */
  defaultMargin: number
  /** Baseline FV/MoS so the panel renders something before any
   *  user interaction. */
  baseFairValue: number
  baseMosPct: number
}

interface SliderRowProps {
  label: string
  hint: string
  min: number
  max: number
  step: number
  value: number
  onChange: (v: number) => void
  format: (v: number) => string
  ariaLabel: string
}

function SliderRow({
  label, hint, min, max, step, value, onChange, format, ariaLabel,
}: SliderRowProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <label className="text-xs font-semibold text-ink">
          {label}
          <span className="ml-2 text-[10px] uppercase tracking-wider text-caption font-normal">
            {hint}
          </span>
        </label>
        <span className="font-mono tabular-nums text-sm font-semibold text-brand">
          {format(value)}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={ariaLabel}
        className="w-full accent-brand h-1 cursor-pointer"
      />
      <div className="flex justify-between text-[10px] font-mono tabular-nums text-caption">
        <span>{format(min)}</span>
        <span>{format(max)}</span>
      </div>
    </div>
  )
}

const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, v))

export default function SensitivityPanel({
  ticker,
  currency,
  defaultWacc,
  defaultGrowth,
  defaultMargin,
  baseFairValue,
  baseMosPct,
}: Props) {
  // Bound defaults to slider ranges so a misconfigured backend
  // payload (e.g. WACC 0.04 from an NBFC pre-floor) doesn't push
  // the slider visually off-track.
  const initialWacc = clamp(defaultWacc || 0.12, 0.05, 0.20)
  const initialGrowth = clamp(defaultGrowth || 0.08, -0.05, 0.30)
  const initialMargin = clamp(defaultMargin || 0.15, 0.0, 0.60)

  const [wacc, setWacc] = useState(initialWacc)
  const [growth, setGrowth] = useState(initialGrowth)
  const [margin, setMargin] = useState(initialMargin)
  const [result, setResult] = useState<RecomputeResponse | null>(null)

  const mutation = useMutation({
    mutationFn: (body: { wacc: number; growth_5y_pct: number; margin_pct: number }) =>
      recomputeDcf(ticker, body),
    onSuccess: (data) => setResult(data),
  })

  // Debounce: only trigger a recompute 300ms after the latest slider
  // movement. Skip the first auto-fire on mount so we don't burn a
  // request showing the same numbers the parent already has.
  const isFirstRun = useRef(true)
  useEffect(() => {
    if (isFirstRun.current) {
      isFirstRun.current = false
      return
    }
    const handle = setTimeout(() => {
      mutation.mutate({
        wacc,
        growth_5y_pct: growth,
        margin_pct: margin,
      })
    }, 300)
    return () => clearTimeout(handle)
    // mutation is stable across renders (useMutation memoises),
    // but include the inputs so the timer resets on every change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wacc, growth, margin])

  const reset = () => {
    setWacc(initialWacc)
    setGrowth(initialGrowth)
    setMargin(initialMargin)
    setResult(null)
  }

  const dirty =
    wacc !== initialWacc || growth !== initialGrowth || margin !== initialMargin

  // Headline values: prefer the latest recompute response; otherwise
  // fall back to the canonical analysis figures so the panel shows
  // something on first paint.
  const fv = result?.fair_value ?? baseFairValue
  const mos = result?.margin_of_safety ?? baseMosPct
  const mosColor =
    mos >= 20 ? "text-success" : mos >= -10 ? "text-brand" : "text-danger"

  const errorMsg = useMemo(() => {
    const err = mutation.error as { response?: { status?: number; data?: { detail?: unknown } }; message?: string } | null
    if (!err) return null
    if (err.response?.status === 403) return "Upgrade to Pro to play with assumptions."
    if (err.response?.status === 404) return "Ticker data unavailable for recompute."
    const d = err.response?.data?.detail
    if (typeof d === "string") return d
    return err.message ?? "Recompute failed"
  }, [mutation.error])

  return (
    <div className="bg-bg rounded-2xl border border-border p-5">
      <div className="flex items-baseline justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">Play with assumptions</h2>
          <p className="text-xs text-caption mt-0.5">
            Drag the sliders to test how WACC, growth, and margins reshape fair value.
          </p>
        </div>
        <button
          type="button"
          onClick={reset}
          disabled={!dirty}
          className="text-xs font-medium text-brand hover:underline disabled:text-caption disabled:no-underline disabled:cursor-not-allowed"
        >
          Reset to model defaults
        </button>
      </div>

      {/* Headline: FV + MoS so the user sees impact above the sliders */}
      <div className="grid grid-cols-2 gap-3 mb-5">
        <div className="rounded-xl border border-border bg-surface p-3 text-center">
          <p className="text-[11px] uppercase tracking-wide text-caption">
            Fair value
          </p>
          <p className="text-2xl font-bold font-mono tabular-nums text-ink mt-0.5">
            {fv > 0 ? formatCurrency(fv, currency) : "—"}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-3 text-center">
          <p className="text-[11px] uppercase tracking-wide text-caption">
            Margin of safety
          </p>
          <p className={`text-2xl font-bold font-mono tabular-nums mt-0.5 ${mosColor}`}>
            {Number.isFinite(mos) ? formatPct(mos) : "—"}
          </p>
        </div>
      </div>

      <div className="space-y-4">
        <SliderRow
          label="WACC"
          hint="discount rate"
          min={0.05}
          max={0.20}
          step={0.001}
          value={wacc}
          onChange={setWacc}
          format={(v) => `${(v * 100).toFixed(1)}%`}
          ariaLabel="Weighted average cost of capital"
        />
        <SliderRow
          label="5-yr FCF growth"
          hint="annual"
          min={-0.05}
          max={0.30}
          step={0.005}
          value={growth}
          onChange={setGrowth}
          format={(v) => `${(v * 100).toFixed(1)}%`}
          ariaLabel="Five-year free cash flow growth rate"
        />
        <SliderRow
          label="Operating margin"
          hint="target"
          min={0.0}
          max={0.60}
          step={0.005}
          value={margin}
          onChange={setMargin}
          format={(v) => `${(v * 100).toFixed(1)}%`}
          ariaLabel="Target operating margin"
        />
      </div>

      <div className="mt-4 flex items-center justify-between min-h-[20px]">
        <div className="text-[11px] text-caption">
          {mutation.isPending ? (
            <span className="inline-flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-full border-2 border-brand border-t-transparent animate-spin" />
              Recomputing…
            </span>
          ) : errorMsg ? (
            <span className="text-danger">{errorMsg}</span>
          ) : result?.warnings?.length ? (
            <span>{result.warnings[0]}</span>
          ) : null}
        </div>
        {result?.scenarios ? (
          <div className="text-[11px] text-caption font-mono tabular-nums">
            Bear {formatCurrency(result.scenarios.bear.iv, currency)} ·{" "}
            Bull {formatCurrency(result.scenarios.bull.iv, currency)}
          </div>
        ) : null}
      </div>
    </div>
  )
}
