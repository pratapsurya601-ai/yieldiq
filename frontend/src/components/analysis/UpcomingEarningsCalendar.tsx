"use client"

// UpcomingEarningsCalendar — forward earnings calendar with FV impact.
//
// What it shows: a big "Next earnings in N days" callout, the
// consensus EPS (per-quarter + annual), this ticker's historical
// surprise track record, and the per-5%-beat FV sensitivity
// derived from the same dampener as the post-print panel.
//
// What it is NOT: a fair-value recompute and not a forecast of
// THIS quarter's print. The panel is a HEURISTIC preview;
// `is_heuristic` from the API is echoed in the header.
//
// Self-hiding: when the API returns `impact: null` (no upcoming
// event within the lookahead, or a fetch failure) the component
// renders nothing. The analysis page mount point depends on this
// — for ~half the universe on any given day, this slot is empty.
// SEBI-safe: zero advisory vocabulary in any rendered string.

import { useEffect, useState } from "react"

interface UpcomingEarningsImpact {
  ticker: string
  estimated_report_date: string
  days_until: number
  consensus_eps_estimate: number | null
  consensus_eps_estimate_annual: number | null
  consensus_revenue_estimate_cr: number | null
  historical_avg_surprise_pct: number
  historical_surprise_quarters: number
  estimated_fv_impact_per_5pct_beat: number
  sector: string | null
  sector_multiplier: number
  implied_growth_used: number
  confirmed: boolean
  source: string
  fiscal_period: string | null
  notes: string[]
  method: string
  is_heuristic: boolean
}

interface UpcomingEarningsResponse {
  ticker: string
  impact: UpcomingEarningsImpact | null
  reason?: string
  disclaimer?: string
  is_heuristic: boolean
}

// ── Formatters ───────────────────────────────────────────────────

function fmtEps(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  // EPS is in Indian rupees per share; two decimals is the
  // convention Finnhub publishes at.
  return `Rs.${v.toFixed(2)}`
}

function fmtPctSigned(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  const pct = v * 100
  const sign = pct > 0 ? "+" : ""
  return `${sign}${pct.toFixed(digits)}%`
}

function fmtPctMagnitude(v: number | null | undefined, digits = 1): string {
  // Used for the per-5%-beat sensitivity — we render it as
  // "+/- Y%" without a sign because a beat moves FV up and a
  // miss moves it down by the same magnitude.
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  const pct = Math.abs(v) * 100
  return `${pct.toFixed(digits)}%`
}

function fmtDate(s: string | null | undefined): string {
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

function daysCalloutLabel(days: number): string {
  // Neutral, descriptive — no urgency framing ("act now", etc).
  if (days === 0) return "today"
  if (days === 1) return "tomorrow"
  return `in ${days} days`
}

// ── Component ────────────────────────────────────────────────────

export default function UpcomingEarningsCalendar({ ticker }: { ticker: string }) {
  const [data, setData] = useState<UpcomingEarningsResponse | null>(null)
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
    fetch(`${base}/api/v1/public/earnings-calendar-fv-impact/${symbol}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: UpcomingEarningsResponse | null) => {
        if (cancelled) return
        setData(j)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Could not load forward earnings calendar")
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  // Silent skeleton — this component sits above the fold; a
  // visible loading state would push everything else down on
  // every render. A short "Loading…" feels noisy.
  if (loading) {
    return null
  }

  // Silent empty state — for ~half the universe on any given day
  // there is no scheduled earnings inside the lookahead. We do
  // NOT want to render a "no upcoming earnings" card above the
  // fold for that case; the panel simply doesn't exist.
  if (!data || !data.impact) {
    if (error) {
      // Error state is also silent — never noise up the analysis
      // page over a transient fetch hiccup.
      return null
    }
    return null
  }

  const i = data.impact
  const days = i.days_until
  const callout = daysCalloutLabel(days)
  const histSign = i.historical_avg_surprise_pct >= 0 ? "+" : ""
  const histText = `${histSign}${(i.historical_avg_surprise_pct * 100).toFixed(1)}%`
  const histTone =
    i.historical_avg_surprise_pct >= 0.005
      ? "text-green-700 dark:text-green-400"
      : i.historical_avg_surprise_pct <= -0.005
        ? "text-red-700 dark:text-red-400"
        : "text-caption"

  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
      aria-label={`Upcoming earnings calendar for ${ticker}`}
      data-testid="upcoming-earnings-calendar"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            Next earnings {callout}
          </h3>
          <p className="text-xs text-caption mt-0.5">
            Scheduled {fmtDate(i.estimated_report_date)}
            {i.fiscal_period ? ` · ${i.fiscal_period}` : ""}
            {i.confirmed ? "" : " · Expected (not yet filed)"}
          </p>
        </div>
        <span
          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px]
                     font-semibold uppercase tracking-wide
                     bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
          title="This panel is a heuristic preview, not a fair-value recompute."
        >
          Heuristic
        </span>
      </div>

      {/* Big "in N days" hero number. tabular-nums so the count
          doesn't jitter when the page is re-rendered (e.g. dark-mode
          toggle re-mounts the tree). */}
      <div
        className="mb-3 flex items-baseline gap-2"
        data-testid="upcoming-earnings-callout"
      >
        <span className="text-3xl font-bold text-ink tabular-nums">
          {days === 0 ? "Today" : days === 1 ? "1 day" : `${days} days`}
        </span>
        <span className="text-xs text-caption">until next print</span>
      </div>

      <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-caption">
            Consensus EPS (per quarter)
          </dt>
          <dd className="text-sm font-semibold text-ink tabular-nums">
            {fmtEps(i.consensus_eps_estimate)}
          </dd>
          {i.consensus_eps_estimate_annual != null && (
            <dd className="text-[11px] text-caption mt-0.5 tabular-nums">
              Annual: {fmtEps(i.consensus_eps_estimate_annual)} (Finnhub)
            </dd>
          )}
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-caption">
            Historical avg surprise
          </dt>
          <dd className={`text-sm font-semibold tabular-nums ${histTone}`}>
            {i.historical_surprise_quarters > 0 ? histText : "—"}
          </dd>
          <dd className="text-[11px] text-caption mt-0.5">
            {i.historical_surprise_quarters > 0
              ? `Last ${i.historical_surprise_quarters} quarter${i.historical_surprise_quarters === 1 ? "" : "s"}`
              : "No track record"}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-caption">
            FV impact per 5% beat
          </dt>
          <dd
            className="text-sm font-semibold text-ink tabular-nums"
            data-testid="upcoming-earnings-per-5pct"
          >
            ±{fmtPctMagnitude(i.estimated_fv_impact_per_5pct_beat, 1)}
          </dd>
          <dd className="text-[11px] text-caption mt-0.5">
            Sector multiplier {i.sector_multiplier.toFixed(1)}x
          </dd>
        </div>
      </dl>

      <div className="border-t border-border pt-3">
        <p className="text-[11px] text-caption leading-relaxed">
          Heuristic preview. Consensus EPS is published annually by
          Finnhub; per-quarter shown above is annual / 4.
          Per-5%-beat sensitivity uses the same sector multiplier
          and dampener as the post-print earnings-impact panel, so
          the forward preview and the post-print reading agree on
          a beat day. Not a fair-value recompute and not a forecast
          of this quarter's print.
          {i.notes && i.notes.includes("consensus_eps_missing") ? (
            <>
              {" "}Consensus EPS unavailable for this ticker — Finnhub
              may not cover the symbol.
            </>
          ) : null}
        </p>
      </div>
    </section>
  )
}
