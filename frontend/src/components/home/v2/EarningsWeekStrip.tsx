"use client"
// Earnings This Week — 7-day horizontal strip.
// Data: /api/v1/public/earnings-calendar?days=7 → { by_date: [{date, events}] }
// Each day card → /earnings-calendar?date=YYYY-MM-DD (the calendar page
// already supports date deeplink via its EarningsCalendarClient).

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import axios from "axios"

interface EarningsEvent {
  ticker: string
  display_ticker: string
  company_name: string
  event_date: string
  event_type: string
}
interface DayGroup {
  date: string
  events: EarningsEvent[]
  count?: number
}
interface EarningsResponse {
  by_date: DayGroup[]
  events: EarningsEvent[]
}

async function fetchEarnings(): Promise<EarningsResponse> {
  const base = process.env.NEXT_PUBLIC_API_URL || ""
  const res = await axios.get(`${base}/api/v1/public/earnings-calendar`, {
    params: { days: 7, limit: 200 },
  })
  return res.data
}

function formatDay(iso: string): { dow: string; dom: string } {
  const d = new Date(iso + "T00:00:00")
  return {
    dow: d.toLocaleDateString("en-US", { weekday: "short" }),
    dom: d.toLocaleDateString("en-US", { day: "numeric", month: "short" }),
  }
}

function Skeleton() {
  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="min-w-[140px] h-24 bg-border/60 rounded-xl animate-pulse flex-shrink-0" />
      ))}
    </div>
  )
}

export default function EarningsWeekStrip() {
  const { data, isLoading } = useQuery({
    queryKey: ["earnings-week-home"],
    queryFn: fetchEarnings,
    staleTime: 30 * 60 * 1000,
    retry: 1,
  })

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-bold uppercase tracking-wider text-ink">
          Earnings this week
        </h2>
        <Link href="/earnings-calendar" className="text-xs font-semibold text-brand hover:underline">
          Full calendar →
        </Link>
      </div>
      {isLoading ? (
        <Skeleton />
      ) : !data || data.by_date.length === 0 ? (
        <div className="bg-surface border border-border rounded-2xl p-4">
          <p className="text-xs text-body">No upcoming earnings this week.</p>
        </div>
      ) : (
        <div className="flex gap-2 overflow-x-auto pb-1 -mx-1 px-1">
          {data.by_date.slice(0, 7).map(day => {
            const { dow, dom } = formatDay(day.date)
            const count = day.count ?? day.events?.length ?? 0
            const top3 = (day.events ?? []).slice(0, 3)
            return (
              <Link
                key={day.date}
                href={`/earnings-calendar#${day.date}`}
                className="min-w-[150px] flex-shrink-0 bg-surface border border-border rounded-xl p-3 hover:border-brand transition"
              >
                <div className="flex items-baseline justify-between mb-2">
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-wider text-caption">{dow}</p>
                    <p className="text-sm font-semibold text-ink">{dom}</p>
                  </div>
                  <span className="text-base font-mono font-bold text-brand tabular-nums">
                    {count}
                  </span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {top3.map(ev => (
                    <span
                      key={ev.ticker}
                      className="text-[9px] font-mono px-1.5 py-0.5 bg-bg border border-border rounded text-body"
                    >
                      {ev.display_ticker}
                    </span>
                  ))}
                </div>
              </Link>
            )
          })}
        </div>
      )}
    </section>
  )
}
