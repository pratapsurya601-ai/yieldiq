"use client"

/**
 * FVProjectionFan — Alpha Spread parity fan-out projection chart.
 *
 * Renders the trailing 24 months of actual close prices as a solid line,
 * then three dashed projection lines (bear / base / bull) fanning out from
 * "today" to +60 months. Endpoint labels show terminal price next to each
 * forecast line's terminal dot. Scenario chips below the chart retain the
 * MoS% and implied CAGR breakdown.
 *
 * Visual contract (AlphaSpread parity, 2026-06-09):
 *   • Calendar-month x-axis labels (e.g. "Jul 2025") at ~6m intervals
 *   • Right-side y-axis labels
 *   • Hover crosshair + floating tooltip with date + value(s)
 *   • Endpoint price labels at the +5y terminus
 *   • Actual line in brand-blue (var(--color-brand)), 2px solid
 *   • Forecast lines thinner (1.5px) with refined "2 3" dash pattern
 *   • 24 months of history (snapped to actual data extent)
 *   • Light + dark mode via CSS variables
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
  // Months relative to today: -24 ... +60 (driven by data extent)
  m: number
  // Unix epoch milliseconds for the calendar x-axis. Allows native
  // Date locale formatting and continuous numeric scaling.
  t: number
  // Actual close price for historic months only
  actual?: number
  // Projection lines start at month 0 (= currentPrice) and end at +60
  bear?: number
  base?: number
  bull?: number
  // ISO date string for tooltip date display
  date: string
}

const HORIZON_MONTHS = 60
const HISTORY_MONTHS = 24
// Average month length in ms. Used to convert month-offset arithmetic
// into the timestamp domain the x-axis renders. Approximation is fine
// here: tick positions are derived from the same constant so they stay
// aligned with the data points.
const MS_PER_MONTH = 30 * 24 * 3600 * 1000

function impliedCagr(start: number, end: number, years: number): number {
  if (!start || start <= 0 || !end || end <= 0 || years <= 0) return 0
  return (Math.pow(end / start, 1 / years) - 1) * 100
}

/** Format a Date into the calendar tick label (e.g. "Jul 25"). Two-digit
 *  year keeps the axis compact at typical viewport widths; the full year
 *  remains visible in the tooltip's longer date string. */
function formatTickDate(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" })
}

/** Format a timestamp into the full long date used in the tooltip header,
 *  e.g. "Tuesday, Apr 28, 2026". en-IN locale matches the rest of the UI. */
function formatTooltipDate(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleDateString("en-IN", {
    weekday: "long",
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

interface FanTooltipEntry {
  name: string
  value: number
  color: string
  payload: ChartPoint
}

function FanTooltip({
  active,
  payload,
  currency,
  ticker,
}: {
  active?: boolean
  payload?: FanTooltipEntry[]
  currency: string
  ticker: string
}) {
  if (!active || !payload?.length) return null
  const p = payload[0]?.payload
  if (!p) return null
  // De-dup entries that share a name (Recharts can include hidden
  // duplicates when activeDot fires across multiple series).
  const seen = new Set<string>()
  const rows = payload.filter((entry) => {
    if (entry.value == null || !Number.isFinite(entry.value)) return false
    if (seen.has(entry.name)) return false
    seen.add(entry.name)
    return true
  })
  if (rows.length === 0) return null
  // Display ticker minus the exchange suffix so the heading stays compact
  // (e.g. "HDFCBANK" not "HDFCBANK.NS"). Falls back to the raw ticker.
  const displayTicker = ticker.split(".")[0] || ticker
  return (
    <div
      className="rounded-lg bg-white px-3 py-2 text-xs text-ink shadow-lg ring-1 ring-black/5 dark:bg-surface dark:ring-white/10 min-w-[180px]"
      data-testid="fv-fan-tooltip"
    >
      <div className="space-y-1">
        {rows.map((entry) => (
          <div key={entry.name} className="flex items-baseline justify-between gap-3">
            <span className="font-medium" style={{ color: entry.color }}>
              {displayTicker} {entry.name}
            </span>
            <span className="font-mono tabular-nums text-ink">
              {formatCurrency(entry.value, currency)}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-1.5 text-[10px] text-caption">{formatTooltipDate(p.t)}</p>
    </div>
  )
}

function buildSeries(
  history: PricePoint[],
  currentPrice: number,
  scenarios: FVProjectionFanProps["scenarios"],
): ChartPoint[] {
  const todayTs = Date.now()
  // Bucket history into the most recent ~24 monthly samples.
  const monthly: { m: number; t: number; actual: number; date: string }[] = []
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
      const upper = lastTs - (offset - 1) * MS_PER_MONTH
      const lower = lastTs - offset * MS_PER_MONTH
      const samples = sorted.filter((p) => {
        const t = new Date(p.date).getTime()
        return t > lower && t <= upper && Number.isFinite(p.price) && p.price > 0
      })
      if (samples.length > 0) {
        const pt = samples[samples.length - 1]
        const ts = new Date(pt.date).getTime()
        monthly.push({
          m: -offset,
          t: ts,
          actual: pt.price,
          date: pt.date,
        })
      }
    }
  }
  const series: ChartPoint[] = monthly.map((p) => ({
    m: p.m,
    t: p.t,
    actual: p.actual,
    date: p.date,
  }))

  // Ensure month 0 (today) has the current price + scenario starting points
  // so the dashed lines anchor cleanly to "today".
  const todayDate = new Date(todayTs).toISOString().slice(0, 10)
  const today: ChartPoint = {
    m: 0,
    t: todayTs,
    actual: currentPrice > 0 ? currentPrice : undefined,
    bear: currentPrice,
    base: currentPrice,
    bull: currentPrice,
    date: todayDate,
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
    const ts = todayTs + m * MS_PER_MONTH
    series.push({
      m,
      t: ts,
      bear: currentPrice + (scenarios.bear.iv - currentPrice) * t,
      base: currentPrice + (scenarios.base.iv - currentPrice) * t,
      bull: currentPrice + (scenarios.bull.iv - currentPrice) * t,
      date: new Date(ts).toISOString().slice(0, 10),
    })
  }

  return series.sort((a, b) => a.m - b.m)
}

/** Custom renderer for the endpoint price labels. Drops a small text
 *  badge to the right of the terminal dot, color-matched to the line. */
function EndpointLabel({
  x,
  y,
  value,
  fill,
}: {
  x?: number
  y?: number
  value?: string
  fill?: string
}) {
  if (x == null || y == null || !value) return null
  return (
    <text
      x={x + 6}
      y={y}
      dy={4}
      fill={fill}
      fontSize={11}
      fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
      fontWeight={600}
      textAnchor="start"
    >
      {value}
    </text>
  )
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

  // Calendar-tick timestamps. Anchor on today's start-of-month so ticks
  // land on month boundaries (e.g. "Jul 25") rather than mid-month dates.
  // Spacing: 6 months — keeps the 24m back + 60m forward window readable
  // at typical desktop widths (~14 ticks) and remains scannable on tablet.
  // A 3-month spacing would push to ~28 ticks and crowd labels under
  // ~900px viewport widths.
  const { xDomain, xTicks } = useMemo(() => {
    const now = new Date()
    const anchor = new Date(now.getFullYear(), now.getMonth(), 1).getTime()
    const ticks: number[] = []
    for (let m = historyExtent; m <= HORIZON_MONTHS; m += 6) {
      ticks.push(anchor + m * MS_PER_MONTH)
    }
    const domain: [number, number] = [
      anchor + historyExtent * MS_PER_MONTH,
      anchor + HORIZON_MONTHS * MS_PER_MONTH,
    ]
    return { xDomain: domain, xTicks: ticks }
  }, [historyExtent])

  const todayTs = useMemo(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1).getTime()
  }, [])

  const showSkeleton = isLoading && !historyOverride
  const showEmpty =
    !showSkeleton &&
    !hasAnyActual &&
    (!currentPrice || currentPrice <= 0)

  const bearCagr = impliedCagr(currentPrice, scenarios.bear.iv, 5)
  const baseCagr = impliedCagr(currentPrice, scenarios.base.iv, 5)
  const bullCagr = impliedCagr(currentPrice, scenarios.bull.iv, 5)

  // Endpoint timestamp: same x-coordinate the projection lines terminate
  // at, used by the ReferenceDot + label group on the right edge.
  const endpointTs = useMemo(() => {
    return todayTs + HORIZON_MONTHS * MS_PER_MONTH
  }, [todayTs])

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
        <div className="w-full" style={{ height: 280 }} data-testid="fv-projection-chart">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={points}
              // Right margin holds the endpoint price labels + right
              // y-axis tick text. Left margin trimmed since axis moved.
              margin={{ top: 12, right: 92, left: 8, bottom: 8 }}
            >
              <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 4" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={xDomain}
                ticks={xTicks}
                tickFormatter={formatTickDate}
                stroke="var(--color-caption)"
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: "var(--color-border)" }}
                allowDataOverflow
              />
              <YAxis
                orientation="right"
                stroke="var(--color-caption)"
                fontSize={10}
                tickFormatter={(v) => formatCurrency(v, currency)}
                width={64}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                cursor={{
                  stroke: "var(--color-caption)",
                  strokeDasharray: "3 3",
                  strokeWidth: 1,
                }}
                content={
                  <FanTooltip currency={currency} ticker={ticker} />
                }
              />
              <ReferenceLine
                x={todayTs}
                stroke="var(--color-caption)"
                strokeDasharray="3 3"
              >
                <Label value="Today" position="top" fontSize={10} fill="var(--color-caption)" />
              </ReferenceLine>
              <Line
                type="monotone"
                dataKey="actual"
                name="Price"
                stroke="var(--color-brand)"
                strokeWidth={2}
                dot={false}
                activeDot={{
                  r: 4,
                  fill: "var(--color-brand)",
                  stroke: "var(--color-bg)",
                  strokeWidth: 2,
                }}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="bull"
                name="Bull"
                stroke="var(--color-success)"
                strokeWidth={1.5}
                strokeDasharray="2 3"
                dot={false}
                activeDot={false}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="base"
                name="Base"
                stroke="var(--color-brand)"
                strokeWidth={1.5}
                strokeDasharray="2 3"
                dot={false}
                activeDot={false}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="bear"
                name="Bear"
                stroke="var(--color-danger)"
                strokeWidth={1.5}
                strokeDasharray="2 3"
                dot={false}
                activeDot={false}
                connectNulls
                isAnimationActive={false}
              />
              {/* Endpoint dots + price labels at +5y. Rendered as
                  ReferenceDot+text overlay rather than LabelList so the
                  positioning is deterministic (LabelList anchors to the
                  last data point in the series which may shift if the
                  projection windows ever change). */}
              <ReferenceDot
                x={endpointTs}
                y={scenarios.bull.iv}
                r={3.5}
                fill="var(--color-success)"
                stroke="none"
                label={
                  <EndpointLabel
                    value={formatCurrency(scenarios.bull.iv, currency)}
                    fill="var(--color-success)"
                  />
                }
              />
              <ReferenceDot
                x={endpointTs}
                y={scenarios.base.iv}
                r={3.5}
                fill="var(--color-brand)"
                stroke="none"
                label={
                  <EndpointLabel
                    value={formatCurrency(scenarios.base.iv, currency)}
                    fill="var(--color-brand)"
                  />
                }
              />
              <ReferenceDot
                x={endpointTs}
                y={scenarios.bear.iv}
                r={3.5}
                fill="var(--color-danger)"
                stroke="none"
                label={
                  <EndpointLabel
                    value={formatCurrency(scenarios.bear.iv, currency)}
                    fill="var(--color-danger)"
                  />
                }
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
