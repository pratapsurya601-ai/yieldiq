"use client"
// ─────────────────────────────────────────────────────────────────────
// Temporarily hidden rails (2026-04-22) — restore when data is reliable:
//   1. NearLowsRail ("52-week lows with strong fundamentals")
//      - Endpoint: GET /api/v1/public/near-52w-lows
//      - Backend: backend/routers/public.py:1829
//      - Re-enable: uncomment line 130 below
//   2. LowestPERail ("Lowest P/E with strong fundamentals")
//      - Endpoint: GET /api/v1/public/lowest-pe
//      - Backend: backend/routers/public.py:1930
//      - Re-enable: uncomment line 133 below
// Both rails fetch from live endpoints but frequently render empty/
// near-empty states for first-time visitors, making the page feel
// half-finished. Hide until the underlying data coverage is denser.
//
// Day-68 (2026-05-21): Default content replacing "warming up" placeholder.
// The 2026-05-20 audit found YIQ50 + FII/DII rails sat in "warming up"
// state for 6+ weeks for new visitors — first-impression activation
// killer. Fix: when YIQ50 is empty, render real default content instead
// of an empty card:
//   1. Top 5 MoS gainers — live from /api/v1/screener/run?min_mos=15
//   2. Earnings reporters today — live from /api/v1/public/earnings-calendar
//   3. Methodology spotlight — 7-day rotating tip array (client-side)
// All three sections are FRONTEND-ONLY (no new backend endpoints, no
// CACHE_VERSION bump). See tests/test_day68_discover_default_content.py.
// ─────────────────────────────────────────────────────────────────────
import { useQuery } from "@tanstack/react-query"
import {
  getYieldIQ50,
  getTopPick,
  runScreener,
  BUILD_ID,
} from "@/lib/api"
import axios from "axios"
import { formatMoS } from "@/lib/utils"
import TopPickCard from "@/components/discover/TopPickCard"
import ScreenerPresetsWithCounts from "@/components/discover/ScreenerPresetsWithCounts"
import { SectorLeaders } from "@/components/discover/DiscoverRails"
import MarketPulse from "@/components/discover/MarketPulse"
// import { NearLowsRail, LowestPERail } from "@/components/discover/DiscoverRails"
import { useAuthStore } from "@/store/authStore"
import Link from "next/link"

// Day-68: Methodology spotlight — 7 daily tips that rotate by day-of-year
// so the same visitor sees a different tip each visit within a week. This
// replaces a "warming up" empty card with always-fresh educational content.
const METHODOLOGY_TIPS: { title: string; body: string; href: string }[] = [
  {
    title: "Why we use 5-year median FCF, not TTM",
    body: "Trailing-12-month free cash flow is noisy — one bad working-capital quarter can swing it 40%. The 5-year median smooths cycles without lagging structural changes.",
    href: "/methodology",
  },
  {
    title: "Margin of Safety isn't a price target",
    body: "A +30% MoS means the stock trades 30% below our fair value range — it's a cushion against being wrong, not a 12-month forecast.",
    href: "/methodology",
  },
  {
    title: "WACC is sector-calibrated, not a single number",
    body: "Banks, FMCG, and capital goods don't share a discount rate. YieldIQ uses sector-median equity beta + India 10Y as the risk-free anchor.",
    href: "/methodology",
  },
  {
    title: "Why narrow moats beat no moats",
    body: "A 'Narrow' moat means 5–10 years of pricing power — long enough for the DCF terminal value to matter. 'None' compounds at WACC, which is why we discount it harder.",
    href: "/methodology",
  },
  {
    title: "Reverse-DCF: what the price is telling you",
    body: "Instead of asking 'what's it worth?' we solve for the growth rate implied by today's price. If the market needs 18% FCF growth for 10 years to break even, that's a red flag.",
    href: "/methodology",
  },
  {
    title: "Three scenarios, not one point estimate",
    body: "Bear / Base / Bull are not opinions — they're sensitivity bounds. If MoS stays positive across all three, the trade is robust to being wrong about growth.",
    href: "/methodology",
  },
  {
    title: "Score and MoS measure different things",
    body: "Score (0–100) is business quality. MoS is price discount. A 90/+5% beats a 60/+40% for most long-horizon investors — quality compounds, discount evaporates.",
    href: "/methodology",
  },
]

function pickTodayTip(): { title: string; body: string; href: string } {
  // Day-of-year mod 7 → stable across the day, rotates weekly.
  const now = new Date()
  const start = new Date(now.getFullYear(), 0, 0)
  const diffMs = now.getTime() - start.getTime()
  const dayOfYear = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  return METHODOLOGY_TIPS[dayOfYear % METHODOLOGY_TIPS.length]
}

interface EarningsEventLite {
  ticker: string
  display_ticker: string
  company_name: string
  event_date: string
  event_type: string
}

async function fetchTodayEarnings(): Promise<EarningsEventLite[]> {
  const base = process.env.NEXT_PUBLIC_API_URL || ""
  const res = await axios.get(`${base}/api/v1/public/earnings-calendar`, {
    params: { days: 1, limit: 50 },
  })
  const events: EarningsEventLite[] = res.data?.events ?? []
  // Keep only events on the soonest available date (today, or the next
  // trading day if today is empty — the backend already filters >= today
  // in IST, so events[0].event_date is the earliest).
  if (events.length === 0) return []
  const target = events[0].event_date
  return events.filter(e => e.event_date === target).slice(0, 5)
}

const RANK_COLORS = ["bg-yellow-500", "bg-gray-400", "bg-amber-600"]

// P0-#3 (2026-04-22): display-side MoS clamp lives in @/lib/utils
// (single source of truth). Backend now filters the YIQ 50 list to
// 0 < MoS ≤ 100, but defense-in-depth: any stray value ≥100 or
// ≤-100 (from a stale cache or older entry) renders as ≥100.0% /
// ≤-100.0% — never a raw "+164%".

export default function DiscoverPage() {
  const { tier } = useAuthStore()
  const todayTip = pickTodayTip()

  // Day-68: Top 5 MoS gainers — used both as default-content when YIQ50
  // is cold, and as a permanent secondary rail. min_mos=15 keeps it from
  // surfacing borderline names; client-side sort by MoS desc since the
  // backend default sort is by PE.
  const { data: mosGainers } = useQuery({
    queryKey: ["top-mos-gainers", BUILD_ID],
    queryFn: async () => {
      const d = await runScreener({ min_mos: 15, page_size: 50 })
      const sorted = [...(d?.results ?? [])].sort(
        (a, b) => b.margin_of_safety - a.margin_of_safety,
      )
      return sorted.slice(0, 5)
    },
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 1,
  })

  // Day-68: Earnings reporters today (or next reporting day). Reuses the
  // /public/earnings-calendar endpoint already powering the home strip.
  const { data: earningsToday } = useQuery({
    queryKey: ["discover-earnings-today", BUILD_ID],
    queryFn: fetchTodayEarnings,
    staleTime: 30 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
    retry: 1,
  })
  // P0 (2026-04-30): old staleTime=86_400_000 (24h) cached the empty
  // "warming up" first-hit response for a full day after each deploy.
  // New policy: 5min stale / 30min gc, retry twice, and THROW on empty
  // payloads so React Query never memoizes a cold-start empty state.
  // See lib/api.ts BUILD_ID — queryKey is suffixed so each Vercel
  // deploy invalidates client caches automatically.
  const { data: topPick } = useQuery({
    queryKey: ["top-pick", BUILD_ID],
    queryFn: async () => {
      const d = await getTopPick()
      if (!d || !d.ticker) throw new Error("cold-start: top-pick empty")
      return d
    },
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 2,
  })
  const {
    data: yiq50,
    refetch: refetchYiq50,
    isFetching: yiq50Fetching,
  } = useQuery({
    queryKey: ["yieldiq50", BUILD_ID],
    queryFn: async () => {
      const d = await getYieldIQ50()
      if (!d?.results?.length) throw new Error("cold-start: yieldiq50 empty")
      return d
    },
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 2,
  })

  return (
    // Day-81 (2026-05-22): Discover UX redesign — Option A (hero +
    // above-the-fold restructure). The audit found the highest-intent
    // surface (ScreenerPresetsWithCounts grid — where passive readers
    // become active filterers) sat at the bottom of the page, behind
    // 6 vertically-stacked rails. New reading order:
    //   1. Top Pick (anchor, highest-scored stock)
    //   2. Daily Insight (methodology spotlight — always-fresh content)
    //   3. Screener Presets (the conversion surface, now above the fold)
    //   4. Top-5 MoS gainers + YIQ 50 (deeper exploration rails)
    //   5. Earnings + Sector Leaders (calendar / browse)
    //   6. MarketPulse (macro context — least time-sensitive)
    // Frontend-only reorder. No new endpoints. No CACHE_VERSION bump.
    <div className="max-w-2xl md:max-w-4xl lg:max-w-5xl mx-auto px-4 py-6 space-y-8 pb-20">
      {/* J-copy-2 (audit item 16): page title + contextual subtitle.
          Cold-read audit found the page opened with "Highest YieldIQ
          score today" — descriptive of a card, not the page. A
          first-time visitor needed a one-line answer to "what is this
          screen for?". */}
      <header className="space-y-1">
        <h1 className="font-display text-2xl sm:text-3xl font-black text-ink">
          Discover
        </h1>
        <p className="text-sm text-caption">
          What looks cheap today &mdash; ranked by margin of safety, not opinion.
        </p>
      </header>

      {/* Day-81 hero (1/6): Highest-scored stock today (anchor). */}
      {topPick && (
        <section>
          <p className="text-[10px] font-bold text-caption uppercase tracking-widest mb-2">Highest YieldIQ score today</p>
          <TopPickCard
            ticker={topPick.ticker}
            companyName={topPick.company_name || topPick.ticker}
            score={topPick.score}
            mos={topPick.mos}
            moat={topPick.moat || "Narrow"}
            summary={topPick.summary || ""}
          />
          <p className="text-[10px] text-caption mt-1">Updated daily. Based on YieldIQ 50 model. Not investment advice.</p>
        </section>
      )}

      {/* Day-81 (2/6): Daily Insight — moved up from bottom-third so
          cold-start visitors get an educational anchor immediately under
          the Top Pick. Rotates daily (day-of-year mod 7). */}
      <section data-day81-slot="daily-insight">
        <p className="text-[10px] font-bold text-caption uppercase tracking-widest mb-3">
          Daily Insight
        </p>
        <Link
          href={todayTip.href}
          className="block bg-bg dark:bg-surface border border-border rounded-xl p-4 hover:border-brand transition"
        >
          <p className="text-sm font-semibold text-ink mb-1">{todayTip.title}</p>
          <p className="text-xs text-caption leading-relaxed">{todayTip.body}</p>
          <p className="text-[11px] font-semibold text-brand mt-2">
            Read the full methodology &rarr;
          </p>
        </Link>
      </section>

      {/* Day-81 (3/6): Screener Presets — promoted from page bottom to
          above-the-fold. This is the highest-intent conversion surface
          (passive reader -> active filterer). Putting it third in
          reading order (after the anchor + educational tile) makes it
          discoverable without scrolling on 1080p+ screens. */}
      <section data-day81-slot="screener-presets">
        <div className="flex items-center justify-between mb-3">
          <p className="text-[10px] font-bold text-caption uppercase tracking-widest">
            Explore the Screener
          </p>
          <Link
            href="/screener"
            className="text-[11px] font-semibold text-brand hover:underline"
          >
            All filters &rarr;
          </Link>
        </div>
        <ScreenerPresetsWithCounts />
      </section>

      {/* YieldIQ 50 */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <p className="text-[10px] font-bold text-caption uppercase tracking-widest">YieldIQ 50</p>
          <p className="text-[10px] text-caption">Updated daily</p>
        </div>
        {yiq50 && yiq50.results.length >= 3 ? (
          <>
            <div className="grid grid-cols-3 gap-2 mb-3">
              {yiq50.results.slice(0, 3).map((s, i) => (
                <Link key={s.ticker} href={`/analysis/${s.ticker}`}
                  className="relative bg-bg dark:bg-surface rounded-xl border border-gray-100 p-4 min-h-[96px] text-center hover:border-blue-300 hover:shadow-sm active:scale-[0.98] transition">
                  {/* Rank badge */}
                  <span className={`absolute -top-2 -left-2 w-6 h-6 rounded-full ${RANK_COLORS[i]} text-white text-[10px] font-bold flex items-center justify-center shadow-sm`}>
                    #{i + 1}
                  </span>
                  <p className="text-sm font-bold text-ink truncate">{s.ticker.replace(".NS", "")}</p>
                  <div className="mt-1 flex items-baseline justify-center gap-1.5">
                    <span className="text-base font-bold text-blue-700 font-mono">{formatMoS(s.margin_of_safety)}</span>
                    <span className="text-xs text-gray-300">·</span>
                    <span className="text-sm font-mono text-ink">{s.score}<span className="text-[10px] text-caption">/100</span></span>
                  </div>
                  {Math.abs(s.margin_of_safety) >= 100 && (
                    <p className="mt-1 text-[10px] text-caption leading-tight">uncertain</p>
                  )}
                </Link>
              ))}
            </div>
            {tier !== "free" && yiq50.results.length > 3 && (
              <div className="bg-bg dark:bg-surface rounded-xl border border-gray-100 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-[10px] text-caption uppercase">
                      <th className="text-left px-3 py-2">#</th>
                      <th className="text-left px-3 py-2">Ticker</th>
                      <th className="text-right px-3 py-2">Score</th>
                      <th className="text-right px-3 py-2">MoS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {yiq50.results.map((s, i) => (
                      <tr key={s.ticker} className={`border-b border-gray-50 hover:bg-blue-50 transition-colors ${i % 2 === 1 ? "bg-gray-50/50" : ""}`}>
                        <td className="px-3 py-2 text-caption">{i + 1}</td>
                        <td className="px-3 py-2 font-medium">
                          <Link href={`/analysis/${s.ticker}`} className="text-blue-700 hover:underline">
                            {s.ticker.replace(".NS", "")}
                          </Link>
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{s.score}</td>
                        <td className="px-3 py-2 text-right font-mono">{formatMoS(s.margin_of_safety)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {tier === "free" && (
              <div className="bg-bg dark:bg-surface rounded-xl border border-gray-100 p-4 text-center">
                <p className="text-lg font-bold text-caption">+{Math.max(0, yiq50.total - 3)} more</p>
                <p className="text-xs text-caption mb-2">Starter plan</p>
                <Link href="/account" className="text-xs text-blue-600 font-medium hover:underline">Unlock all 50</Link>
              </div>
            )}
          </>
        ) : (
          // Day-68 (2026-05-21): replaced the YIQ50 "warming up" empty
          // card with live default content (Top 5 MoS gainers from the
          // screener) so new visitors never see a placeholder-only page.
          // Falls back to a thin Refresh affordance if even the screener
          // is empty (extremely unlikely — analysis_cache is populated
          // for ~1,700 tickers).
          <div className="bg-bg dark:bg-surface border border-border rounded-xl p-4">
            <p className="text-xs font-semibold text-ink mb-1">
              Top 5 MoS gainers
            </p>
            <p className="text-[11px] text-caption mb-3">
              Largest discounts to fair value right now. Refreshes with the daily run.
            </p>
            {mosGainers && mosGainers.length > 0 ? (
              <ul className="divide-y divide-border">
                {mosGainers.map((s, i) => (
                  <li key={s.ticker}>
                    <Link
                      href={`/analysis/${s.ticker}`}
                      className="flex items-center justify-between py-2 hover:bg-bg/50 rounded px-1 -mx-1 transition"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-mono text-caption w-4">
                          {i + 1}
                        </span>
                        <span className="text-sm font-semibold text-ink">
                          {s.ticker.replace(".NS", "")}
                        </span>
                      </div>
                      <div className="flex items-baseline gap-3 font-mono">
                        <span className="text-sm text-brand">
                          {formatMoS(s.margin_of_safety)}
                        </span>
                        <span className="text-xs text-caption">
                          {s.score}
                          <span className="text-[10px] text-caption/70">/100</span>
                        </span>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="flex items-center justify-between">
                <p className="text-xs text-caption">
                  Daily shortlist refreshes overnight.
                </p>
                <button
                  type="button"
                  onClick={() => refetchYiq50()}
                  disabled={yiq50Fetching}
                  className="text-xs font-semibold text-brand hover:underline disabled:opacity-50"
                >
                  {yiq50Fetching ? "Refreshing…" : "Refresh"}
                </button>
              </div>
            )}
            <div className="mt-3 pt-3 border-t border-border flex items-center justify-between">
              <Link
                href="/discover/screener"
                className="text-xs font-semibold text-brand hover:underline"
              >
                Browse full Screener &rarr;
              </Link>
              <button
                type="button"
                onClick={() => refetchYiq50()}
                disabled={yiq50Fetching}
                className="text-[11px] text-caption hover:text-ink disabled:opacity-50"
              >
                {yiq50Fetching ? "Refreshing YIQ 50…" : "Retry YIQ 50"}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Day-68: Earnings reporters today — reuses /public/earnings-calendar
          (the same endpoint that powers the home "Earnings this week" strip).
          Renders the soonest reporting day; max 5 tickers. */}
      <section>
        <p className="text-[10px] font-bold text-caption uppercase tracking-widest mb-3">
          Earnings reporters today
        </p>
        {earningsToday && earningsToday.length > 0 ? (
          <div className="bg-bg dark:bg-surface border border-border rounded-xl overflow-hidden">
            <ul className="divide-y divide-border">
              {earningsToday.map(ev => (
                <li key={ev.ticker}>
                  <Link
                    href={`/analysis/${ev.ticker}`}
                    className="flex items-center justify-between px-3 py-2.5 hover:bg-bg/50 transition"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-ink truncate">
                        {ev.display_ticker}
                      </p>
                      <p className="text-[11px] text-caption truncate">
                        {ev.company_name}
                      </p>
                    </div>
                    <span className="text-[10px] font-mono text-caption uppercase tracking-wide flex-shrink-0 ml-3">
                      {ev.event_type}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            <div className="px-3 py-2 border-t border-border">
              <Link
                href="/earnings-calendar"
                className="text-xs font-semibold text-brand hover:underline"
              >
                Full earnings calendar &rarr;
              </Link>
            </div>
          </div>
        ) : (
          <div className="bg-bg dark:bg-surface border border-border rounded-xl p-4">
            <p className="text-xs text-caption">
              No earnings filings on the immediate horizon.{" "}
              <Link href="/earnings-calendar" className="text-brand font-semibold hover:underline">
                See the full calendar &rarr;
              </Link>
            </p>
          </div>
        )}
      </section>

      {/* Day-81 (5/6): Sector leaders — top ticker per sector from YIQ 50. */}
      {yiq50 && yiq50.results.length > 0 && (
        <SectorLeaders stocks={yiq50.results} />
      )}

      {/* UNCOMMENT WHEN /api/v1/public/near-52w-lows RETURNS DENSE DATA */}
      {/* <NearLowsRail /> */}

      {/* UNCOMMENT WHEN /api/v1/public/lowest-pe RETURNS DENSE DATA */}
      {/* {yiq50 && <LowestPERail stocks={yiq50.results} />} */}

      {/* Day-81 (6/6): Market Pulse — FII vs DII daily flow. Demoted to
          bottom because it's macro context (least time-sensitive for the
          per-stock workflow that the Screener Presets surface drives). */}
      <section data-day81-slot="market-pulse">
        <MarketPulse days={30} />
      </section>
    </div>
  )
}
