"use client"

// EarningsImpactPanel — heuristic earnings-impact estimator.
//
// What it shows: the latest reported quarter's revenue, YieldIQ's
// expected baseline (built from YoY same-quarter scaled by the DCF
// implied growth rate), the surprise %, and a CLAMPED RANGE of
// likely fair-value impact at the next nightly recompute.
//
// What it is NOT: a fair-value recompute. The DCF on this page is
// unchanged after a fresh earnings print. The formal recompute
// happens on the next nightly run and incorporates concall
// guidance, capex, currency, and sector context that this
// heuristic deliberately ignores.
//
// Discipline: the API payload carries `is_heuristic: true` and a
// `disclaimer` string. We surface both, prominently, every render.
// SEBI-safe: no advice vocabulary — see check_sebi_words.py for
// only a description of the print and a range estimate.

import { useEffect, useState } from "react"

interface ImpactQuarter {
  period_end: string | null
  revenue_cr: number
  net_profit_cr: number | null
}

interface ImpactBaseline {
  kind: "yoy" | "qoq"
  period_end: string | null
  revenue_cr: number | null
}

interface ImpactPayload {
  latest_quarter: ImpactQuarter
  baseline: ImpactBaseline
  expected_revenue_cr: number
  surprise_pct: number
  sector: string | null
  sector_multiplier: number
  implied_growth_used: number
  fv_delta_estimate: number
  fv_delta_range: { low: number; high: number }
  notes: string[]
  method: string
  is_heuristic: boolean
}

interface ImpactResponse {
  ticker: string
  impact: ImpactPayload | null
  reason?: string
  disclaimer?: string
  is_heuristic: boolean
}

// ── Formatters ───────────────────────────────────────────────────

function fmtCr(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  // Crores → ₹X,XXX Cr (no decimals at this magnitude).
  const rounded = Math.round(v)
  return `₹${rounded.toLocaleString("en-IN")} Cr`
}

function fmtPctSigned(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  const pct = v * 100
  const sign = pct > 0 ? "+" : ""
  return `${sign}${pct.toFixed(digits)}%`
}

function fmtRange(lo: number, hi: number): string {
  // Inputs are signed fractions. Show as "+X% to +Y%" / "−X% to −Y%"
  // with explicit signs so the direction is unambiguous.
  return `${fmtPctSigned(lo, 1)} to ${fmtPctSigned(hi, 1)}`
}

function fmtPeriodEnd(s: string | null): string {
  if (!s) return "—"
  try {
    return new Date(s).toLocaleDateString("en-IN", {
      year: "numeric",
      month: "short",
      day: "numeric",
    })
  } catch {
    return s
  }
}

function surpriseLabel(pct: number): string {
  // Neutral, descriptive vocabulary only — no "beat the street" or
  // advisory framing. "Beat" / "miss" describe the math
  // (actual vs YieldIQ expected); they don't imply an action.
  if (pct >= 0.005) return "beat"
  if (pct <= -0.005) return "miss"
  return "in line"
}

function surpriseTone(pct: number): string {
  if (pct >= 0.005) return "text-green-700 dark:text-green-400"
  if (pct <= -0.005) return "text-red-700 dark:text-red-400"
  return "text-caption"
}

// ── Component ────────────────────────────────────────────────────

export default function EarningsImpactPanel({ ticker }: { ticker: string }) {
  const [data, setData] = useState<ImpactResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    const symbol = (ticker || "").trim()
    if (!symbol) {
      setLoading(false)
      return
    }
    fetch(`${base}/api/v1/analysis/${symbol}/earnings-impact`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: ImpactResponse | null) => {
        if (cancelled) return
        setData(j)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Could not load earnings impact")
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  if (loading) {
    return (
      <section className="bg-bg dark:bg-surface rounded-2xl border border-border p-4">
        <h3 className="text-sm font-semibold text-ink mb-2">
          Last quarter vs YieldIQ expected
        </h3>
        <div className="text-xs text-caption">Loading…</div>
      </section>
    )
  }

  // Empty state — silent when no quarterly data exists for the
  // ticker. We don't want to noise up the page with "no data" for
  // the ~half of the universe we don't cover yet.
  if (!data || !data.impact) {
    if (error) {
      return (
        <section className="bg-bg dark:bg-surface rounded-2xl border border-border p-4">
          <h3 className="text-sm font-semibold text-ink mb-2">
            Last quarter vs YieldIQ expected
          </h3>
          <div className="text-xs text-caption">{error}</div>
        </section>
      )
    }
    return null
  }

  const i = data.impact
  const label = surpriseLabel(i.surprise_pct)
  const tone = surpriseTone(i.surprise_pct)

  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
      aria-label={`Earnings impact estimator for ${ticker}`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            Last quarter vs YieldIQ expected
          </h3>
          <p className="text-xs text-caption mt-0.5">
            Quarter ending {fmtPeriodEnd(i.latest_quarter.period_end)} · baseline:{" "}
            {i.baseline.kind === "yoy"
              ? `same quarter last year (${fmtPeriodEnd(i.baseline.period_end)})`
              : `previous quarter (${fmtPeriodEnd(i.baseline.period_end)})`}
          </p>
        </div>
        <span
          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px]
                     font-semibold uppercase tracking-wide
                     bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
          title="This panel is a heuristic estimate, not a fair-value recompute."
        >
          Heuristic
        </span>
      </div>

      <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-caption">
            Actual revenue
          </dt>
          <dd className="text-sm font-semibold text-ink tabular-nums">
            {fmtCr(i.latest_quarter.revenue_cr)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-caption">
            YieldIQ expected
          </dt>
          <dd className="text-sm font-semibold text-ink tabular-nums">
            {fmtCr(i.expected_revenue_cr)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-caption">
            Surprise
          </dt>
          <dd className={`text-sm font-semibold tabular-nums ${tone}`}>
            {fmtPctSigned(i.surprise_pct, 1)} ({label})
          </dd>
        </div>
      </dl>

      <div className="border-t border-border pt-3">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[11px] uppercase tracking-wide text-caption">
            Likely FV impact at next recompute (range)
          </span>
          <span className="text-sm font-semibold text-ink tabular-nums">
            {fmtRange(i.fv_delta_range.low, i.fv_delta_range.high)}
          </span>
        </div>
        <p className="text-[11px] text-caption mt-2 leading-relaxed">
          Heuristic estimate. The fair value shown on this page is
          unchanged — YieldIQ will recompute the formal fair value
          after the next nightly run, which incorporates concall
          guidance, capex, currency, and sector context that this
          one-quarter estimate does not. Range is clamped to ±15%.
        </p>
      </div>
    </section>
  )
}
