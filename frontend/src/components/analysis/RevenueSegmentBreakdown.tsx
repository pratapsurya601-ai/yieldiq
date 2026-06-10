"use client"

/**
 * RevenueSegmentBreakdown — twin donut charts for business + geography
 * revenue split. AlphaSpread + Tickertape both ship this; we read the
 * latest extracted ar_signals.segment_data via the public revenue-
 * segments endpoint.
 *
 * Honesty discipline:
 *   - When the ticker has no AR extraction yet, render a clearly
 *     labelled "AR signals coming soon" empty state. NEVER fabricate.
 *   - The fastest-growing chip only renders when the latest AR carried
 *     yoy_growth_pct for ≥1 segment AND the top growth is positive.
 *   - Withheld envelope → neutral "quality review pending" placeholder,
 *     same pattern as ARSignalsPanel.
 *
 * Endpoint: GET /api/v1/public/revenue-segments/{ticker}
 *
 * Self-contained SVG donut (no recharts dep) — kept light because this
 * panel renders inside the Financials tab below the heavier Sankey +
 * Waterfall components.
 */

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import axios from "axios"

import { formatINR } from "@/lib/currency"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// Palette — tuned for both light + dark. Business uses cool blues /
// teals; geography uses warm earth tones so a side-by-side glance
// reads as two different categories.
const BUSINESS_PALETTE = [
  "#1d4ed8", // blue-700
  "#0891b2", // cyan-600
  "#0d9488", // teal-600
  "#7c3aed", // violet-600
  "#0369a1", // sky-700
  "#4338ca", // indigo-700
  "#0e7490", // cyan-700
  "#5b21b6", // violet-800
]

const GEO_PALETTE = [
  "#b45309", // amber-700
  "#dc2626", // red-600
  "#ca8a04", // yellow-600
  "#9a3412", // orange-800
  "#a16207", // yellow-700
  "#c2410c", // orange-700
  "#7c2d12", // orange-900
  "#92400e", // amber-800
]

const OTHER_FILL = "#94a3b8" // slate-400

export interface Segment {
  name: string
  revenue_cr: number
  pct: number
  ebit_cr: number | null
  yoy_growth_pct: number | null
  fy: string | null
}

export interface RevenueSegmentsPayload {
  ticker: string | null
  fiscal_year: number | null
  published_at: string | null
  business_segments: Segment[]
  geo_segments: Segment[]
  trend: { name: string; yoy_growth_pct: number } | null
  withheld: boolean
  source: string
}

interface PanelProps {
  ticker: string
  initialData?: RevenueSegmentsPayload | null
}

async function fetchSegments(ticker: string): Promise<RevenueSegmentsPayload> {
  const url = `${API_BASE}/api/v1/public/revenue-segments/${encodeURIComponent(
    ticker,
  )}`
  const res = await axios.get(url, { timeout: 15000 })
  return res.data as RevenueSegmentsPayload
}

/**
 * Roll segments past `topN` into a single "Other" bucket so the donut
 * stays readable. We keep the underlying revenue + pct so the legend
 * total still reconciles.
 */
function rollupOther(items: Segment[], topN: number): Segment[] {
  if (items.length <= topN) return items
  const head = items.slice(0, topN)
  const tail = items.slice(topN)
  const revenue = tail.reduce((s, r) => s + (r.revenue_cr || 0), 0)
  const pct = tail.reduce((s, r) => s + (r.pct || 0), 0)
  return [
    ...head,
    {
      name: `Other (${tail.length})`,
      revenue_cr: Math.round(revenue * 100) / 100,
      pct: Math.round(pct * 100) / 100,
      ebit_cr: null,
      yoy_growth_pct: null,
      fy: tail[0]?.fy ?? null,
    },
  ]
}

/**
 * Build the SVG arc-path d-attribute for a donut slice. Donut sized
 * to a unit-circle box at (50, 50). Caller passes startAngle /
 * endAngle in radians, CCW from -π/2 (top).
 */
function arcPath(
  startAngle: number,
  endAngle: number,
  outerR: number,
  innerR: number,
): string {
  const start = polar(50, 50, outerR, startAngle)
  const end = polar(50, 50, outerR, endAngle)
  const startInner = polar(50, 50, innerR, endAngle)
  const endInner = polar(50, 50, innerR, startAngle)
  const largeArc = endAngle - startAngle > Math.PI ? 1 : 0
  return [
    `M ${start.x} ${start.y}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 1 ${end.x} ${end.y}`,
    `L ${startInner.x} ${startInner.y}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 0 ${endInner.x} ${endInner.y}`,
    "Z",
  ].join(" ")
}

function polar(cx: number, cy: number, r: number, angleRad: number) {
  return {
    x: cx + r * Math.cos(angleRad - Math.PI / 2),
    y: cy + r * Math.sin(angleRad - Math.PI / 2),
  }
}

interface DonutProps {
  items: Segment[]
  palette: string[]
  titleId: string
  ariaLabel: string
}

function Donut({ items, palette, titleId, ariaLabel }: DonutProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  // Cumulative slice angles. If the bucket only has one item, render a
  // full ring rather than a near-360 arc (avoids artefacts where the
  // start and end point collapse).
  const slices = useMemo(() => {
    const total = items.reduce((s, r) => s + (r.pct || 0), 0)
    if (total <= 0) return []
    let acc = 0
    return items.map((row, idx) => {
      const frac = (row.pct || 0) / total
      const start = acc * 2 * Math.PI
      const end = (acc + frac) * 2 * Math.PI
      acc += frac
      return {
        row,
        start,
        end,
        color: idx < palette.length ? palette[idx] : OTHER_FILL,
      }
    })
  }, [items, palette])

  if (slices.length === 0) {
    return null
  }

  // Single-slice ring (100% one segment) — draw a plain ring so we
  // avoid the arc-collapse rendering bug.
  const singleSlice = slices.length === 1

  const hovered = hoverIdx !== null ? slices[hoverIdx] : null

  return (
    <div className="flex flex-col items-center">
      <svg
        viewBox="0 0 100 100"
        role="img"
        aria-labelledby={titleId}
        aria-label={ariaLabel}
        className="w-full max-w-[220px] h-auto"
      >
        <title id={titleId}>{ariaLabel}</title>
        {singleSlice ? (
          <>
            <circle
              cx="50"
              cy="50"
              r="44"
              fill={slices[0].color}
              onMouseEnter={() => setHoverIdx(0)}
              onMouseLeave={() => setHoverIdx(null)}
            />
            <circle cx="50" cy="50" r="26" className="fill-bg" />
          </>
        ) : (
          slices.map((s, i) => (
            <path
              key={`${s.row.name}-${i}`}
              d={arcPath(s.start, s.end, 44, 26)}
              fill={s.color}
              opacity={hoverIdx === null || hoverIdx === i ? 1 : 0.45}
              onMouseEnter={() => setHoverIdx(i)}
              onMouseLeave={() => setHoverIdx(null)}
              data-testid={`donut-slice-${i}`}
              style={{ transition: "opacity 120ms ease" }}
            />
          ))
        )}
        <text
          x="50"
          y={hovered ? 47 : 52}
          textAnchor="middle"
          className="fill-ink"
          style={{ fontSize: "8px", fontWeight: 600 }}
        >
          {hovered
            ? `${hovered.row.pct.toFixed(1)}%`
            : `${items.length} segs`}
        </text>
        {hovered && (
          <text
            x="50"
            y="56"
            textAnchor="middle"
            className="fill-caption"
            style={{ fontSize: "5px" }}
          >
            {hovered.row.name.length > 22
              ? `${hovered.row.name.slice(0, 21)}…`
              : hovered.row.name}
          </text>
        )}
      </svg>
    </div>
  )
}

interface LegendProps {
  items: Segment[]
  palette: string[]
  testIdPrefix: string
}

function Legend({ items, palette, testIdPrefix }: LegendProps) {
  return (
    <ul
      className="mt-3 space-y-1.5 text-[12px]"
      data-testid={`${testIdPrefix}-legend`}
    >
      {items.map((row, idx) => {
        const swatch = idx < palette.length ? palette[idx] : OTHER_FILL
        return (
          <li
            key={`${row.name}-${idx}`}
            className="flex items-center justify-between gap-2"
            data-testid={`${testIdPrefix}-row-${idx}`}
          >
            <div className="flex items-center gap-2 min-w-0">
              <span
                aria-hidden="true"
                className="inline-block h-2.5 w-2.5 rounded-sm shrink-0"
                style={{ backgroundColor: swatch }}
              />
              <span className="text-ink truncate" title={row.name}>
                {row.name}
              </span>
            </div>
            <div className="flex items-center gap-2 shrink-0 tabular-nums">
              <span className="text-caption">
                {formatINR(row.revenue_cr, { compact: true })}
              </span>
              <span className="text-ink font-medium w-12 text-right">
                {row.pct.toFixed(1)}%
              </span>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

interface ChartCardProps {
  title: string
  caption: string
  items: Segment[]
  palette: string[]
  testIdPrefix: string
  emptyLabel: string
}

function ChartCard({
  title,
  caption,
  items,
  palette,
  testIdPrefix,
  emptyLabel,
}: ChartCardProps) {
  if (items.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center text-center px-3 py-8"
        data-testid={`${testIdPrefix}-empty`}
      >
        <h3 className="text-[12px] font-semibold uppercase tracking-wide text-caption mb-1">
          {title}
        </h3>
        <p className="text-xs text-caption">{emptyLabel}</p>
      </div>
    )
  }
  return (
    <div data-testid={`${testIdPrefix}-card`}>
      <h3 className="text-[12px] font-semibold uppercase tracking-wide text-caption mb-2 text-center">
        {title}
      </h3>
      <Donut
        items={items}
        palette={palette}
        titleId={`${testIdPrefix}-donut-title`}
        ariaLabel={caption}
      />
      <Legend
        items={items}
        palette={palette}
        testIdPrefix={testIdPrefix}
      />
    </div>
  )
}

export default function RevenueSegmentBreakdown({
  ticker,
  initialData,
}: PanelProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["revenue-segments", ticker],
    queryFn: () => fetchSegments(ticker),
    enabled: !!ticker && initialData === undefined,
    staleTime: 6 * 60 * 60 * 1000, // 6h — AR data is slow-moving
    retry: 1,
    initialData: initialData === undefined ? undefined : initialData,
  })

  const payload = data ?? initialData ?? null

  // Withheld envelope branch — neutral copy, no free text.
  if (payload && payload.withheld) {
    return (
      <div
        className="bg-bg rounded-2xl border border-border p-4"
        data-testid="revenue-segments-withheld"
      >
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-ink">
            Revenue by Segment
          </h2>
          <span className="text-[10px] uppercase tracking-wide text-caption">
            quality review
          </span>
        </div>
        <p className="text-xs italic text-caption">
          Withheld pending review. The most recent extraction tripped the
          quality vocabulary check and is queued for operator re-review.
        </p>
      </div>
    )
  }

  // Loading skeleton.
  if (isLoading) {
    return (
      <div
        className="bg-bg rounded-2xl border border-border p-4"
        data-testid="revenue-segments-loading"
      >
        <div className="h-4 w-40 bg-surface rounded animate-pulse mb-4" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="h-44 bg-surface rounded animate-pulse" />
          <div className="h-44 bg-surface rounded animate-pulse" />
        </div>
      </div>
    )
  }

  // Network error / missing payload — render the same honest empty
  // state as "no extraction yet" rather than a scary error chip. The
  // panel is additive (Sankey + Waterfall above it stay live).
  const business = rollupOther(payload?.business_segments ?? [], 6)
  const geo = rollupOther(payload?.geo_segments ?? [], 6)
  const hasAny = business.length > 0 || geo.length > 0

  if (!hasAny) {
    return (
      <div
        className="bg-bg rounded-2xl border border-border p-4"
        data-testid="revenue-segments-empty"
      >
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-ink">
            Revenue by Segment
          </h2>
          <span className="text-[10px] uppercase tracking-wide text-caption">
            annual report
          </span>
        </div>
        <p className="text-xs text-caption">
          {isError
            ? "Could not load segment breakdown. Try refreshing."
            : "Segment breakdown will appear once the annual report has been processed. Coverage is rolling out across the universe."}
        </p>
      </div>
    )
  }

  const fyLabel = payload?.fiscal_year ? `FY${String(payload.fiscal_year).slice(-2)}` : null
  const publishedLabel = payload?.published_at
    ? new Date(payload.published_at).toLocaleDateString("en-IN", {
        month: "short",
        year: "numeric",
      })
    : null

  return (
    <div
      className="bg-bg rounded-2xl border border-border p-4"
      data-testid="revenue-segments-panel"
    >
      <header className="flex items-center justify-between mb-1">
        <h2 className="text-sm font-semibold text-ink">
          Revenue by Segment
        </h2>
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-caption">
          {fyLabel && <span data-testid="revenue-segments-fy">{fyLabel}</span>}
          {publishedLabel && (
            <span aria-hidden="true">·</span>
          )}
          {publishedLabel && <span>{publishedLabel}</span>}
        </div>
      </header>
      <p className="text-[11px] text-caption mb-3">
        Source: latest annual report. Business segments left, geography
        right. Hover a slice for share, revenue, and segment name.
      </p>

      {payload?.trend && (
        <div
          className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-[11px]"
          data-testid="revenue-segments-trend-chip"
        >
          <span className="text-caption">Fastest growing:</span>
          <span className="font-medium text-ink truncate max-w-[220px]" title={payload.trend.name}>
            {payload.trend.name}
          </span>
          <span className="font-semibold text-emerald-700 dark:text-emerald-400 tabular-nums">
            +{payload.trend.yoy_growth_pct.toFixed(1)}% YoY
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <ChartCard
          title="Business segments"
          caption="Revenue share by business segment"
          items={business}
          palette={BUSINESS_PALETTE}
          testIdPrefix="rev-seg-business"
          emptyLabel="No business-segment split disclosed in the latest AR."
        />
        <ChartCard
          title="Geographic segments"
          caption="Revenue share by geography"
          items={geo}
          palette={GEO_PALETTE}
          testIdPrefix="rev-seg-geo"
          emptyLabel="No geographic split disclosed in the latest AR."
        />
      </div>
    </div>
  )
}
