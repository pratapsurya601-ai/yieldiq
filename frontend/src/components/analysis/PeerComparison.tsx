"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { getPeers, type PeerRow, type PeersResponse } from "@/lib/api"
import { cn } from "@/lib/utils"
import { formatMarketCap } from "@/lib/formatters"

interface Props {
  ticker: string
  currency?: string
}

/* ------------------------------------------------------------------ */
/* Skeleton                                                            */
/* ------------------------------------------------------------------ */
function Skeleton() {
  return (
    <div className="bg-surface rounded-2xl border border-border p-5 space-y-3">
      <div className="h-5 w-40 bg-border rounded animate-pulse" />
      <div className="h-3 w-24 bg-bg rounded animate-pulse" />
      <div className="space-y-2 pt-2">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-8 bg-bg rounded animate-pulse" />
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Cell formatters                                                     */
/* ------------------------------------------------------------------ */
function truncate(s: string, max: number): string {
  if (s.length <= max) return s
  return s.slice(0, max - 1) + "…"
}

function fmtRatio(v: number | null): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(1)}x`
}

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(1)}%`
}

function fmtMoS(v: number | null): string {
  if (v === null || v === undefined) return "—"
  const sign = v > 0 ? "+" : ""
  return `${sign}${v.toFixed(1)}%`
}

function fmtMarketCap(cr: number | null, currency: string): string {
  if (cr === null || cr === undefined) return "\u2014"
  if (currency === "INR") {
    // Canonical "Lakh Cr" formatter.
    return formatMarketCap(cr)
  }
  // USD path — "market_cap_cr" is actually millions for US tickers
  const sym = "$"
  if (cr >= 1_000_000) return `${sym}${(cr / 1_000_000).toFixed(1)}T`
  if (cr >= 1_000) return `${sym}${(cr / 1_000).toFixed(1)}B`
  return `${sym}${cr.toFixed(0)}M`
}

function fmtFV(v: number | null, currency: string): string {
  if (v === null || v === undefined) return "—"
  const sym = currency === "INR" ? "\u20b9" : "$"
  const locale = currency === "INR" ? "en-IN" : "en-US"
  return `${sym}${v.toLocaleString(locale, { maximumFractionDigits: 0 })}`
}

function gradeColor(grade: string | null, score: number | null): string {
  if (score === null || score === undefined) return "bg-border text-caption"
  if (score >= 75) return "bg-green-500 text-white"
  if (score >= 55) return "bg-blue-500 text-white"
  if (score >= 35) return "bg-yellow-500 text-white"
  if (score >= 20) return "bg-orange-500 text-white"
  return "bg-red-500 text-white"
}

function ScoreBadge({ score, grade }: { score: number | null; grade: string | null }) {
  if (score === null || score === undefined) {
    return <span className="text-caption">—</span>
  }
  return (
    <div className="inline-flex flex-col items-center gap-0.5">
      <span
        className={cn(
          "inline-flex items-center justify-center",
          "h-5 w-5 rounded text-[10px] font-bold",
          gradeColor(grade, score),
        )}
      >
        {grade ?? ""}
      </span>
      <span className="text-[10px] text-caption font-medium">{score}</span>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Table column definitions                                            */
/* ------------------------------------------------------------------ */
type ColumnKey =
  | "company"
  | "yieldiq_score"
  | "fair_value"
  | "mos_pct"
  | "pe_ratio"
  | "pb_ratio"
  | "roe_pct"
  | "net_margin_pct"
  | "market_cap_cr"

type Column = {
  key: ColumnKey
  label: string
  metric?: keyof PeerRow      // the best_in_sector metric to match (omit for no highlight)
  render: (row: PeerRow) => React.ReactNode
  className?: string
}

const buildColumns = (currency: string): Column[] => [
  {
    key: "company",
    label: "Company",
    render: row => (
      <div className="flex flex-col">
        <span className="text-xs font-medium text-ink">
          {row.is_main && "★ "}
          {truncate(row.company_name, 14)}
        </span>
        <span className="text-[10px] text-caption">
          {row.ticker.replace(".NS", "").replace(".BO", "")}
        </span>
      </div>
    ),
  },
  {
    key: "yieldiq_score",
    label: "Score",
    metric: "yieldiq_score",
    render: row => <ScoreBadge score={row.yieldiq_score} grade={row.grade} />,
  },
  {
    key: "fair_value",
    label: "Fair Val",
    render: row => <span className="tabular-nums">{fmtFV(row.fair_value, currency)}</span>,
  },
  {
    key: "mos_pct",
    label: "MoS",
    metric: "mos_pct",
    render: row => {
      const v = row.mos_pct
      if (v === null || v === undefined) return <span className="text-caption">—</span>
      const cls = v > 0 ? "text-green-600" : v < 0 ? "text-red-500" : "text-caption"
      return <span className={cn("tabular-nums font-medium", cls)}>{fmtMoS(v)}</span>
    },
  },
  {
    key: "pe_ratio",
    label: "P/E",
    metric: "pe_ratio",
    render: row => <span className="tabular-nums">{fmtRatio(row.pe_ratio)}</span>,
  },
  {
    key: "pb_ratio",
    label: "P/B",
    metric: "pb_ratio",
    render: row => <span className="tabular-nums">{fmtRatio(row.pb_ratio)}</span>,
  },
  {
    key: "roe_pct",
    label: "ROE",
    metric: "roe_pct",
    render: row => <span className="tabular-nums">{fmtPct(row.roe_pct)}</span>,
  },
  {
    key: "net_margin_pct",
    label: "Net Mgn",
    metric: "net_margin_pct",
    render: row => <span className="tabular-nums">{fmtPct(row.net_margin_pct)}</span>,
  },
  {
    key: "market_cap_cr",
    label: "Mkt Cap",
    render: row => <span className="tabular-nums">{fmtMarketCap(row.market_cap_cr, currency)}</span>,
  },
]

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */
export default function PeerComparison({ ticker, currency = "INR" }: Props) {
  const router = useRouter()
  const [visible, setVisible] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const columns = useMemo(() => buildColumns(currency), [currency])

  useEffect(() => {
    if (visible) return
    const el = containerRef.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true)
          obs.disconnect()
        }
      },
      { rootMargin: "300px" }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [visible])

  const { data, isLoading, isError, refetch } = useQuery<PeersResponse>({
    queryKey: ["peers", ticker],
    queryFn: () => getPeers(ticker),
    enabled: visible && !!ticker,
    staleTime: 30 * 60 * 1000,
    retry: 1,
  })

  // `has_peers` is the authoritative signal from /analysis/{t}/peers, but
  // we fall back to `peers.length > 0` so an accidental backend drop of
  // the field never silently empties this section again (see the
  // 2026-04-29 hotfix on /public/peers/{t} for the regression we're
  // hardening against).
  const hasPeers = (data?.has_peers ?? ((data?.peers?.length ?? 0) > 0))

  const insight = useMemo(() => {
    if (!hasPeers || !data?.peers?.length) return null
    const scored = data.peers.filter(p => p.yieldiq_score !== null)
    if (scored.length < 2) return null
    const ranked = [...scored].sort(
      (a, b) => (b.yieldiq_score ?? 0) - (a.yieldiq_score ?? 0)
    )
    const top = ranked[0]
    const main = data.peers.find(p => p.is_main)
    if (!main) return null
    if (top.ticker === main.ticker) {
      return `★ ${main.company_name} has the highest YieldIQ Score in ${data.sector_label ?? "this sector"}.`
    }
    const rank = ranked.findIndex(p => p.ticker === main.ticker) + 1
    if (rank === 0) return null
    return `${top.company_name} leads ${data.sector_label ?? "the sector"} with a score of ${top.yieldiq_score}. ${main.company_name} ranks #${rank}.`
  }, [data, hasPeers])

  const anyMissingScore = data?.peers?.some(p => p.yieldiq_score === null) ?? false

  /* ---------- Render states ---------- */
  if (!visible || isLoading) {
    return (
      <div ref={containerRef}>
        <Skeleton />
      </div>
    )
  }

  if (isError) {
    return (
      <div ref={containerRef} className="bg-surface rounded-2xl border border-border p-5">
        <h2 className="text-sm font-semibold text-ink mb-2">Compare with Peers</h2>
        <p className="text-sm text-caption text-center py-6">Peer data unavailable</p>
        <div className="text-center">
          <button
            onClick={() => refetch()}
            className="text-xs font-medium text-brand hover:underline"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (!hasPeers || !data?.peers?.length) {
    return (
      <div ref={containerRef} className="bg-surface rounded-2xl border border-border p-5">
        <h2 className="text-sm font-semibold text-ink mb-2">Compare with Peers</h2>
        <p className="text-xs text-caption text-center py-6">
          {data?.message ?? "Peer comparison coming soon for this sector."}
        </p>
      </div>
    )
  }

  const rows = data.peers

  return (
    <div ref={containerRef} className="bg-surface rounded-2xl border border-border p-5 space-y-3">
      {/* Header */}
      <div>
        <h2 className="text-sm font-semibold text-ink">Compare with Peers</h2>
        {data.sector_label && (
          <p className="text-[11px] text-caption mt-0.5">{data.sector_label}</p>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border">
              {columns.map((col, i) => (
                <th
                  key={col.key}
                  className={cn(
                    "py-2 text-[10px] font-medium text-caption uppercase tracking-wide",
                    i === 0
                      ? "sticky left-0 bg-surface z-10 text-left pl-1 pr-3 min-w-[140px]"
                      : "text-right px-2 min-w-[70px]",
                  )}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => {
              const isMain = row.is_main
              return (
                <tr
                  key={row.ticker}
                  onMouseEnter={() => {
                    if (!isMain) router.prefetch(`/analysis/${row.ticker}`)
                  }}
                  onClick={() => {
                    if (!isMain) router.push(`/analysis/${row.ticker}`)
                  }}
                  className={cn(
                    "border-b border-border last:border-0 transition-colors",
                    isMain
                      ? "bg-brand-50/60 border-l-4 border-l-brand"
                      : "cursor-pointer hover:bg-bg",
                  )}
                >
                  {columns.map((col, i) => {
                    const isBest =
                      col.metric !== undefined &&
                      (data.best_in_sector?.[col.metric as string] ?? null) === row.ticker
                    return (
                      <td
                        key={col.key}
                        className={cn(
                          "py-2 relative",
                          i === 0
                            ? cn(
                                "sticky left-0 z-10 pl-1 pr-3",
                                isMain ? "bg-brand-50/60" : "bg-surface",
                              )
                            : "text-right px-2",
                          isBest && !isMain && "bg-green-50/70",
                        )}
                      >
                        {col.render(row)}
                        {isBest && i !== 0 && (
                          <span
                            className="absolute top-1 right-1 text-green-500"
                            aria-hidden="true"
                            title="Best in sector"
                          >
                            ●
                          </span>
                        )}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Auto-generated insight line */}
      {insight && (
        <p className="text-xs text-body bg-bg rounded-xl p-3 leading-relaxed">
          {insight}
        </p>
      )}

      {/* Missing scores note */}
      {anyMissingScore && (
        <p className="text-[11px] text-caption">
          — YieldIQ Score not yet computed for some peers. Analyse them to see scores.
        </p>
      )}
    </div>
  )
}
