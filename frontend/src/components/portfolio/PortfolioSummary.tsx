import Link from "next/link"
import { cache } from "react"
import { getStockSummary, type StockSummary } from "@/lib/api"

/**
 * Portfolio summary (Task C3 — server half).
 * --------------------------------------------------------------------------
 * Server component that resolves a list of holdings (parsed by the client
 * uploader and serialised into the URL) into a fully-priced portfolio view:
 * total invested, current value, weighted FV/MoS, top mover, sector mix.
 *
 * Per-ticker fetches go through `getStockSummary` wrapped in React `cache()`
 * so render passes within the same request dedupe (and the underlying
 * `fetch` already participates in Next 16's data cache via `revalidate`,
 * so the same ticker requested twice in a row hits the in-memory cache).
 */

export interface ParsedHolding {
  ticker: string
  quantity: number
  buy_price: number
  buy_date: string
}

const cachedSummary = cache(async (ticker: string): Promise<StockSummary | null> => {
  return getStockSummary(ticker)
})

interface ResolvedHolding {
  h: ParsedHolding
  s: StockSummary | null
  invested: number
  currentValue: number
  pnlAbs: number
  pnlPct: number
  weightedFV: number | null
  weightedMos: number | null
}

function fmt(n: number, currency = "INR"): string {
  if (!isFinite(n)) return "—"
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(n)
}

function pct(n: number): string {
  if (!isFinite(n)) return "—"
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`
}

interface Props {
  holdings: ParsedHolding[]
}

export default async function PortfolioSummary({ holdings }: Props) {
  if (!holdings.length) return null

  // Parallelise per-ticker fetches via Promise.all + cache().
  const summaries = await Promise.all(holdings.map(h => cachedSummary(h.ticker)))

  const resolved: ResolvedHolding[] = holdings.map((h, i) => {
    const s = summaries[i]
    const invested = h.quantity * h.buy_price
    const cmp = s?.current_price ?? h.buy_price
    const currentValue = h.quantity * cmp
    const pnlAbs = currentValue - invested
    const pnlPct = invested > 0 ? (pnlAbs / invested) * 100 : 0
    const weightedFV = s ? s.fair_value * h.quantity : null
    const weightedMos = s ? s.mos : null
    return { h, s, invested, currentValue, pnlAbs, pnlPct, weightedFV, weightedMos }
  })

  const totalInvested = resolved.reduce((a, r) => a + r.invested, 0)
  const totalCurrent = resolved.reduce((a, r) => a + r.currentValue, 0)
  const totalPnL = totalCurrent - totalInvested
  const totalPnLPct = totalInvested > 0 ? (totalPnL / totalInvested) * 100 : 0

  // Weighted aggregates (skip holdings with no summary).
  const priced = resolved.filter(r => r.s)
  const aggFV = priced.reduce((a, r) => a + (r.weightedFV ?? 0), 0)
  const weightedMos = (() => {
    const totalWeight = priced.reduce((a, r) => a + r.currentValue, 0)
    if (totalWeight <= 0) return 0
    const num = priced.reduce((a, r) => a + (r.s!.mos * r.currentValue), 0)
    return num / totalWeight
  })()

  // Top gainer / loser by % P&L.
  const sortedByPct = [...resolved].sort((a, b) => b.pnlPct - a.pnlPct)
  const topGainer = sortedByPct[0]
  const topLoser = sortedByPct[sortedByPct.length - 1]

  // Sector exposure by current value.
  const sectorMap = new Map<string, number>()
  for (const r of resolved) {
    const sector = r.s?.sector || "Unknown"
    sectorMap.set(sector, (sectorMap.get(sector) ?? 0) + r.currentValue)
  }
  const sectorRows = Array.from(sectorMap.entries())
    .map(([sector, value]) => ({ sector, value, pct: totalCurrent > 0 ? (value / totalCurrent) * 100 : 0 }))
    .sort((a, b) => b.value - a.value)

  return (
    <div className="space-y-6">
      {/* Headline KPIs */}
      <section
        className="rounded-2xl border bg-white p-5 sm:p-6"
        style={{ borderColor: "var(--color-border, #E2E8F0)" }}
      >
        <h2 className="text-lg font-bold mb-4" style={{ color: "var(--color-ink, #0F172A)" }}>
          Portfolio overview
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Kpi label="Invested" value={fmt(totalInvested)} />
          <Kpi label="Current value" value={fmt(totalCurrent)} />
          <Kpi
            label="P&L"
            value={`${totalPnL >= 0 ? "+" : "-"}${fmt(Math.abs(totalPnL))}`}
            color={totalPnL >= 0 ? "text-green-600" : "text-red-600"}
          />
          <Kpi
            label="P&L %"
            value={pct(totalPnLPct)}
            color={totalPnLPct >= 0 ? "text-green-600" : "text-red-600"}
          />
          <Kpi label="Aggregated FV" value={fmt(aggFV)} />
          <Kpi
            label="Weighted MoS"
            value={pct(weightedMos)}
            color={weightedMos >= 0 ? "text-green-600" : "text-red-600"}
          />
          <Kpi
            label="Top gainer"
            value={topGainer ? `${topGainer.h.ticker} ${pct(topGainer.pnlPct)}` : "—"}
            color="text-green-600"
          />
          <Kpi
            label="Top loser"
            value={topLoser ? `${topLoser.h.ticker} ${pct(topLoser.pnlPct)}` : "—"}
            color="text-red-600"
          />
        </div>
      </section>

      {/* Holdings table */}
      <section
        className="rounded-2xl border bg-white p-5 sm:p-6"
        style={{ borderColor: "var(--color-border, #E2E8F0)" }}
      >
        <h2 className="text-lg font-bold mb-3" style={{ color: "var(--color-ink, #0F172A)" }}>
          Holdings ({resolved.length})
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-gray-400">
                <th className="px-2 py-2">Ticker</th>
                <th className="px-2 py-2 text-right">Qty</th>
                <th className="px-2 py-2 text-right">Buy</th>
                <th className="px-2 py-2 text-right">CMP</th>
                <th className="px-2 py-2 text-right">Invested</th>
                <th className="px-2 py-2 text-right">Value</th>
                <th className="px-2 py-2 text-right">P&L</th>
                <th className="px-2 py-2 text-right">P&L %</th>
                <th className="px-2 py-2 text-right">FV</th>
                <th className="px-2 py-2 text-right">MoS</th>
              </tr>
            </thead>
            <tbody>
              {resolved.map(r => {
                const cmp = r.s?.current_price ?? r.h.buy_price
                const fv = r.s?.fair_value ?? null
                const mos = r.s?.mos ?? null
                return (
                  <tr
                    key={r.h.ticker}
                    className="border-t font-mono text-xs"
                    style={{ borderColor: "var(--color-border, #E2E8F0)" }}
                  >
                    <td className="px-2 py-2 font-semibold">
                      <Link
                        href={`/stocks/${r.h.ticker}/fair-value`}
                        className="text-blue-700 hover:underline"
                      >
                        {r.h.ticker}
                      </Link>
                      {!r.s && (
                        <span className="ml-1 text-[10px] text-amber-600">·under review</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right">{r.h.quantity}</td>
                    <td className="px-2 py-2 text-right">{fmt(r.h.buy_price)}</td>
                    <td className="px-2 py-2 text-right">{fmt(cmp)}</td>
                    <td className="px-2 py-2 text-right">{fmt(r.invested)}</td>
                    <td className="px-2 py-2 text-right">{fmt(r.currentValue)}</td>
                    <td className={`px-2 py-2 text-right ${r.pnlAbs >= 0 ? "text-green-600" : "text-red-600"}`}>
                      {r.pnlAbs >= 0 ? "+" : "-"}{fmt(Math.abs(r.pnlAbs))}
                    </td>
                    <td className={`px-2 py-2 text-right ${r.pnlPct >= 0 ? "text-green-600" : "text-red-600"}`}>
                      {pct(r.pnlPct)}
                    </td>
                    <td className="px-2 py-2 text-right">{fv != null ? fmt(fv) : "—"}</td>
                    <td className={`px-2 py-2 text-right ${mos != null && mos >= 0 ? "text-green-600" : "text-red-600"}`}>
                      {mos != null ? pct(mos) : "—"}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Sector mix */}
      <section
        className="rounded-2xl border bg-white p-5 sm:p-6"
        style={{ borderColor: "var(--color-border, #E2E8F0)" }}
      >
        <h2 className="text-lg font-bold mb-3" style={{ color: "var(--color-ink, #0F172A)" }}>
          Sector exposure
        </h2>
        <ul className="space-y-2">
          {sectorRows.map(s => (
            <li key={s.sector} className="text-xs">
              <div className="flex justify-between mb-1">
                <span className="font-semibold" style={{ color: "var(--color-ink, #0F172A)" }}>
                  {s.sector}
                </span>
                <span className="font-mono text-gray-500">
                  {fmt(s.value)} · {s.pct != null ? s.pct.toFixed(1) : "0"}%
                </span>
              </div>
              <div
                className="h-1.5 rounded-full overflow-hidden"
                style={{ background: "var(--color-border, #E2E8F0)" }}
              >
                <div
                  className="h-full"
                  style={{ width: `${s.pct}%`, background: "var(--color-brand, #2563EB)" }}
                />
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

function Kpi({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div
      className="rounded-xl border p-3"
      style={{ borderColor: "var(--color-border, #E2E8F0)" }}
    >
      <p className="text-[10px] uppercase tracking-wider text-gray-400">{label}</p>
      <p className={`text-base font-bold font-mono mt-1 ${color ?? ""}`}>{value}</p>
    </div>
  )
}
