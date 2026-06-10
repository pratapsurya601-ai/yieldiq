"use client"

// HoldingsTrendMiniChart — 8-quarter promoter/FII/DII/public stacked
// area chart for the Quality section of the analysis page.
//
// Tickertape-parity. The current snapshot is already on the analyze
// response (promoter_pct/fii_pct/dii_pct/public_pct on QualityOutput),
// but the trend is what differentiates "FII inflows persistent" from
// "FII spike in latest quarter only" — load-bearing context for
// flow + governance analysis.
//
// Data source: /api/v1/public/holdings-trend/{ticker} (additive,
// no auth, 6h CDN cache). Self-fetches because the trend series is
// not on the analyze contract — kept additive and lazy, like the
// promoter-pledge panel.
//
// Fallback: when the backend returns an empty `trend` array (ticker
// has only the current quarter on file, or hasn't been backfilled
// yet), the component renders a compact current-only readout so the
// user still sees the four percentages.

import { useEffect, useState } from "react"
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts"

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

export interface HoldingsTrendDataPoint {
  quarter_end: string | null
  quarter_label: string
  promoter_pct: number | null
  fii_pct: number | null
  dii_pct: number | null
  public_pct: number | null
}

export interface HoldingsCurrentPattern {
  promoter_pct: number | null
  fii_pct: number | null
  dii_pct: number | null
  public_pct: number | null
}

export interface HoldingsTrendResponse {
  ticker: string
  trend: HoldingsTrendDataPoint[]
  current: HoldingsTrendDataPoint | null
  source: string
}

interface HoldingsTrendMiniChartProps {
  ticker: string
  /** Optional pre-fetched trend (lets parents skip the self-fetch). */
  trendData?: HoldingsTrendDataPoint[] | null
  /** Current-quarter pattern from the analyze response. Used as the
   *  empty-state fallback so we render something useful even when the
   *  historical backfill hasn't reached this ticker. */
  currentPattern?: HoldingsCurrentPattern | null
  className?: string
}

/* ------------------------------------------------------------------ */
/* Colour palette — picked to match the dividend / FV-history charts   */
/* and remain legible in both themes. Promoter sits at the base of the */
/* stack (most stable, anchors the chart visually).                    */
/* ------------------------------------------------------------------ */

const SERIES = [
  { key: "promoter_pct", label: "Promoter", color: "#1e40af" }, // blue-800
  { key: "fii_pct",      label: "FII",      color: "#0ea5e9" }, // sky-500
  { key: "dii_pct",      label: "DII",      color: "#10b981" }, // emerald-500
  { key: "public_pct",   label: "Public",   color: "#94a3b8" }, // slate-400
] as const

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—"
  return `${v.toFixed(1)}%`
}

/** Compute pp delta between latest and earliest non-null values. */
function ppDelta(points: HoldingsTrendDataPoint[], key: keyof HoldingsTrendDataPoint): number | null {
  const nums = points
    .map((p) => p[key])
    .filter((v): v is number => typeof v === "number" && !Number.isNaN(v))
  if (nums.length < 2) return null
  return nums[nums.length - 1] - nums[0]
}

/** Stable rounded value with a sign prefix for display. */
function fmtPp(delta: number | null): string {
  if (delta == null || Number.isNaN(delta)) return "—"
  const sign = delta > 0 ? "+" : ""
  return `${sign}${delta.toFixed(1)}pp`
}

/** Phrase a delta in compliant, non-recommendation language.
 *  Avoids SEBI banned vocab (no "accumulate", "buy", "sell", etc.) —
 *  we describe the move, not opinions about it. */
function trendPhrase(label: string, delta: number | null, quarters: number): string {
  if (delta == null) return `${label}: history incomplete`
  const span = quarters >= 2 ? `over ${quarters} quarters` : ""
  if (Math.abs(delta) < 0.5) return `${label} share little changed ${span}`.trim()
  const dir = delta > 0 ? "rose" : "fell"
  return `${label} share ${dir} ${Math.abs(delta).toFixed(1)}pp ${span}`.trim()
}

/* ------------------------------------------------------------------ */
/* Tooltip                                                             */
/* ------------------------------------------------------------------ */

interface RechartsTooltipPayload {
  value: number
  name: string
  color: string
  dataKey: string
}

function HoldingsTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: RechartsTooltipPayload[]
  label?: string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg bg-gray-900 px-3 py-2 text-xs text-white shadow-lg min-w-[160px]">
      <p className="text-gray-300 font-medium mb-1">{label}</p>
      {payload.map((entry) => (
        <p key={entry.dataKey} className="font-medium" style={{ color: entry.color }}>
          {entry.name}:{" "}
          <span className="font-mono text-white">
            {fmtPct(typeof entry.value === "number" ? entry.value : null)}
          </span>
        </p>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Trend-insights strip (sits beneath the chart)                       */
/* ------------------------------------------------------------------ */

function TrendInsights({ data }: { data: HoldingsTrendDataPoint[] }) {
  if (data.length < 2) return null
  const n = data.length
  const items: { label: string; delta: number | null }[] = [
    { label: "Promoter", delta: ppDelta(data, "promoter_pct") },
    { label: "FII",      delta: ppDelta(data, "fii_pct") },
    { label: "DII",      delta: ppDelta(data, "dii_pct") },
  ]
  return (
    <ul
      className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs text-caption"
      aria-label="Holdings trend insights"
    >
      {items.map(({ label, delta }) => (
        <li
          key={label}
          className="flex items-center justify-between rounded-md bg-bg/60 dark:bg-surface/60 px-2 py-1 border border-border"
        >
          <span>{trendPhrase(label, delta, n)}</span>
          <span
            className={
              "ml-2 font-mono tabular-nums " +
              (delta == null
                ? "text-caption"
                : delta > 0
                ? "text-emerald-600 dark:text-emerald-400"
                : delta < 0
                ? "text-red-600 dark:text-red-400"
                : "text-caption")
            }
          >
            {fmtPp(delta)}
          </span>
        </li>
      ))}
    </ul>
  )
}

/* ------------------------------------------------------------------ */
/* Current-only fallback                                               */
/* ------------------------------------------------------------------ */

function HoldingsCurrentOnly({
  current,
  message,
}: {
  current: HoldingsCurrentPattern | null
  message?: string
}) {
  const hasAny =
    current &&
    (current.promoter_pct != null ||
      current.fii_pct != null ||
      current.dii_pct != null ||
      current.public_pct != null)
  if (!hasAny) {
    return (
      <section
        className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
        data-testid="holdings-trend-empty"
      >
        <h3 className="text-sm font-semibold text-ink mb-1">Holding pattern</h3>
        <p className="text-xs text-caption">
          {message ?? "No shareholding pattern on file yet."}
        </p>
      </section>
    )
  }
  const rows: { label: string; value: number | null; color: string }[] = [
    { label: "Promoter", value: current!.promoter_pct, color: SERIES[0].color },
    { label: "FII",      value: current!.fii_pct,      color: SERIES[1].color },
    { label: "DII",      value: current!.dii_pct,      color: SERIES[2].color },
    { label: "Public",   value: current!.public_pct,   color: SERIES[3].color },
  ]
  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
      data-testid="holdings-trend-current-only"
    >
      <h3 className="text-sm font-semibold text-ink mb-2">Holding pattern</h3>
      <p className="text-xs text-caption mb-3">
        Latest quarter only. 8-quarter trend pending backfill for this ticker.
      </p>
      <dl className="grid grid-cols-4 gap-2">
        {rows.map(({ label, value, color }) => (
          <div key={label} className="text-center">
            <dt className="text-[10px] uppercase tracking-wide text-caption">{label}</dt>
            <dd
              className="mt-1 text-lg font-semibold tabular-nums"
              style={{ color }}
            >
              {fmtPct(value)}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */

export function HoldingsTrendMiniChart({
  ticker,
  trendData: trendDataProp,
  currentPattern,
  className,
}: HoldingsTrendMiniChartProps) {
  // When `trendData` is supplied by the parent we skip the self-fetch
  // entirely (used by tests + future SSR paths). Otherwise we fetch
  // lazily on mount, mirroring PromoterPledgePanel.
  const [fetched, setFetched] = useState<HoldingsTrendResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(trendDataProp === undefined)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (trendDataProp !== undefined) {
      setLoading(false)
      return
    }
    let cancelled = false
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    const symbol = (ticker || "").replace(".NS", "").replace(".BO", "")
    if (!symbol) {
      setLoading(false)
      return
    }
    fetch(`${base}/api/v1/public/holdings-trend/${symbol}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: HoldingsTrendResponse | null) => {
        if (cancelled) return
        setFetched(j)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Could not load holdings trend")
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticker, trendDataProp])

  if (loading) {
    return (
      <section
        className={
          "bg-bg dark:bg-surface rounded-2xl border border-border p-4 " + (className ?? "")
        }
        data-testid="holdings-trend-loading"
      >
        <h3 className="text-sm font-semibold text-ink mb-2">Holding pattern</h3>
        <div className="text-xs text-caption">Loading…</div>
      </section>
    )
  }

  const trend =
    (trendDataProp !== undefined ? trendDataProp : fetched?.trend) ?? []
  const fallbackCurrent =
    currentPattern ??
    (fetched?.current
      ? {
          promoter_pct: fetched.current.promoter_pct,
          fii_pct: fetched.current.fii_pct,
          dii_pct: fetched.current.dii_pct,
          public_pct: fetched.current.public_pct,
        }
      : null)

  // Need at least 2 points to draw a trend; otherwise fall back to the
  // current-quarter readout. We still render the fallback (instead of
  // returning null) so the slot doesn't visually collapse on the page.
  if (!trend || trend.length < 2) {
    return (
      <div className={className}>
        <HoldingsCurrentOnly
          current={fallbackCurrent}
          message={error ?? undefined}
        />
      </div>
    )
  }

  return (
    <section
      className={
        "bg-bg dark:bg-surface rounded-2xl border border-border p-4 " + (className ?? "")
      }
      data-testid="holdings-trend-chart"
      aria-label={`Holding pattern trend for ${ticker}`}
    >
      <header className="mb-3">
        <h3 className="text-sm font-semibold text-ink">
          Holding pattern — {trend.length}-quarter trend
        </h3>
        <p className="text-xs text-caption mt-0.5">
          Promoter, FII, DII and public shareholding from quarterly filings.
        </p>
      </header>

      <div className="w-full" style={{ height: 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={trend}
            margin={{ top: 4, right: 8, bottom: 0, left: -16 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.25)" />
            <XAxis
              dataKey="quarter_label"
              tick={{ fontSize: 10, fill: "currentColor" }}
              interval={0}
            />
            <YAxis
              domain={[0, 100]}
              tickFormatter={(v) => `${v}%`}
              tick={{ fontSize: 10, fill: "currentColor" }}
              width={36}
            />
            <Tooltip content={<HoldingsTooltip />} />
            <Legend
              iconType="circle"
              wrapperStyle={{ fontSize: 11, paddingTop: 4 }}
            />
            {SERIES.map((s) => (
              <Area
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stackId="holdings"
                stroke={s.color}
                fill={s.color}
                fillOpacity={0.55}
                strokeWidth={1.2}
                isAnimationActive={false}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <TrendInsights data={trend} />
    </section>
  )
}

export default HoldingsTrendMiniChart
export { HoldingsCurrentOnly, ppDelta, trendPhrase }
