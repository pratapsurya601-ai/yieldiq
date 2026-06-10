"use client"

/**
 * EarningsWaterfallChart — Q-by-Q earnings cadence.
 *
 * Distinct from EarningsWaterfall.tsx (which is a Revenue → Net
 * Income BRIDGE for a single period). This component plots the LAST
 * EIGHT QUARTERS of Revenue, EBITDA and PAT side-by-side, with a
 * YoY-growth line overlay, beat/miss callouts where consensus data
 * is available, and a quarter-selector chip strip that focuses any
 * single column.
 *
 * Inspiration: AlphaSpread's "earnings waterfall" surface — a
 * compact way to see the trajectory at a glance without leaving the
 * page.
 *
 * Data source: existing `getFinancials(ticker, "quarterly", 8)`. No
 * backend change needed — quarterly income rows already carry
 * revenue, ebitda, net_income and net_income_growth_pct. Consensus /
 * beat-miss is NOT currently in the financials payload; the
 * component degrades gracefully (no badges, no orange dot) when
 * absent.
 *
 * SEBI-safe (no banned vocab). Mobile responsive — bars stack
 * vertically on < 520px. Dark-mode parity via design tokens.
 */

import * as React from "react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
  ReferenceLine,
} from "recharts"
import { getFinancials, type FinancialYear, type FinancialsResponse } from "@/lib/api"

interface EarningsWaterfallChartProps {
  ticker: string
  /** Optional pre-fetched annual payload (kept for symmetry with
   *  EarningsWaterfall — currently unused but lets a parent prime the
   *  React Query cache via initialData later). */
  annual?: FinancialsResponse | null
  currency?: string | null
}

// ────────────────────────────────────────────────────────────────────
// Quarter labelling (Indian-FY convention — Q1 = Apr-Jun).
// ────────────────────────────────────────────────────────────────────
/**
 * Map a period_end ISO date string ("YYYY-MM-DD") to a human "QX FY26"
 * label using Indian fiscal year (Apr-Mar). Defaults to the raw
 * `year` field when the date can't be parsed — empty fixtures and
 * older payloads sometimes carry `period_end = null`.
 */
export function labelQuarter(row: { year: string; period_end: string | null }): string {
  const iso = row.period_end
  if (!iso) return row.year
  const m = /^(\d{4})-(\d{2})/.exec(iso)
  if (!m) return row.year
  const calMonth = parseInt(m[2], 10)
  const calYear = parseInt(m[1], 10)
  if (!Number.isFinite(calMonth) || !Number.isFinite(calYear)) return row.year
  // Indian FY: Apr-Jun=Q1, Jul-Sep=Q2, Oct-Dec=Q3, Jan-Mar=Q4.
  let q: number
  let fyEndYear: number
  if (calMonth >= 4 && calMonth <= 6) {
    q = 1
    fyEndYear = calYear + 1
  } else if (calMonth >= 7 && calMonth <= 9) {
    q = 2
    fyEndYear = calYear + 1
  } else if (calMonth >= 10 && calMonth <= 12) {
    q = 3
    fyEndYear = calYear + 1
  } else {
    q = 4
    fyEndYear = calYear
  }
  return `Q${q} FY${String(fyEndYear).slice(-2)}`
}

// ────────────────────────────────────────────────────────────────────
// Beat / miss derivation
// ────────────────────────────────────────────────────────────────────
export type BeatMiss = "beat" | "miss" | "inline" | null

interface RawConsensus {
  consensus_revenue?: number | null
}

/**
 * Classify reported vs consensus revenue. ±2% band = "inline", above
 * = "beat", below = "miss", null when consensus is missing.
 */
export function classifyBeatMiss(
  reportedRevenue: number | null | undefined,
  consensusRevenue: number | null | undefined,
): BeatMiss {
  if (reportedRevenue == null || !Number.isFinite(reportedRevenue)) return null
  if (consensusRevenue == null || !Number.isFinite(consensusRevenue) || consensusRevenue <= 0) {
    return null
  }
  const surprisePct = ((reportedRevenue - consensusRevenue) / consensusRevenue) * 100
  if (surprisePct > 2) return "beat"
  if (surprisePct < -2) return "miss"
  return "inline"
}

// ────────────────────────────────────────────────────────────────────
// Row builder — takes raw quarterly income rows from the financials
// endpoint and produces a chart-ready row per quarter, with YoY
// growth computed against the row 4 quarters earlier when available.
// ────────────────────────────────────────────────────────────────────
export interface ChartRow {
  key: string
  /** Display label ("Q1 FY26"). */
  label: string
  /** ISO period_end (or "" when unknown). */
  period_end: string
  revenue: number | null
  ebitda: number | null
  pat: number | null
  yoy_revenue_pct: number | null
  yoy_pat_pct: number | null
  beat_miss: BeatMiss
  consensus_revenue: number | null
}

/**
 * Build the 8-quarter chart series. Input is a slice of quarterly
 * income rows ordered MOST RECENT FIRST (matches the financials
 * endpoint's contract). YoY growth is computed against the row at
 * index `i + 4` in the SAME input (i.e. the same calendar quarter
 * one year ago), so the function needs up to 12 rows to populate YoY
 * for every visible quarter. Missing inputs degrade to null.
 */
export function buildChartRows(
  rows: (FinancialYear & RawConsensus)[] | null | undefined,
  visibleCount = 8,
): ChartRow[] {
  if (!rows || rows.length === 0) return []
  const out: ChartRow[] = []
  const limit = Math.min(rows.length, visibleCount)
  for (let i = 0; i < limit; i++) {
    const row = rows[i]
    const yoyRef = rows[i + 4] ?? null
    const yoyRevenuePct =
      row.revenue != null &&
      yoyRef?.revenue != null &&
      Number.isFinite(row.revenue) &&
      Number.isFinite(yoyRef.revenue) &&
      yoyRef.revenue !== 0
        ? ((row.revenue - yoyRef.revenue) / Math.abs(yoyRef.revenue)) * 100
        : null
    const yoyPatPct =
      row.net_income != null &&
      yoyRef?.net_income != null &&
      Number.isFinite(row.net_income) &&
      Number.isFinite(yoyRef.net_income) &&
      yoyRef.net_income !== 0
        ? ((row.net_income - yoyRef.net_income) / Math.abs(yoyRef.net_income)) * 100
        : null
    out.push({
      key: row.period_end ?? row.year,
      label: labelQuarter(row),
      period_end: row.period_end ?? "",
      revenue: Number.isFinite(row.revenue as number) ? (row.revenue as number) : null,
      ebitda: Number.isFinite(row.ebitda as number) ? (row.ebitda as number) : null,
      pat: Number.isFinite(row.net_income as number) ? (row.net_income as number) : null,
      yoy_revenue_pct: yoyRevenuePct,
      yoy_pat_pct: yoyPatPct,
      beat_miss: classifyBeatMiss(row.revenue, row.consensus_revenue ?? null),
      consensus_revenue:
        row.consensus_revenue != null && Number.isFinite(row.consensus_revenue)
          ? row.consensus_revenue
          : null,
    })
  }
  // X-axis reads left-to-right oldest → newest, so flip the
  // most-recent-first input.
  return out.reverse()
}

// ────────────────────────────────────────────────────────────────────
// Formatting helpers
// ────────────────────────────────────────────────────────────────────
function formatCr(cr: number | null | undefined): string {
  if (cr == null || !Number.isFinite(cr)) return "—"
  const abs = Math.abs(cr)
  const sign = cr < 0 ? "-" : ""
  if (abs >= 100_000) return `${sign}₹${(abs / 100_000).toFixed(2)} Lakh Cr`
  if (abs >= 1_000) return `${sign}₹${Math.round(abs).toLocaleString("en-IN")} Cr`
  if (abs >= 1) return `${sign}₹${abs.toFixed(1)} Cr`
  return `${sign}₹${abs.toFixed(2)} Cr`
}
function formatPct(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct)) return "—"
  const sign = pct >= 0 ? "+" : ""
  return `${sign}${pct.toFixed(1)}%`
}

// ────────────────────────────────────────────────────────────────────
// Colours — kept in sync with the rest of the analysis surfaces
// (CompoundedGrowthPanel, FinancialsChartPanel).
// ────────────────────────────────────────────────────────────────────
const COLORS = {
  revenue: "#1d4ed8", // blue-700
  ebitda: "#0d9488", // teal-600
  pat: "#047857", // emerald-700
  yoy: "#f59e0b", // amber-500 line overlay
  zero: "#94a3b8", // slate-400 axis baseline
} as const

// ────────────────────────────────────────────────────────────────────
// Tooltip
// ────────────────────────────────────────────────────────────────────
interface WaterfallTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: ChartRow }>
  label?: string
}
function WaterfallTooltip({ active, payload }: WaterfallTooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  const row = (payload[0]?.payload ?? null) as ChartRow | null
  if (!row) return null
  return (
    <div
      role="tooltip"
      data-testid="earnings-waterfall-chart-tooltip"
      className="rounded-md border border-border bg-bg px-2.5 py-1.5 shadow-md text-xs space-y-0.5"
    >
      <div className="font-semibold text-ink">{row.label}</div>
      <div className="text-caption tabular-nums">
        Revenue: <span className="text-ink">{formatCr(row.revenue)}</span>
        {row.yoy_revenue_pct != null && (
          <span className="ml-1 text-[10px]">(YoY {formatPct(row.yoy_revenue_pct)})</span>
        )}
      </div>
      <div className="text-caption tabular-nums">
        EBITDA: <span className="text-ink">{formatCr(row.ebitda)}</span>
      </div>
      <div className="text-caption tabular-nums">
        PAT: <span className="text-ink">{formatCr(row.pat)}</span>
        {row.yoy_pat_pct != null && (
          <span className="ml-1 text-[10px]">(YoY {formatPct(row.yoy_pat_pct)})</span>
        )}
      </div>
      {row.beat_miss && row.consensus_revenue != null && (
        <div className="text-[10px] mt-0.5 pt-0.5 border-t border-border/60">
          vs consensus {formatCr(row.consensus_revenue)} — surprise{" "}
          {row.beat_miss === "beat"
            ? "above estimate"
            : row.beat_miss === "miss"
              ? "below estimate"
              : "in line"}
        </div>
      )}
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────
// Quarter chip strip — lets a reader focus a single quarter; clicking
// the "All" pill restores the full 8-quarter view.
// ────────────────────────────────────────────────────────────────────
function QuarterChipStrip({
  rows,
  selected,
  onSelect,
}: {
  rows: ChartRow[]
  selected: string | null
  onSelect: (key: string | null) => void
}) {
  if (rows.length === 0) return null
  return (
    <div
      role="tablist"
      aria-label="Quarter focus"
      className="flex flex-wrap gap-1 text-[10px]"
      data-testid="earnings-waterfall-chip-strip"
    >
      <button
        type="button"
        role="tab"
        aria-selected={selected === null}
        onClick={() => onSelect(null)}
        className={`px-2 py-0.5 rounded-full border font-semibold uppercase tracking-wide transition-colors ${
          selected === null
            ? "bg-slate-900 text-white border-slate-900"
            : "border-border text-muted hover:text-ink"
        }`}
        data-testid="earnings-waterfall-chip-all"
      >
        All 8Q
      </button>
      {rows.map((r) => (
        <button
          key={r.key}
          type="button"
          role="tab"
          aria-selected={selected === r.key}
          onClick={() => onSelect(r.key)}
          className={`px-2 py-0.5 rounded-full border font-semibold uppercase tracking-wide transition-colors ${
            selected === r.key
              ? "bg-slate-900 text-white border-slate-900"
              : "border-border text-muted hover:text-ink"
          }`}
          data-testid={`earnings-waterfall-chip-${r.key}`}
        >
          {r.label}
          {r.beat_miss === "beat" && (
            <span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 align-middle" />
          )}
          {r.beat_miss === "miss" && (
            <span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-rose-500 align-middle" />
          )}
        </button>
      ))}
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────
// Component
// ────────────────────────────────────────────────────────────────────
export default function EarningsWaterfallChart({
  ticker,
  currency,
}: EarningsWaterfallChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [isMobile, setIsMobile] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)

  // 12 quarters lets us compute YoY for the full 8-quarter view (each
  // visible quarter needs the same-calendar-quarter row one year
  // earlier as its YoY reference). Backend tolerates over-requesting
  // and just returns however many it has.
  const quarterlyQuery = useQuery({
    queryKey: ["financials", ticker, "quarterly", 12],
    queryFn: () => getFinancials(ticker, "quarterly", 12),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setIsMobile(e.contentRect.width < 520)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const rows = useMemo(
    () => buildChartRows(quarterlyQuery.data?.income as (FinancialYear & RawConsensus)[] | undefined, 8),
    [quarterlyQuery.data],
  )

  const visibleRows = useMemo(
    () => (selected ? rows.filter((r) => r.key === selected) : rows),
    [rows, selected],
  )

  const summary = useMemo(() => {
    if (rows.length === 0) return null
    const latest = rows[rows.length - 1]
    const oldest = rows[0]
    return { latest, oldest }
  }, [rows])

  const loading = quarterlyQuery.isLoading && !quarterlyQuery.data
  const empty = !loading && rows.length === 0

  if (loading) {
    return (
      <div
        className="bg-bg rounded-2xl border border-border p-6"
        data-testid="earnings-waterfall-chart-loading"
      >
        <div className="h-4 w-48 bg-border/40 rounded mb-3 animate-pulse" />
        <div className="h-[280px] bg-border/20 rounded animate-pulse" />
      </div>
    )
  }

  if (empty) {
    return (
      <div
        className="bg-bg rounded-2xl border border-border p-6 text-center"
        data-testid="earnings-waterfall-chart-empty"
      >
        <p className="text-sm font-semibold text-ink">Quarterly cadence not available</p>
        <p className="text-xs text-caption mt-1 max-w-prose mx-auto">
          We need at least four quarters of reported income data to render the
          earnings cadence. Check back after the next exchange filing refresh.
        </p>
      </div>
    )
  }

  return (
    <div
      className="bg-bg rounded-2xl border border-border p-4"
      data-testid="earnings-waterfall-chart"
    >
      <header className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-ink">Quarter-by-quarter earnings cadence</h3>
          <p className="text-xs text-caption mt-0.5">
            Last {rows.length} quarters of revenue, EBITDA and PAT, with year-on-year revenue
            growth overlaid as a line.
          </p>
        </div>
        {summary && (
          <div className="text-right text-[11px] tabular-nums">
            <div className="text-caption uppercase tracking-wide">Latest</div>
            <div className="text-ink font-semibold">
              {summary.latest.label} · {formatCr(summary.latest.revenue)}
            </div>
            {summary.latest.yoy_revenue_pct != null && (
              <div className="text-caption">YoY {formatPct(summary.latest.yoy_revenue_pct)}</div>
            )}
          </div>
        )}
      </header>

      <div className="mb-2">
        <QuarterChipStrip rows={rows} selected={selected} onSelect={setSelected} />
      </div>

      <div ref={containerRef} className="w-full" style={{ height: 320 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={visibleRows}
            margin={{ top: 16, right: 16, left: 8, bottom: isMobile ? 56 : 16 }}
          >
            <CartesianGrid stroke="currentColor" strokeOpacity={0.08} vertical={false} />
            <XAxis
              dataKey="label"
              interval={0}
              tick={{ fontSize: isMobile ? 9 : 11, fill: "currentColor" }}
              angle={isMobile ? -30 : 0}
              textAnchor={isMobile ? "end" : "middle"}
              height={isMobile ? 50 : 24}
              stroke="currentColor"
              className="text-caption"
            />
            <YAxis
              yAxisId="left"
              tick={{ fontSize: 10, fill: "currentColor" }}
              tickFormatter={(v: number) => formatCr(v).replace("₹", "")}
              width={70}
              stroke="currentColor"
              className="text-caption"
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fontSize: 10, fill: "currentColor" }}
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              width={44}
              stroke="currentColor"
              className="text-caption"
            />
            <Tooltip
              cursor={{ fill: "rgba(148, 163, 184, 0.12)" }}
              content={((props: unknown) => (
                <WaterfallTooltip {...(props as WaterfallTooltipProps)} />
              )) as React.ComponentProps<typeof Tooltip>["content"]}
            />
            <Legend
              wrapperStyle={{ fontSize: 11, paddingTop: 4 }}
              iconType="circle"
              iconSize={8}
            />
            <ReferenceLine y={0} yAxisId="left" stroke={COLORS.zero} strokeDasharray="2 2" />
            <Bar
              yAxisId="left"
              dataKey="revenue"
              name="Revenue"
              fill={COLORS.revenue}
              radius={[3, 3, 0, 0]}
              maxBarSize={32}
              data-testid="earnings-waterfall-bar-revenue"
            />
            <Bar
              yAxisId="left"
              dataKey="ebitda"
              name="EBITDA"
              fill={COLORS.ebitda}
              radius={[3, 3, 0, 0]}
              maxBarSize={32}
              data-testid="earnings-waterfall-bar-ebitda"
            />
            <Bar
              yAxisId="left"
              dataKey="pat"
              name="PAT"
              fill={COLORS.pat}
              radius={[3, 3, 0, 0]}
              maxBarSize={32}
              data-testid="earnings-waterfall-bar-pat"
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="yoy_revenue_pct"
              name="YoY revenue %"
              stroke={COLORS.yoy}
              strokeWidth={2}
              dot={{ r: 3, fill: COLORS.yoy }}
              activeDot={{ r: 4 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Beat/miss legend strip — only renders when at least one
          quarter in view has consensus data. */}
      {rows.some((r) => r.beat_miss != null) && (
        <div
          className="mt-3 flex items-center gap-3 text-[10px] text-caption"
          data-testid="earnings-waterfall-beatmiss-legend"
        >
          <span className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> Reported above estimate
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" /> Reported below estimate
          </span>
        </div>
      )}

      <p className="text-[11px] text-caption mt-3 max-w-prose">
        YoY % uses the same calendar quarter one year prior as the reference. Quarters with
        insufficient prior-year data are plotted on the bars only (line skips them).
        {currency && currency !== "INR" ? ` Values reported in ${currency}.` : ""}
      </p>
    </div>
  )
}
