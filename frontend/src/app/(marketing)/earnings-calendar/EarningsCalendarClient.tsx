"use client"

import { useState, useMemo } from "react"
import Link from "next/link"
import MarketingTopNav from "@/components/marketing/MarketingTopNav"

interface EarningsEvent {
  ticker: string
  display_ticker: string
  company_name: string
  sector: string | null
  event_date: string
  event_type: string
  purpose: string
  days_away: number
}

interface CalendarData {
  total: number
  window_days: number
  by_date: { date: string; count: number; tickers: string[] }[]
  events: EarningsEvent[]
}

/**
 * Normalize calendar sector strings to the NSE-canonical taxonomy used
 * on stock pages. Backend-supplied raw labels drift between yfinance,
 * NSE corporate-event feed, and screener — auditor 2026-05-02 found
 * "Automobiles" / "Realty" / "Healthcare|Pharmaceuticals" on the
 * calendar while stock pages render "Auto OEM" / "Real Estate" / "Pharma".
 * Frontend-only normalization keeps backend untouched (no canary needed).
 *
 * Map kept lowercase-keyed for case-insensitive matching. Unknown
 * sectors fall through unchanged so we don't accidentally erase any
 * sector we haven't explicitly mapped.
 */
const SECTOR_ALIAS_MAP: Record<string, string> = {
  // Auto family
  "auto": "Auto",
  "auto oem": "Auto",
  "automobile": "Auto",
  "automobiles": "Auto",
  "auto components": "Auto",
  // IT / tech
  "it": "IT Services",
  "it services": "IT Services",
  "technology": "IT Services",
  "information technology": "IT Services",
  // Pharma / healthcare
  "pharma": "Pharma",
  "pharmaceuticals": "Pharma",
  "healthcare": "Pharma",
  "health care": "Pharma",
  // Realty
  "realty": "Real Estate",
  "real estate": "Real Estate",
  // Banks
  "bank": "Bank",
  "banks": "Bank",
  "private bank": "Private Bank",
  "psu bank": "PSU Bank",
  // Other NSE sectorals — pass-throughs with consistent casing
  "fmcg": "FMCG",
  "energy": "Energy",
  "metal": "Metal",
  "metals": "Metal",
  "media": "Media",
  "financial services": "Financial Services",
}

function normalizeSector(raw: string | null | undefined): string | null {
  if (!raw) return null
  const key = raw.trim().toLowerCase()
  return SECTOR_ALIAS_MAP[key] ?? raw
}

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })
  } catch {
    return iso
  }
}

function dayLabel(daysAway: number): string {
  if (daysAway === 0) return "Today"
  if (daysAway === 1) return "Tomorrow"
  if (daysAway <= 7) return `In ${daysAway} days`
  return `In ${daysAway} days`
}

function dayBadge(daysAway: number): string {
  if (daysAway === 0) return "bg-red-50 text-red-700 border-red-200"
  if (daysAway === 1) return "bg-amber-50 text-amber-700 border-amber-200"
  if (daysAway <= 7) return "bg-blue-50 text-blue-700 border-blue-200"
  return "bg-gray-50 text-gray-600 border-gray-200"
}

export default function EarningsCalendarClient({ data }: { data: CalendarData }) {
  const [sectorFilter, setSectorFilter] = useState("")
  const [search, setSearch] = useState("")

  // Build the dropdown from NORMALIZED sector names so the user sees
  // one entry per canonical sector (e.g. "Auto" — not separate
  // "Automobiles" / "Auto OEM" rows). See SECTOR_ALIAS_MAP above.
  const sectors = useMemo(() => {
    const s = new Set(
      data.events
        .map(e => normalizeSector(e.sector))
        .filter((x): x is string => Boolean(x)),
    )
    return Array.from(s).sort()
  }, [data.events])

  const filtered = useMemo(() => {
    return data.events.filter(e => {
      if (sectorFilter && normalizeSector(e.sector) !== sectorFilter) return false
      if (search) {
        const q = search.toLowerCase()
        if (!e.display_ticker.toLowerCase().includes(q) &&
            !e.company_name.toLowerCase().includes(q)) return false
      }
      return true
    })
  }, [data.events, sectorFilter, search])

  // Group filtered events by date
  const grouped = useMemo(() => {
    const map = new Map<string, EarningsEvent[]>()
    filtered.forEach(e => {
      if (!map.has(e.event_date)) map.set(e.event_date, [])
      map.get(e.event_date)!.push(e)
    })
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [filtered])

  return (
    <div className="min-h-screen bg-white">
      <MarketingTopNav />

      {/* Header */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-12 sm:py-16">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h1 className="text-3xl sm:text-4xl font-black text-white mb-3">Earnings Calendar</h1>
          <p className="text-gray-400 mb-4">
            Upcoming results for Indian stocks &middot; Next {data.window_days} days &middot; {data.total} events
          </p>
          {data.by_date.length > 0 && (
            <div className="flex flex-wrap justify-center gap-2 mt-4">
              {data.by_date.slice(0, 7).map(d => (
                <div key={d.date} className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs">
                  <span className="text-gray-400">{fmtDate(d.date)}</span>
                  <span className="text-blue-400 font-bold ml-2">{d.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Filters */}
      <section className="max-w-4xl mx-auto px-4 py-6 border-b border-gray-100">
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            type="text"
            placeholder="Search ticker or company..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="flex-1 px-4 py-2.5 border border-gray-200 rounded-lg text-sm bg-white"
          />
          <select
            value={sectorFilter}
            onChange={e => setSectorFilter(e.target.value)}
            className="px-4 py-2.5 border border-gray-200 rounded-lg text-sm bg-white text-gray-700"
          >
            <option value="">All Sectors</option>
            {sectors.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </section>

      {/* Events grouped by date */}
      <section className="max-w-4xl mx-auto px-4 py-8 space-y-6">
        {grouped.length === 0 && (
          <div className="text-center py-16 text-gray-400">
            <p className="text-lg font-semibold mb-1">No upcoming earnings found</p>
            <p className="text-sm">Try adjusting filters, or check back soon — calendar updates daily from NSE</p>
          </div>
        )}

        {grouped.map(([date, events]) => {
          const daysAway = events[0].days_away
          return (
            <div key={date}>
              <div className="flex items-baseline justify-between mb-3 border-b border-gray-100 pb-2">
                <div>
                  <h2 className="text-lg font-bold text-gray-900">{fmtDate(date)}</h2>
                  <p className="text-xs text-gray-400">{events.length} {events.length === 1 ? "result" : "results"}</p>
                </div>
                <span className={`text-[10px] font-bold px-2 py-1 rounded-full border ${dayBadge(daysAway)}`}>
                  {dayLabel(daysAway)}
                </span>
              </div>
              <div className="grid sm:grid-cols-2 gap-2">
                {events.map((e, i) => (
                  <Link
                    key={`${e.ticker}-${i}`}
                    href={`/stocks/${e.display_ticker}/fair-value`}
                    className="flex items-center gap-3 px-4 py-3 bg-white border border-gray-100 rounded-lg hover:border-blue-200 hover:shadow-sm transition"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-bold text-gray-900">{e.display_ticker}</p>
                      <p className="text-xs text-gray-500 truncate">{e.company_name}</p>
                      {e.sector && <p className="text-[10px] text-gray-400 mt-0.5">{normalizeSector(e.sector)}</p>}
                    </div>
                    <div className="text-right">
                      <p className="text-[10px] text-gray-400 uppercase tracking-wider">{e.event_type}</p>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          )
        })}
      </section>

      {/* CTA */}
      <section className="bg-gray-50 border-t border-gray-100 py-12">
        <div className="max-w-3xl mx-auto px-4 text-center">
          <h2 className="text-2xl font-black text-gray-900 mb-3">Get notified before earnings</h2>
          <p className="text-gray-500 mb-6">Set price alerts and get notified before any stock&apos;s earnings call.</p>
          <Link href="/auth/signup" className="inline-block bg-blue-600 text-white font-bold px-8 py-4 rounded-xl text-lg hover:bg-blue-700 transition shadow-lg shadow-blue-500/20">
            Start Free &rarr;
          </Link>
        </div>
      </section>

      <footer className="py-6 border-t border-gray-100">
        <p className="text-[10px] text-gray-400 text-center max-w-2xl mx-auto px-4">
          Data sourced from NSE corporate event calendar. Not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser.
        </p>
      </footer>
    </div>
  )
}
