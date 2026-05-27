"use client"

// BankKpiPanel -- Phase I-frontend (Block II).
//
// Renders per-bank operational + asset-quality KPIs on
// /analysis/[ticker] for the 38 tickers in PURE_BANK_TICKERS_FOR_DE.
//
// Data source: GET /api/v1/banks/{ticker}/kpis
//   -> { is_bank, latest_annual, quarterly_trend }
//
// Layout: 3x3 grid:
//   Row 1: branches_total | atms_total          | customers_millions
//   Row 2: gnpa_pct       | nnpa_pct            | pcr_pct
//   Row 3: casa_pct       | cost_to_income_pct  | credit_deposit_pct
//
// Each cell: large number + metric label + sparkline of the last 4
// quarters for the 6 quarterly metrics (rows 2 & 3). Branches /
// ATMs / customers do not get a quarterly trend (annual only).
//
// Empty-cell affordance: "—" placeholder. The panel itself renders
// nothing if (a) the ticker is not a bank, or (b) the API returns
// is_bank=false (which it will for non-banks), or (c) every field
// in latest_annual is null AND every quarterly_trend list is
// empty -- there's nothing useful to show.

import { useQuery } from "@tanstack/react-query"

interface QuarterlyPoint {
  period_end: string
  value: number
}

export interface BankKpisLatest {
  period_end?: string | null
  period_type?: string | null
  branches_total?: number | null
  branches_tier1?: number | null
  branches_tier2?: number | null
  branches_tier3?: number | null
  atms_total?: number | null
  customers_millions?: number | null
  gnpa_pct?: number | null
  nnpa_pct?: number | null
  pcr_pct?: number | null
  casa_pct?: number | null
  cost_to_income_pct?: number | null
  credit_deposit_pct?: number | null
  sources?: string[]
}

export interface BankKpisResponse {
  ticker: string | null
  is_bank: boolean
  latest_annual: BankKpisLatest | null
  quarterly_trend: {
    gnpa_pct?: QuarterlyPoint[]
    nnpa_pct?: QuarterlyPoint[]
    pcr_pct?: QuarterlyPoint[]
    casa_pct?: QuarterlyPoint[]
    cost_to_income_pct?: QuarterlyPoint[]
    credit_deposit_pct?: QuarterlyPoint[]
  }
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

async function fetchBankKpis(ticker: string): Promise<BankKpisResponse | null> {
  const t = (ticker || "").trim().toUpperCase()
  if (!t) return null
  const res = await fetch(`${API_BASE}/api/v1/banks/${encodeURIComponent(t)}/kpis`)
  if (!res.ok) return null
  return res.json()
}

function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  return Math.round(Number(v)).toLocaleString("en-IN")
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  return `${Number(v).toFixed(2)}%`
}

function fmtMillions(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  return `${Number(v).toFixed(1)} M`
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return ""
  try {
    const d = new Date(iso)
    if (!isFinite(d.getTime())) return ""
    return d.toLocaleDateString("en-IN", {
      day: "numeric", month: "short", year: "numeric",
    })
  } catch {
    return ""
  }
}

// Minimal inline-SVG sparkline. We deliberately avoid pulling
// recharts here -- this is one ~40x12 px line per cell, 6 cells.
// Empty / single-point input renders nothing.
function Sparkline({ points }: { points: QuarterlyPoint[] }) {
  if (!points || points.length < 2) return null
  // Oldest -> newest for left-to-right rendering.
  const ordered = [...points].reverse()
  const values = ordered.map((p) => p.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const width = 60
  const height = 16
  const stepX = width / (ordered.length - 1)
  const path = ordered
    .map((p, i) => {
      const x = i * stepX
      const y = height - ((p.value - min) / range) * height
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      data-testid="bank-kpi-sparkline"
      className="mt-1 text-accent"
    >
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

interface CellProps {
  label: string
  value: string
  testId: string
  trend?: QuarterlyPoint[]
}

function KpiCell({ label, value, testId, trend }: CellProps) {
  return (
    <div
      className="border border-border rounded-lg p-3 bg-surface/40"
      data-testid={testId}
    >
      <div className="text-[10px] uppercase tracking-wide text-caption">
        {label}
      </div>
      <div className="mt-1 text-base font-semibold text-ink leading-tight">
        {value}
      </div>
      {trend && trend.length > 0 && <Sparkline points={trend} />}
    </div>
  )
}

interface PanelProps {
  ticker: string
  initialData?: BankKpisResponse | null
}

export default function BankKpiPanel({ ticker, initialData }: PanelProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["bank-kpis", ticker],
    queryFn: () => fetchBankKpis(ticker),
    enabled: !!ticker && initialData === undefined,
    staleTime: 6 * 60 * 60 * 1000,
    retry: 1,
    initialData: initialData === undefined ? undefined : initialData,
  })

  const payload = data ?? initialData ?? null

  // Non-bank ticker -> render nothing. The endpoint returns
  // is_bank=false; we also short-circuit the no-payload case.
  if (!payload || payload.is_bank === false) return null

  if (isLoading && !payload.latest_annual) {
    return (
      <div className="bg-bg rounded-2xl border border-border p-4">
        <div className="h-4 w-32 bg-surface rounded animate-pulse mb-4" />
        <div className="grid grid-cols-3 gap-3">
          {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <div key={i} className="h-20 bg-surface rounded animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  const latest = payload.latest_annual
  const trend = payload.quarterly_trend ?? {}

  // If we have neither a latest annual snapshot nor any quarterly
  // trend points, render nothing -- the user sees no half-empty
  // shell on a bank we haven't ingested yet.
  const hasAnyLatest =
    latest && Object.entries(latest).some(
      ([k, v]) =>
        k !== "period_end" && k !== "period_type" && k !== "sources" &&
        v !== null && v !== undefined,
    )
  const hasAnyTrend = Object.values(trend).some(
    (arr) => Array.isArray(arr) && arr.length > 0,
  )
  if (!hasAnyLatest && !hasAnyTrend) return null

  const periodLabel = fmtDate(latest?.period_end)
  const sources = latest?.sources ?? []

  return (
    <div
      className="bg-bg rounded-2xl border border-border p-4"
      data-testid="bank-kpi-panel"
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">Bank operational KPIs</h2>
          <p className="text-[11px] text-caption mt-0.5">
            Branches, ATMs, customer base, and asset-quality / liability-mix
            ratios. Sparklines show the most recent four quarters where
            available.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {periodLabel && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-accent/10 text-accent">
              as of {periodLabel}
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {/* Row 1: branches / ATMs / customers (annual only) */}
        <KpiCell
          testId="kpi-branches"
          label="Branches"
          value={fmtInt(latest?.branches_total)}
        />
        <KpiCell
          testId="kpi-atms"
          label="ATMs"
          value={fmtInt(latest?.atms_total)}
        />
        <KpiCell
          testId="kpi-customers"
          label="Customers"
          value={fmtMillions(latest?.customers_millions)}
        />

        {/* Row 2: asset quality (with quarterly sparklines) */}
        <KpiCell
          testId="kpi-gnpa"
          label="GNPA"
          value={fmtPct(latest?.gnpa_pct)}
          trend={trend.gnpa_pct}
        />
        <KpiCell
          testId="kpi-nnpa"
          label="NNPA"
          value={fmtPct(latest?.nnpa_pct)}
          trend={trend.nnpa_pct}
        />
        <KpiCell
          testId="kpi-pcr"
          label="PCR"
          value={fmtPct(latest?.pcr_pct)}
          trend={trend.pcr_pct}
        />

        {/* Row 3: liability / efficiency / lending mix (with sparklines) */}
        <KpiCell
          testId="kpi-casa"
          label="CASA"
          value={fmtPct(latest?.casa_pct)}
          trend={trend.casa_pct}
        />
        <KpiCell
          testId="kpi-cost-to-income"
          label="Cost / income"
          value={fmtPct(latest?.cost_to_income_pct)}
          trend={trend.cost_to_income_pct}
        />
        <KpiCell
          testId="kpi-credit-deposit"
          label="Credit / deposits"
          value={fmtPct(latest?.credit_deposit_pct)}
          trend={trend.credit_deposit_pct}
        />
      </div>

      {(latest?.branches_tier1 || latest?.branches_tier2 || latest?.branches_tier3) && (
        <div
          className="mt-3 text-[11px] text-caption flex flex-wrap gap-x-3 gap-y-1"
          data-testid="bank-kpi-branch-tiers"
        >
          {latest?.branches_tier1 != null && (
            <span>Tier 1: <span className="font-semibold text-ink">{fmtInt(latest.branches_tier1)}</span></span>
          )}
          {latest?.branches_tier2 != null && (
            <span>Tier 2: <span className="font-semibold text-ink">{fmtInt(latest.branches_tier2)}</span></span>
          )}
          {latest?.branches_tier3 != null && (
            <span>Tier 3: <span className="font-semibold text-ink">{fmtInt(latest.branches_tier3)}</span></span>
          )}
        </div>
      )}

      {sources.length > 0 && (
        <p
          className="mt-4 text-[10px] text-caption leading-relaxed"
          data-testid="bank-kpi-sources"
        >
          Source{sources.length > 1 ? "s" : ""}: {sources.join(", ")}.
          KPI values are extracted from the latest disclosed period and
          will populate over time as the bank-KPI backfill workflow runs.
        </p>
      )}
    </div>
  )
}
