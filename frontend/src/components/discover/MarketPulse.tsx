"use client"
// MarketPulse — FII vs DII net daily flow over the last N days.
//
// Backend: GET /api/v1/public/market-flows?days=30
// Self-archived from NSE snapshot at 19:00 IST via the daily cron
// (.github/workflows/nse_flows_daily.yml). Coverage starts the day
// the cron first ran — empty state is the expected first-run UI.
//
// Renders a compact bar list (no chart library dependency) so the
// widget stays lightweight enough for the /discover page above the
// fold. Net positive (buy-side) is blue, net negative (sell-side)
// is red. All values are in ₹ crore as published by NSE.
import { useQuery } from "@tanstack/react-query"
import { getMarketFlows, BUILD_ID, type MarketFlowRow } from "@/lib/api"

interface DayBar {
  date: string
  fii_net: number | null
  dii_net: number | null
}

function groupByDate(flows: MarketFlowRow[]): DayBar[] {
  const map = new Map<string, DayBar>()
  for (const f of flows) {
    const k = f.trade_date
    if (!map.has(k)) {
      map.set(k, { date: k, fii_net: null, dii_net: null })
    }
    const row = map.get(k)!
    if (f.category === "FII") row.fii_net = f.net_value_cr
    else if (f.category === "DII") row.dii_net = f.net_value_cr
  }
  return Array.from(map.values()).sort((a, b) => (a.date < b.date ? 1 : -1))
}

function fmtCr(v: number | null): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  const abs = Math.abs(v)
  const sign = v >= 0 ? "+" : "−"
  return `${sign}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`
}

export default function MarketPulse({ days = 30 }: { days?: number }) {
  // P0 (2026-04-30): empty {flows: []} response was cached for 30min and,
  // on the discover page, often persisted across the daily cron tick because
  // refetchOnWindowFocus is off globally. Throw on empty so RQ retries.
  const { data, isLoading } = useQuery({
    queryKey: ["market-flows", days, BUILD_ID],
    queryFn: async () => {
      const d = await getMarketFlows(days)
      if (!d?.flows?.length) throw new Error("cold-start: market-flows empty")
      return d
    },
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 2,
  })

  const flows = data?.flows ?? []
  const days_ = groupByDate(flows).slice(0, 10)

  // Loading + zero-row branches collapsed into one calm explainer card.
  // The daily NSE cron is currently producing zero rows; rendering
  // "Loading flows…" or "warming up" reads as broken product to anon
  // visitors. When data lands the live table below renders normally.
  if (isLoading || days_.length === 0) {
    return (
      <section>
        <p className="text-[10px] font-bold text-caption uppercase tracking-widest mb-3">
          Market Pulse — FII vs DII
        </p>
        <div className="bg-bg dark:bg-surface border border-border rounded-xl p-6">
          <p className="text-sm font-semibold text-ink mb-2">
            Foreign vs domestic institutional flows
          </p>
          <p className="text-xs text-caption leading-relaxed">
            Tracks net daily flow (in ₹ crore) from Foreign Institutional
            Investors (FII) and Domestic Institutional Investors (DII) on
            NSE. Use it to read where large-pool money is leaning on any
            given session.
          </p>
          <p className="text-[10px] text-caption mt-3">
            Source: NSE FII/DII snapshot, archived daily by YieldIQ.
          </p>
        </div>
      </section>
    )
  }

  // For bar width scaling
  const maxAbs = Math.max(
    1,
    ...days_.flatMap((d) => [
      Math.abs(d.fii_net ?? 0),
      Math.abs(d.dii_net ?? 0),
    ]),
  )

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <p className="text-[10px] font-bold text-caption uppercase tracking-widest">
          Market Pulse — FII vs DII
        </p>
        <p className="text-[10px] text-caption">Last {days_.length} sessions · ₹ Cr</p>
      </div>
      <div className="bg-bg dark:bg-surface border border-border rounded-xl overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-[10px] text-caption uppercase">
              <th className="text-left px-3 py-2">Date</th>
              <th className="text-right px-3 py-2">FII Net</th>
              <th className="text-right px-3 py-2">DII Net</th>
            </tr>
          </thead>
          <tbody>
            {days_.map((d, i) => {
              const fiiPct = d.fii_net !== null
                ? Math.min(100, (Math.abs(d.fii_net) / maxAbs) * 100)
                : 0
              const diiPct = d.dii_net !== null
                ? Math.min(100, (Math.abs(d.dii_net) / maxAbs) * 100)
                : 0
              return (
                <tr key={d.date} className={`border-b border-border ${i % 2 === 1 ? "bg-surface/50" : ""}`}>
                  <td className="px-3 py-2 text-ink font-mono">{d.date}</td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <span
                        className={`inline-block h-1.5 rounded ${(d.fii_net ?? 0) >= 0 ? "bg-blue-400" : "bg-red-400"}`}
                        style={{ width: `${fiiPct * 0.5}px` }}
                      />
                      <span
                        className={`font-mono ${(d.fii_net ?? 0) >= 0 ? "text-tone-info-fg" : "text-tone-bad-fg"}`}
                      >
                        {fmtCr(d.fii_net)}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <span
                        className={`inline-block h-1.5 rounded ${(d.dii_net ?? 0) >= 0 ? "bg-blue-400" : "bg-red-400"}`}
                        style={{ width: `${diiPct * 0.5}px` }}
                      />
                      <span
                        className={`font-mono ${(d.dii_net ?? 0) >= 0 ? "text-tone-info-fg" : "text-tone-bad-fg"}`}
                      >
                        {fmtCr(d.dii_net)}
                      </span>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-caption mt-1">
        Source: NSE FII/DII snapshot, archived daily by YieldIQ.
      </p>
    </section>
  )
}
