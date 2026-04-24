import Link from "next/link"
import type { PublicPeersResponse } from "@/lib/api"
import MetricTooltip from "@/components/analysis/MetricTooltip"

interface Props {
  ticker: string
  data: PublicPeersResponse | null
}

function verdictClasses(v: string | null | undefined): string {
  if (!v) return "bg-gray-50 text-gray-600 border-gray-200"
  const k = v.toLowerCase()
  if (k === "undervalued") return "bg-green-50 text-green-700 border-green-200"
  if (k === "overvalued") return "bg-red-50 text-red-700 border-red-200"
  if (k === "avoid") return "bg-red-100 text-red-800 border-red-300"
  if (k === "fairly_valued" || k === "fairly valued") return "bg-blue-50 text-blue-700 border-blue-200"
  return "bg-gray-50 text-gray-600 border-gray-200"
}

function verdictLabel(v: string | null | undefined): string {
  // Fallback was a bare em-dash, which read as broken. "Pending" is
  // honest — the verdict hasn't been computed for this peer yet.
  if (!v) return "Pending"
  const k = v.toLowerCase()
  const map: Record<string, string> = {
    undervalued: "Below Fair Value",
    fairly_valued: "Near Fair Value",
    overvalued: "Above Fair Value",
    avoid: "High Risk",
    data_limited: "Data Limited",
  }
  if (map[k]) return map[k]
  return v.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())
}

function fmtPct(v: number | null | undefined, decimals = 1): string {
  if (v == null || isNaN(v)) return "\u2014"
  return `${v >= 0 ? "+" : ""}${v.toFixed(decimals)}%`
}

function fmtNum(v: number | null | undefined, decimals = 1, suffix = ""): string {
  if (v == null || isNaN(v)) return "\u2014"
  return `${v.toFixed(decimals)}${suffix}`
}

function Placeholder({ ticker }: { ticker: string }) {
  return (
    <section
      className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8"
      aria-label={`Peer comparison for ${ticker}`}
    >
      <h2 className="text-lg font-bold text-gray-900 mb-1">Peer Comparison</h2>
      <p className="text-sm text-gray-500">
        Peers not yet ranked for {ticker}. Comparable companies and side-by-side
        valuation will appear here once the peer set is established.
      </p>
    </section>
  )
}

export default function PeerComparisonCard({ ticker, data }: Props) {
  if (!data || !data.peers || data.peers.length === 0) {
    return <Placeholder ticker={ticker} />
  }

  return (
    <section
      className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8"
      aria-label={`Peer comparison for ${ticker}`}
    >
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-900">Peer Comparison</h2>
        <p className="text-xs text-gray-400">
          {ticker.toUpperCase()} vs {data.peers.length} closest peer{data.peers.length === 1 ? "" : "s"} by market-cap band
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-gray-500 border-b border-gray-200">
              <th className="text-left py-2 pr-3 font-semibold">Peer</th>
              <th className="text-right py-2 px-2 font-semibold">
                <span className="inline-flex items-center justify-end gap-1 w-full">
                  <MetricTooltip metricKey="mos">MoS</MetricTooltip>
                </span>
              </th>
              <th className="text-right py-2 px-2 font-semibold">
                <span className="inline-flex items-center justify-end gap-1 w-full">
                  <MetricTooltip metricKey="yieldiq_score">Score</MetricTooltip>
                </span>
              </th>
              <th className="text-left py-2 px-2 font-semibold">
                <MetricTooltip metricKey="verdict">Verdict</MetricTooltip>
              </th>
              <th className="text-right py-2 px-2 font-semibold">
                <span className="inline-flex items-center justify-end gap-1 w-full">
                  <MetricTooltip metricKey="roe">ROE</MetricTooltip>
                </span>
              </th>
              <th className="text-right py-2 pl-2 font-semibold">
                <span className="inline-flex items-center justify-end gap-1 w-full">
                  <MetricTooltip metricKey="pe_ratio">PE</MetricTooltip>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {data.peers.map(peer => {
              const vc = verdictClasses(peer.verdict)
              return (
                <tr
                  key={peer.peer_ticker}
                  className="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition"
                >
                  <td className="py-2 pr-3">
                    <Link
                      href={`/stocks/${peer.peer_ticker}/fair-value`}
                      className="text-blue-600 hover:text-blue-700 font-semibold font-mono"
                    >
                      {peer.peer_ticker}
                    </Link>
                    {peer.company_name ? (
                      <p className="text-[10px] text-gray-400 truncate max-w-[200px]">
                        {peer.company_name}
                      </p>
                    ) : null}
                  </td>
                  <td
                    className={`py-2 px-2 text-right font-mono tabular-nums ${
                      peer.margin_of_safety != null
                        ? peer.margin_of_safety >= 0
                          ? "text-green-600"
                          : "text-red-600"
                        : "text-gray-400"
                    }`}
                  >
                    {fmtPct(peer.margin_of_safety)}
                  </td>
                  <td className="py-2 px-2 text-right font-mono tabular-nums text-gray-900">
                    {peer.score != null ? peer.score.toFixed(0) : "\u2014"}
                  </td>
                  <td className="py-2 px-2">
                    <span
                      className={`inline-block px-2 py-0.5 rounded-full border text-[10px] font-semibold ${vc}`}
                    >
                      {verdictLabel(peer.verdict)}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-right font-mono tabular-nums text-gray-900">
                    {fmtNum(peer.roe, 1, "%")}
                  </td>
                  <td className="py-2 pl-2 text-right font-mono tabular-nums text-gray-900">
                    {fmtNum(peer.pe_ratio, 1, "\u00D7")}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[10px] text-gray-400">
        Click a ticker to view its fair-value analysis.
      </p>
    </section>
  )
}
