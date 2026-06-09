"use client"

/**
 * ValuationHistoryPanel — Premium Feel R3 calibration chart.
 *
 * Renders the past `N` months of (date, price, fair_value, deviation)
 * observations from /api/v1/public/valuation-history/{ticker} as:
 *   1. A row of read-only stats chips (n observations, median error,
 *      pct within ±20%, discount threshold).
 *   2. A two-line chart: realized close (solid brand-blue) + model
 *      fair-value estimate (dashed caption). Hover crosshair surfaces
 *      (price, FV, deviation) for the hovered date. Small diamond
 *      markers at "signal event" dates (where deviation crossed
 *      -threshold%).
 *   3. A bulleted caveats block including the SEBI-mandated footnote.
 *
 * Empty state:
 *   * If fewer than 12 observations exist, the backend returns
 *     stats=null and a single caveat naming the deficit. We render an
 *     icon + the caveat copy in place of the chart.
 *
 * SEBI discipline:
 *   * Descriptive, observational vocabulary throughout
 *     ("calibration", "tracked", "hypothetical outcome").
 *   * No advisory verbs. Footnote pinned to the panel:
 *       "Past calibration is a description of model behavior, not a
 *        forecast of future outcomes. Not investment advice."
 *
 * Visual contract mirrors FVProjectionFan (PR #767):
 *   * Calendar-month x-axis ticks
 *   * Right-side y-axis with currency-formatted ticks
 *   * Dashed crosshair via Tooltip cursor
 *   * Light + dark mode via CSS variables
 */

import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Scatter,
} from "recharts"
import {
  getValuationHistoryBacktest,
} from "@/lib/api"
import type {
  ValuationHistoryBacktestResponse,
  ValuationHistorySeriesPoint,
} from "@/types/api"
import { formatCurrency } from "@/lib/utils"

export interface ValuationHistoryPanelProps {
  ticker: string
  currency: string
}

interface ChartPoint extends ValuationHistorySeriesPoint {
  t: number              // epoch ms — drives the numeric time x-axis
  signal_y?: number      // y-coordinate for the diamond marker (only on events)
}

/** Formatter for the calendar-month x-axis label, e.g. "Jul 25". */
function formatTickDate(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" })
}

/** Long-form date string for the tooltip header. */
function formatTooltipDate(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleDateString("en-IN", {
    weekday: "long",
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

interface TooltipEntry {
  name: string
  value: number
  color: string
  payload: ChartPoint
}

function CalibrationTooltip({
  active,
  payload,
  currency,
  ticker,
}: {
  active?: boolean
  payload?: TooltipEntry[]
  currency: string
  ticker: string
}) {
  if (!active || !payload?.length) return null
  const p = payload[0]?.payload
  if (!p) return null
  const displayTicker = ticker.split(".")[0] || ticker
  const dev = p.deviation_pct
  const devSign = dev >= 0 ? "+" : ""
  return (
    <div
      className="rounded-lg bg-white px-3 py-2 text-xs text-ink shadow-lg ring-1 ring-black/5 dark:bg-surface dark:ring-white/10 min-w-[200px]"
      data-testid="valuation-history-tooltip"
    >
      <p className="text-[10px] text-caption mb-1.5">{formatTooltipDate(p.t)}</p>
      <div className="space-y-1">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-medium text-brand">{displayTicker} Price</span>
          <span className="font-mono tabular-nums text-ink">
            {formatCurrency(p.price, currency)}
          </span>
        </div>
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-medium text-caption">Fair value</span>
          <span className="font-mono tabular-nums text-ink">
            {formatCurrency(p.fair_value, currency)}
          </span>
        </div>
        <div className="flex items-baseline justify-between gap-3 pt-1 border-t border-border/60">
          <span className="font-medium text-caption">Deviation</span>
          <span
            className={
              "font-mono tabular-nums " +
              (dev <= -10 ? "text-success" : dev >= 10 ? "text-danger" : "text-ink")
            }
          >
            {devSign}
            {dev.toFixed(1)}%
          </span>
        </div>
      </div>
    </div>
  )
}

function StatsChip({
  label,
  value,
  testId,
}: {
  label: string
  value: string
  testId: string
}) {
  return (
    <div
      data-testid={testId}
      className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2.5 py-1.5"
    >
      <span className="text-[11px] text-caption">{label}</span>
      <span className="ml-auto text-[12px] font-mono tabular-nums font-semibold text-ink">
        {value}
      </span>
    </div>
  )
}

function PanelSkeleton() {
  return (
    <div
      className="bg-bg rounded-2xl border border-border p-4"
      data-testid="valuation-history-skeleton"
    >
      <div className="h-4 w-44 bg-surface rounded animate-pulse mb-2" />
      <div className="h-3 w-64 bg-surface rounded animate-pulse mb-4" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-8 rounded-lg bg-surface animate-pulse" />
        ))}
      </div>
      <div className="h-[280px] rounded-lg bg-surface animate-pulse" />
    </div>
  )
}

function PanelError({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      className="bg-bg rounded-2xl border border-border p-4"
      data-testid="valuation-history-error"
    >
      <h2 className="text-sm font-semibold text-ink mb-2">Valuation History</h2>
      <div className="rounded-lg border border-dashed border-border p-4 text-xs text-caption">
        <p>Couldn&apos;t load valuation history.</p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 text-brand hover:underline font-medium"
        >
          Try again
        </button>
      </div>
    </div>
  )
}

function PanelEmptyState({ caveat }: { caveat: string }) {
  return (
    <div
      className="rounded-lg border border-dashed border-border p-6 text-center"
      data-testid="valuation-history-empty"
    >
      {/* Soft hourglass icon — purely decorative. */}
      <svg
        className="mx-auto mb-2 h-8 w-8 text-caption opacity-60"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        aria-hidden
      >
        <path d="M6 2h12M6 22h12M7 2v5l5 5-5 5v5M17 2v5l-5 5 5 5v5" />
      </svg>
      <p className="text-sm text-ink font-medium">Not enough history yet</p>
      <p className="mt-1 text-xs text-caption">{caveat}</p>
    </div>
  )
}

export default function ValuationHistoryPanel({
  ticker,
  currency,
}: ValuationHistoryPanelProps) {
  const query = useQuery<ValuationHistoryBacktestResponse>({
    queryKey: ["valuation-history-backtest", ticker],
    queryFn: () => getValuationHistoryBacktest(ticker),
    // Backend caches 1h; UI freshness buffer at 5m so a single page
    // navigation never re-fetches and the chart stays stable.
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const { points, signalPoints, yDomain } = useMemo(() => {
    const series = query.data?.series ?? []
    const threshold = query.data?.stats?.signal_threshold_pct ?? 20
    const allValues: number[] = []
    const out: ChartPoint[] = series.map((p) => {
      allValues.push(p.price, p.fair_value)
      const ts = new Date(p.date).getTime()
      // Mark a signal-event point so the Scatter overlay can render
      // a diamond at the entry price (visual cue: "model flagged a
      // discount of ≥ threshold here").
      const isEvent = p.deviation_pct <= -threshold
      return {
        ...p,
        t: ts,
        signal_y: isEvent ? p.price : undefined,
      }
    })
    const signals = out.filter((p) => p.signal_y !== undefined)
    const min = Math.min(...allValues)
    const max = Math.max(...allValues)
    // Pad ±5% so markers / dots don't touch the axis edges.
    const pad = Math.max((max - min) * 0.05, 1)
    return {
      points: out,
      signalPoints: signals,
      yDomain: allValues.length
        ? ([Math.max(0, min - pad), max + pad] as [number, number])
        : ([0, 1] as [number, number]),
    }
  }, [query.data])

  if (query.isLoading && !query.data) return <PanelSkeleton />
  if (query.isError || !query.data) {
    return <PanelError onRetry={() => query.refetch()} />
  }

  const data = query.data
  const stats = data.stats
  const hasStats = stats !== null
  const hasChart = data.series.length >= 12
  const monthsCopy = `${data.history_window_months} month${data.history_window_months === 1 ? "" : "s"}`

  return (
    <div
      className="bg-bg rounded-2xl border border-border p-4"
      data-testid="valuation-history-panel"
    >
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-ink">Valuation History</h2>
        <p className="text-xs text-caption">
          Hypothetical model calibration over {monthsCopy}.
        </p>
      </div>

      {hasStats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
          <StatsChip
            label="Observations"
            value={`${stats!.n_observations}`}
            testId="stats-chip-observations"
          />
          <StatsChip
            label="Median error"
            value={`${stats!.median_abs_error_pct.toFixed(1)}%`}
            testId="stats-chip-median-error"
          />
          <StatsChip
            label={"Within ±20%"}
            value={`${Math.round(stats!.pct_within_20 * 100)}%`}
            testId="stats-chip-within-20"
          />
          <StatsChip
            label="Discount threshold"
            value={`-${stats!.signal_threshold_pct.toFixed(0)}%`}
            testId="stats-chip-threshold"
          />
        </div>
      )}

      {hasChart ? (
        <div
          className="w-full"
          style={{ height: 280 }}
          data-testid="valuation-history-chart"
        >
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={points}
              margin={{ top: 12, right: 16, left: 8, bottom: 8 }}
            >
              <CartesianGrid
                stroke="var(--color-border)"
                strokeDasharray="2 4"
                vertical={false}
              />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={formatTickDate}
                stroke="var(--color-caption)"
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: "var(--color-border)" }}
                allowDataOverflow
              />
              <YAxis
                orientation="right"
                domain={yDomain}
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
                  <CalibrationTooltip currency={currency} ticker={ticker} />
                }
              />
              <Line
                type="monotone"
                dataKey="price"
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
                dataKey="fair_value"
                name="Fair value"
                stroke="var(--color-caption)"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
                activeDot={false}
                connectNulls
                isAnimationActive={false}
              />
              {/* Signal-event markers — small diamonds at entry prices.
                  Recharts Scatter projects on the same x/y scales as the
                  surrounding lines, so the visual stays aligned even
                  when the y-domain rescales. */}
              {signalPoints.length > 0 && (
                <Scatter
                  data={signalPoints}
                  name="Signal event"
                  dataKey="signal_y"
                  fill="var(--color-success)"
                  shape="diamond"
                  isAnimationActive={false}
                  legendType="none"
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <PanelEmptyState
          caveat={
            data.caveats[0] ??
            "Calibration stats need at least 12 months of fair-value history."
          }
        />
      )}

      <div className="mt-3 text-[11px] text-caption space-y-1">
        {data.caveats.map((c, i) => (
          <p
            key={i}
            className="flex gap-2"
            data-testid={`valuation-history-caveat-${i}`}
          >
            <span aria-hidden>&bull;</span>
            <span>{c}</span>
          </p>
        ))}
        <p className="flex gap-2 pt-1 border-t border-border/40 italic">
          <span aria-hidden>&bull;</span>
          <span>
            Past calibration is a description of model behavior, not a
            forecast of future outcomes. Not investment advice.
          </span>
        </p>
      </div>
    </div>
  )
}
