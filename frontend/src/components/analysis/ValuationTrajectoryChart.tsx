"use client"

/**
 * ValuationTrajectoryChart — T5.2 (2026-06-10).
 *
 * AlphaSpread-grade Intrinsic-Value trajectory chart. Renders the
 * per-day persisted DCF fair value alongside market price, overlays
 * the current bull / base / bear scenario as horizontal reference
 * bands, and (when supplied) overlays today's composite intrinsic
 * value (Phase C, task #303) as a separate reference line so the
 * user can see at a glance whether composite agrees with DCF.
 *
 * Why scenarios + composite IV are passed as PROPS rather than
 * per-day series:
 *   - `fair_value_history` schema (data_pipeline/models.py:258) stores
 *     ONE FV per (ticker, date). There is no per-day bull/bear or
 *     composite history at rest — those are products of TODAY's
 *     analysis run.
 *   - Building a real per-day scenarios series requires a schema
 *     change + multi-year backfill. Out of scope for T5.2.
 *   - The honest visualization is: "here's how DCF FV has tracked
 *     the price over time, and here are the bands today's analysis
 *     anchors to". That's what AlphaSpread does for free users too —
 *     scenarios are bands across the chart, not a series.
 *
 * Sits ABOVE the existing FairValueHistory component in AnalysisBody
 * (option b from the brief). FairValueHistory keeps its tier-gated
 * 1Y/2Y/3Y selector and its own DB-bound query; this component is a
 * thin presentational layer that re-uses the same fetched data via
 * the shared React-Query cache key (zero extra round-trips).
 */
import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  ReferenceLine,
  ReferenceArea,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts"
import { getFVHistory, type FVHistoryPoint, type FVHistoryResponse } from "@/lib/api"
import { cn, formatCurrency } from "@/lib/utils"

export type TrajectoryRange = "1Y" | "3Y" | "5Y" | "All"

export interface ValuationTrajectoryChartProps {
  ticker: string
  /** ISO currency code (defaults to INR). */
  currency?: string
  /** Today's quote — drawn as a horizontal reference. */
  currentPrice?: number | null
  /** Today's composite intrinsic value (Phase C) — horizontal reference. */
  compositeIntrinsicValue?: number | null
  /** Today's scenario IVs from the live analysis. Drawn as bands. */
  scenarios?: {
    bull?: number | null
    base?: number | null
    bear?: number | null
  } | null
  /**
   * When provided, skips the network fetch and renders supplied
   * points directly. Test-only escape hatch — production callers
   * should leave undefined and let the component fetch.
   */
  historyOverride?: FVHistoryPoint[]
  className?: string
}

type ChartPoint = FVHistoryPoint & { displayDate: string; ts: number }

const RANGE_OPTIONS: TrajectoryRange[] = ["1Y", "3Y", "5Y", "All"]

function rangeToCutoffMs(range: TrajectoryRange, latestTs: number): number {
  if (range === "All") return 0
  const years = range === "1Y" ? 1 : range === "3Y" ? 3 : 5
  return latestTs - years * 365 * 24 * 60 * 60 * 1000
}

function rangeToYears(range: TrajectoryRange): number {
  return range === "1Y" ? 1 : range === "3Y" ? 3 : 5
}

function pctChange(from: number, to: number): number {
  if (!from || from === 0) return 0
  return ((to - from) / Math.abs(from)) * 100
}

function formatShortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", {
    month: "short",
    year: "2-digit",
  })
}

/* ------------------------------------------------------------------ */
/* Tooltip                                                             */
/* ------------------------------------------------------------------ */
interface TooltipPayloadEntry {
  payload?: ChartPoint
}

function TrajectoryTooltip({
  active,
  payload,
  currency,
  currentPrice,
  compositeIntrinsicValue,
}: {
  active?: boolean
  payload?: TooltipPayloadEntry[]
  currency: string
  currentPrice?: number | null
  compositeIntrinsicValue?: number | null
}) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null

  const gapToPrice =
    currentPrice && currentPrice > 0
      ? pctChange(currentPrice, point.fair_value)
      : null

  return (
    <div
      data-testid="trajectory-tooltip"
      className="rounded-xl border border-border bg-surface px-3 py-2 text-xs text-ink shadow-xl min-w-[210px]"
    >
      <p className="text-caption mb-1">
        {new Date(point.date).toLocaleDateString("en-IN", {
          day: "numeric",
          month: "short",
          year: "numeric",
        })}
      </p>
      <div className="flex justify-between font-medium">
        <span className="text-caption">DCF fair value</span>
        <span className="font-mono">
          {formatCurrency(point.fair_value, currency)}
        </span>
      </div>
      <div className="flex justify-between font-medium">
        <span className="text-caption">Market price</span>
        <span className="font-mono">
          {formatCurrency(point.price, currency)}
        </span>
      </div>
      <div
        className={cn(
          "flex justify-between font-semibold mt-1 pt-1 border-t border-border",
          point.mos_pct >= 0 ? "text-green-600" : "text-red-600",
        )}
      >
        <span>Gap (price vs FV)</span>
        <span className="font-mono">
          {point.mos_pct > 0 ? "+" : ""}
          {point.mos_pct.toFixed(1)}%
        </span>
      </div>
      {compositeIntrinsicValue != null && (
        <div className="mt-1 text-caption">
          Composite IV today:{" "}
          <span className="font-mono text-ink">
            {formatCurrency(compositeIntrinsicValue, currency)}
          </span>
        </div>
      )}
      {gapToPrice != null && (
        <div className="mt-0.5 text-caption">
          FV vs today&rsquo;s price: {gapToPrice > 0 ? "+" : ""}
          {gapToPrice.toFixed(1)}%
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Range selector                                                      */
/* ------------------------------------------------------------------ */
function RangeSelector({
  value,
  onChange,
  availableYears,
}: {
  value: TrajectoryRange
  onChange: (next: TrajectoryRange) => void
  availableYears: number
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Time range"
      className="flex gap-1 rounded-lg bg-bg p-0.5"
    >
      {RANGE_OPTIONS.map((opt) => {
        const disabled = opt !== "All" && rangeToYears(opt) > availableYears + 1
        const active = value === opt
        return (
          <button
            key={opt}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={`${opt} range`}
            disabled={disabled}
            onClick={() => onChange(opt)}
            className={cn(
              "text-xs px-2.5 py-1 rounded-md font-medium transition-colors min-w-[36px]",
              active
                ? "bg-brand text-white shadow-sm"
                : "text-caption hover:bg-border/40",
              disabled && "opacity-30 cursor-not-allowed hover:bg-transparent",
            )}
          >
            {opt}
          </button>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Insights panel                                                      */
/* ------------------------------------------------------------------ */
function ChartInsightsPanel({
  data,
  currentPrice,
  compositeIntrinsicValue,
  currency,
}: {
  data: ChartPoint[]
  currentPrice?: number | null
  compositeIntrinsicValue?: number | null
  currency: string
}) {
  const insights = useMemo(() => {
    if (data.length < 2) return [] as string[]
    const first = data[0]
    const last = data[data.length - 1]
    const out: string[] = []

    const fvTrend = pctChange(first.fair_value, last.fair_value)
    if (Math.abs(fvTrend) >= 1) {
      const arrow = fvTrend > 0 ? "up" : "down"
      out.push(
        `DCF fair value has trended ${arrow} ${Math.abs(fvTrend).toFixed(1)}% over the selected range.`,
      )
    } else {
      out.push("DCF fair value has been broadly stable over the selected range.")
    }

    const withinBand = data.filter(
      (d) => d.price <= d.fair_value * 1.2 && d.price >= d.fair_value * 0.8,
    ).length
    const pctWithin = Math.round((withinBand / data.length) * 100)
    out.push(
      `Market price traded within ±20% of DCF fair value on ${pctWithin}% of tracked days.`,
    )

    // Largest single-day FV revision
    let largestPct = 0
    let largestDate = ""
    for (let i = 1; i < data.length; i++) {
      const prev = data[i - 1].fair_value
      const cur = data[i].fair_value
      if (!prev) continue
      const drift = Math.abs(pctChange(prev, cur))
      if (drift > largestPct) {
        largestPct = drift
        largestDate = data[i].date
      }
    }
    if (largestPct >= 1 && largestDate) {
      out.push(
        `Largest single-day FV revision: ${largestPct.toFixed(1)}% on ${new Date(largestDate).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}.`,
      )
    }

    if (
      currentPrice &&
      currentPrice > 0 &&
      compositeIntrinsicValue &&
      compositeIntrinsicValue > 0
    ) {
      const gap = pctChange(currentPrice, compositeIntrinsicValue)
      const dir = gap >= 0 ? "above" : "below"
      out.push(
        `Today's composite intrinsic value sits ${Math.abs(gap).toFixed(1)}% ${dir} the live market price.`,
      )
    }

    return out
  }, [data, currentPrice, compositeIntrinsicValue, currency])

  if (insights.length === 0) return null

  return (
    <ul
      data-testid="trajectory-insights"
      className="mt-3 space-y-1.5 rounded-xl bg-bg p-3 text-xs text-body"
    >
      {insights.map((line, idx) => (
        <li key={idx} className="flex gap-2">
          <span className="text-caption">&middot;</span>
          <span>{line}</span>
        </li>
      ))}
    </ul>
  )
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */
export default function ValuationTrajectoryChart({
  ticker,
  currency = "INR",
  currentPrice,
  compositeIntrinsicValue,
  scenarios,
  historyOverride,
  className,
}: ValuationTrajectoryChartProps) {
  const [range, setRange] = useState<TrajectoryRange>("3Y")

  // Reuse the same React-Query key as FairValueHistory so this component
  // costs zero extra network — when the sibling component is also
  // mounted, both observers share the same cache entry.
  const { data, isLoading, isError } = useQuery<FVHistoryResponse>({
    queryKey: ["fv-history", ticker, 5],
    queryFn: () => getFVHistory(ticker, 5),
    enabled: !!ticker && !historyOverride,
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })

  const rawHistory: FVHistoryPoint[] = historyOverride ?? data?.data ?? []
  const hasData = rawHistory.length > 0

  const allPoints: ChartPoint[] = useMemo(
    () =>
      rawHistory.map((d) => ({
        ...d,
        displayDate: formatShortDate(d.date),
        ts: new Date(d.date).getTime(),
      })),
    [rawHistory],
  )

  const availableYears = useMemo(() => {
    if (allPoints.length < 2) return 0
    const spanMs = allPoints[allPoints.length - 1].ts - allPoints[0].ts
    return Math.max(0, Math.round(spanMs / (365 * 24 * 60 * 60 * 1000)))
  }, [allPoints])

  const filtered: ChartPoint[] = useMemo(() => {
    if (allPoints.length === 0) return []
    const latest = allPoints[allPoints.length - 1].ts
    const cutoff = rangeToCutoffMs(range, latest)
    return cutoff === 0 ? allPoints : allPoints.filter((p) => p.ts >= cutoff)
  }, [allPoints, range])

  // Y-axis domain — pad enough to include scenarios + composite if they
  // sit outside the historical envelope.
  const yDomain = useMemo<[number, number]>(() => {
    if (filtered.length === 0) return [0, 1]
    const values: number[] = []
    for (const p of filtered) {
      values.push(p.fair_value, p.price)
    }
    if (scenarios?.bear && scenarios.bear > 0) values.push(scenarios.bear)
    if (scenarios?.base && scenarios.base > 0) values.push(scenarios.base)
    if (scenarios?.bull && scenarios.bull > 0) values.push(scenarios.bull)
    if (currentPrice && currentPrice > 0) values.push(currentPrice)
    if (compositeIntrinsicValue && compositeIntrinsicValue > 0) {
      values.push(compositeIntrinsicValue)
    }
    const min = Math.min(...values)
    const max = Math.max(...values)
    return [min * 0.92, max * 1.08]
  }, [filtered, scenarios, currentPrice, compositeIntrinsicValue])

  /* ---------- Render branches ---------- */
  if (isLoading && !historyOverride) {
    return (
      <section
        data-testid="valuation-trajectory-chart"
        data-state="loading"
        className={cn(
          "bg-surface rounded-2xl border border-border p-5",
          className,
        )}
      >
        <div className="h-5 w-48 bg-bg rounded animate-pulse mb-3" />
        <div className="h-[380px] bg-bg rounded-xl animate-pulse" />
      </section>
    )
  }

  if (isError && !historyOverride) {
    return (
      <section
        data-testid="valuation-trajectory-chart"
        data-state="error"
        className={cn(
          "bg-surface rounded-2xl border border-border p-5",
          className,
        )}
      >
        <h3 className="text-sm font-semibold text-ink mb-2">
          Fair value trajectory
        </h3>
        <p className="text-xs text-caption">
          Trajectory data unavailable right now. Refresh in a moment.
        </p>
      </section>
    )
  }

  if (!hasData) {
    return (
      <section
        data-testid="valuation-trajectory-chart"
        data-state="empty"
        className={cn(
          "bg-surface rounded-2xl border border-border p-5",
          className,
        )}
      >
        <h3 className="text-sm font-semibold text-ink mb-2">
          Fair value trajectory
        </h3>
        <p className="text-xs text-caption">
          Trajectory builds up as the engine recomputes this ticker. Check
          back after a few daily refreshes.
        </p>
      </section>
    )
  }

  const bull = scenarios?.bull && scenarios.bull > 0 ? scenarios.bull : null
  const base = scenarios?.base && scenarios.base > 0 ? scenarios.base : null
  const bear = scenarios?.bear && scenarios.bear > 0 ? scenarios.bear : null

  return (
    <section
      data-testid="valuation-trajectory-chart"
      data-state="ready"
      className={cn(
        "bg-surface rounded-2xl border border-border p-5",
        className,
      )}
    >
      <header className="flex items-center justify-between mb-3 gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            Fair value vs price trajectory
          </h3>
          <p className="text-[11px] text-caption mt-0.5">
            DCF estimate over time, with today&rsquo;s scenario bands and
            composite intrinsic value overlaid.
          </p>
        </div>
        <RangeSelector
          value={range}
          onChange={setRange}
          availableYears={availableYears}
        />
      </header>

      <div className="h-[380px]" data-testid="trajectory-chart-canvas">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={filtered}
            margin={{ top: 12, right: 16, bottom: 8, left: 8 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
            <XAxis
              dataKey="displayDate"
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              interval={Math.max(0, Math.floor(filtered.length / 8))}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              domain={yDomain}
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              tickFormatter={(v: number) => formatCurrency(v, currency)}
              axisLine={false}
              tickLine={false}
              width={64}
            />
            <Tooltip
              content={
                <TrajectoryTooltip
                  currency={currency}
                  currentPrice={currentPrice ?? null}
                  compositeIntrinsicValue={compositeIntrinsicValue ?? null}
                />
              }
            />
            <Legend
              iconType="line"
              iconSize={14}
              wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
            />

            {/* Bull / bear band — horizontal shaded zone across the
                visible range. AlphaSpread renders these as wide green
                (bull) and red (bear) regions; we do the same with
                ReferenceArea so it never overlaps an axis-tick. */}
            {bull && base && (
              <ReferenceArea
                y1={base}
                y2={bull}
                fill="#16a34a"
                fillOpacity={0.08}
                stroke="none"
                ifOverflow="extendDomain"
                label={{
                  value: "Bull band",
                  position: "insideTopRight",
                  fontSize: 10,
                  fill: "#16a34a",
                }}
              />
            )}
            {bear && base && (
              <ReferenceArea
                y1={bear}
                y2={base}
                fill="#dc2626"
                fillOpacity={0.06}
                stroke="none"
                ifOverflow="extendDomain"
                label={{
                  value: "Bear band",
                  position: "insideBottomRight",
                  fontSize: 10,
                  fill: "#dc2626",
                }}
              />
            )}

            {/* Reference lines for today's anchors */}
            {currentPrice && currentPrice > 0 && (
              <ReferenceLine
                y={currentPrice}
                stroke="#185FA5"
                strokeDasharray="2 4"
                strokeWidth={1}
                label={{
                  value: `Price ${formatCurrency(currentPrice, currency)}`,
                  position: "insideTopLeft",
                  fontSize: 10,
                  fill: "#185FA5",
                }}
              />
            )}
            {compositeIntrinsicValue && compositeIntrinsicValue > 0 && (
              <ReferenceLine
                y={compositeIntrinsicValue}
                stroke="#9333ea"
                strokeDasharray="6 4"
                strokeWidth={1.5}
                label={{
                  value: `Composite IV ${formatCurrency(compositeIntrinsicValue, currency)}`,
                  position: "insideBottomLeft",
                  fontSize: 10,
                  fill: "#9333ea",
                }}
              />
            )}

            {/* The two primary historical series */}
            <Line
              type="monotone"
              dataKey="fair_value"
              name="DCF fair value"
              stroke="#16a34a"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="price"
              name="Market price"
              stroke="#185FA5"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <ChartInsightsPanel
        data={filtered}
        currentPrice={currentPrice ?? null}
        compositeIntrinsicValue={compositeIntrinsicValue ?? null}
        currency={currency}
      />
    </section>
  )
}
