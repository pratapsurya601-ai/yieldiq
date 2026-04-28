"use client"

// PromoterPledgePanel — promoter share-pledge tracker for the Quality
// section of the analysis page.
//
// Indian governance signal #1: when a promoter group pledges shares as
// collateral, sharp jumps in pledged_pct have historically preceded
// price collapses (RCOM, Zee, Future Retail). The panel renders:
//   - current pledged_pct prominently
//   - 24-month sparkline of pledged_pct
//   - "HIGH PLEDGE" badge when pledged_pct > 30%
//   - "RECENT CHANGE" badge when 90d change > 5pp
//   - last-updated date and source-filing link
//
// Data source: /api/v1/public/promoter-pledge/{ticker} (additive,
// no auth, 1h CDN cache). Self-fetches because pledge data isn't on
// the StockSummary contract — we deliberately keep this surface
// additive and lazy.

import { useEffect, useState } from "react"

interface PledgeHistoryPoint {
  as_of_date: string
  pledged_pct: number | null
  promoter_group_pct: number | null
}

interface PledgeLatest {
  ticker: string
  as_of_date: string
  promoter_group_pct: number | null
  pledged_pct: number | null
  pledged_shares: number | null
  source_url: string | null
}

interface PledgeResponse {
  ticker: string
  latest: PledgeLatest | null
  history: PledgeHistoryPoint[]
  change_90d_pp: number | null
}

const HIGH_PLEDGE_PCT = 30.0
const RECENT_CHANGE_PP = 5.0

function fmtPct(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—"
  return `${v.toFixed(1)}%`
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—"
  try {
    return new Date(s).toLocaleDateString("en-IN", {
      year: "numeric", month: "short", day: "numeric",
    })
  } catch {
    return s
  }
}

function Sparkline({ points }: { points: PledgeHistoryPoint[] }) {
  if (!points.length) {
    return (
      <div className="text-xs text-caption italic">
        No history yet — first disclosure pending.
      </div>
    )
  }
  const W = 320
  const H = 56
  const PAD = 4
  const vals = points.map(p => p.pledged_pct ?? 0)
  const maxV = Math.max(100, ...vals)  // anchor to 100% so visual scale is stable
  const stepX = vals.length > 1 ? (W - 2 * PAD) / (vals.length - 1) : 0

  const coords = vals.map((v, i) => {
    const x = PAD + i * stepX
    const y = H - PAD - (v / maxV) * (H - 2 * PAD)
    return [x, y] as const
  })
  const dPath = coords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ")
  const lastPct = vals[vals.length - 1] ?? 0
  const stroke = lastPct >= HIGH_PLEDGE_PCT ? "#dc2626" : "#2563eb"

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height={H}
      role="img"
      aria-label="Promoter pledge percentage over the last 24 months"
    >
      <path d={dPath} fill="none" stroke={stroke} strokeWidth={1.6} />
      {coords.length > 0 && (
        <circle
          cx={coords[coords.length - 1][0]}
          cy={coords[coords.length - 1][1]}
          r={2.5}
          fill={stroke}
        />
      )}
    </svg>
  )
}

export default function PromoterPledgePanel({ ticker }: { ticker: string }) {
  const [data, setData] = useState<PledgeResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    const symbol = (ticker || "").replace(".NS", "").replace(".BO", "")
    if (!symbol) { setLoading(false); return }
    fetch(`${base}/api/v1/public/promoter-pledge/${symbol}`)
      .then(r => (r.ok ? r.json() : null))
      .then((j: PledgeResponse | null) => {
        if (cancelled) return
        setData(j)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Could not load pledge data")
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [ticker])

  if (loading) {
    return (
      <section className="bg-bg dark:bg-surface rounded-2xl border border-border p-5">
        <h3 className="text-sm font-semibold text-ink mb-2">Promoter Pledge</h3>
        <div className="text-xs text-caption">Loading…</div>
      </section>
    )
  }

  // No pledge record at all — likely a clean promoter group; render a
  // muted "no pledge on file" line so the user knows we checked.
  if (!data || !data.latest || data.latest.pledged_pct == null) {
    return (
      <section className="bg-bg dark:bg-surface rounded-2xl border border-border p-5">
        <h3 className="text-sm font-semibold text-ink mb-2">Promoter Pledge</h3>
        <div className="text-xs text-caption">
          No promoter-pledge disclosure on file
          {error ? ` (${error})` : "."}
        </div>
      </section>
    )
  }

  const latest = data.latest
  const pledgedPct = latest.pledged_pct ?? 0
  const change90 = data.change_90d_pp ?? 0
  const isHigh = pledgedPct > HIGH_PLEDGE_PCT
  const isRecentChange = Math.abs(change90) > RECENT_CHANGE_PP

  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border p-5"
      aria-label={`Promoter pledge data for ${ticker}`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Promoter Pledge</h3>
          <p className="text-xs text-caption mt-0.5">
            Share of promoter holding pledged as collateral. Indian governance
            signal: jumps &gt; 5pp historically precede distress.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          {isHigh && (
            <span
              className="inline-flex items-center px-2 py-0.5 rounded-full
                         text-[10px] font-semibold tracking-wide uppercase
                         bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"
            >
              High Pledge
            </span>
          )}
          {isRecentChange && (
            <span
              className="inline-flex items-center px-2 py-0.5 rounded-full
                         text-[10px] font-semibold tracking-wide uppercase
                         bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
            >
              Recent Change
            </span>
          )}
        </div>
      </div>

      <div className="flex items-baseline gap-3 mb-3">
        <div className="text-3xl font-bold text-ink tabular-nums">
          {fmtPct(pledgedPct)}
        </div>
        {data.change_90d_pp != null && (
          <div
            className={
              "text-xs font-medium " +
              (data.change_90d_pp > 0
                ? "text-red-600 dark:text-red-400"
                : data.change_90d_pp < 0
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-caption")
            }
          >
            {data.change_90d_pp > 0 ? "+" : ""}
            {data.change_90d_pp.toFixed(1)}pp · 90d
          </div>
        )}
      </div>

      <div className="mb-3">
        <Sparkline points={data.history} />
      </div>

      <div className="flex items-center justify-between text-xs text-caption">
        <span>Last updated: {fmtDate(latest.as_of_date)}</span>
        {latest.source_url && (
          <a
            href={latest.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline dark:text-blue-400"
          >
            Source filing →
          </a>
        )}
      </div>
    </section>
  )
}
