"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import { CountUp } from "@/components/anim"
import {
  recomputeDcfPlayground,
  reverseEngineerDcf,
  type DCFPlaygroundResponse,
  type DCFReverseEngineerResponse,
} from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import PlaygroundSlider from "./PlaygroundSlider"

// ── Slider definitions (mirror backend bounds in dcf_playground.py) ──
export interface SliderDef {
  key: "wacc" | "terminal_growth" | "revenue_cagr_yr1_5" | "operating_margin" | "tax_rate"
  label: string
  min: number
  max: number
  step: number
  defaultValue: number
  tooltip: string
  paidOnly: boolean
}

const SLIDERS: SliderDef[] = [
  {
    key: "wacc",
    label: "Discount Rate (WACC)",
    min: 0.06,
    max: 0.15,
    step: 0.001,
    defaultValue: 0.11,
    tooltip:
      "What return you demand for tying up your money in this stock. Higher WACC = more skeptical = lower fair value.",
    paidOnly: false,
  },
  {
    key: "terminal_growth",
    label: "Terminal Growth",
    min: 0.0,
    max: 0.07,
    step: 0.001,
    defaultValue: 0.04,
    tooltip:
      "How fast the business grows forever after year 10. Indian nominal GDP is around 10-11%, so 3-5% is the sane range.",
    paidOnly: true,
  },
  {
    key: "revenue_cagr_yr1_5",
    label: "Revenue CAGR (yrs 1-5)",
    min: -0.05,
    max: 0.30,
    step: 0.005,
    defaultValue: 0.10,
    tooltip:
      "Annual revenue growth for the next 5 years. Then it fades toward terminal growth across years 6-10.",
    paidOnly: true,
  },
  {
    key: "operating_margin",
    label: "Operating Margin",
    min: 0.0,
    max: 0.50,
    step: 0.005,
    defaultValue: 0.20,
    tooltip:
      "Steady-state operating margin. Drives how much of every revenue rupee converts to cash.",
    paidOnly: true,
  },
  {
    key: "tax_rate",
    label: "Tax Rate",
    min: 0.0,
    max: 0.50,
    step: 0.005,
    defaultValue: 0.25,
    tooltip:
      "Effective corporate tax rate on operating profit. Indian listed-co statutory rate is 25% for most.",
    paidOnly: true,
  },
]

interface SliderState {
  wacc: number
  terminal_growth: number
  revenue_cagr_yr1_5: number
  operating_margin: number
  tax_rate: number
}

const INITIAL_STATE: SliderState = SLIDERS.reduce(
  (acc, s) => ({ ...acc, [s.key]: s.defaultValue }),
  {} as SliderState,
)

export default function PlaygroundBody({ ticker }: { ticker: string }) {
  const tier = useAuthStore((s) => s.tier)
  const isPaid = useMemo(() => {
    const t = (tier || "free").toLowerCase()
    return t === "pro" || t === "starter" || t === "analyst"
  }, [tier])

  const [inputs, setInputs] = useState<SliderState>(INITIAL_STATE)
  const [result, setResult] = useState<DCFPlaygroundResponse | null>(null)
  const [reverse, setReverse] = useState<DCFReverseEngineerResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Slider change with 300ms debounce ──────────────────────────
  const onSliderChange = useCallback((key: keyof SliderState, value: number) => {
    setInputs((prev) => ({ ...prev, [key]: value }))
  }, [])

  // Debounced POST. Runs whenever `inputs` changes; cancels prior
  // pending call so a fast drag fires exactly one network round-trip
  // 300ms after the user stops moving.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      let cancelled = false
      setLoading(true)
      setError(null)
      recomputeDcfPlayground(ticker, inputs)
        .then((r) => {
          if (cancelled) return
          setResult(r)
        })
        .catch((e) => {
          if (cancelled) return
          const msg =
            (e && typeof e === "object" && "message" in e
              ? String((e as { message?: unknown }).message)
              : null) || "Recompute failed"
          setError(msg)
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
      return () => {
        cancelled = true
      }
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [ticker, inputs])

  // ── Reverse-engineer once we have a current_price ─────────────
  useEffect(() => {
    if (!result?.current_price || result.current_price <= 0) return
    let cancelled = false
    reverseEngineerDcf(ticker, {
      market_price: result.current_price,
      wacc: inputs.wacc,
      terminal_growth: inputs.terminal_growth,
      revenue_cagr_yr1_5: inputs.revenue_cagr_yr1_5,
      operating_margin: inputs.operating_margin,
      tax_rate: inputs.tax_rate,
    })
      .then((r) => {
        if (cancelled) return
        setReverse(r)
      })
      .catch(() => {
        // Reverse panel is additive — silently degrade
      })
    return () => {
      cancelled = true
    }
    // Intentionally key only on price + ticker — we don't want to
    // re-bisect on every slider tweak (expensive + the implied numbers
    // would jiggle distractingly).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, result?.current_price])

  const resetAll = useCallback(() => {
    setInputs(INITIAL_STATE)
  }, [])

  const adoptMarketImplied = useCallback(() => {
    if (!reverse) return
    setInputs((prev) => ({
      ...prev,
      wacc: clamp(reverse.implied_wacc, 0.06, 0.15),
      terminal_growth: clamp(reverse.implied_terminal_growth, 0.0, 0.07),
      revenue_cagr_yr1_5: clamp(reverse.implied_revenue_cagr, -0.05, 0.30),
    }))
  }, [reverse])

  const fv = result?.fair_value ?? 0
  const bear = result?.bear_fv ?? 0
  const bull = result?.bull_fv ?? 0
  const price = result?.current_price ?? 0
  const upsidePct = price > 0 && fv > 0 ? ((fv - price) / price) * 100 : 0

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:py-12">
      {/* Header */}
      <div className="mb-8 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.25em] text-muted">
            DCF Playground
          </p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-ink sm:text-3xl">
            {ticker.replace(".NS", "").replace(".BO", "")} &middot; What if&hellip;?
          </h1>
          <p className="mt-1 max-w-prose text-sm text-muted">
            Drag the five inputs. Watch the fair value recompute live. See what
            the market is implicitly assuming below.
          </p>
        </div>
        <Link
          href={`/analysis/${encodeURIComponent(ticker)}`}
          className="text-sm font-medium text-emerald-700 hover:underline dark:text-emerald-300"
        >
          &larr; Back to full analysis
        </Link>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* ── LEFT: Sliders ──────────────────────────────────── */}
        <section
          aria-label="DCF input sliders"
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-ink">
              Inputs
            </h2>
            <button
              type="button"
              onClick={resetAll}
              className="text-xs font-medium text-slate-600 hover:text-emerald-700 dark:text-slate-300 dark:hover:text-emerald-300"
            >
              Reset all
            </button>
          </div>
          <div className="flex flex-col gap-4">
            {SLIDERS.map((s) => (
              <PlaygroundSlider
                key={s.key}
                def={s}
                value={inputs[s.key]}
                onChange={(v) => onSliderChange(s.key, v)}
                locked={s.paidOnly && !isPaid}
              />
            ))}
          </div>
          {!isPaid && (
            <div className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs dark:border-emerald-900 dark:bg-emerald-950/30">
              <p className="font-medium text-emerald-900 dark:text-emerald-200">
                Free plan: only the WACC slider is unlocked.
              </p>
              <Link
                href="/pricing"
                className="mt-1 inline-block font-semibold text-emerald-700 hover:underline dark:text-emerald-300"
              >
                Unlock all inputs &rarr;
              </Link>
            </div>
          )}
        </section>

        {/* ── RIGHT: Live FV + band ─────────────────────────── */}
        <section
          aria-label="Live fair value"
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
        >
          <h2 className="text-sm font-semibold uppercase tracking-wider text-ink">
            Fair Value
          </h2>
          <div className="mt-2 flex items-baseline gap-3">
            <span className="font-mono text-4xl font-bold tabular-nums text-ink sm:text-5xl">
              {fv > 0 ? (
                <>
                  &#x20B9;
                  <CountUp to={fv} decimals={0} duration={0.6} />
                </>
              ) : (
                <span className="text-2xl text-muted">—</span>
              )}
            </span>
            {price > 0 && fv > 0 && (
              <span
                className={
                  upsidePct >= 0
                    ? "rounded-md bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
                    : "rounded-md bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
                }
              >
                {upsidePct >= 0 ? "+" : ""}
                {upsidePct.toFixed(1)}% vs market
              </span>
            )}
          </div>
          {price > 0 && (
            <p className="mt-1 text-xs text-muted">
              Market price: &#x20B9;
              {price.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
            </p>
          )}
          {result?.base_fv ? (
            <p className="mt-1 text-xs text-muted">
              Analyst base FV: &#x20B9;
              {Number(result.base_fv).toLocaleString("en-IN", {
                maximumFractionDigits: 0,
              })}
            </p>
          ) : null}

          {/* Bear / Base / Bull mini fan-out */}
          {fv > 0 && (
            <div
              className="mt-5"
              aria-label="Fair value range under one-sigma input shifts"
            >
              <div className="mb-1 flex justify-between text-[10px] uppercase tracking-wider text-muted">
                <span>Pessimistic</span>
                <span>Optimistic</span>
              </div>
              <FanOutBar bear={bear} base={fv} bull={bull} />
              <div className="mt-1 flex justify-between font-mono text-xs tabular-nums text-ink">
                <span>&#x20B9;{Math.round(bear).toLocaleString("en-IN")}</span>
                <span className="font-semibold">
                  &#x20B9;{Math.round(fv).toLocaleString("en-IN")}
                </span>
                <span>&#x20B9;{Math.round(bull).toLocaleString("en-IN")}</span>
              </div>
            </div>
          )}

          {loading && (
            <p className="mt-3 text-xs italic text-muted">Recomputing&hellip;</p>
          )}
          {error && (
            <p className="mt-3 text-xs text-rose-700 dark:text-rose-300">
              {error}
            </p>
          )}
        </section>
      </div>

      {/* ── BELOW: Reverse-engineered card ─────────────────────── */}
      {reverse && price > 0 && (
        <section
          aria-label="Market-implied assumptions"
          className="mt-6 rounded-xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-5 shadow-sm dark:border-slate-800 dark:from-slate-900 dark:to-slate-950"
        >
          <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-muted">
            What the market is pricing in
          </p>
          <p className="mt-2 text-base leading-relaxed text-ink sm:text-lg">
            At &#x20B9;
            {price.toLocaleString("en-IN", { maximumFractionDigits: 0 })}, the
            market is implicitly assuming&hellip;
          </p>
          <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <ImpliedStat
              label="Discount Rate"
              value={pct(reverse.implied_wacc)}
              converged={reverse.iterations.wacc_converged}
            />
            <ImpliedStat
              label="Revenue CAGR"
              value={pct(reverse.implied_revenue_cagr)}
              converged={reverse.iterations.revenue_cagr_converged}
            />
            <ImpliedStat
              label="Terminal Growth"
              value={pct(reverse.implied_terminal_growth)}
              converged={reverse.iterations.terminal_growth_converged}
            />
          </dl>
          <p className="mt-3 text-[11px] italic text-muted">
            Each input was solved independently &mdash; holding the other four
            at your current slider positions.
          </p>
          <button
            type="button"
            onClick={adoptMarketImplied}
            className="mt-4 inline-flex items-center justify-center rounded-md bg-emerald-700 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-800 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2"
          >
            Adopt these assumptions
          </button>
        </section>
      )}
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────────
function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

function FanOutBar({ bear, base, bull }: { bear: number; base: number; bull: number }) {
  const span = Math.max(bull - bear, 1e-6)
  const baseFrac = clamp((base - bear) / span, 0, 1)
  return (
    <div
      className="relative h-2 w-full rounded-full bg-gradient-to-r from-amber-300 via-slate-300 to-emerald-400 dark:from-amber-700 dark:via-slate-700 dark:to-emerald-600"
      role="presentation"
    >
      <div
        className="absolute -top-1 h-4 w-1 rounded-sm bg-slate-900 dark:bg-white"
        style={{ left: `calc(${(baseFrac * 100).toFixed(2)}% - 2px)` }}
      />
    </div>
  )
}

function ImpliedStat({
  label,
  value,
  converged,
}: {
  label: string
  value: string
  converged: boolean
}) {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted">
        {label}
      </dt>
      <dd className="mt-0.5 font-mono text-xl font-semibold tabular-nums text-ink">
        {converged ? value : <>~{value}</>}
      </dd>
      {!converged && (
        <p className="text-[10px] italic text-muted">solver did not converge</p>
      )}
    </div>
  )
}
