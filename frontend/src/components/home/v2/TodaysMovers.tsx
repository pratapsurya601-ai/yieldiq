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
//
// Empty-state policy (2026-06-09): NEVER render a wasted whitespace
// block. The previous "Markets data lagging — try in a few minutes"
// empty card occupied the full panel height with zero information.
// The new fallback chain (Tier-1 → Tier-2 → Tier-3) guarantees the
// component always renders meaningful content within its allocated
// vertical space:
//
//   Tier-1 — cached LAST KNOWN movers from localStorage
//            (`lastSeenMovers` key, written on every successful fetch).
//            Renders with "Showing last refresh • {timestamp}" tag.
//   Tier-2 — top-3 of each quant-pick preset, as a static
//            "Worth a look" preview. SEBI-neutral phrasing.
//            Re-uses the React-Query cache already populated by
//            QuantPicksGrid (same panel on /home), so no extra
//            round-trip when both are mounted together.
//   Tier-3 — one-line "Markets data lagging — refreshing in a moment"
//            + an actionable "Retry →" button. Compact, single row.
//
// A small Refresh icon in the top-right of the panel lets users
// manually re-fetch instead of waiting for the auto-refresh tick.

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw } from "lucide-react"

import TickerAvatar from "@/components/common/TickerAvatar"
import { Sparkline } from "@/components/common/Sparkline"
import { getSparklines, getTodayMovers } from "@/lib/api"
import { formatPct, trueMosFromUpside } from "@/lib/utils"
import type { TodayMover, TodayMoversResponse, ScreenerResponse } from "@/types/api"
import {
  QUANT_PRESETS,
  quantPresetQueryKey,
  type QuantPresetConfig,
} from "./quantPicksPresets"
import HoverCard from "@/components/motion/HoverCard"
import RevealStagger from "@/components/motion/RevealStagger"

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

// ─── localStorage cache for the last successful fetch ────────────────
// Survives reload / cross-session and is the Tier-1 fallback when the
// live response comes back stale or empty. Kept in its own helper so
// the test can hermetically mock window.localStorage.
const LAST_MOVERS_KEY = "yieldiq:lastSeenMovers"

interface CachedMovers {
  cached_at: string                  // ISO timestamp written by client
  payload: TodayMoversResponse       // shape matches the live API
}

function readCachedMovers(): CachedMovers | null {
  if (typeof window === "undefined") return null
  try {
    const raw = window.localStorage.getItem(LAST_MOVERS_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as CachedMovers
    // Defensive: ignore caches older than 7 days; better to fall
    // through to the quant-picks preview than to surface a week-old
    // gainers list as if it were today's.
    const ageMs = Date.now() - new Date(parsed.cached_at).getTime()
    if (!Number.isFinite(ageMs) || ageMs > 7 * 24 * 60 * 60 * 1000) return null
    if (!parsed.payload?.gainers?.length) return null
    return parsed
  } catch {
    return null
  }
}

function writeCachedMovers(payload: TodayMoversResponse): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(
      LAST_MOVERS_KEY,
      JSON.stringify({ cached_at: new Date().toISOString(), payload }),
    )
  } catch {
    // Quota exceeded / disabled storage — best-effort cache, swallow.
  }
}

function MoverRow({
  mover,
  sparkline,
}: {
  mover: TodayMover
  /** 7-day close series; omitted when the batch fetch had no rows. */
  sparkline?: number[]
}) {
  const up = mover.change_pct >= 0
  const color = up
    ? "text-green-600 dark:text-green-400"
    : "text-red-600 dark:text-red-400"
  // Sparkline color tracks today's % change (the rail's headline
  // signal), not the 7d series direction — keeps the visual story
  // coherent: green row = green sparkline. Falls back to the
  // component's auto-derive when sparkline is empty.
  const sparkColor: "green" | "red" = up ? "green" : "red"
  const hasSpark = Array.isArray(sparkline) && sparkline.length >= 2
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
      {hasSpark && (
        <Sparkline
          values={sparkline as number[]}
          width={48}
          height={16}
          color={sparkColor}
        />
      )}
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
  sparklines,
}: {
  title: string
  movers: TodayMover[]
  emptyMessage: string
  sparklines?: Record<string, number[]>
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
        <RevealStagger staggerMs={40}>
          {movers.map((m) => (
            <MoverRow
              key={m.ticker}
              mover={m}
              sparkline={sparklines?.[m.ticker]}
            />
          ))}
        </RevealStagger>
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

// Preview presets — the first 3 quant-pick tiles (`quality_discount` is
// dropped because it overlaps heavily with `buffett` and we want
// distinct content per fallback column). Hoisted to module scope so
// the array identity is stable across re-renders.
const PREVIEW_PRESETS: QuantPresetConfig[] = QUANT_PRESETS.filter(
  p => p.key !== "quality_discount",
)

// ─── Worth-a-look preview (Tier-2 fallback) ──────────────────────────
// Renders the top-3 of each preset as a single 3-column grid. Each
// preset becomes a mini-column with up to 3 ticker rows. Sourced from
// the React-Query cache populated by QuantPicksGrid (identical
// queryKey) — when both components are mounted on /home this is a
// pure cache read, no extra network. If QuantPicksGrid hasn't mounted
// yet (e.g. it's dynamic()-imported below the fold and the user is
// still above-the-fold), `useQueries` will issue the fetch itself,
// staleTime keeps the result hot for both consumers.
function WorthALookPreview({
  queries,
}: {
  queries: ReadonlyArray<{ data?: ScreenerResponse }>
}) {
  return (
    <div
      className="grid grid-cols-1 md:grid-cols-3 gap-4"
      data-testid="movers-worth-a-look"
    >
      {PREVIEW_PRESETS.map((preset, i) => {
        const data: ScreenerResponse | undefined = queries[i]?.data
        const top = (data?.results ?? []).slice(0, 3)
        return (
          <HoverCard
            key={preset.key}
            className="bg-surface border border-border rounded-xl overflow-hidden"
          >
            <div className="px-3 py-2 border-b border-border bg-bg/30 flex items-center justify-between gap-2">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-caption truncate">
                {preset.title}
              </h3>
              <Link
                href={preset.href}
                className="text-[10px] font-semibold text-brand hover:underline flex-shrink-0"
              >
                See all →
              </Link>
            </div>
            {top.length === 0 ? (
              <div className="px-3 py-6 text-xs text-caption text-center">
                Refreshing…
              </div>
            ) : (
              <div>
                {top.map((s) => {
                  const display = s.ticker.replace(/\.(NS|BO)$/, "")
                  const v = (s.verdict || "").toLowerCase()
                  const underReview =
                    v === "data_limited" ||
                    v === "under_review" ||
                    v === "unavailable"
                  return (
                    <Link
                      key={s.ticker}
                      href={`/analysis/${display}`}
                      className="flex items-center gap-2.5 px-3 py-2 hover:bg-bg/40 transition border-b border-border last:border-b-0"
                      data-testid="movers-worth-a-look-row"
                    >
                      <TickerAvatar ticker={s.ticker} size="sm" />
                      <span className="font-mono font-semibold text-sm text-ink truncate min-w-0 flex-shrink">
                        {display}
                      </span>
                      {underReview ? (
                        <span className="ml-auto text-[11px] text-caption italic flex-shrink-0">
                          Under Review
                        </span>
                      ) : (
                        <span className="ml-auto flex flex-col items-end flex-shrink-0">
                          <span className="font-mono text-sm tabular-nums text-green-600 dark:text-green-400">
                            MoS {(() => {
                              const trueMos = trueMosFromUpside(s.margin_of_safety)
                              return trueMos != null
                                ? `${trueMos >= 0 ? "+" : ""}${trueMos.toFixed(0)}%`
                                : "—"
                            })()}
                          </span>
                          <span className="text-[10px] text-caption tabular-nums">
                            Implied upside {s.margin_of_safety >= 0 ? "+" : ""}{s.margin_of_safety.toFixed(0)}%
                          </span>
                        </span>
                      )}
                    </Link>
                  )
                })}
              </div>
            )}
          </HoverCard>
        )
      })}
    </div>
  )
}

export default function TodaysMovers() {
  const queryClient = useQueryClient()
  // 2026-06-11 (P0 fix — Markets data lagging error)
  // Previous retry: 1 fast retry, then surface the Tier-3 "lagging" copy
  // and stall until the user clicked Retry or the next 60s tick. On a
  // transient backend hiccup (cold-start, redeploy mid-fetch, Aiven
  // rate-limit blip) the user sat on the error banner for 30-60s with
  // no auto-recovery. Bumped to 3 retries with exponential backoff
  // (1s → 2s → 4s, capped at 8s) so most blips heal silently before
  // the fallback chain runs at all.
  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ["today-movers", "nifty500", 5],
    queryFn: () => getTodayMovers("nifty500", 5),
    staleTime: 60 * 1000,
    refetchInterval: () => (isMarketHoursIST() ? 60 * 1000 : false),
    refetchIntervalInBackground: false,
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * Math.pow(2, attempt), 8000),
  })

  // Persist every fresh, non-stale, non-empty payload so the Tier-1
  // fallback has something real to render when the next fetch goes
  // sideways. Effect runs on every data change; quick JSON.stringify
  // even on the largest payloads.
  useEffect(() => {
    if (data && !data.stale && (data.gainers?.length ?? 0) > 0) {
      writeCachedMovers(data)
    }
  }, [data])

  // Tier-1 cached snapshot — read once on the client AFTER hydration.
  // We can't read localStorage during SSR, and we can't read it during
  // the first render either (would cause a hydration mismatch when the
  // SSR HTML has no cached payload but the client does). The
  // useEffect-on-mount pattern is the documented React 19 fix: render
  // empty on the server, fill in on the client.
  const [cached, setCached] = useState<CachedMovers | null>(null)
  useEffect(() => {
    setCached(readCachedMovers())
  }, [])

  // Classification: which render path are we on?
  //   - "loading"   → no data yet, no cache, no preview
  //   - "live"      → fresh data is good
  //   - "cached"    → live is bad, cache exists → render cache
  //   - "preview"   → live + cache both bad → try quant-picks preview
  //   - "retry"     → nothing at all renders → minimal retry line
  // The preview classification is "best effort" — the preview itself
  // returns null when it has nothing to show, and the final retry tier
  // takes over.
  type Mode = "loading" | "live" | "cached" | "preview" | "retry"
  const mode: Mode = useMemo(() => {
    if (isLoading) return "loading"
    const liveOk = !!data && !data.stale && (data.gainers?.length ?? 0) > 0
    if (liveOk) return "live"
    if (cached) return "cached"
    return "preview"
    // The "preview" → "retry" transition is decided inside the render
    // path because we can only know if the preview has data after
    // querying the cache.
  }, [isLoading, data, cached])

  // Header text changes when we're showing the Worth-a-look fallback
  // — the user shouldn't see "Today's Movers" above a panel that
  // contains no actual movers. For live + cached, the original label
  // stays.
  const heading =
    mode === "preview" ? "Worth a look" : "Today’s Movers"

  // Manual retry — refetches the movers query and invalidates the
  // preset queries so the Worth-a-look fallback can refresh too if it
  // ends up being what we render.
  const handleRetry = () => {
    refetch()
    queryClient.invalidateQueries({ queryKey: ["quant-tile"] })
  }

  // Right-aligned freshness annotation. For live we show today's
  // date; for cached we show "Showing last refresh • DD MMM".
  let freshnessTag: React.ReactNode = null
  if (mode === "live" && data?.as_of) {
    freshnessTag = (
      <span className="text-[11px] text-caption font-mono">
        {new Date(data.as_of).toLocaleDateString("en-IN", {
          day: "2-digit",
          month: "short",
        })}
      </span>
    )
  } else if (mode === "cached" && cached) {
    freshnessTag = (
      <span
        className="text-[11px] text-caption font-mono"
        data-testid="movers-cached-tag"
      >
        Showing last refresh ·{" "}
        {new Date(cached.cached_at).toLocaleDateString("en-IN", {
          day: "2-digit",
          month: "short",
        })}
      </span>
    )
  }

  // Sparkline batch — ONLY when the live movers data is populated.
  // Skipped during cached/preview/retry fallback paths since those
  // rows render without sparklines (cleaner empty-state UX).
  const moverTickers = mode === "live" && data
    ? [...(data.gainers ?? []), ...(data.losers ?? [])].map(m => m.ticker)
    : []
  const { data: sparkResp } = useQuery({
    queryKey: ["movers-sparklines", [...moverTickers].sort().join(",")],
    queryFn: () => getSparklines(moverTickers, "7d"),
    enabled: moverTickers.length > 0,
    staleTime: 60 * 1000,
    refetchInterval: () => (isMarketHoursIST() ? 5 * 60 * 1000 : false),
    refetchIntervalInBackground: false,
    retry: 1,
  })
  const sparkSeries = sparkResp?.series ?? {}

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-bold uppercase tracking-wider text-ink">
          {heading}
        </h2>
        <div className="flex items-center gap-3">
          {freshnessTag}
          {/* Manual refresh — always visible so users have an
              alternative to waiting for the 60s auto-refresh. Disabled
              during in-flight fetches to dampen retry storms. */}
          <button
            type="button"
            onClick={handleRetry}
            disabled={isFetching}
            aria-label="Refresh today's movers"
            title="Refresh"
            data-testid="movers-refresh"
            className="text-caption hover:text-brand disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`}
            />
          </button>
        </div>
      </div>

      {mode === "loading" ? (
        <Skeleton />
      ) : mode === "live" ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Column
            title="Top Gainers"
            movers={data?.gainers ?? []}
            emptyMessage="No movers right now."
            sparklines={sparkSeries}
          />
          <Column
            title="Top Losers"
            movers={data?.losers ?? []}
            emptyMessage="No movers right now."
            sparklines={sparkSeries}
          />
        </div>
      ) : mode === "cached" && cached ? (
        // Tier-1: render the last known good payload from localStorage.
        // Visually identical to "live" — only the freshnessTag differs.
        <div
          className="grid grid-cols-1 md:grid-cols-2 gap-4"
          data-testid="movers-cached"
        >
          <Column
            title="Top Gainers"
            movers={cached.payload.gainers ?? []}
            emptyMessage="No movers right now."
          />
          <Column
            title="Top Losers"
            movers={cached.payload.losers ?? []}
            emptyMessage="No movers right now."
          />
        </div>
      ) : (
        // Tier-2 or Tier-3. WorthALookPreview returns null when it has
        // nothing useful in cache; the LastResort fallback then takes
        // over. This way the JSX stays declarative — no flicker, no
        // additional state.
        <PreviewOrRetry onRetry={handleRetry} isFetching={isFetching} />
      )}
    </section>
  )
}

// ─── Tier-2 / Tier-3 wrapper ─────────────────────────────────────────
// Splits the preview render so the parent stays simple. Single
// `useQueries` call drives both the preview-or-not decision AND the
// rendered grid — no duplicate query hooks across components.
function PreviewOrRetry({
  onRetry,
  isFetching,
}: {
  onRetry: () => void
  isFetching: boolean
}) {
  const queries = useQueries({
    queries: PREVIEW_PRESETS.map((p: QuantPresetConfig) => ({
      queryKey: quantPresetQueryKey(p.key),
      queryFn: p.fetcher,
      staleTime: 10 * 60 * 1000,
      retry: 1,
    })),
  })
  const anyLoaded = queries.some(q => (q.data?.results?.length ?? 0) > 0)
  const stillFetchingPreviews = queries.some(q => q.isLoading)

  if (anyLoaded) {
    return <WorthALookPreview queries={queries} />
  }
  if (stillFetchingPreviews) {
    // Don't immediately show "Markets data lagging" — give the
    // preview queries a moment to come back. The skeleton fits this
    // gap honestly.
    return <Skeleton />
  }
  // Tier-3: actionable single-line retry, compact (no full-panel
  // wasted whitespace). Uses the existing "lagging" copy as required
  // by the SEBI vocabulary review but pairs it with TWO actions:
  // (a) Retry → in-place refetch, (b) Open Markets hub → /markets,
  // which has its own indices + sector view and is the right escape
  // hatch when the movers endpoint stays down. 2026-06-11: added the
  // hub link so the user is never strung along by Retry alone on a
  // sustained outage.
  return (
    <div
      className="bg-surface border border-border rounded-xl px-4 py-3 flex items-center justify-between gap-3"
      data-testid="movers-empty"
    >
      <p className="text-xs text-caption">
        Markets data lagging &mdash; refreshing in a moment.
      </p>
      <div className="flex items-center gap-3 flex-shrink-0">
        <button
          type="button"
          onClick={onRetry}
          disabled={isFetching}
          className="text-xs font-semibold text-brand hover:underline disabled:opacity-40 disabled:cursor-not-allowed"
          data-testid="movers-retry"
        >
          Retry →
        </button>
        <Link
          href="/markets"
          className="text-xs font-semibold text-brand hover:underline"
          data-testid="movers-markets-hub"
        >
          Open Markets hub →
        </Link>
      </div>
    </div>
  )
}
