import Link from "next/link"
import { useMemo } from "react"
import type { PublicPeersResponse } from "@/lib/api"
import MetricTooltip from "@/components/analysis/MetricTooltip"
import { verdictClassesWithDark } from "@/lib/constants"
import { formatNumberWithSuffix, formatPctSigned, cn } from "@/lib/utils"
import { metricToneClass } from "@/lib/metricTone"
import { DataCard } from "@/components/cards"

interface Props {
  ticker: string
  data: PublicPeersResponse | null
}

// Day-34 (2026-05-20): the local verdictClasses() helper used to
// duplicate the bg/text/border tailwind triplet inline AND diverged
// from VERDICT_COLORS (green for undervalued vs canonical blue). Now
// delegates to verdictClassesWithDark() in lib/constants.ts so peer
// chips stay in lockstep with VerdictChip + the hero pill.
function verdictClasses(v: string | null | undefined): string {
  return verdictClassesWithDark(v)
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

// Day-35 (2026-05-20): local fmtPct / fmtNum replaced by canonical
// helpers from lib/utils.ts. The local versions diverged on the
// em-dash fallback path (isNaN check ignored +/- Infinity) and the
// default decimal precision. One source of truth now.
const fmtPct = formatPctSigned
const fmtNum = formatNumberWithSuffix

function Placeholder({ ticker }: { ticker: string }) {
  // PR-B (design-synthesis §5): peers is data-dense → DataCard variant.
  // mb-8 stays outside the card to preserve section vertical rhythm.
  return (
    <DataCard
      hover={false}
      role="region"
      className="mb-8 p-6 text-sm leading-normal"
      aria-label={`Peer comparison for ${ticker}`}
    >
      <h2 className="text-lg font-bold text-ink mb-1">Peer Comparison</h2>
      <p className="text-sm text-caption">
        Peers not yet ranked for {ticker}. Comparable companies and side-by-side
        valuation will appear here once the peer set is established.
      </p>
    </DataCard>
  )
}

export default function PeerComparisonCard({ ticker, data }: Props) {
  // `has_peers` is the canonical signal but is optional for backward
  // compat with cached responses that pre-date the 2026-04-29 fix.
  // Fall back to a non-empty `peers` array.
  const hasPeers = data?.has_peers ?? ((data?.peers?.length ?? 0) > 0)

  // Tickertape trick #4 (.audit/tickertape-deep-walk-2026-05-27.md): color
  // each peer's P/E vs the cohort median rendered in this table. Hook lives
  // before the early return so React-rules-of-hooks is honored on empty
  // cohorts (Placeholder branch below).
  const cohortPeMedian = useMemo<number | null>(() => {
    const xs = (data?.peers ?? [])
      .map(p => p.pe_ratio)
      .filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v > 0)
      .sort((a, b) => a - b)
    if (xs.length === 0) return null
    const mid = Math.floor(xs.length / 2)
    return xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2
  }, [data])

  if (!data || !hasPeers || !data.peers?.length) {
    return <Placeholder ticker={ticker} />
  }

  return (
    // PR-B (design-synthesis §5): peers table → DataCard.
    // p-6 + mb-8 retained to preserve section vertical rhythm; hover off
    // because the card itself is non-interactive (only inner rows are).
    <DataCard
      hover={false}
      role="region"
      className="mb-8 p-6 text-sm leading-normal"
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
                      className="text-blue-600 hover:text-tone-info-fg font-semibold font-mono"
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
                  <td
                    className={cn(
                      "py-2 px-2 text-right font-mono tabular-nums",
                      metricToneClass({ metric: "roe", value: peer.roe }),
                    )}
                  >
                    {fmtNum(peer.roe, 1, "%")}
                  </td>
                  <td
                    className={cn(
                      "py-2 pl-2 text-right font-mono tabular-nums",
                      metricToneClass({
                        metric: "pe",
                        value: peer.pe_ratio,
                        sectorMedian: cohortPeMedian,
                      }),
                    )}
                  >
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
    </DataCard>
  )
}
