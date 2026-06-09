"use client"

import { useState, useMemo } from "react"
import Link from "next/link"
import { verdictLabel } from "@/lib/verdict"
import TickerAvatar from "@/components/common/TickerAvatar"
// Nav is now provided by (marketing)/layout.tsx

interface Stock {
  ticker: string
  display_ticker: string
  company_name: string
  sector: string
  current_price: number
  fair_value: number
  mos: number
  verdict: string
  score: number
  grade: string
  moat: string
  market_cap: number
}

interface DashboardData {
  index_id: string
  index_name: string
  description: string
  total_stocks: number
  available_stocks: number
  stocks: Stock[]
  summary: {
    undervalued: number
    fairly_valued: number
    overvalued: number
    most_undervalued: Stock | null
    most_overvalued: Stock | null
  }
}

type SortKey = "score" | "mos" | "current_price" | "fair_value" | "company_name"
type SortDir = "asc" | "desc"

function fmt(n: number): string {
  return n ? `\u20B9${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "\u2014"
}

function verdictBadge(v: string) {
  // SEBI-safe: route raw backend verdict through verdictLabel().
  // Dark-mode-aware colours added 2026-06-09 so the badges read on
  // the dark surface of the dashboard table.
  const label = verdictLabel(v)
  if (v === "undervalued")
    return (
      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-green-50 text-green-700 dark:bg-green-900/40 dark:text-green-300">
        {label}
      </span>
    )
  if (v === "overvalued" || v === "avoid")
    return (
      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-50 text-red-700 dark:bg-red-900/40 dark:text-red-300">
        {label}
      </span>
    )
  return (
    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
      {label}
    </span>
  )
}

function rowBg(mos: number): string {
  if (mos > 20) return "bg-green-50/50 dark:bg-green-950/20"
  if (mos < -20) return "bg-red-50/50 dark:bg-red-950/20"
  return ""
}

export default function IndexDashboardClient({ data }: { data: DashboardData }) {
  // 2026-06-09 Bug 2: default sort is MoS descending so the most-
  // undervalued constituents land at the top. Pre-fix the default was
  // score-desc, which buried the (often higher-MoS) mid-cap names.
  const [sortKey, setSortKey] = useState<SortKey>("mos")
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  const [sectorFilter, setSectorFilter] = useState("")

  const sectors = useMemo(() => {
    const s = new Set(data.stocks.map(st => st.sector).filter(Boolean))
    return Array.from(s).sort()
  }, [data.stocks])

  // 2026-06-09 — sector breakdown chip strip. Counts constituents per
  // sector and renders one chip per sector so the user can quickly
  // gauge cohort composition without scanning the table. Clicking a
  // chip filters the table to that sector (toggle on second click).
  const sectorCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const st of data.stocks) {
      if (!st.sector) continue
      counts.set(st.sector, (counts.get(st.sector) ?? 0) + 1)
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
  }, [data.stocks])

  const sorted = useMemo(() => {
    let filtered = data.stocks
    if (sectorFilter) filtered = filtered.filter(s => s.sector === sectorFilter)
    return [...filtered].sort((a, b) => {
      const aVal = a[sortKey] ?? 0
      const bVal = b[sortKey] ?? 0
      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortDir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal)
      }
      return sortDir === "asc" ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number)
    })
  }, [data.stocks, sortKey, sortDir, sectorFilter])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc")
    else { setSortKey(key); setSortDir("desc") }
  }

  const arrow = (key: SortKey) => sortKey === key ? (sortDir === "desc" ? " \u25BC" : " \u25B2") : ""

  const { summary } = data

  return (
    <div className="min-h-screen bg-bg dark:bg-surface">
      {/* Header */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-12 sm:py-16">
        <div className="max-w-6xl mx-auto px-4 text-center">
          <h1 className="text-3xl sm:text-4xl font-black text-white mb-3">{data.index_name}</h1>
          <p className="text-caption mb-6">{data.description} &middot; Updated daily &middot; Powered by DCF</p>

          {/* Summary stats */}
          <div className="flex flex-wrap justify-center gap-4 sm:gap-8">
            <div className="bg-bg dark:bg-surface/5 border border-white/10 rounded-xl px-4 py-3 text-center">
              <p className="text-2xl font-black text-green-400">{summary.undervalued}</p>
              <p className="text-xs text-caption">Below Fair Value</p>
            </div>
            <div className="bg-bg dark:bg-surface/5 border border-white/10 rounded-xl px-4 py-3 text-center">
              <p className="text-2xl font-black text-blue-400">{summary.fairly_valued}</p>
              <p className="text-xs text-caption">Near Fair Value</p>
            </div>
            <div className="bg-bg dark:bg-surface/5 border border-white/10 rounded-xl px-4 py-3 text-center">
              <p className="text-2xl font-black text-red-400">{summary.overvalued}</p>
              <p className="text-xs text-caption">Above Fair Value</p>
            </div>
          </div>

          {summary.most_undervalued && (
            <p className="text-sm text-caption mt-4">
              Largest discount to fair value: <span className="text-green-400 font-semibold">{summary.most_undervalued.display_ticker}</span> (+{summary.most_undervalued.mos.toFixed(1)}%)
              {summary.most_overvalued && (
                <> &middot; Largest premium to fair value: <span className="text-red-400 font-semibold">{summary.most_overvalued.display_ticker}</span> ({summary.most_overvalued.mos.toFixed(1)}%)</>
              )}
            </p>
          )}
        </div>
      </section>

      {/* Table */}
      <section className="max-w-6xl mx-auto px-4 py-8">
        {/* Sector breakdown chips — count of constituents per sector,
            wired as a filter shortcut. Hides when only one (or zero)
            sectors are present (e.g. NIFTY Bank, NIFTY IT). */}
        {sectorCounts.length > 1 && (
          <div
            className="flex flex-wrap gap-2 mb-4"
            data-testid="sector-chip-strip"
          >
            <button
              type="button"
              onClick={() => setSectorFilter("")}
              className={`text-[11px] font-semibold px-2.5 py-1 rounded-full border transition ${
                sectorFilter === ""
                  ? "bg-brand text-white border-brand"
                  : "bg-bg dark:bg-surface text-caption border-border hover:border-brand"
              }`}
            >
              All ({data.stocks.length})
            </button>
            {sectorCounts.map(([sector, count]) => (
              <button
                key={sector}
                type="button"
                onClick={() =>
                  setSectorFilter(prev => (prev === sector ? "" : sector))
                }
                className={`text-[11px] font-semibold px-2.5 py-1 rounded-full border transition ${
                  sectorFilter === sector
                    ? "bg-brand text-white border-brand"
                    : "bg-bg dark:bg-surface text-caption border-border hover:border-brand"
                }`}
              >
                {sector} ({count})
              </button>
            ))}
          </div>
        )}

        {/* Filter */}
        <div className="flex items-center justify-between mb-4">
          <p className="text-sm text-caption">
            Showing {sorted.length} of {data.available_stocks} stocks
            {data.available_stocks < data.total_stocks && (
              <span className="text-caption"> (cache warming — {data.total_stocks - data.available_stocks} remaining)</span>
            )}
          </p>
          <select
            value={sectorFilter}
            onChange={e => setSectorFilter(e.target.value)}
            className="text-sm border border-border rounded-lg px-3 py-2 bg-bg dark:bg-surface text-ink"
          >
            <option value="">All Sectors</option>
            {sectors.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-bg dark:bg-surface border-b border-border">
                <th className="text-left px-4 py-3 font-semibold text-caption w-10">#</th>
                <th className="text-left px-4 py-3 font-semibold text-caption cursor-pointer hover:text-ink select-none" onClick={() => toggleSort("company_name")}>
                  Company{arrow("company_name")}
                </th>
                <th className="text-right px-4 py-3 font-semibold text-caption cursor-pointer hover:text-ink select-none" onClick={() => toggleSort("current_price")}>
                  Price{arrow("current_price")}
                </th>
                <th className="text-right px-4 py-3 font-semibold text-caption cursor-pointer hover:text-ink select-none" onClick={() => toggleSort("fair_value")}>
                  Fair Value{arrow("fair_value")}
                </th>
                <th className="text-right px-4 py-3 font-semibold text-caption cursor-pointer hover:text-ink select-none" onClick={() => toggleSort("mos")}>
                  MoS%{arrow("mos")}
                </th>
                <th className="text-right px-4 py-3 font-semibold text-caption cursor-pointer hover:text-ink select-none" onClick={() => toggleSort("score")}>
                  Score{arrow("score")}
                </th>
                <th className="text-center px-4 py-3 font-semibold text-caption">Verdict</th>
                <th className="text-left px-4 py-3 font-semibold text-caption hidden sm:table-cell">Sector</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s, i) => (
                <tr
                  key={s.ticker}
                  className={`border-b border-border hover:bg-bg/60 dark:hover:bg-surface/60 transition cursor-pointer ${rowBg(s.mos)}`}
                >
                  <td className="px-4 py-3 text-caption text-xs">{i + 1}</td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/stocks/${s.display_ticker}/fair-value`}
                      className="flex items-center gap-3 group"
                    >
                      <TickerAvatar
                        ticker={s.ticker}
                        sector={s.sector}
                        size="sm"
                        className="flex-shrink-0 group-hover:scale-110 transition"
                      />
                      <div className="min-w-0">
                        <p className="font-semibold text-ink group-hover:text-brand transition">
                          {s.display_ticker}
                        </p>
                        <p className="text-xs text-caption truncate max-w-[180px]">
                          {s.company_name}
                        </p>
                      </div>
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-ink">{fmt(s.current_price)}</td>
                  <td className="px-4 py-3 text-right font-mono text-ink">{fmt(s.fair_value)}</td>
                  <td className={`px-4 py-3 text-right font-mono font-semibold ${s.mos >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {s.mos >= 0 ? "+" : ""}{s.mos.toFixed(1)}%
                  </td>
                  <td className="px-4 py-3 text-right font-bold text-ink">{s.score}</td>
                  <td className="px-4 py-3 text-center">{verdictBadge(s.verdict)}</td>
                  <td className="px-4 py-3 text-xs text-caption hidden sm:table-cell">{s.sector}</td>
                </tr>
              ))}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center text-caption">
                    <p className="font-semibold text-ink mb-1">
                      Nifty 50 fair-value snapshot
                    </p>
                    <p className="text-xs max-w-md mx-auto">
                      A ranked view of the Nifty 50 by DCF margin-of-safety,
                      score, and verdict. Click any ticker for full
                      fair-value analysis.
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* CTA */}
      <section className="bg-bg dark:bg-surface border-t border-border py-12">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h2 className="text-2xl font-black text-ink mb-3">Want full DCF analysis for any stock?</h2>
          <p className="text-caption mb-6">YieldIQ analyses 2,300+ Indian stocks with interactive DCF, sensitivity heatmap, and AI insights.</p>
          <Link href="/auth/signup" className="inline-block bg-blue-600 text-white font-bold px-8 py-4 rounded-xl text-lg hover:bg-blue-700 transition shadow-lg shadow-blue-500/20">
            Start Free &rarr;
          </Link>
        </div>
      </section>

      {/* Disclaimer */}
      <footer className="py-6 border-t border-border">
        <p className="text-xs text-caption text-center max-w-2xl mx-auto px-4 leading-relaxed">
          Model estimates using publicly available data. Not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser or research analyst.
        </p>
        <div className="flex justify-center gap-4 mt-3 text-xs text-caption">
          <Link href="/" className="hover:text-ink">&copy; 2026 YieldIQ</Link>
          <Link href="/terms" className="hover:text-ink">Terms</Link>
          <Link href="/privacy" className="hover:text-ink">Privacy</Link>
        </div>
      </footer>
    </div>
  )
}
