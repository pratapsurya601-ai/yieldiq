import Link from "next/link"
import type { PublicPeersResponse } from "@/lib/api"
import MetricTooltip from "@/components/analysis/MetricTooltip"

interface Props {
  ticker: string
  data: PublicPeersResponse | null
}

function verdictClasses(v: string | null | undefined): string {
  // Each verdict carries an explicit dark: variant so the chip text stays
  // legible against the dark-mode card surface.
  if (!v) return "bg-gray-50 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700"
  const k = v.toLowerCase()
  if (k === "undervalued") return "bg-green-50 text-green-700 border-green-200 dark:bg-green-950/40 dark:text-green-300 dark:border-green-900"
  if (k === "overvalued") return "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900"
  if (k === "avoid") return "bg-red-100 text-red-800 border-red-300 dark:bg-red-950/50 dark:text-red-200 dark:border-red-900"
  if (k === "fairly_valued" || k === "fairly valued") return "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-900"
  return "bg-gray-50 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700"
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
      className="bg-bg dark:bg-surface rounded-2xl border border-border shadow-sm p-6 mb-8"
      aria-label={`Peer comparison for ${ticker}`}
    >
      <h2 className="text-lg font-bold text-ink mb-1">Peer Comparison</h2>
      <p className="text-sm text-caption">
        Peers not yet ranked for {ticker}. Comparable companies and side-by-side
        valuation will appear here once the peer set is established.
      </p>
    </section>
  )
}

export default function PeerComparisonCard({ ticker, data }: Props) {
  // `has_peers` is the canonical signal but is optional for backward
  // compat with cached responses that pre-date the 2026-04-29 fix.
  // Fall back to a non-empty `peers` array.
  const hasPeers = data?.has_peers ?? ((data?.peers?.length ?? 0) > 0)
  if (!data || !hasPeers || !data.peers?.length) {
    return <Placeholder ticker={ticker} />
  }

  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border shadow-sm p-6 mb-8"
      aria-label={`Peer comparison for ${ticker}`}
    >
      <div className="mb-4">
        <h2 className="text-lg font-bold text-ink">Peer Comparison</h2>
        <p className="text-xs text-caption">
          {ticker.toUpperCase()} vs {data.peers.length} closest peer{data.peers.length === 1 ? "" : "s"} by market-cap band
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-caption border-b border-border">
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
              // Tolerate either field — backend now sends both `ticker`
              // (canonical) and `peer_ticker` (legacy alias).
              const peerTicker = peer.ticker ?? peer.peer_ticker
              return (
                <tr
                  key={peerTicker}
                  className="border-b border-border last:border-0 hover:bg-surface dark:hover:bg-bg transition"
                >
                  <td className="py-2 pr-3">
                    <Link
                      href={`/stocks/${peerTicker}/fair-value`}
                      className="text-blue-600 hover:text-blue-700 font-semibold font-mono"
                    >
                      {peerTicker}
                    </Link>
                    {peer.company_name ? (
                      <p className="text-[10px] text-caption truncate max-w-[200px]">
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
                        : "text-caption"
                    }`}
                  >
                    {fmtPct(peer.margin_of_safety)}
                  </td>
                  <td className="py-2 px-2 text-right font-mono tabular-nums text-ink">
                    {peer.score != null ? peer.score.toFixed(0) : "\u2014"}
                  </td>
                  <td className="py-2 px-2">
                    <span
                      className={`inline-block px-2 py-0.5 rounded-full border text-[10px] font-semibold ${vc}`}
                    >
                      {verdictLabel(peer.verdict)}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-right font-mono tabular-nums text-ink">
                    {fmtNum(peer.roe, 1, "%")}
                  </td>
                  <td className="py-2 pl-2 text-right font-mono tabular-nums text-ink">
                    {fmtNum(peer.pe_ratio, 1, "\u00D7")}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[10px] text-caption">
        Click a ticker to view its fair-value analysis.
      </p>
    </section>
  )
}
