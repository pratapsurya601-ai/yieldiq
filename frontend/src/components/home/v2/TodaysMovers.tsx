"use client"
// Today's Movers — top 5 gainers + top 5 losers from the NIFTY 500.
// Daily-engagement widget on /home, slotted between the MarketsStrip
// and the Portfolio/Watchlist hero. Rows link to /analysis/{ticker}.
//
// SEBI watch: the label is "Today's Movers" — never "Top Picks", never
// "Buy these". The only on-row signal is the raw % change. There is no // sebi-allow: Buy
// implied recommendation in any string here. // sebi-allow: recommendation
//
// Data: /api/v1/market/today-movers?cohort=nifty500&limit=5
// Cached 60s server-side; client refetches every 60s during market hours.

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"

import TickerAvatar from "@/components/common/TickerAvatar"
import { getTodayMovers } from "@/lib/api"
import { formatPct } from "@/lib/utils"
import type { TodayMover } from "@/types/api"

// Mirrors MarketsStrip's hours gate so both widgets refresh in lockstep
// during market hours and idle after-hours. Duplicated rather than
// hoisted to a shared module because (a) it's two lines, (b) hoisting
// would create a hidden dependency across two home panels for no real
// gain.
function isMarketHoursIST(): boolean {
  const now = new Date()
  const istMs = now.getTime() + (now.getTimezoneOffset() + 330) * 60 * 1000
  const ist = new Date(istMs)
  const day = ist.getUTCDay()
  if (day === 0 || day === 6) return false
  const hour = ist.getUTCHours()
  return hour >= 9 && hour < 16
}

function MoverRow({ mover }: { mover: TodayMover }) {
  const up = mover.change_pct >= 0
  const color = up
    ? "text-green-600 dark:text-green-400"
    : "text-red-600 dark:text-red-400"
  return (
    <Link
      href={`/analysis/${mover.ticker}`}
      className="flex items-center gap-2.5 px-3 py-2 hover:bg-bg/40 transition border-b border-border last:border-b-0"
      data-testid="movers-row"
    >
      <TickerAvatar ticker={mover.ticker} size="sm" />
      <span className="font-mono font-semibold text-sm text-ink truncate min-w-0 flex-shrink">
        {mover.ticker}
      </span>
      <span className={`ml-auto font-mono text-sm tabular-nums ${color}`}>
        {formatPct(mover.change_pct)}
      </span>
    </Link>
  )
}

function Column({
  title,
  movers,
  emptyMessage,
}: {
  title: string
  movers: TodayMover[]
  emptyMessage: string
}) {
  return (
    <div className="bg-surface border border-border rounded-xl overflow-hidden">
      <div className="px-3 py-2 border-b border-border bg-bg/30">
        <h3 className="text-[11px] font-bold uppercase tracking-wider text-caption">
          {title}
        </h3>
      </div>
      {movers.length === 0 ? (
        <div className="px-3 py-6 text-xs text-caption text-center">
          {emptyMessage}
        </div>
      ) : (
        <div>
          {movers.map((m) => (
            <MoverRow key={m.ticker} mover={m} />
          ))}
        </div>
      )}
    </div>
  )
}

function Skeleton() {
  return (
    <div
      className="grid grid-cols-1 md:grid-cols-2 gap-4"
      data-testid="movers-skeleton"
    >
      {[0, 1].map((col) => (
        <div
          key={col}
          className="bg-surface border border-border rounded-xl overflow-hidden"
        >
          <div className="px-3 py-2 border-b border-border bg-bg/30">
            <div className="h-3 w-20 bg-border rounded animate-pulse" />
          </div>
          <div>
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                className="flex items-center gap-2.5 px-3 py-2 border-b border-border last:border-b-0"
              >
                <div className="h-6 w-6 bg-border rounded animate-pulse" />
                <div className="h-3 w-20 bg-border rounded animate-pulse" />
                <div className="ml-auto h-3 w-10 bg-border rounded animate-pulse" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function TodaysMovers() {
  const { data, isLoading } = useQuery({
    queryKey: ["today-movers", "nifty500", 5],
    queryFn: () => getTodayMovers("nifty500", 5),
    staleTime: 60 * 1000,
    refetchInterval: () => (isMarketHoursIST() ? 60 * 1000 : false),
    refetchIntervalInBackground: false,
    retry: 1,
  })

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-bold uppercase tracking-wider text-ink">
          Today&rsquo;s Movers
        </h2>
        {data?.as_of && !data.stale && (
          <span className="text-[11px] text-caption font-mono">
            {/*
              IST timestamp from the server; we render the date part as
              "DD MMM" so it stays under 80px on mobile. No relative
              "X mins ago" formatting because the underlying data is
              once-daily — relative time would imply more freshness
              than the source supports.
            */}
            {new Date(data.as_of).toLocaleDateString("en-IN", {
              day: "2-digit",
              month: "short",
            })}
          </span>
        )}
      </div>

      {isLoading ? (
        <Skeleton />
      ) : data?.stale || !data?.gainers?.length ? (
        // Single shared empty-state spans both columns. Copy is neutral
        // and explanatory, never implies a system error to the user
        // when the real cause is just lagging market data.
        <div
          className="bg-surface border border-border rounded-xl px-4 py-8 text-center"
          data-testid="movers-empty"
        >
          <p className="text-xs text-caption">
            Markets data lagging &mdash; try in a few minutes.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Column
            title="Top Gainers"
            movers={data?.gainers ?? []}
            emptyMessage="No movers right now."
          />
          <Column
            title="Top Losers"
            movers={data?.losers ?? []}
            emptyMessage="No movers right now."
          />
        </div>
      )}
    </section>
  )
}
