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
import { getMarketFlows, type MarketFlowRow } from "@/lib/api"

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
  const { data, isLoading } = useQuery({
    queryKey: ["market-flows", days],
    queryFn: () => getMarketFlows(days),
    staleTime: 1800_000,
  })

  if (isLoading) {
    return (
      <section>
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-3">
          Market Pulse — FII vs DII
        </p>
        <div className="bg-white border border-gray-100 rounded-xl p-6 text-center">
          <p className="text-xs text-gray-400">Loading flows…</p>
        </div>
      </section>
    )
  }

  const flows = data?.flows ?? []
  const days_ = groupByDate(flows).slice(0, 10)

  if (days_.length === 0) {
    return (
      <section>
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-3">
          Market Pulse — FII vs DII
        </p>
        <div className="bg-white border border-gray-100 rounded-xl p-6 text-center">
          <p className="text-sm font-semibold text-gray-900 mb-1">
            FII / DII flows are warming up
          </p>
          <p className="text-xs text-gray-500 max-w-xs mx-auto">
            NSE only publishes a current-day snapshot. Daily archive starts the day this feature ships — check back tomorrow.
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
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">
          Market Pulse — FII vs DII
        </p>
        <p className="text-[10px] text-gray-500">Last {days_.length} sessions · ₹ Cr</p>
      </div>
      <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-100 text-[10px] text-gray-400 uppercase">
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
                <tr key={d.date} className={`border-b border-gray-50 ${i % 2 === 1 ? "bg-gray-50/50" : ""}`}>
                  <td className="px-3 py-2 text-gray-700 font-mono">{d.date}</td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <span
                        className={`inline-block h-1.5 rounded ${(d.fii_net ?? 0) >= 0 ? "bg-blue-400" : "bg-red-400"}`}
                        style={{ width: `${fiiPct * 0.5}px` }}
                      />
                      <span
                        className={`font-mono ${(d.fii_net ?? 0) >= 0 ? "text-blue-700" : "text-red-700"}`}
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
                        className={`font-mono ${(d.dii_net ?? 0) >= 0 ? "text-blue-700" : "text-red-700"}`}
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
      <p className="text-[10px] text-gray-400 mt-1">
        Source: NSE FII/DII snapshot, archived daily by YieldIQ.
      </p>
    </section>
  )
}
