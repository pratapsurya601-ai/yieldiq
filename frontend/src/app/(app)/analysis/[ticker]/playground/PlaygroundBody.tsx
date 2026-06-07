"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { CountUp } from "@/components/anim"
import {
  recomputeDcfPlayground,
  reverseEngineerDcf,
  type DCFPlaygroundResponse,
  type DCFReverseEngineerResponse,
} from "@/lib/api"
import {
  calibrateFromSingleAnchor,
  calibrateFromTwoAnchors,
  computeFairValue,
  type DcfCalibration,
  type PlaygroundInputs,
} from "@/lib/dcfClient"
import { formatCurrency } from "@/lib/utils"
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

// Default slider positions. The "Reset to YieldIQ defaults" button
// snaps every slider back here — these mirror the bounds enforced by
// `backend/services/analysis/dcf_playground.py` BASE_TAX_RATE and the
// recompute call we issue on mount to calibrate the client engine.
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

// "What if…?" preset scenarios. Each preset returns a partial override
// to fold into the current slider state — keys not in the override stay
// at their current values. The labels stay strictly descriptive of the
// assumption tweak (no advisory vocabulary), in line with the SEBI lint.
interface Preset {
  key: string
  label: string
  blurb: string
  apply: (defaults: SliderState) => Partial<SliderState>
}

const PRESETS: Preset[] = [
  {
    key: "growth_halved",
    label: "Growth halved",
    blurb: "Revenue CAGR cut in half",
    apply: (d) => ({ revenue_cagr_yr1_5: d.revenue_cagr_yr1_5 / 2 }),
  },
  {
    key: "margins_compress",
    label: "Margins compress",
    blurb: "Operating margin down ~30%",
    apply: (d) => ({ operating_margin: Math.max(0.0, d.operating_margin * 0.7) }),
  },
  {
    key: "higher_rates",
    label: "Higher rates",
    blurb: "WACC +2pp, terminal growth -1pp",
    apply: (d) => ({
      wacc: Math.min(0.15, d.wacc + 0.02),
      terminal_growth: Math.max(0.0, d.terminal_growth - 0.01),
    }),
  },
  {
    key: "tax_reform",
    label: "Tax cut",
    blurb: "Effective tax rate to 20%",
    apply: () => ({ tax_rate: 0.20 }),
  },
]

interface SliderState {
  wacc: number
  terminal_growth: number
  revenue_cagr_yr1_5: number
  operating_margin: number
  tax_rate: number
}

const ANALYST_DEFAULTS: SliderState = SLIDERS.reduce(
  (acc, s) => ({ ...acc, [s.key]: s.defaultValue }),
  {} as SliderState,
)

// ── URL <-> state plumbing ────────────────────────────────────────
// We serialise the slider state into the query string so a user can
// share their model. Keys are short to keep the URL readable:
//   ?w=0.11&tg=0.04&g=0.10&om=0.20&t=0.25
// Values are decimals with up to 4 sig figs (slider step is 0.001).
const URL_KEYS: Record<keyof SliderState, string> = {
  wacc: "w",
  terminal_growth: "tg",
  revenue_cagr_yr1_5: "g",
  operating_margin: "om",
  tax_rate: "t",
}

function inputsToQueryString(s: SliderState): string {
  const params = new URLSearchParams()
  ;(Object.keys(URL_KEYS) as (keyof SliderState)[]).forEach((k) => {
    params.set(URL_KEYS[k], s[k].toFixed(4))
  })
  return params.toString()
}

function inputsFromSearchParams(
  sp: URLSearchParams,
  fallback: SliderState,
): SliderState {
  const out = { ...fallback }
  ;(Object.keys(URL_KEYS) as (keyof SliderState)[]).forEach((k) => {
    const raw = sp.get(URL_KEYS[k])
    if (raw == null) return
    const v = Number(raw)
    if (!Number.isFinite(v)) return
    const def = SLIDERS.find((s) => s.key === k)
    if (!def) return
    // Clamp to slider bounds — defensive against hand-edited URLs.
    out[k] = Math.max(def.min, Math.min(def.max, v))
  })
  return out
}

export default function PlaygroundBody({ ticker }: { ticker: string }) {
  const tier = useAuthStore((s) => s.tier)
  const isPaid = useMemo(() => {
    const t = (tier || "free").toLowerCase()
    return t === "pro" || t === "starter" || t === "analyst"
  }, [tier])

  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  // Initial state: URL params if present, else analyst defaults.
  const [inputs, setInputs] = useState<SliderState>(() =>
    inputsFromSearchParams(
      new URLSearchParams(searchParams?.toString() ?? ""),
      ANALYST_DEFAULTS,
    ),
  )

  // Calibration is fetched once via the existing recompute endpoint —
  // we call it twice on mount (canonical inputs + one perturbed WACC)
  // to solve for both FCF base and net debt per share. Every subsequent
  // slider drag is a pure client-side recompute (~50µs).
  const [calibration, setCalibration] = useState<DcfCalibration | null>(null)
  const [analystFv, setAnalystFv] = useState<number>(0)
  const [marketPrice, setMarketPrice] = useState<number>(0)
  const [reverse, setReverse] = useState<DCFReverseEngineerResponse | null>(null)
  const [calibrating, setCalibrating] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const calibratedRef = useRef(false)

  // ── One-shot calibration on mount ───────────────────────────────
  // `calibrating` initialises to `true` and `error` to `null` so we
  // don't need synchronous setState calls in the effect body (the
  // `react-hooks/set-state-in-effect` lint rule would flag them). Only
  // the async .then() / .catch() / .finally() callbacks update state.
  useEffect(() => {
    if (calibratedRef.current) return
    calibratedRef.current = true
    let cancelled = false

    const anchorAInputs: PlaygroundInputs = { ...ANALYST_DEFAULTS }
    // Perturb WACC by +2pp for the second anchor — large enough to
    // separate the two factor values, small enough to stay realistic.
    const anchorBInputs: PlaygroundInputs = {
      ...ANALYST_DEFAULTS,
      wacc: Math.min(0.15, ANALYST_DEFAULTS.wacc + 0.02),
    }

    Promise.all([
      recomputeDcfPlayground(ticker, anchorAInputs),
      recomputeDcfPlayground(ticker, anchorBInputs),
    ])
      .then(([respA, respB]: [DCFPlaygroundResponse, DCFPlaygroundResponse]) => {
        if (cancelled) return
        const fvA = Number(respA?.fair_value) || 0
        const fvB = Number(respB?.fair_value) || 0
        const price = Number(respA?.current_price) || 0
        const baseFv = Number(respA?.base_fv ?? respA?.fair_value) || 0
        setMarketPrice(price)
        setAnalystFv(baseFv)

        let calib =
          fvA > 0 && fvB > 0
            ? calibrateFromTwoAnchors(
                { inputs: anchorAInputs, fairValue: fvA },
                { inputs: anchorBInputs, fairValue: fvB },
              )
            : null

        if (!calib && fvA > 0) {
          // Two-anchor solve failed (degenerate corner); fall back to
          // a single-anchor calibration with zero net debt.
          calib = calibrateFromSingleAnchor({
            inputs: anchorAInputs,
            fairValue: fvA,
          })
        }
        setCalibration(calib)
      })
      .catch((e) => {
        if (cancelled) return
        const msg =
          (e && typeof e === "object" && "message" in e
            ? String((e as { message?: unknown }).message)
            : null) || "Could not load DCF baseline"
        setError(msg)
      })
      .finally(() => {
        if (!cancelled) setCalibrating(false)
      })

    return () => {
      cancelled = true
    }
  }, [ticker])

  // ── Reverse-engineer once we have a market price ─────────────────
  // Fired once on mount; the implied numbers are anchored to the
  // analyst-default sliders, so they don't jiggle as the user drags.
  useEffect(() => {
    if (marketPrice <= 0) return
    let cancelled = false
    reverseEngineerDcf(ticker, {
      market_price: marketPrice,
      wacc: ANALYST_DEFAULTS.wacc,
      terminal_growth: ANALYST_DEFAULTS.terminal_growth,
      revenue_cagr_yr1_5: ANALYST_DEFAULTS.revenue_cagr_yr1_5,
      operating_margin: ANALYST_DEFAULTS.operating_margin,
      tax_rate: ANALYST_DEFAULTS.tax_rate,
    })
      .then((r) => {
        if (cancelled) return
        setReverse(r)
      })
      .catch(() => {
        // Reverse panel is additive; silently degrade on failure.
      })
    return () => {
      cancelled = true
    }
  }, [ticker, marketPrice])

  // ── URL sync (debounced 250ms) ──────────────────────────────────
  // Updating the URL on every keystroke would spam the History API.
  // 250ms is below the perception threshold for "this is interactive"
  // but high enough that a quick drag flushes one entry, not 60.
  const urlDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (urlDebounceRef.current) clearTimeout(urlDebounceRef.current)
    urlDebounceRef.current = setTimeout(() => {
      const qs = inputsToQueryString(inputs)
      const currentQs = searchParams?.toString() ?? ""
      if (qs === currentQs) return
      const target = `${pathname}?${qs}`
      // replace() not push() — drag scrubbing must not pollute back-button.
      router.replace(target, { scroll: false })
    }, 250)
    return () => {
      if (urlDebounceRef.current) clearTimeout(urlDebounceRef.current)
    }
  }, [inputs, pathname, router, searchParams])

  // ── Client-side recompute on every slider change ─────────────────
  // Pure synchronous math — no debounce, no network, no jank.
  const userFv = useMemo(() => {
    if (!calibration) return 0
    return computeFairValue(inputs, calibration)
  }, [inputs, calibration])

  const onSliderChange = useCallback((key: keyof SliderState, value: number) => {
    setInputs((prev) => ({ ...prev, [key]: value }))
  }, [])

  const resetToAnalyst = useCallback(() => {
    setInputs(ANALYST_DEFAULTS)
  }, [])

  const applyPreset = useCallback((p: Preset) => {
    setInputs((prev) => ({ ...prev, ...p.apply(prev) }))
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

  const copyShareLink = useCallback(async () => {
    if (typeof window === "undefined") return
    const url = `${window.location.origin}${pathname}?${inputsToQueryString(
      inputs,
    )}`
    try {
      await navigator.clipboard.writeText(url)
    } catch {
      // Older browsers / insecure origin — fall back to a prompt.
      window.prompt("Copy this URL", url)
    }
  }, [inputs, pathname])

  const isAtAnalystDefaults = useMemo(
    () =>
      (Object.keys(URL_KEYS) as (keyof SliderState)[]).every(
        (k) => Math.abs(inputs[k] - ANALYST_DEFAULTS[k]) < 1e-6,
      ),
    [inputs],
  )

  const fvDeltaPct =
    analystFv > 0 && userFv > 0 ? ((userFv - analystFv) / analystFv) * 100 : 0
  const upsidePct =
    marketPrice > 0 && userFv > 0
      ? ((userFv - marketPrice) / marketPrice) * 100
      : 0

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
            Drag the five inputs. The fair value recomputes locally in your
            browser. See how YieldIQ&rsquo;s base case compares to your tweaks,
            and what the market is implicitly assuming below.
          </p>
        </div>
        <Link
          href={`/analysis/${encodeURIComponent(ticker)}`}
          className="text-sm font-medium text-emerald-700 hover:underline dark:text-emerald-300"
        >
          &larr; Back to full analysis
        </Link>
      </div>

      {/* Preset scenario buttons */}
      <div className="mb-5 flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
          What if&hellip;
        </span>
        {PRESETS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => applyPreset(p)}
            title={p.blurb}
            className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-ink shadow-sm transition hover:border-emerald-300 hover:bg-emerald-50 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-emerald-700 dark:hover:bg-emerald-950/30"
          >
            {p.label}
          </button>
        ))}
        <button
          type="button"
          onClick={copyShareLink}
          className="ml-auto rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-ink shadow-sm transition hover:border-emerald-300 hover:bg-emerald-50 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-emerald-700 dark:hover:bg-emerald-950/30"
          aria-label="Copy a shareable link with your current assumptions"
        >
          Copy share link
        </button>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* ── LEFT: Sliders ──────────────────────────────────── */}
        <section
          aria-label="DCF input sliders"
          className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-ink">
              Inputs
            </h2>
            <button
              type="button"
              onClick={resetToAnalyst}
              disabled={isAtAnalystDefaults}
              className="text-xs font-medium text-slate-600 hover:text-emerald-700 disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-300 dark:hover:text-emerald-300"
            >
              Reset to YieldIQ defaults
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
            <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs dark:border-emerald-900 dark:bg-emerald-950/30">
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

        {/* ── RIGHT: Live FV side-by-side ─────────────────────── */}
        <section
          aria-label="Live fair value"
          className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
        >
          <h2 className="text-sm font-semibold uppercase tracking-wider text-ink">
            Fair Value
          </h2>

          {/* Side-by-side: YieldIQ base FV vs Your tweaked FV */}
          <div className="mt-3 grid grid-cols-2 gap-4">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">
                YieldIQ base
              </p>
              <p className="mt-1 font-mono text-2xl font-semibold tabular-nums text-ink sm:text-3xl">
                {analystFv > 0 ? (
                  formatCurrency(analystFv, "INR", ticker)
                ) : (
                  <span className="text-base text-muted">—</span>
                )}
              </p>
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-300">
                  Your assumptions
                </p>
              </div>
              <p className="mt-1 font-mono text-2xl font-bold tabular-nums text-ink sm:text-3xl">
                {userFv > 0 ? (
                  <CountUp
                    to={userFv}
                    duration={0.4}
                    format={(n) => formatCurrency(n, "INR", ticker)}
                  />
                ) : (
                  <span className="text-base text-muted">—</span>
                )}
              </p>
              {analystFv > 0 && userFv > 0 && Math.abs(fvDeltaPct) >= 0.05 && (
                <p
                  className={
                    fvDeltaPct >= 0
                      ? "mt-1 text-xs font-semibold text-emerald-700 dark:text-emerald-300"
                      : "mt-1 text-xs font-semibold text-amber-700 dark:text-amber-300"
                  }
                >
                  {fvDeltaPct >= 0 ? "+" : ""}
                  {fvDeltaPct.toFixed(1)}% vs YieldIQ base
                </p>
              )}
            </div>
          </div>

          {marketPrice > 0 && (
            <div className="mt-4 flex items-baseline justify-between border-t border-slate-100 pt-3 dark:border-slate-800">
              <p className="text-xs text-muted">
                Market price: {formatCurrency(marketPrice, "INR", ticker)}
              </p>
              {userFv > 0 && (
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
          )}

          {calibrating && (
            <p className="mt-3 text-xs italic text-muted">
              Loading baseline DCF&hellip;
            </p>
          )}
          {error && (
            <p className="mt-3 text-xs text-rose-700 dark:text-rose-300">
              {error}
            </p>
          )}
          {!calibrating && !error && calibration && (
            <p className="mt-3 text-[11px] italic text-muted">
              Recomputed locally in your browser. Numbers update instantly as
              you drag.
            </p>
          )}
        </section>
      </div>

      {/* ── BELOW: Reverse-engineered card ─────────────────────── */}
      {reverse && marketPrice > 0 && (
        <section
          aria-label="Market-implied assumptions"
          className="mt-6 rounded-xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-4 shadow-sm dark:border-slate-800 dark:from-slate-900 dark:to-slate-950"
        >
          <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-muted">
            What the market is pricing in
          </p>
          <p className="mt-2 text-base leading-relaxed text-ink sm:text-lg">
            At {formatCurrency(marketPrice, "INR", ticker)}, the market is
            implicitly assuming&hellip;
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
            at YieldIQ&rsquo;s default positions.
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
