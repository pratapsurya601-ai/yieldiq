"use client"
// TODO: swap to design tokens
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getHoldingsLive, getWatchlist } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { ArrowRight } from "lucide-react"
// PreloadTicker removed 2026-04-27: speculative preload of
// api.yieldiq.in/api/v1/prism/<ticker> (e.g. TITAN.NS) showed up as an
// unused preload in DevTools because most users do not click the CTA.

// Picks the single most important "your next action" card for the logged-in
// user. Priority:
//   1. Holding with largest absolute MoS deviation from fair value (acts as a
//      review prompt when one of the user's own stocks has drifted far from
//      fair value — either way).
//   2. First watchlist item.
//   3. First-time-user fallback that sends them to /search.
export default function TopAction() {
  const token = useAuthStore((s) => s.token)

  const { data: holdingsData } = useQuery({
    queryKey: ["holdings-live-home"],
    queryFn: getHoldingsLive,
    enabled: !!token,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
  const { data: watchlist } = useQuery({
    queryKey: ["watchlist-home"],
    queryFn: getWatchlist,
    enabled: !!token,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const holdings = holdingsData?.holdings ?? []
  const withMos = holdings.filter((h) => typeof h.mos_pct === "number")
  const topHolding = withMos.length
    ? [...withMos].sort(
        (a, b) => Math.abs((b.mos_pct ?? 0)) - Math.abs((a.mos_pct ?? 0)),
      )[0]
    : null

  if (topHolding) {
    const mos = topHolding.mos_pct ?? 0
    const reason =
      mos >= 20
        ? `now trades ${mos.toFixed(0)}% below fair value — time to revisit your thesis.`
        : mos <= -10
        ? `now trades ${Math.abs(mos).toFixed(0)}% above fair value — check whether to trim.`
        : `has drifted ${mos >= 0 ? mos.toFixed(0) : Math.abs(mos).toFixed(0)}% from fair value.`
    return (
      <ActionCard
        label="Your top action"
        title={`Review ${topHolding.display_ticker}`}
        body={`${topHolding.company_name} ${reason}`}
        ctaLabel={`Open ${topHolding.display_ticker}`}
        href={`/analysis/${topHolding.display_ticker}`}
        footnote="Model estimate. Not investment advice."
      />
    )
  }

  const firstWatch = watchlist && watchlist.length > 0 ? watchlist[0] : null
  if (firstWatch) {
    return (
      <ActionCard
        label="Your top action"
        title={`Check in on ${firstWatch.ticker}`}
        body={`You added ${firstWatch.company_name} to your watchlist. See where it stands today.`}
        ctaLabel={`Open ${firstWatch.ticker}`}
        href={`/analysis/${firstWatch.ticker}`}
        footnote="Model estimate. Not investment advice."
      />
    )
  }

  return (
    <ActionCard
      label="Start here"
      title="Analyse your first stock"
      body="Type any NSE/BSE ticker and get a fair value estimate in about 30 seconds."
      ctaLabel="Find a stock"
      href="/search"
    />
  )
}

function ActionCard({
  label,
  title,
  body,
  ctaLabel,
  href,
  footnote,
}: {
  label: string
  title: string
  body: string
  ctaLabel: string
  href: string
  footnote?: string
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 md:p-6 shadow-sm">
      <p className="text-[10px] font-bold text-caption uppercase tracking-widest mb-2">
        {label}
      </p>
      <h2 className="font-display text-xl md:text-2xl font-bold text-ink leading-snug mb-2">
        {title}
      </h2>
      <p className="text-sm text-body leading-relaxed mb-5">{body}</p>
      <Link
        href={href}
        className="inline-flex items-center gap-2 min-h-[44px] bg-brand text-white font-semibold text-sm px-5 py-3 rounded-xl hover:opacity-90 active:scale-[0.98] transition"
      >
        {ctaLabel} <ArrowRight className="w-4 h-4" />
      </Link>
      {footnote && (
        <p className="text-[11px] text-caption mt-3">{footnote}</p>
      )}
    </div>
  )
}
