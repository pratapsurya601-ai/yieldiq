"use client"

/**
 * SeeAlsoPeers — Alpha Spread style peer mini-cards.
 *
 * Surfaces 6-8 sector peers as tappable mini-cards at the bottom of the
 * analysis page. Each card carries the peer's current price, MoS chip
 * (color-coded), and verdict label. Click → navigate to that ticker's
 * analysis page so users keep moving through the same screen archetype
 * instead of bouncing back to search.
 *
 * Data: reuses the existing /api/v1/analysis/{ticker}/peers endpoint
 * (PeersResponse / PeerRow in lib/api.ts) — no backend change.
 */

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getPeers, type PeerRow } from "@/lib/api"
import {
  formatCurrency,
  formatPct,
  formatCompanyName,
  verdictDisplayLabel,
} from "@/lib/utils"
import TickerAvatar from "@/components/common/TickerAvatar"

interface Props {
  ticker: string
  currency: string
  /** Cap on cards rendered. Defaults to 8 (Alpha-Spread parity). */
  limit?: number
}

function mosTone(mos: number | null): string {
  if (mos == null || !Number.isFinite(mos)) return "bg-surface text-caption"
  if (mos >= 10) return "bg-[color:var(--color-success)]/10 text-success"
  if (mos <= -10) return "bg-[color:var(--color-danger)]/10 text-danger"
  return "bg-surface text-body"
}

function displayTicker(t: string): string {
  return t.replace(".NS", "").replace(".BO", "")
}

function PeerCard({
  peer,
  currency,
}: {
  peer: PeerRow
  currency: string
}) {
  const t = displayTicker(peer.ticker)
  const mos = peer.mos_pct
  const verdict = verdictDisplayLabel(peer.verdict ?? "")
  // Current price isn't on PeerRow — derive from fair_value + MoS so we
  // can render *something* in the price slot. Falls back to N/A.
  const derivedPrice =
    peer.fair_value != null && mos != null && Number.isFinite(mos)
      ? peer.fair_value / (1 + mos / 100)
      : null
  return (
    <Link
      href={`/analysis/${peer.ticker}`}
      className="group block rounded-xl border border-border bg-bg hover:border-brand hover:bg-surface transition p-3"
    >
      <div className="flex items-baseline justify-between gap-2 mb-1">
        <span className="flex items-center gap-1.5 min-w-0">
          <TickerAvatar ticker={peer.ticker} size="sm" />
          <span className="font-display text-sm font-semibold text-ink truncate group-hover:text-brand">
            {t}
          </span>
        </span>
        {derivedPrice != null && derivedPrice > 0 && (
          <span className="font-mono tabular-nums text-xs text-body shrink-0">
            {formatCurrency(derivedPrice, currency, peer.ticker)}
          </span>
        )}
      </div>
      <p className="text-[11px] text-caption truncate mb-2">
        {formatCompanyName(peer.company_name)}
      </p>
      <div className="flex items-center gap-2 flex-wrap">
        {mos != null && Number.isFinite(mos) && (
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-mono tabular-nums ${mosTone(mos)}`}
          >
            MoS {formatPct(mos)}
          </span>
        )}
        {verdict && (
          <span className="text-[11px] text-caption truncate">{verdict}</span>
        )}
      </div>
    </Link>
  )
}

export default function SeeAlsoPeers({ ticker, currency, limit = 8 }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["peers", ticker],
    queryFn: () => getPeers(ticker),
    enabled: !!ticker,
    staleTime: 30 * 60 * 1000,
    retry: 1,
  })

  if (isLoading) {
    return (
      <section className="bg-bg rounded-2xl border border-border p-4">
        <h2 className="text-sm font-semibold text-ink mb-3">See also</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-24 rounded-xl bg-surface animate-pulse" />
          ))}
        </div>
      </section>
    )
  }

  if (isError || !data || !data.has_peers || data.peers.length === 0) {
    return null
  }

  // Drop the main ticker itself (the peers endpoint sometimes echoes it
  // back with is_main=true) and cap to `limit`.
  const peers = data.peers
    .filter((p) => !p.is_main && p.ticker.toUpperCase() !== ticker.toUpperCase())
    .slice(0, limit)

  if (peers.length === 0) return null

  return (
    <section className="bg-bg rounded-2xl border border-border p-4">
      <div className="flex items-baseline justify-between mb-3 gap-2 flex-wrap">
        <h2 className="text-sm font-semibold text-ink">See also</h2>
        {data.sector_label && (
          <p className="text-xs text-caption">
            Showing peers in {data.sector_label}
          </p>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {peers.map((p) => (
          <PeerCard key={p.ticker} peer={p} currency={currency} />
        ))}
      </div>
    </section>
  )
}
