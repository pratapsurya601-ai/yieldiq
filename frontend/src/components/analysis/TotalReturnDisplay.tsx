"use client"

// TotalReturnDisplay — price return vs total return (dividend reinvestment).
//
// Lives on the History tab of the analysis page. Material for high-payout
// names (FMCG, IT) where 5y total return can be 30%+ above price return.
//
// The big number tells the headline story: "₹1L invested 5 years ago in
// price-only returned ₹X; with dividend reinvestment, ₹Y." The breakdown
// rows split capital appreciation from reinvested dividends; the chart
// overlays the two cumulative-return curves so divergence is visible
// at a glance.
//
// SEBI-safe copy: descriptive only. We never say "buy"/"better"/"strong".

import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts"
import { getTotalReturn, type TotalReturnResponse } from "@/lib/api"
import { formatCurrency } from "@/lib/utils"
import { formatPct as formatPctCanonical } from "@/lib/formatNumbers"

interface Props {
  ticker: string
  /** Currency code (defaults to INR); only used for the rupee/dollar prefix. */
  currency?: string
  /** Optional company display name for the headline copy. */
  companyName?: string
}

type ViewMode = "total" | "price"
const YEARS_OPTIONS: { key: 1 | 3 | 5 | 10; label: string }[] = [
  { key: 1, label: "1Y" },
  { key: 3, label: "3Y" },
  { key: 5, label: "5Y" },
  { key: 10, label: "10Y" },
]

const DEFAULT_NOTIONAL = 100_000

// ── tiny helpers ──────────────────────────────────────────────────────

/* Returns are deltas → signed percentage via the canonical formatter
   (lib/formatNumbers). Missing values render the standard em-dash. */
function formatPct(value: number | null | undefined): string {
  return formatPctCanonical(value, { signed: true })
}

function pctTone(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "text-caption"
  if (value > 0) return "text-success"
  if (value < 0) return "text-danger"
  return "text-ink"
}

function formatLakhInr(value: number | null | undefined, currency: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—"
  return formatCurrency(value, currency, null)
}

// ── tooltip ────────────────────────────────────────────────────────────

interface CurvePoint {
  date: string
  price_return: number
  total_return: number
}

function CurveTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ payload: CurvePoint; dataKey: string; value: number }>
  label?: string
}) {
  if (!active || !payload || payload.length === 0) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <div className="rounded-md border border-border bg-bg/95 px-3 py-2 text-xs shadow-md">
      <div className="font-medium text-ink">{label}</div>
      <div className="mt-1 flex flex-col gap-0.5">
        <div className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full bg-[var(--brand-500,#3b82f6)]" />
          <span className="text-caption">Total return</span>
          <span className={`ml-auto font-medium ${pctTone(point.total_return)}`}>
            {formatPct(point.total_return)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full bg-caption" />
          <span className="text-caption">Price only</span>
          <span className={`ml-auto font-medium ${pctTone(point.price_return)}`}>
            {formatPct(point.price_return)}
          </span>
        </div>
      </div>
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────

export default function TotalReturnDisplay({
  ticker,
  currency = "INR",
  companyName,
}: Props) {
  const [years, setYears] = useState<1 | 3 | 5 | 10>(5)
  const [view, setView] = useState<ViewMode>("total")

  const query = useQuery({
    queryKey: ["total-return", ticker, years, DEFAULT_NOTIONAL],
    queryFn: () => getTotalReturn(ticker, years, DEFAULT_NOTIONAL),
    staleTime: 6 * 60 * 60 * 1000,        // matches backend 6h cache
  })

  // Keep the last good payload across queryKey changes so toggling
  // years (which is a different queryKey) doesn't flash the skeleton
  // between periods. The chart updates as soon as the new data lands.
  const lastGoodRef = useRef<TotalReturnResponse | null>(null)
  useEffect(() => {
    if (query.data) {
      lastGoodRef.current = query.data
    }
  }, [query.data])

  const data: TotalReturnResponse | null =
    query.data ?? lastGoodRef.current ?? null

  const tickerLabel = useMemo(() => {
    if (companyName) return companyName
    return ticker.replace(/\.(NS|BO)$/i, "")
  }, [companyName, ticker])

  // ── loading + error states ─────────────────────────────────────────
  // Only render the skeleton on the FIRST ever load — once we've seen
  // any data, period-toggle refetches keep the populated UI visible
  // (lastGoodRef holds the last-rendered payload across queryKey
  // changes) to avoid skeleton flashes on every chip click.
  if (query.isLoading && lastGoodRef.current === null) {
    return (
      <section
        aria-label="Total return vs price return"
        className="bg-bg rounded-2xl border border-border p-4"
      >
        <h2 className="text-sm font-semibold text-ink mb-3">
          Total return vs price return
        </h2>
        <div className="space-y-2">
          <div className="h-8 w-48 animate-pulse rounded bg-border/40" />
          <div className="h-4 w-72 animate-pulse rounded bg-border/40" />
          <div className="mt-4 h-60 w-full animate-pulse rounded bg-border/40" />
        </div>
      </section>
    )
  }

  if (
    !data ||
    data.price_return === null ||
    data.total_return === null ||
    data.start_price === null ||
    data.end_price === null
  ) {
    return (
      <section
        aria-label="Total return vs price return"
        className="bg-bg rounded-2xl border border-border p-4"
      >
        <h2 className="text-sm font-semibold text-ink mb-3">
          Total return vs price return
        </h2>
        <div className="text-sm text-caption">
          Total-return history is not available for this ticker yet. We need at
          least one in-window trading day on both ends of the period to anchor
          the calculation.
        </div>
        <div className="mt-3 flex gap-2">
          {YEARS_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              type="button"
              aria-pressed={years === opt.key}
              onClick={() => setYears(opt.key)}
              className={`px-2.5 py-1 text-xs rounded-md border ${
                years === opt.key
                  ? "bg-ink text-bg border-ink"
                  : "bg-bg text-ink border-border hover:bg-border/30"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </section>
    )
  }

  const capitalAppreciationPct = data.price_return ?? 0
  const dividendBoostPct = data.dividend_boost_pct ?? 0
  const dividendYieldOnCostPct =
    data.start_price && data.start_price > 0
      ? (data.dividends_paid_total / data.start_price) * 100
      : null

  return (
    <section
      aria-label="Total return vs price return"
      className="bg-bg rounded-2xl border border-border p-4"
    >
      {/* ── header + toggles ─────────────────────────────────────── */}
      <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">
            Total return vs price return
          </h2>
          <p className="text-xs text-caption mt-0.5">
            Dividends reinvested at the close-on-ex-date for each event in the
            window. No tax drag.
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {/* View toggle */}
          <div
            role="tablist"
            aria-label="Return type"
            className="inline-flex rounded-md border border-border overflow-hidden text-xs"
          >
            <button
              type="button"
              role="tab"
              aria-selected={view === "price"}
              onClick={() => setView("price")}
              className={`px-2.5 py-1 ${
                view === "price"
                  ? "bg-ink text-bg"
                  : "bg-bg text-ink hover:bg-border/30"
              }`}
            >
              Price only
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === "total"}
              onClick={() => setView("total")}
              className={`px-2.5 py-1 border-l border-border ${
                view === "total"
                  ? "bg-ink text-bg"
                  : "bg-bg text-ink hover:bg-border/30"
              }`}
            >
              Total return
            </button>
          </div>
          {/* Period selector */}
          <div
            role="tablist"
            aria-label="Window in years"
            className="inline-flex rounded-md border border-border overflow-hidden text-xs"
          >
            {YEARS_OPTIONS.map((opt) => (
              <button
                key={opt.key}
                type="button"
                role="tab"
                aria-selected={years === opt.key}
                onClick={() => setYears(opt.key)}
                className={`px-2.5 py-1 ${
                  years === opt.key
                    ? "bg-ink text-bg"
                    : "bg-bg text-ink hover:bg-border/30"
                } ${opt.key !== YEARS_OPTIONS[0]?.key ? "border-l border-border" : ""}`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── big number ───────────────────────────────────────────── */}
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <div
          className={`text-3xl font-semibold ${pctTone(
            view === "total" ? data.total_return : data.price_return,
          )}`}
          data-testid="tr-headline-pct"
        >
          {formatPct(view === "total" ? data.total_return : data.price_return)}
        </div>
        <div className="text-sm text-caption">
          over {data.years}{data.years === 1 ? " year" : " years"}
        </div>
      </div>

      {/* ── narrative line ────────────────────────────────────────── */}
      <p className="mt-2 text-sm text-ink" data-testid="tr-headline-copy">
        Over {data.years}{data.years === 1 ? " year" : " years"},{" "}
        {formatLakhInr(data.initial_investment, currency)} invested in{" "}
        <span className="font-medium">{tickerLabel}</span> price-only returned{" "}
        <span className="font-semibold">
          {formatLakhInr(data.price_only_value, currency)}
        </span>
        . With dividend reinvestment,{" "}
        <span className="font-semibold">
          {formatLakhInr(data.total_return_value, currency)}
        </span>
        .
      </p>

      {/* ── breakdown grid ────────────────────────────────────────── */}
      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3">
        <BreakdownTile
          label="Capital appreciation"
          value={formatPct(capitalAppreciationPct)}
          tone={pctTone(capitalAppreciationPct)}
          hint="Change in share price, ex-dividends."
        />
        <BreakdownTile
          label="Dividend reinvestment lift"
          value={formatPct(dividendBoostPct)}
          tone={pctTone(dividendBoostPct)}
          hint="How much reinvested dividends added on top of price return."
        />
        <BreakdownTile
          label="Dividends paid (per share)"
          value={formatLakhInr(data.dividends_paid_total, currency)}
          tone="text-ink"
          hint={`${data.dividend_count} payment${
            data.dividend_count === 1 ? "" : "s"
          } in window.`}
        />
        {dividendYieldOnCostPct !== null && (
          <BreakdownTile
            label="Yield on cost (cumulative)"
            value={formatPct(dividendYieldOnCostPct)}
            tone="text-ink"
            hint="Total per-share dividends divided by start-date price."
          />
        )}
        <BreakdownTile
          label="Start price"
          value={formatLakhInr(data.start_price, currency)}
          tone="text-ink"
          hint={data.start_date ?? undefined}
        />
        <BreakdownTile
          label="End price"
          value={formatLakhInr(data.end_price, currency)}
          tone="text-ink"
          hint={data.end_date ?? undefined}
        />
      </div>

      {/* ── chart: both curves overlaid ──────────────────────────── */}
      <div className="mt-4 h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data.curve}
            margin={{ top: 8, right: 16, left: 0, bottom: 4 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "var(--caption)" }}
              minTickGap={32}
              tickFormatter={(d: string) =>
                d ? d.slice(0, 7) : ""
              }
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--caption)" }}
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              width={42}
            />
            <Tooltip content={<CurveTooltip />} />
            <Legend
              verticalAlign="top"
              height={24}
              wrapperStyle={{ fontSize: 11 }}
            />
            <Line
              type="monotone"
              dataKey="price_return"
              name="Price only"
              stroke="var(--caption)"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="total_return"
              name="Total return"
              stroke="var(--brand-500, #3b82f6)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* ── footer / source line ─────────────────────────────────── */}
      <div className="mt-3 text-xs text-caption">
        {data.dividend_count > 0 ? (
          <>
            {data.dividend_count} dividend event
            {data.dividend_count === 1 ? "" : "s"} reinvested. Data source:{" "}
            {data.data_source}.
          </>
        ) : (
          <>
            No dividends recorded inside this window. Total return equals price
            return.
          </>
        )}
        {data.notes.length > 0 && (
          <div className="mt-1 italic">{data.notes.join(" ")}</div>
        )}
      </div>
    </section>
  )
}

// ── breakdown tile ───────────────────────────────────────────────────

interface TileProps {
  label: string
  value: string
  tone: string
  hint?: string
}

function BreakdownTile({ label, value, tone, hint }: TileProps) {
  return (
    <div className="rounded-md border border-border bg-bg/50 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-caption">
        {label}
      </div>
      <div className={`mt-1 text-base font-semibold ${tone}`}>{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-caption">{hint}</div>}
    </div>
  )
}
