"use client"

/**
 * FVProjectionFan — Alpha Spread style fan-out projection chart.
 *
 * Renders the trailing 24 months of actual close prices as a solid line,
 * then three dashed projection lines (bear / base / bull) fanning out from
 * "today" to +60 months. Endpoint labels show terminal price, MoS%, and
 * implied CAGR for each case. Replaces the three bear/base/bull cards
 * with a single information-dense visualization.
 *
 * Data sources:
 *   • Historical close prices — `getChartData(ticker, "1y")` (daily_prices
 *     table, ~12m of NSE bhavcopy-sourced closes). Falls back to the
 *     `getFVHistory` `price` column when chart-data is unavailable
 *     (network error, tier limit, missing ticker).
 *   • FV overlay context      — `getFVHistory(ticker, 2)` retained for the
 *     fair-value overlay column (read elsewhere) and as a fallback source
 *     of `price` samples when chart-data is empty.
 *   • Forward scenarios       — passed in from AnalysisBody (already on
 *                               the analysis payload, no extra fetch).
 *
 * Both fetches run in parallel via independent useQuery hooks so the
 * network round-trips overlap. See PR fix(analysis): 5Y projection
 * actual-price line reads daily_prices, not fair_value_history.
 *
 * SEBI discipline: banned advisory vocabulary excluded from labels.
 * "Projection" instead of advisory phrasing. 5y horizon matches DCF window.
 */

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceDot,
  Label,
} from "recharts"
import { getChartData, getFVHistory, type FVHistoryPoint } from "@/lib/api"
import { formatCurrency, formatPct } from "@/lib/utils"

/** Subset of `/chart-data` we read. The endpoint returns more fields
 *  (financials etc.) but we only need the price series here. */
interface ChartDataResponse {
  prices?: Array<{ date: string; price: number }>
}

/** Minimal shape used by buildSeries to populate the `actual` line.
 *  Both chart-data points and fv-history points coerce into this. */
interface PricePoint {
  date: string
  price: number
}

interface ScenarioCase {
  iv: number
  mos_pct: number
}

export interface FVProjectionFanProps {
  ticker: string
  currency: string
  currentPrice: number
  scenarios: {
    bear: ScenarioCase
    base: ScenarioCase
    bull: ScenarioCase
  }
  /** Optional pre-fetched history so callers can avoid a duplicate request. */
  historyOverride?: FVHistoryPoint[] | null
}

interface ChartPoint {
  // Months relative to today: -12 ... +60
  m: number
  // Actual close price for historic months only
  actual?: number
  // Projection lines start at month 0 (= currentPrice) and end at +60
  bear?: number
  base?: number
  bull?: number
  // Tooltip helpers
  label: string
}

const HORIZON_MONTHS = 60
const HISTORY_MONTHS = 24

function impliedCagr(start: number, end: number, years: number): number {
  if (!start || start <= 0 || !end || end <= 0 || years <= 0) return 0
  return (Math.pow(end / start, 1 / years) - 1) * 100
}

function FanTooltip({
  active,
  payload,
  currency,
  currentPrice,
}: {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string; payload: ChartPoint }>
  currency: string
  currentPrice: number
}) {
  if (!active || !payload?.length) return null
  const p = payload[0]?.payload
  if (!p) return null
  return (
    <div className="rounded-xl bg-gray-900 px-3 py-2 text-xs text-white shadow-lg min-w-[180px]">
      <p className="text-gray-400 mb-1">{p.label}</p>
      {payload.map((entry) => {
        const v = entry.value
        if (v == null || !Number.isFinite(v)) return null
        const delta = currentPrice > 0 ? ((v - currentPrice) / currentPrice) * 100 : 0
        return (
          <p key={entry.name} className="font-medium" style={{ color: entry.color }}>
            {entry.name}:{" "}
            <span className="font-mono">{formatCurrency(v, currency)}</span>{" "}
            <span className="opacity-80">
              ({delta >= 0 ? "+" : ""}
              {delta.toFixed(1)}% vs today)
            </span>
          </p>
        )
      })}
    </div>
  )
}

function buildSeries(
  history: PricePoint[],
  currentPrice: number,
  scenarios: FVProjectionFanProps["scenarios"],
): ChartPoint[] {
  // Bucket history into the most recent ~24 monthly samples.
  const monthly: { m: number; actual: number; label: string }[] = []
  if (history.length > 0) {
    // Sort ascending by date.
    const sorted = [...history].sort(
      (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime(),
    )
    const last = sorted[sorted.length - 1]
    const lastTs = new Date(last.date).getTime()
    // For each bucket month (-24..0), pick the latest sample within
    // that month-window. O(n*24) — n is bounded by the payload
    // (~250 trading days/year ⇒ ~500 rows for 2y of daily_prices).
    for (let offset = HISTORY_MONTHS; offset >= 0; offset--) {
      const upper = lastTs - (offset - 1) * 30 * 24 * 3600 * 1000
      const lower = lastTs - offset * 30 * 24 * 3600 * 1000
      const samples = sorted.filter((p) => {
        const t = new Date(p.date).getTime()
        return t > lower && t <= upper && Number.isFinite(p.price) && p.price > 0
      })
      if (samples.length > 0) {
        const pt = samples[samples.length - 1]
        const d = new Date(pt.date)
        monthly.push({
          m: -offset,
          actual: pt.price,
          label: d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" }),
        })
      }
    }
  }
  const series: ChartPoint[] = monthly.map((p) => ({
    m: p.m,
    actual: p.actual,
    label: p.label,
  }))

  // Ensure month 0 (today) has the current price + scenario starting points
  // so the dashed lines anchor cleanly to "today".
  const todayLabel = "Today"
  const today: ChartPoint = {
    m: 0,
    actual: currentPrice > 0 ? currentPrice : undefined,
    bear: currentPrice,
    base: currentPrice,
    bull: currentPrice,
    label: todayLabel,
  }
  // Replace any synthetic m===0 entry that lacked projections.
  const existingTodayIdx = series.findIndex((p) => p.m === 0)
  if (existingTodayIdx >= 0) {
    series[existingTodayIdx] = { ...series[existingTodayIdx], ...today }
  } else {
    series.push(today)
  }

  // Projections: straight-line interpolation from currentPrice (m=0) to
  // each scenario's terminal value at m=+60. We sample every 6 months so
  // tooltips remain readable but the line stays smooth.
  for (let m = 6; m <= HORIZON_MONTHS; m += 6) {
    const t = m / HORIZON_MONTHS
    series.push({
      m,
      bear: currentPrice + (scenarios.bear.iv - currentPrice) * t,
      base: currentPrice + (scenarios.base.iv - currentPrice) * t,
      bull: currentPrice + (scenarios.bull.iv - currentPrice) * t,
      label: m === HORIZON_MONTHS ? "+5y" : `+${m}m`,
    })
  }

  return series.sort((a, b) => a.m - b.m)
}

export default function FVProjectionFan({
  ticker,
  currency,
  currentPrice,
  scenarios,
  historyOverride = null,
}: FVProjectionFanProps) {
  const [showNumbers, setShowNumbers] = useState(false)

  // Two independent useQuery hooks fire in parallel — React Query
  // dispatches both fetches on the same render, so the network round-
  // trips overlap. We deliberately don't gate one on the other: a
  // failure in one must not block the other from rendering.
  const fvHistoryQuery = useQuery({
    queryKey: ["fv-history", ticker, 2],
    queryFn: () => getFVHistory(ticker, 2),
    enabled: !!ticker && !historyOverride,
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })

  // 1y is the longest period the chart-data endpoint currently
  // supports (_PERIOD_MAP in backend/routers/analysis.py). It feeds
  // the X-axis's leftmost ~12 monthly buckets cleanly — far more
  // than the ~65d fv_history table covered. If/when chart-data
  // grows a 2y/5y option, bump this string.
  const chartDataQuery = useQuery<ChartDataResponse>({
    queryKey: ["chart-data", ticker, "1y"],
    queryFn: () => getChartData(ticker, "1y") as Promise<ChartDataResponse>,
    enabled: !!ticker && !historyOverride,
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })

  const points = useMemo(() => {
    if (historyOverride) {
      return buildSeries(historyOverride, currentPrice, scenarios)
    }
    // Prefer chart-data (daily_prices, ~12m of trading-day closes).
    // Fall back to fv-history's `price` column when chart-data is
    // unavailable (network error, free-tier limit, or ticker missing
    // from daily_prices). Either source feeds the same PricePoint
    // shape; buildSeries handles the rest.
    const chartPrices = chartDataQuery.data?.prices ?? []
    if (chartPrices.length > 0) {
      const src: PricePoint[] = chartPrices
        .filter((p) => p && Number.isFinite(p.price) && p.price > 0 && p.date)
        .map((p) => ({ date: p.date, price: p.price }))
      return buildSeries(src, currentPrice, scenarios)
    }
    const fvPoints = fvHistoryQuery.data?.data ?? []
    const fallback: PricePoint[] = fvPoints
      .filter((p) => p && Number.isFinite(p.price) && p.price > 0 && p.date)
      .map((p) => ({ date: p.date, price: p.price }))
    return buildSeries(fallback, currentPrice, scenarios)
  }, [
    historyOverride,
    chartDataQuery.data,
    fvHistoryQuery.data,
    currentPrice,
    scenarios,
  ])

  // Loading: still loading while at least one source is in-flight AND
  // we don't yet have any data to render. Both errored is the only
  // "real" error state (we can survive one source failing).
  const isLoading = chartDataQuery.isLoading || fvHistoryQuery.isLoading
  const isError = chartDataQuery.isError && fvHistoryQuery.isError

  const hasAnyActual = points.some((p) => p.actual != null && p.actual > 0)
  // Determine how far back actual history extends (most-negative m with an
  // actual sample). Free-tier users may only get ~12m even though we asked
  // for 24m, so drive the x-axis domain off real data instead of the const.
  const historyExtent = useMemo(() => {
    let minM = 0
    for (const p of points) {
      if (p.actual != null && p.actual > 0 && p.m < minM) minM = p.m
    }
    // Snap to the nearest multiple of 6 (rounded down) so axis ticks align.
    const snapped = Math.floor(minM / 6) * 6
    return Math.max(-HISTORY_MONTHS, snapped || -HISTORY_MONTHS)
  }, [points])
  const historyTicks = useMemo(() => {
    // Build symmetric-ish ticks across the historical window: every 6m.
    const ticks: number[] = []
    for (let m = historyExtent; m < 0; m += 6) ticks.push(m)
    return [...ticks, 0, 12, 24, 36, 48, 60]
  }, [historyExtent])
  const showSkeleton = isLoading && !historyOverride
  const showEmpty =
    !showSkeleton &&
    !hasAnyActual &&
    (!currentPrice || currentPrice <= 0)

  const bearCagr = impliedCagr(currentPrice, scenarios.bear.iv, 5)
  const baseCagr = impliedCagr(currentPrice, scenarios.base.iv, 5)
  const bullCagr = impliedCagr(currentPrice, scenarios.bull.iv, 5)

  return (
    <div className="bg-bg rounded-2xl border border-border p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">5-Year Projection</h2>
          <p className="text-xs text-caption">
            Actual price (left) and bear / base / bull scenarios over the DCF horizon (right).
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowNumbers((v) => !v)}
          className="text-xs font-medium text-brand hover:underline shrink-0"
          aria-expanded={showNumbers}
        >
          {showNumbers ? "Hide numbers" : "Show numbers"}
        </button>
      </div>

      {showSkeleton ? (
        <div className="h-[280px] rounded-lg bg-surface animate-pulse" aria-label="Loading projection" />
      ) : showEmpty || isError ? (
        <div className="h-[280px] rounded-lg border border-dashed border-border flex items-center justify-center text-xs text-caption">
          No price history available
        </div>
      ) : (
        <div className="w-full" style={{ height: 280 }}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={points}
              margin={{ top: 12, right: 96, left: 8, bottom: 8 }}
            >
              <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 4" />
              <XAxis
                dataKey="m"
                type="number"
                domain={[historyExtent, HORIZON_MONTHS]}
                ticks={historyTicks}
                tickFormatter={(m) =>
                  m === 0 ? "Today" : m < 0 ? `${m}m` : `+${m / 12}y`
                }
                stroke="var(--color-caption)"
                fontSize={10}
              />
              <YAxis
                stroke="var(--color-caption)"
                fontSize={10}
                tickFormatter={(v) => formatCurrency(v, currency)}
                width={60}
              />
              <Tooltip
                content={
                  <FanTooltip currency={currency} currentPrice={currentPrice} />
                }
              />
              <ReferenceLine
                x={0}
                stroke="var(--color-caption)"
                strokeDasharray="3 3"
              >
                <Label value="Today" position="top" fontSize={10} fill="var(--color-caption)" />
              </ReferenceLine>
              <Line
                type="monotone"
                dataKey="actual"
                name="Actual"
                stroke="var(--color-ink)"
                strokeWidth={2}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="bull"
                name="Bull"
                stroke="var(--color-success)"
                strokeWidth={2}
                strokeDasharray="5 4"
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="base"
                name="Base"
                stroke="var(--color-brand)"
                strokeWidth={2}
                strokeDasharray="5 4"
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="bear"
                name="Bear"
                stroke="var(--color-danger)"
                strokeWidth={2}
                strokeDasharray="5 4"
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
              <ReferenceDot
                x={HORIZON_MONTHS}
                y={scenarios.bull.iv}
                r={3}
                fill="var(--color-success)"
                stroke="none"
              />
              <ReferenceDot
                x={HORIZON_MONTHS}
                y={scenarios.base.iv}
                r={3}
                fill="var(--color-brand)"
                stroke="none"
              />
              <ReferenceDot
                x={HORIZON_MONTHS}
                y={scenarios.bear.iv}
                r={3}
                fill="var(--color-danger)"
                stroke="none"
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Endpoint chips — rendered below the chart so they stay readable
          on narrow mobile widths where right-edge labels would clip. */}
      <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px]">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2 py-1.5">
          <span className="w-2 h-2 rounded-full bg-success" aria-hidden />
          <span className="text-caption">Bull</span>
          <span className="ml-auto font-mono tabular-nums text-ink">
            {formatCurrency(scenarios.bull.iv, currency)} ·{" "}
            {formatPct(scenarios.bull.mos_pct)} · {bullCagr.toFixed(1)}% CAGR
          </span>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2 py-1.5">
          <span className="w-2 h-2 rounded-full bg-brand" aria-hidden />
          <span className="text-caption">Base</span>
          <span className="ml-auto font-mono tabular-nums text-ink">
            {formatCurrency(scenarios.base.iv, currency)} ·{" "}
            {formatPct(scenarios.base.mos_pct)} · {baseCagr.toFixed(1)}% CAGR
          </span>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2 py-1.5">
          <span className="w-2 h-2 rounded-full bg-danger" aria-hidden />
          <span className="text-caption">Bear</span>
          <span className="ml-auto font-mono tabular-nums text-ink">
            {formatCurrency(scenarios.bear.iv, currency)} ·{" "}
            {formatPct(scenarios.bear.mos_pct)} · {bearCagr.toFixed(1)}% CAGR
          </span>
        </div>
      </div>

      <p className="mt-2 text-[11px] text-caption">
        Implied 5y CAGR: {baseCagr.toFixed(1)}% (base). Projections are
        scenario outputs, not price targets.
      </p>

      {showNumbers && (
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
          {(["bear", "base", "bull"] as const).map((key) => {
            const sc = scenarios[key]
            const label = key === "bear" ? "Bear" : key === "base" ? "Base" : "Bull"
            const color =
              key === "bear"
                ? "text-danger"
                : key === "bull"
                  ? "text-success"
                  : "text-brand"
            return (
              <div
                key={key}
                className="text-center p-3 rounded-xl border border-border bg-surface"
              >
                <p className="text-xs text-caption mb-1">{label} case</p>
                <p className={`text-lg font-bold font-mono tabular-nums ${color}`}>
                  {formatCurrency(sc.iv, currency, ticker)}
                </p>
                <p className="text-xs text-caption">MoS: {formatPct(sc.mos_pct)}</p>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
