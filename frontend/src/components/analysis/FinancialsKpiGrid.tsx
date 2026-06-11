"use client"

/**
 * FinancialsKpiGrid — the 6-card top strip of the Financials tab.
 *
 * Implements Design Manifesto Tier 1 #4 (Alpha Spread's iconic top-strip,
 * Indianised). Each card shows: label, latest value, YoY trend chip,
 * mini bar sparkline of the last N periods, and 3 CAGR chips (3Y/5Y/10Y).
 *
 * Data source: the existing /api/v1/analysis/{ticker}/financials
 * endpoint (FinancialsResponse). All 6 metrics already exist on
 * FinancialYear; we derive YoY + CAGR client-side from the
 * income/balance/cash_flow arrays (same data, same indexing).
 *
 * No CACHE_VERSION bump. Manifest entry is informational only — the
 * surface is purely additive.
 *
 * Mobile: 1 column. md+: 2 columns. lg+: 3 columns (2x3 grid).
 */

import { useMemo, useState } from "react"
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
} from "recharts"
import type {
  FinancialsResponse,
  FinancialYear,
} from "@/lib/api"
import { useQuery } from "@tanstack/react-query"
import { getFinancials } from "@/lib/api"
import { formatCrore, formatPct as formatPctCanonical } from "@/lib/formatNumbers"
import NumberContext from "@/components/common/NumberContext"

type Period = "annual" | "quarterly" | "ttm"

interface FinancialsKpiGridProps {
  ticker: string
  /**
   * Pre-fetched annual financials. The grid uses this for the Annual
   * + TTM views and fetches quarterly on demand when the user toggles.
   */
  annual: FinancialsResponse | null | undefined
  /** Optional ISO currency hint (display only). */
  currency?: string | null
}

interface MetricSpec {
  key: keyof Pick<
    FinancialYear,
    | "revenue"
    | "operating_income"
    | "net_income"
    | "eps_diluted"
    | "operating_cash_flow"
    | "free_cash_flow"
  >
  label: string
  /** EPS is per-share, not a Crore amount — formatted differently. */
  isPerShare?: boolean
}

const METRICS: MetricSpec[] = [
  { key: "revenue", label: "Revenue" },
  { key: "operating_income", label: "Operating Income" },
  { key: "net_income", label: "Net Income" },
  { key: "eps_diluted", label: "EPS", isPerShare: true },
  { key: "operating_cash_flow", label: "Operating Cash Flow" },
  { key: "free_cash_flow", label: "Free Cash Flow" },
]

// ─── formatters ─────────────────────────────────────────────────────

/**
 * Crore amounts route through the canonical formatter
 * (lib/formatNumbers.formatCrore) — same tiering as before
 * ("₹2.40 Lakh Cr" / "₹14,400 Cr" / "₹850.4 Cr"), single source of
 * truth for thresholds + em-dash fallback.
 */
const formatCroreCompact = (cr: number | null): string => formatCrore(cr)

/** EPS (per-share) — never compacted to Cr; fixed 2 decimals. */
function formatEps(v: number | null, currency?: string | null): string {
  if (v == null || !Number.isFinite(v)) return "—"
  const sym = currency && currency.toUpperCase() === "USD" ? "$" : "₹"
  return `${sym}${v.toFixed(2)}`
}

const formatPctSigned = (p: number | null): string =>
  formatPctCanonical(p, { signed: true })

// ─── derivations ────────────────────────────────────────────────────

/**
 * Returns `years` in OLDEST→NEWEST order. The backend returns newest
 * first (index 0 = latest). We flip so the sparkline reads left-to-
 * right chronologically, like every financial chart users expect.
 */
function chronological(years: FinancialYear[] | undefined): FinancialYear[] {
  if (!years || years.length === 0) return []
  return [...years].reverse()
}

function yoyPct(latest: number | null, prior: number | null): number | null {
  if (latest == null || prior == null || !Number.isFinite(latest) || !Number.isFinite(prior)) {
    return null
  }
  if (prior === 0) return null
  // YoY on negatives is misleading; clamp to null if signs differ.
  if (prior < 0) return null
  return ((latest - prior) / Math.abs(prior)) * 100
}

function cagrPct(latest: number | null, oldest: number | null, years: number): number | null {
  if (latest == null || oldest == null || !Number.isFinite(latest) || !Number.isFinite(oldest)) {
    return null
  }
  if (oldest <= 0 || latest <= 0 || years <= 0) return null
  try {
    return ((Math.pow(latest / oldest, 1 / years) - 1) * 100)
  } catch {
    return null
  }
}

interface DerivedMetric {
  latest: number | null
  yoy: number | null
  spark: { period: string; value: number }[]
  cagr_3y: number | null
  cagr_5y: number | null
  cagr_10y: number | null
}

export function deriveMetric(
  series: FinancialYear[],
  field: MetricSpec["key"],
): DerivedMetric {
  // `series` arrives oldest→newest.
  const points = series
    .map(y => ({ period: y.year, value: y[field] }))
    .filter(p => p.value != null && Number.isFinite(p.value as number)) as {
      period: string
      value: number
    }[]

  if (points.length === 0) {
    return { latest: null, yoy: null, spark: [], cagr_3y: null, cagr_5y: null, cagr_10y: null }
  }

  const latest = points[points.length - 1].value
  const prior = points.length >= 2 ? points[points.length - 2].value : null

  const cagrFromBack = (n: number): number | null => {
    if (points.length < n + 1) return null
    const oldest = points[points.length - 1 - n].value
    return cagrPct(latest, oldest, n)
  }

  return {
    latest,
    yoy: yoyPct(latest, prior),
    spark: points,
    cagr_3y: cagrFromBack(3),
    cagr_5y: cagrFromBack(5),
    cagr_10y: cagrFromBack(10),
  }
}

/**
 * Mean of the last (up to) `n` points in the sparkline series — the
 * "5y avg" context caption on each KPI card. Needs at least 3 numeric
 * periods so one filing can't pose as a five-year norm. Derived from
 * the same financials series that draws the bars — no new data.
 */
export function avgOfLastN(
  spark: { value: number }[],
  n: number,
): number | null {
  const vals = spark
    .slice(-n)
    .map(p => p.value)
    .filter(v => Number.isFinite(v))
  if (vals.length < 3) return null
  return vals.reduce((s, v) => s + v, 0) / vals.length
}

// ─── card ───────────────────────────────────────────────────────────

interface CardProps {
  spec: MetricSpec
  derived: DerivedMetric
  currency?: string | null
  hasData: boolean
  /** Pre-formatted 5-year average ("₹9,610 Cr"); null hides the caption. */
  fiveYearAvgLabel?: string | null
}

function trendTone(yoy: number | null): "up" | "down" | "neutral" {
  if (yoy == null) return "neutral"
  if (yoy > 0.5) return "up"
  if (yoy < -0.5) return "down"
  return "neutral"
}

function KpiCard({ spec, derived, currency, hasData, fiveYearAvgLabel }: CardProps) {
  const tone = trendTone(derived.yoy)
  const trendColor =
    tone === "up" ? "text-tone-good-fg bg-tone-good-bg"
      : tone === "down" ? "text-rust-800 bg-rust-50"
        : "text-slate-600 bg-slate-100"
  const barColor =
    tone === "up" ? "#0f766e"  // teal-700
      : tone === "down" ? "#9a3412"  // rust-800
        : "#64748b"  // slate-500
  const arrow = tone === "up" ? "↗" : tone === "down" ? "↘" : "→"

  const valueStr = spec.isPerShare
    ? formatEps(derived.latest, currency)
    : formatCroreCompact(derived.latest)

  return (
    <div
      className="bg-bg rounded-2xl border border-border p-4 flex flex-col"
      data-testid={`kpi-card-${spec.key}`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">
          {spec.label}
        </span>
        {derived.yoy != null && (
          <span
            className={`text-xs font-semibold tabular-nums px-2 py-0.5 rounded-full ${trendColor}`}
            data-testid={`kpi-yoy-${spec.key}`}
          >
            {arrow} {formatPctSigned(derived.yoy)}
          </span>
        )}
        {!hasData && (
          <span className="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">
            Limited data
          </span>
        )}
      </div>

      <div className="mt-2">
        <span className="text-3xl font-bold tabular-nums text-ink" data-testid={`kpi-value-${spec.key}`}>
          {valueStr}
        </span>
        <NumberContext
          label="5y avg"
          value={fiveYearAvgLabel}
          className="block mt-0.5"
        />
      </div>

      <div className="mt-3 h-6 w-full">
        {derived.spark.length >= 2 ? (
          <ResponsiveContainer width="100%" height={24}>
            <BarChart data={derived.spark} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
              <Bar dataKey="value" radius={[2, 2, 0, 0]} isAnimationActive={false}>
                {derived.spark.map((_, i) => (
                  <Cell key={i} fill={barColor} fillOpacity={0.35 + (0.65 * i) / Math.max(1, derived.spark.length - 1)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-full w-full rounded bg-tone-neutral-bg" />
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {[
          { label: "3Y", v: derived.cagr_3y },
          { label: "5Y", v: derived.cagr_5y },
          { label: "10Y", v: derived.cagr_10y },
        ].map(c => (
          <span
            key={c.label}
            className="text-[11px] tabular-nums px-2 py-0.5 rounded-md bg-tone-neutral-bg text-tone-neutral-fg"
            title={`${c.label} compounded annual growth`}
          >
            <span className="text-muted mr-1">{c.label}</span>
            <span className="font-semibold">{formatPctSigned(c.v)}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

// ─── grid ───────────────────────────────────────────────────────────

export default function FinancialsKpiGrid({
  ticker,
  annual,
  currency,
}: FinancialsKpiGridProps) {
  const [period, setPeriod] = useState<Period>("ttm")

  // Quarterly is lazy — only fetched when the user toggles to it.
  const quarterlyQuery = useQuery({
    queryKey: ["financials", ticker, "quarterly"],
    queryFn: () => getFinancials(ticker, "quarterly", 5),
    enabled: !!ticker && period === "quarterly",
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  // Select the series the user asked for.
  //   - Annual: oldest→newest of the 10-year (or available) annual rows
  //   - Quarterly: oldest→newest of the last ~12 quarters
  //   - TTM: same as annual for now (the backend's annual rows already
  //     reflect the latest full year; a future enhancement can stitch
  //     a real trailing-twelve-months row at the head).
  const series = useMemo(() => {
    if (period === "quarterly") return chronological(quarterlyQuery.data?.income)
    return chronological(annual?.income)
  }, [period, annual, quarterlyQuery.data])

  const derivedByKey = useMemo(() => {
    const out: Record<string, DerivedMetric> = {}
    for (const m of METRICS) {
      out[m.key] = deriveMetric(series, m.key)
    }
    return out
  }, [series])

  return (
    <section
      className="bg-bg rounded-2xl border border-border p-4"
      data-testid="financials-kpi-grid"
    >
      <header className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-ink">Financial Performance</h2>
          <p className="text-xs text-muted mt-0.5">
            Headline metrics with growth context. Bars show the last {period === "quarterly" ? "12 quarters" : "10 years"}.
          </p>
        </div>
        <div
          className="inline-flex rounded-lg border border-border bg-bg p-0.5 text-xs"
          role="tablist"
          aria-label="Period"
        >
          {(["annual", "quarterly", "ttm"] as const).map(p => (
            <button
              key={p}
              role="tab"
              aria-selected={period === p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 rounded-md font-semibold uppercase tracking-wide transition-colors ${
                period === p
                  ? "bg-slate-900 text-white"
                  : "text-muted hover:text-ink"
              }`}
              data-testid={`kpi-period-${p}`}
            >
              {p}
            </button>
          ))}
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {METRICS.map(m => {
          const d = derivedByKey[m.key]
          const hasData = d.spark.length > 0
          // "5y avg" context only makes sense on annual-shaped series;
          // the quarterly toggle would average 5 quarters, not 5 years.
          const avg = period === "quarterly" ? null : avgOfLastN(d.spark, 5)
          const avgLabel =
            avg == null
              ? null
              : m.isPerShare
                ? formatEps(avg, currency)
                : formatCroreCompact(avg)
          return (
            <KpiCard
              key={m.key}
              spec={m}
              derived={d}
              currency={currency}
              hasData={hasData}
              fiveYearAvgLabel={avgLabel}
            />
          )
        })}
      </div>
    </section>
  )
}
