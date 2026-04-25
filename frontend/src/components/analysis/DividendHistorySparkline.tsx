// Server Component — pure SVG sparkline for the dividend-history feed.
// Receives a pre-fetched DividendHistoryResponse (never fetches itself,
// keeps the page-level Promise.all parallelism intact) and degrades to
// a neutral placeholder when the payload is null / empty.
import type { DividendHistoryResponse } from "@/lib/api"

interface Props {
  ticker: string
  data: DividendHistoryResponse | null
  // Optional — when provided we render an estimated dividend yield off
  // the most recent year of payouts (sum / current_price × 100).
  currentPrice?: number | null
}

function fmtINR(n: number | null | undefined, maxFractionDigits = 2): string {
  if (n == null || isNaN(n)) return "\u2014"
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: maxFractionDigits,
  }).format(n)
}

function Placeholder({ ticker }: { ticker: string }) {
  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border shadow-sm p-6 mb-8"
      aria-label={`Dividend history for ${ticker}`}
    >
      <h2 className="text-lg font-bold text-ink mb-1">Dividend History</h2>
      <p className="text-sm text-caption">
        No dividend events recorded for {ticker} in the last 10 years.
      </p>
    </section>
  )
}

export default function DividendHistorySparkline({ ticker, data, currentPrice }: Props) {
  if (!data || !data.dividends || data.dividends.length === 0) {
    return <Placeholder ticker={ticker} />
  }

  // Build the sparkline series. We render *all* events (including those
  // we couldn't parse an amount for, plotted at 0) in chronological
  // order so the visual rhythm of payouts is preserved even when a few
  // amounts are missing. X-axis = event index (uniform spacing — date
  // gaps would compress 2020 events into pixels on a 10y window).
  const events = [...data.dividends].sort(
    (a, b) => a.ex_date.localeCompare(b.ex_date),
  )
  const points = events.map(e => ({
    ex_date: e.ex_date,
    amount: e.amount ?? 0,
  }))

  const W = 320
  const H = 64
  const PAD = 4
  const maxAmt = points.reduce((m, p) => Math.max(m, p.amount), 0)
  const usable = maxAmt > 0 ? maxAmt : 1
  const innerW = W - PAD * 2
  const innerH = H - PAD * 2
  const stepX = points.length > 1 ? innerW / (points.length - 1) : 0

  const path = points
    .map((p, i) => {
      const x = PAD + i * stepX
      const y = PAD + innerH - (p.amount / usable) * innerH
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(" ")

  // Optional: trailing-year yield estimate (sum of last 12 months ÷ price).
  let trailingYield: number | null = null
  if (currentPrice && currentPrice > 0) {
    const cutoffMs = Date.now() - 365 * 24 * 60 * 60 * 1000
    let trail = 0
    for (const e of events) {
      const t = Date.parse(e.ex_date)
      if (!isNaN(t) && t >= cutoffMs && e.amount != null) {
        trail += e.amount
      }
    }
    if (trail > 0) {
      trailingYield = (trail / currentPrice) * 100
    }
  }

  const lastEvent = events[events.length - 1]

  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border shadow-sm p-6 mb-8"
      aria-label={`Dividend history for ${ticker}`}
    >
      <div className="flex items-start justify-between gap-4 mb-3">
        <div>
          <h2 className="text-lg font-bold text-ink">Dividend History</h2>
          <p className="text-xs text-caption">
            {data.count} ex-dividend event{data.count === 1 ? "" : "s"} on file.
            Source: NSE corporate-actions feed.
          </p>
        </div>
        <div className="text-right">
          <p className="text-[10px] text-caption uppercase tracking-wider">Total paid (5Y)</p>
          <p className="text-base font-bold text-ink font-mono">
            {data.total_paid_5y != null ? `${fmtINR(data.total_paid_5y)}/sh` : "\u2014"}
          </p>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-16"
        role="img"
        aria-label={`${ticker} dividend amount sparkline over ${events.length} payouts`}
        preserveAspectRatio="none"
      >
        {/* Baseline */}
        <line
          x1={PAD}
          y1={H - PAD}
          x2={W - PAD}
          y2={H - PAD}
          stroke="#E5E7EB"
          strokeWidth="1"
        />
        {/* Sparkline */}
        {points.length > 1 && (
          <path
            d={path}
            fill="none"
            stroke="#2563EB"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
        {/* Event dots — visible payouts only (skip the parsed-as-zero rows) */}
        {points.map((p, i) => {
          if (p.amount <= 0) return null
          const x = PAD + i * stepX
          const y = PAD + innerH - (p.amount / usable) * innerH
          return (
            <circle key={`${p.ex_date}-${i}`} cx={x} cy={y} r="1.6" fill="#2563EB" />
          )
        })}
      </svg>

      <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
        <div>
          <p className="text-[10px] text-caption uppercase tracking-wider">Last payout</p>
          <p className="font-semibold text-ink">
            {lastEvent ? lastEvent.ex_date : "\u2014"}
          </p>
          <p className="text-caption font-mono">
            {lastEvent && lastEvent.amount != null ? fmtINR(lastEvent.amount) : "\u2014"}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-caption uppercase tracking-wider">Peak payout</p>
          <p className="font-semibold text-ink font-mono">
            {maxAmt > 0 ? fmtINR(maxAmt) : "\u2014"}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-caption uppercase tracking-wider">Trailing yield</p>
          <p className="font-semibold text-ink font-mono">
            {trailingYield != null ? `${trailingYield.toFixed(2)}%` : "\u2014"}
          </p>
        </div>
      </div>

      <p className="mt-3 text-[10px] text-caption">
        Amounts parsed from NSE subject lines; percent-of-face-value declarations
        are not converted and shown as missing.
      </p>
    </section>
  )
}
