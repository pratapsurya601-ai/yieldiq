"use client"

/**
 * RevenueSankey — flow-of-money diagram for the Financials tab.
 *
 * Implements Design Manifesto Tier-2 "Sankey on Financials". Built on
 * d3-sankey (Recharts has no Sankey primitive). Shows:
 *
 *   Revenue ─┬─► Cost of Revenue
 *            ├─► Operating Expenses
 *            ├─► Interest
 *            ├─► Tax & Other
 *            └─► Net Income
 *
 * The breakdown is derived from the existing /api/v1/analysis/{ticker}/
 * financials response. Fields used (FinancialYear):
 *   revenue, gross_profit, operating_income, interest_expense, net_income
 *
 * Derivations (so the diagram balances even when sub-fields are missing
 * — per the spec: "missing nodes = aggregated as Other"):
 *
 *   cost_of_revenue   = revenue        − gross_profit
 *   operating_expenses = gross_profit  − operating_income
 *   interest          = interest_expense (when present)
 *   tax_and_other     = operating_income − interest − net_income
 *   net_income        = net_income
 *
 * For banks (isPureBank): we relabel
 *   Revenue            → Total Income
 *   Cost of Revenue    → Interest Expense
 *   Operating Expenses → Other Operating Expenses
 *
 * Period selector: Last Quarter / Last 4 Quarters (TTM, default) / Last FY.
 *
 * Visual: blue ribbons for revenue inflow, green for profit, red for
 * expense outflows. Width fills container; height 280px on mobile, 400px
 * desktop. Hover a ribbon → tooltip with absolute ₹ value + % of revenue.
 *
 * SEBI-safe: captions never use banned words; all language is descriptive.
 */

import * as React from "react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  sankey as d3sankey,
  sankeyLinkHorizontal,
  type SankeyGraph,
  type SankeyNode,
  type SankeyLink,
} from "d3-sankey"
import { getFinancials, type FinancialsResponse, type FinancialYear } from "@/lib/api"
import { isPureBank } from "@/lib/bankTickers"

type Period = "quarter" | "ttm" | "fy"

interface RevenueSankeyProps {
  ticker: string
  /** Pre-fetched annual financials (used for the "Last FY" and TTM views). */
  annual: FinancialsResponse | null | undefined
  currency?: string | null
}

// Internal node type — we tag every node with a semantic role so the
// renderer can colour it without string-matching the label.
type NodeRole = "revenue" | "profit" | "expense"
interface FinNode {
  id: string
  label: string
  role: NodeRole
  value: number  // Cr, always positive
}
interface FinLink {
  source: string
  target: string
  value: number  // Cr, always positive
  role: NodeRole
}

// ────────────────────────────────────────────────────────────────────
// Formatting (Indian compaction — same convention as FinancialsKpiGrid)
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

function pct(num: number, denom: number): string {
  if (!Number.isFinite(num) || !Number.isFinite(denom) || denom === 0) return "—"
  return `${((num / denom) * 100).toFixed(1)}%`
}

// ────────────────────────────────────────────────────────────────────
// Period selection — collapses the backend's newest-first arrays into
// a single "current period" FinancialYear used by the diagram.
// ────────────────────────────────────────────────────────────────────
function pickPeriod(
  annual: FinancialsResponse | null | undefined,
  quarterly: FinancialsResponse | null | undefined,
  period: Period,
): FinancialYear | null {
  if (period === "fy") {
    return annual?.income?.[0] ?? null
  }
  if (period === "quarter") {
    return quarterly?.income?.[0] ?? null
  }
  // TTM = last 4 quarters summed. If quarterly is missing, fall back
  // to the most recent annual row (the backend treats latest annual
  // as a reasonable proxy until a real TTM stitcher exists).
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
// Graph builder
// ────────────────────────────────────────────────────────────────────
export interface SankeyGraphData {
  nodes: FinNode[]
  links: FinLink[]
  revenue: number
}

export function buildSankey(row: FinancialYear | null, opts: { bank: boolean }): SankeyGraphData | null {
  if (!row) return null
  const rev = row.revenue
  if (rev == null || !Number.isFinite(rev) || rev <= 0) return null

  const gross = row.gross_profit
  const opInc = row.operating_income
  const ni = row.net_income
  const interest = (row.interest_expense ?? null) as number | null

  // Derive missing sub-totals. All math clamped to non-negative — a
  // negative cost would render as a reversed ribbon and confuse users.
  const cogs = gross != null && Number.isFinite(gross) ? Math.max(0, rev - gross) : null
  const opEx = gross != null && opInc != null && Number.isFinite(gross) && Number.isFinite(opInc)
    ? Math.max(0, gross - opInc)
    : null
  const interestCr = interest != null && Number.isFinite(interest) ? Math.max(0, interest) : null
  const taxAndOther = opInc != null && ni != null && Number.isFinite(opInc) && Number.isFinite(ni)
    ? Math.max(0, opInc - (interestCr ?? 0) - ni)
    : null
  const netIncome = ni != null && Number.isFinite(ni) ? Math.max(0, ni) : null

  const labels = opts.bank
    ? {
        revenue: "Total Income",
        cogs: "Interest Expense",
        opEx: "Other Operating Expenses",
      }
    : {
        revenue: "Revenue",
        cogs: "Cost of Revenue",
        opEx: "Operating Expenses",
      }

  const nodes: FinNode[] = [
    { id: "revenue", label: labels.revenue, role: "revenue", value: rev },
  ]
  const links: FinLink[] = []

  const addOutflow = (id: string, label: string, value: number | null, role: NodeRole) => {
    if (value == null || value <= 0) return
    nodes.push({ id, label, role, value })
    links.push({ source: "revenue", target: id, value, role })
  }

  addOutflow("cogs", labels.cogs, cogs, "expense")
  addOutflow("opex", labels.opEx, opEx, "expense")
  addOutflow("interest", "Interest", interestCr, "expense")
  addOutflow("tax_other", "Tax & Other", taxAndOther, "expense")
  addOutflow("net_income", "Net Income", netIncome, "profit")

  // If nothing flowed out (degenerate row), bail.
  if (links.length === 0) return null

  return { nodes, links, revenue: rev }
}

// ────────────────────────────────────────────────────────────────────
// Color tokens (verdict-independent — Sankey is a structural chart)
// ────────────────────────────────────────────────────────────────────
const NODE_FILL: Record<NodeRole, string> = {
  revenue: "#1d4ed8",  // blue-700
  profit: "#047857",   // emerald-700
  expense: "#b91c1c",  // red-700
}
const LINK_FILL: Record<NodeRole, string> = {
  revenue: "rgba(29, 78, 216, 0.35)",
  profit: "rgba(4, 120, 87, 0.45)",
  expense: "rgba(185, 28, 28, 0.32)",
}

// ────────────────────────────────────────────────────────────────────
// Component
// ────────────────────────────────────────────────────────────────────
type LayoutNode = SankeyNode<FinNode, FinLink>
type LayoutLink = SankeyLink<FinNode, FinLink>

interface TooltipState {
  x: number
  y: number
  title: string
  body: string
}

export default function RevenueSankey({
  ticker,
  annual,
  currency,
}: RevenueSankeyProps) {
  const [period, setPeriod] = useState<Period>("ttm")
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState<number>(640)
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)
  const [isMobile, setIsMobile] = useState<boolean>(false)

  // Quarterly is lazy — only fetched when the user needs it.
  const quarterlyQuery = useQuery({
    queryKey: ["financials", ticker, "quarterly"],
    queryFn: () => getFinancials(ticker, "quarterly", 8),
    enabled: !!ticker && (period === "ttm" || period === "quarter"),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  // Track container width so the SVG scales fluidly.
  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const w = Math.max(280, Math.floor(e.contentRect.width))
        setWidth(w)
        setIsMobile(w < 520)
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
  const graph = useMemo(() => buildSankey(row, { bank }), [row, bank])

  const height = isMobile ? 280 : 400
  const margin = { top: 12, right: 140, bottom: 12, left: 12 }

  const layout = useMemo(() => {
    if (!graph) return null
    // d3-sankey mutates its input — clone to keep `graph` referentially stable.
    const input: SankeyGraph<FinNode, FinLink> = {
      nodes: graph.nodes.map(n => ({ ...n })),
      links: graph.links.map(l => ({ ...l })),
    }
    const innerW = Math.max(120, width - margin.left - margin.right)
    const innerH = Math.max(80, height - margin.top - margin.bottom)
    const generator = d3sankey<FinNode, FinLink>()
      .nodeId(d => d.id)
      .nodeWidth(14)
      .nodePadding(isMobile ? 10 : 18)
      .extent([[0, 0], [innerW, innerH]])
    return generator(input)
  }, [graph, width, height, isMobile, margin.left, margin.right, margin.top, margin.bottom])

  if (!graph || !layout) {
    return (
      <div
        className="bg-bg rounded-2xl border border-border p-6 text-center"
        data-testid="revenue-sankey-empty"
      >
        <p className="text-sm font-semibold text-ink">Revenue flow not available</p>
        <p className="text-xs text-caption mt-1 max-w-prose mx-auto">
          We need at least revenue and net-income figures to draw the
          flow. Check back after the next data refresh.
        </p>
      </div>
    )
  }

  const linkPath = sankeyLinkHorizontal<FinNode, FinLink>()
  const revenueTotal = graph.revenue

  const showLink = (l: LayoutLink, evt: React.MouseEvent) => {
    const targetNode = (typeof l.target === "object" ? l.target : null) as LayoutNode | null
    const targetLabel = targetNode?.label ?? "—"
    setTooltip({
      x: evt.nativeEvent.offsetX,
      y: evt.nativeEvent.offsetY,
      title: `Revenue → ${targetLabel}`,
      body: `${formatCr(l.value as number)} · ${pct(l.value as number, revenueTotal)} of revenue`,
    })
  }
  const showNode = (n: LayoutNode, evt: React.MouseEvent) => {
    setTooltip({
      x: evt.nativeEvent.offsetX,
      y: evt.nativeEvent.offsetY,
      title: n.label,
      body: `${formatCr(n.value as number)} · ${pct(n.value as number, revenueTotal)} of revenue`,
    })
  }
  const hide = () => setTooltip(null)

  return (
    <div
      className="bg-bg rounded-2xl border border-border p-5"
      data-testid="revenue-sankey"
    >
      <header className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-ink">Revenue flow</h3>
          <p className="text-xs text-caption mt-0.5">
            How each rupee of {bank ? "total income" : "revenue"} is split between costs and profit.
          </p>
        </div>
        <PeriodTabs period={period} onChange={setPeriod} />
      </header>

      <div ref={containerRef} className="relative w-full overflow-hidden">
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`Revenue flow Sankey diagram for ${ticker}`}
          data-testid="revenue-sankey-svg"
        >
          <g transform={`translate(${margin.left},${margin.top})`}>
            {/* Links first so nodes sit on top */}
            <g fill="none">
              {(layout.links as LayoutLink[]).map((l, i) => {
                const targetNode = (typeof l.target === "object" ? l.target : null) as LayoutNode | null
                const role: NodeRole = (targetNode?.role ?? "expense") as NodeRole
                const d = linkPath(l) ?? ""
                return (
                  <path
                    key={`link-${i}`}
                    d={d}
                    stroke={LINK_FILL[role]}
                    strokeWidth={Math.max(1, l.width ?? 1)}
                    onMouseMove={(e) => showLink(l, e)}
                    onMouseLeave={hide}
                    style={{ transition: "opacity 200ms", cursor: "pointer" }}
                    data-testid={`sankey-link-${(typeof l.source === "object" ? (l.source as LayoutNode).id : "")}-${(typeof l.target === "object" ? (l.target as LayoutNode).id : "")}`}
                  />
                )
              })}
            </g>

            {/* Nodes */}
            <g>
              {(layout.nodes as LayoutNode[]).map((n) => {
                const x0 = n.x0 ?? 0
                const x1 = n.x1 ?? 0
                const y0 = n.y0 ?? 0
                const y1 = n.y1 ?? 0
                const isRight = (n.depth ?? 0) > 0
                const labelX = isRight ? x1 + 6 : x0 - 6
                const anchor = isRight ? "start" : "end"
                return (
                  <g key={`node-${n.id}`} data-testid={`sankey-node-${n.id}`}>
                    <rect
                      x={x0}
                      y={y0}
                      width={Math.max(1, x1 - x0)}
                      height={Math.max(1, y1 - y0)}
                      fill={NODE_FILL[n.role]}
                      onMouseMove={(e) => showNode(n, e)}
                      onMouseLeave={hide}
                      style={{ cursor: "pointer" }}
                    />
                    <text
                      x={labelX}
                      y={(y0 + y1) / 2}
                      dy="0.35em"
                      textAnchor={anchor}
                      fontSize={isMobile ? 10 : 11}
                      className="fill-ink"
                      style={{ pointerEvents: "none", fontWeight: 600 }}
                    >
                      {n.label}
                    </text>
                    <text
                      x={labelX}
                      y={(y0 + y1) / 2 + (isMobile ? 11 : 13)}
                      dy="0.35em"
                      textAnchor={anchor}
                      fontSize={isMobile ? 9 : 10}
                      className="fill-caption"
                      style={{ pointerEvents: "none" }}
                    >
                      {formatCr(n.value as number)} · {pct(n.value as number, revenueTotal)}
                    </text>
                  </g>
                )
              })}
            </g>
          </g>
        </svg>

        {tooltip && (
          <div
            role="tooltip"
            data-testid="sankey-tooltip"
            className="pointer-events-none absolute z-10 rounded-md border border-border bg-bg px-2.5 py-1.5 shadow-md text-xs"
            style={{
              left: Math.min(width - 180, tooltip.x + 10),
              top: Math.max(0, tooltip.y - 36),
            }}
          >
            <div className="font-semibold text-ink">{tooltip.title}</div>
            <div className="text-caption tabular-nums">{tooltip.body}</div>
          </div>
        )}
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
// Period tabs
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
          data-testid={`sankey-period-${o.key}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
