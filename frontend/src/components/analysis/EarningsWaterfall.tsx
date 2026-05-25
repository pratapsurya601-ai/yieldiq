"use client"

/**
 * EarningsWaterfall — bar-chart waterfall walking from Revenue to Net
 * Income through every major cost / subtotal step.
 *
 * Steps:
 *   Revenue → −Cost of Revenue → Gross Profit → −Operating Expenses →
 *   Operating Income → −Interest → −Tax & Other → Net Income
 *
 * Implemented with Recharts BarChart + a custom Bar that floats each
 * step at the previous cumulative position. Subtotal bars (Gross, Op
 * Income, Net Income) are rendered from the baseline. Hover any bar →
 * tooltip with absolute ₹ value, % of revenue, and a one-line caption.
 *
 * Data source: same as RevenueSankey — /api/v1/analysis/{ticker}/
 * financials. Period selector mirrors the Sankey (Last Q / TTM / Last FY).
 *
 * SEBI-safe. Mobile responsive. Dark-mode parity via Tailwind tokens.
 */

import * as React from "react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Cell,
  Tooltip,
} from "recharts"
import { getFinancials, type FinancialsResponse, type FinancialYear } from "@/lib/api"
import { isPureBank } from "@/lib/bankTickers"

type Period = "quarter" | "ttm" | "fy"

type StepKind = "start" | "decrease" | "subtotal" | "end"

export interface WaterfallStep {
  key: string
  label: string
  /** Signed delta vs the running cumulative (negative for cost lines). */
  delta: number
  /** Cumulative value at the END of this step. */
  cumulative: number
  /** Visualisation kind — drives colour + floating-bar geometry. */
  kind: StepKind
  /** Short caption for the tooltip. */
  caption: string
}

interface ChartRow {
  name: string
  /** Lower baseline of the floating bar. */
  base: number
  /** Length of the floating bar (always positive). */
  span: number
  delta: number
  value: number
  kind: StepKind
  caption: string
}

interface EarningsWaterfallProps {
  ticker: string
  annual: FinancialsResponse | null | undefined
  currency?: string | null
}

// ────────────────────────────────────────────────────────────────────
// Period collapse (mirrors RevenueSankey.pickPeriod, intentionally
// duplicated — both surfaces should keep their own copy so a future
// refactor of one doesn't silently change the other).
// ────────────────────────────────────────────────────────────────────
function pickPeriod(
  annual: FinancialsResponse | null | undefined,
  quarterly: FinancialsResponse | null | undefined,
  period: Period,
): FinancialYear | null {
  if (period === "fy") return annual?.income?.[0] ?? null
  if (period === "quarter") return quarterly?.income?.[0] ?? null
  const q = quarterly?.income ?? []
  if (q.length === 0) return annual?.income?.[0] ?? null
  const last4 = q.slice(0, 4)
  const sumField = (k: keyof FinancialYear): number | null => {
    let total = 0
    let seen = 0
    for (const row of last4) {
      const v = row[k]
      if (typeof v === "number" && Number.isFinite(v)) {
        total += v
        seen += 1
      }
    }
    return seen > 0 ? total : null
  }
  return {
    year: "TTM",
    period_end: last4[0]?.period_end ?? null,
    revenue: sumField("revenue"),
    revenue_growth_pct: null,
    gross_profit: sumField("gross_profit"),
    gross_margin_pct: null,
    ebitda: sumField("ebitda"),
    operating_income: sumField("operating_income"),
    operating_margin_pct: null,
    net_income: sumField("net_income"),
    net_income_growth_pct: null,
    net_margin_pct: null,
    eps_diluted: null,
    total_assets: null,
    total_equity: null,
    total_debt: null,
    cash: null,
    net_debt: null,
    debt_to_equity: null,
    book_value_per_share: null,
    operating_cash_flow: null,
    capex: null,
    free_cash_flow: null,
    fcf_margin_pct: null,
    interest_expense: sumField("interest_expense" as keyof FinancialYear),
  }
}

// ────────────────────────────────────────────────────────────────────
// Formatting
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
function pctOf(num: number, denom: number): string {
  if (!Number.isFinite(num) || !Number.isFinite(denom) || denom === 0) return "—"
  return `${((num / denom) * 100).toFixed(1)}%`
}

// ────────────────────────────────────────────────────────────────────
// Step builder
// ────────────────────────────────────────────────────────────────────
export function buildWaterfall(row: FinancialYear | null, opts: { bank: boolean }): WaterfallStep[] | null {
  if (!row) return null
  const rev = row.revenue
  if (rev == null || !Number.isFinite(rev) || rev <= 0) return null

  const gross = row.gross_profit
  const opInc = row.operating_income
  const ni = row.net_income
  const interest = (row.interest_expense ?? null) as number | null

  // Sub-totals are computed in left-to-right order so each step lands
  // at exactly the figure the income statement reports — no rounding drift.
  const steps: WaterfallStep[] = []
  let cum = rev

  steps.push({
    key: "revenue",
    label: opts.bank ? "Total Income" : "Revenue",
    delta: rev,
    cumulative: rev,
    kind: "start",
    caption: opts.bank ? "Net interest income plus other income." : "Top-line sales for the period.",
  })

  if (gross != null && Number.isFinite(gross)) {
    const cogs = Math.max(0, rev - gross)
    cum = cum - cogs
    steps.push({
      key: "cost_of_revenue",
      label: opts.bank ? "−Interest Expense" : "−Cost of Revenue",
      delta: -cogs,
      cumulative: cum,
      kind: "decrease",
      caption: opts.bank
        ? "Interest paid on deposits and borrowings."
        : "Direct costs of producing the revenue.",
    })
    steps.push({
      key: "gross_profit",
      label: opts.bank ? "Net Interest Income" : "Gross Profit",
      delta: cum,
      cumulative: cum,
      kind: "subtotal",
      caption: opts.bank
        ? "Income left after paying interest costs."
        : "What's left after direct costs.",
    })
  }

  if (gross != null && opInc != null && Number.isFinite(gross) && Number.isFinite(opInc)) {
    const opEx = Math.max(0, gross - opInc)
    cum = cum - opEx
    steps.push({
      key: "operating_expenses",
      label: opts.bank ? "−Other Operating Expenses" : "−Operating Expenses",
      delta: -opEx,
      cumulative: cum,
      kind: "decrease",
      caption: "Salaries, rent, marketing, R&D and other overheads.",
    })
    steps.push({
      key: "operating_income",
      label: "Operating Income",
      delta: cum,
      cumulative: cum,
      kind: "subtotal",
      caption: "Profit from the core business, before interest and tax.",
    })
  }

  if (interest != null && Number.isFinite(interest) && !opts.bank) {
    // For banks the interest leg already lives in "−Interest Expense" above.
    const intCr = Math.max(0, interest)
    cum = cum - intCr
    steps.push({
      key: "interest",
      label: "−Interest",
      delta: -intCr,
      cumulative: cum,
      kind: "decrease",
      caption: "Interest paid on debt during the period.",
    })
  }

  if (opInc != null && ni != null && Number.isFinite(opInc) && Number.isFinite(ni)) {
    const taxOther = Math.max(0, opInc - (interest && !opts.bank ? Math.max(0, interest) : 0) - ni)
    cum = cum - taxOther
    if (taxOther > 0) {
      steps.push({
        key: "tax_other",
        label: "−Tax & Other",
        delta: -taxOther,
        cumulative: cum,
        kind: "decrease",
        caption: "Income tax, minority interest, exceptional items.",
      })
    }
    // Force the final cumulative to land on reported net income — any
    // residual rounding gets absorbed silently.
    cum = ni
    steps.push({
      key: "net_income",
      label: "Net Income",
      delta: cum,
      cumulative: cum,
      kind: "end",
      caption: "Bottom-line profit attributable to shareholders.",
    })
  }

  if (steps.length < 3) return null
  return steps
}

// ────────────────────────────────────────────────────────────────────
// Colours
// ────────────────────────────────────────────────────────────────────
const COLOR: Record<StepKind, string> = {
  start: "#1d4ed8",      // blue-700  (revenue)
  decrease: "#b91c1c",   // red-700   (cost)
  subtotal: "#475569",   // slate-600
  end: "#047857",        // emerald-700
}

// ────────────────────────────────────────────────────────────────────
// Chart-row mapping
// ────────────────────────────────────────────────────────────────────
function stepsToChartRows(steps: WaterfallStep[]): ChartRow[] {
  // For start/end/subtotal we draw a floor-to-value bar. For decrease
  // we draw a floating bar from the previous cumulative DOWN to the
  // new cumulative, of length = |delta|.
  const out: ChartRow[] = []
  let prevCum = 0
  for (const s of steps) {
    if (s.kind === "decrease") {
      const top = prevCum
      const bottom = s.cumulative
      out.push({
        name: s.label,
        base: bottom,
        span: Math.max(0, top - bottom),
        delta: s.delta,
        value: s.cumulative,
        kind: s.kind,
        caption: s.caption,
      })
    } else {
      out.push({
        name: s.label,
        base: 0,
        span: Math.max(0, s.cumulative),
        delta: s.delta,
        value: s.cumulative,
        kind: s.kind,
        caption: s.caption,
      })
    }
    prevCum = s.cumulative
  }
  return out
}

// Stacked Bar trick: render an invisible "base" bar, then the "span"
// bar on top. Recharts stacks them so each span floats at its base.
interface WaterfallTooltipProps {
  active?: boolean
  // Recharts v3's content-callback Tooltip props omit `payload` /
  // `label` from the public type even though they're passed at
  // runtime. We accept them as loose to keep TS happy.
  payload?: ReadonlyArray<{ payload?: ChartRow }>
  label?: string
  revenue: number
}
function WaterfallTooltip({ active, payload, label, revenue }: WaterfallTooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  const row = (payload[0]?.payload ?? null) as ChartRow | null
  if (!row) return null
  return (
    <div
      role="tooltip"
      data-testid="waterfall-tooltip"
      className="rounded-md border border-border bg-bg px-2.5 py-1.5 shadow-md text-xs"
    >
      <div className="font-semibold text-ink">{label}</div>
      <div className="text-caption tabular-nums">
        {row.kind === "decrease"
          ? `${formatCr(row.delta)} · ${pctOf(Math.abs(row.delta), revenue)} of revenue`
          : `${formatCr(row.value)} · ${pctOf(row.value, revenue)} of revenue`}
      </div>
      <div className="text-caption mt-0.5 max-w-[18rem]">{row.caption}</div>
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────
// Component
// ────────────────────────────────────────────────────────────────────
export default function EarningsWaterfall({
  ticker,
  annual,
  currency,
}: EarningsWaterfallProps) {
  const [period, setPeriod] = useState<Period>("ttm")
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [isMobile, setIsMobile] = useState(false)

  const quarterlyQuery = useQuery({
    queryKey: ["financials", ticker, "quarterly"],
    queryFn: () => getFinancials(ticker, "quarterly", 8),
    enabled: !!ticker && (period === "ttm" || period === "quarter"),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setIsMobile(e.contentRect.width < 520)
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const bank = useMemo(() => isPureBank(ticker), [ticker])
  const row = useMemo(
    () => pickPeriod(annual, quarterlyQuery.data, period),
    [annual, quarterlyQuery.data, period],
  )
  const steps = useMemo(() => buildWaterfall(row, { bank }), [row, bank])
  const chartData = useMemo(() => (steps ? stepsToChartRows(steps) : []), [steps])
  const revenue = row?.revenue ?? 0

  if (!steps || steps.length === 0) {
    return (
      <div
        className="bg-bg rounded-2xl border border-border p-6 text-center"
        data-testid="earnings-waterfall-empty"
      >
        <p className="text-sm font-semibold text-ink">Earnings walk not available</p>
        <p className="text-xs text-caption mt-1 max-w-prose mx-auto">
          We need revenue, gross profit, operating income and net income
          to draw the waterfall. Check back after the next data refresh.
        </p>
      </div>
    )
  }

  return (
    <div
      className="bg-bg rounded-2xl border border-border p-5"
      data-testid="earnings-waterfall"
    >
      <header className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-ink">Revenue to Net Income walk</h3>
          <p className="text-xs text-caption mt-0.5">
            Each step shows what subtracts from {bank ? "total income" : "revenue"} on the way to the bottom line.
          </p>
        </div>
        <PeriodTabs period={period} onChange={setPeriod} />
      </header>

      <div ref={containerRef} className="w-full" style={{ height: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            margin={{ top: 24, right: 12, left: 12, bottom: isMobile ? 64 : 24 }}
          >
            <XAxis
              dataKey="name"
              interval={0}
              tick={{ fontSize: isMobile ? 9 : 11, fill: "currentColor" }}
              angle={isMobile ? -30 : 0}
              textAnchor={isMobile ? "end" : "middle"}
              height={isMobile ? 60 : 30}
              stroke="currentColor"
              className="text-caption"
            />
            <YAxis
              tick={{ fontSize: 10, fill: "currentColor" }}
              tickFormatter={(v: number) => formatCr(v).replace("₹", "")}
              width={70}
              stroke="currentColor"
              className="text-caption"
            />
            <Tooltip
              cursor={{ fill: "rgba(148, 163, 184, 0.12)" }}
              content={((props: unknown) => (
                <WaterfallTooltip
                  {...(props as Omit<WaterfallTooltipProps, "revenue">)}
                  revenue={revenue}
                />
              )) as React.ComponentProps<typeof Tooltip>["content"]}
            />
            {/* Invisible spacer — pushes the visible bar up to its base. */}
            <Bar dataKey="base" stackId="wf" fill="transparent" isAnimationActive={false} />
            <Bar dataKey="span" stackId="wf" radius={[3, 3, 0, 0]}>
              {chartData.map((row, i) => (
                <Cell
                  key={`cell-${i}`}
                  fill={COLOR[row.kind]}
                  data-testid={`waterfall-bar-${row.name}`}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <p className="text-[11px] text-caption mt-3 max-w-prose">
        {period === "quarter"
          ? "Latest reported quarter."
          : period === "fy"
            ? "Most recent full financial year."
            : "Trailing twelve months (sum of the last four quarters)."}
        {" "}Missing sub-line items are grouped into &ldquo;Tax &amp; Other&rdquo;.
        {currency && currency !== "INR" ? ` Reported in ${currency}.` : ""}
      </p>
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────
// Period tabs (kept local — same shape as Sankey's tabs but each
// component owns its own toggle state).
// ────────────────────────────────────────────────────────────────────
function PeriodTabs({ period, onChange }: { period: Period; onChange: (p: Period) => void }) {
  const opts: { key: Period; label: string }[] = [
    { key: "quarter", label: "Last Q" },
    { key: "ttm", label: "TTM" },
    { key: "fy", label: "Last FY" },
  ]
  return (
    <div
      className="inline-flex rounded-lg border border-border bg-bg p-0.5 text-xs"
      role="tablist"
      aria-label="Period"
    >
      {opts.map(o => (
        <button
          key={o.key}
          role="tab"
          aria-selected={period === o.key}
          onClick={() => onChange(o.key)}
          className={`px-3 py-1.5 rounded-md font-semibold uppercase tracking-wide transition-colors ${
            period === o.key
              ? "bg-slate-900 text-white"
              : "text-muted hover:text-ink"
          }`}
          data-testid={`waterfall-period-${o.key}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
