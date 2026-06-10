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
  // ROOT CAUSE #8 (2026-06-11): may be null when M&A distortion is
  // active — backend strips the surprise number so we don't render
  // a misleading -14.9% etc.
  surprise_pct: number | null
  sector: string | null
  sector_multiplier: number
  implied_growth_used: number
  fv_delta_estimate: number | null
  fv_delta_range: { low: number; high: number } | null
  notes: string[]
  method: string
  is_heuristic: boolean
  ma_distortion_flag?: boolean
}

interface MAEventPayload {
  event_date: string
  event_type: string
  magnitude_pct: number | null
  multiplier: number | null
  normalization_window_quarters: number
  quarters_since_event: number
  description: string
  source_url: string | null
  source_doc: string | null
  is_within_normalization_window: boolean
}

interface ImpactResponse {
  ticker: string
  impact: ImpactPayload | null
  reason?: string
  disclaimer?: string
  is_heuristic: boolean
  // ROOT CAUSE #8 (2026-06-11): M&A distortion suppression. When
  // `ma_distortion_flag` is true, the YoY comp straddles a material
  // structural event and the surprise % / FV-delta range are
  // structurally meaningless. The panel renders `suppression_copy`
  // instead of the numeric grid + range.
  ma_distortion_flag?: boolean
  ma_event?: MAEventPayload | null
  suppression_copy?: string | null
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
  //
  // ROOT CAUSE #8 (2026-06-11) — exception: when M&A distortion is
  // active AND the heuristic could not compute, the backend still
  // returns a payload with `ma_distortion_flag=true` and a
  // `suppression_copy` body. We render the explainer instead of
  // hiding so the user understands why no surprise is shown for a
  // ticker that just reported.
  if (!data || !data.impact) {
    if (data && data.ma_distortion_flag && data.ma_event) {
      return (
        <section
          data-testid="earnings-impact-ma-suppressed"
          className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
          aria-label="Earnings impact suppressed due to M&A distortion"
        >
          <div className="flex items-start justify-between gap-3 mb-2">
            <h3 className="text-sm font-semibold text-ink">
              Last quarter vs YieldIQ expected
            </h3>
            <span
              className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px]
                         font-semibold uppercase tracking-wide
                         bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
            >
              Baseline distorted
            </span>
          </div>
          <p className="text-sm text-body leading-relaxed">
            {data.suppression_copy ||
              "YoY comparison disabled while the year-ago baseline straddles a structural M&A event."}
          </p>
        </section>
      )
    }
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
  const maSuppressed = Boolean(data.ma_distortion_flag)
  const surprisePct = i.surprise_pct
  const label = surprisePct === null ? "" : surpriseLabel(surprisePct)
  const tone = surprisePct === null ? "text-caption" : surpriseTone(surprisePct)

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
            {maSuppressed ? "—" : fmtCr(i.expected_revenue_cr)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-caption">
            Surprise
          </dt>
          <dd className={`text-sm font-semibold tabular-nums ${tone}`}>
            {maSuppressed || surprisePct === null
              ? "—"
              : `${fmtPctSigned(surprisePct, 1)} (${label})`}
          </dd>
        </div>
      </dl>

      <div className="border-t border-border pt-3">
        {maSuppressed && data.ma_event ? (
          <div
            data-testid="earnings-impact-ma-suppressed-body"
            className="rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-3"
          >
            <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-300 mb-1">
              Baseline distorted by M&amp;A
            </p>
            <p className="text-sm text-body leading-relaxed">
              {data.suppression_copy ||
                "YoY comparison disabled while the year-ago baseline straddles a structural M&A event."}
            </p>
            {data.ma_event.source_url && (
              <p className="mt-2 text-[11px] text-caption">
                <a
                  href={data.ma_event.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline decoration-dotted underline-offset-2 hover:text-ink"
                >
                  Filing
                </a>
              </p>
            )}
          </div>
        ) : (
          <>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[11px] uppercase tracking-wide text-caption">
                Likely FV impact at next recompute (range)
              </span>
              <span className="text-sm font-semibold text-ink tabular-nums">
                {i.fv_delta_range
                  ? fmtRange(i.fv_delta_range.low, i.fv_delta_range.high)
                  : "—"}
              </span>
            </div>
            <p className="text-[11px] text-caption mt-2 leading-relaxed">
              Heuristic estimate. The fair value shown on this page is
              unchanged — YieldIQ will recompute the formal fair value
              after the next nightly run, which incorporates concall
              guidance, capex, currency, and sector context that this
              one-quarter estimate does not. Range is clamped to ±15%.
            </p>
          </>
        )}
      </div>
    </section>
  )
}
