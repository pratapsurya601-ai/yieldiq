"use client"

/**
 * PortfolioHero — top-of-page hero for `/portfolio` (and `/watchlist`,
 * which redirects to `/portfolio?tab=watchlist`).
 *
 * Audit 2026-06-10 (P2): previously the portfolio page rendered an
 * empty `.skeleton rounded-2xl` gradient block above the tabs when
 * `PortfolioSumOfPartsCard` was loading or returning null for users
 * with zero holdings. From the watchlist tab — where the user has
 * never had a reason to import holdings — that empty gradient block
 * read as a placeholder that never got filled. This hero replaces
 * that surface with content that is useful in BOTH states:
 *
 *   - Empty (no holdings): a SEBI-clean value prop describing what
 *     the portfolio page does, plus CTAs to import or explore.
 *   - Populated: a gradient summary card with total value, P&L
 *     abs/%, invested, winners/losers, and a top-mover chip.
 *
 * Because the hero now lives ABOVE the tabs it stays visible whether
 * the user is on Holdings, Watchlist, Alerts, or Updates — so the
 * watchlist-tab landing experience is no longer dominated by an
 * empty rectangle.
 *
 * Loading state is rendered with `aria-busy="true"` so screen readers
 * announce the wait without spamming the rest of the page.
 */
import Link from "next/link"
import type { LiveHolding, HoldingsLiveResponse } from "@/lib/api"
import { NumberFlip, RevealStagger } from "@/components/motion"

type Summary = HoldingsLiveResponse["summary"]

interface PortfolioHeroProps {
  /** From `useQuery(["holdings-live"])` — undefined while loading. */
  summary: Summary | undefined
  /** From `useQuery(["holdings-live"])` — empty array while loading or when none exist. */
  holdings: LiveHolding[]
  /** True while the holdings-live query is in flight. */
  isLoading: boolean
}

function fmtRsCompact(n: number): string {
  const abs = Math.abs(n)
  const sign = n < 0 ? "-" : ""
  if (abs >= 10_000_000) return `${sign}₹${(abs / 10_000_000).toFixed(2)}Cr`
  if (abs >= 100_000) return `${sign}₹${(abs / 100_000).toFixed(2)}L`
  if (abs >= 1_000) return `${sign}₹${(abs / 1_000).toFixed(1)}K`
  return `${sign}₹${abs.toFixed(0)}`
}

function displayTicker(raw: string): string {
  // Same trailing `-X` fallback marker strip used elsewhere on the page.
  return raw.replace(/[-_][Xx]$/, "").replace(".NS", "")
}

export default function PortfolioHero({ summary, holdings, isLoading }: PortfolioHeroProps) {
  // Loading: render a clean skeleton sized to match the gradient height
  // so the layout below doesn't pop when data resolves. Distinct from
  // the prior "empty gradient" placeholder — this one explicitly
  // announces itself as a loading region.
  if (isLoading) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading portfolio summary"
        data-testid="portfolio-hero-loading"
        className="skeleton rounded-2xl h-[148px]"
      />
    )
  }

  const hasHoldings = !!summary && summary.count > 0 && holdings.length > 0

  // Empty state — value prop + CTAs. Stays SEBI-clean: no advisory
  // vocabulary and no opinion verbs. Frames the page as a tracking
  // + alerting tool rather than advice.
  if (!hasHoldings) {
    return (
      <section
        aria-label="Portfolio overview (empty)"
        data-testid="portfolio-hero-empty"
        className="bg-gradient-to-br from-blue-600 to-cyan-500 rounded-2xl p-5 sm:p-6 text-white"
      >
        <p className="text-xs font-bold uppercase tracking-wider opacity-80 mb-1">
          Your portfolio
        </p>
        <h2 className="text-xl sm:text-2xl font-black mb-2 leading-tight">
          Track your stocks. See where they stand.
        </h2>
        <p className="text-sm opacity-90 mb-4 max-w-prose">
          Import your holdings to see fair-value gaps, aggregated quality
          scores, and alerts when valuation bands shift. Watchlist any
          ticker to follow it without committing capital.
        </p>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/portfolio/import"
            data-testid="portfolio-hero-import"
            className="inline-flex items-center justify-center min-h-[40px] bg-white text-blue-700 text-sm font-semibold px-4 py-2 rounded-lg hover:bg-blue-50 active:scale-[0.98] transition"
          >
            Import portfolio
          </Link>
          <Link
            href="/search"
            data-testid="portfolio-hero-search"
            className="inline-flex items-center justify-center min-h-[40px] bg-white/15 ring-1 ring-white/30 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-white/25 active:scale-[0.98] transition"
          >
            Explore stocks
          </Link>
        </div>
      </section>
    )
  }

  // Populated state — summary KPI card.
  // Winners/losers are recomputed client-side with ties going to
  // winners (>= 0) so the two buckets always sum to count — same
  // convention as the old inline summary card on the holdings tab.
  const winners = holdings.filter((h) => h.pnl_pct >= 0).length
  const losers = holdings.filter((h) => h.pnl_pct < 0).length

  // Top mover by absolute P&L percent (positive OR negative). Lets the
  // hero call attention to the biggest single-position swing without
  // ranking it as good/bad.
  const ranked = [...holdings].sort(
    (a, b) => Math.abs(b.pnl_pct) - Math.abs(a.pnl_pct),
  )
  const topMover = ranked[0]

  return (
    <section
      aria-label="Portfolio overview"
      data-testid="portfolio-hero-summary"
      className="bg-gradient-to-br from-blue-600 to-cyan-500 rounded-2xl p-4 sm:p-5 text-white"
    >
      <p className="text-xs font-bold uppercase tracking-wider opacity-80 mb-1">
        Total Value
      </p>
      {/* Motion: NumberFlip on Total Value so a holding-add or price
          tick is acknowledged with a flip rather than silently swapping.
          Custom `format` keeps the compact-rupees rendering (Cr/L/K). */}
      <p className="text-3xl font-black mb-1" data-testid="portfolio-hero-total-value">
        <NumberFlip
          value={summary!.total_current_value}
          format={fmtRsCompact}
        />
      </p>
      <div className="flex items-baseline gap-2">
        <p
          className={`text-sm font-bold ${summary!.total_pnl_abs >= 0 ? "text-green-200" : "text-red-200"}`}
          data-testid="portfolio-hero-pnl-abs"
        >
          {summary!.total_pnl_abs >= 0 ? "+" : ""}
          {fmtRsCompact(summary!.total_pnl_abs)}
        </p>
        <p
          className={`text-sm font-semibold ${summary!.total_pnl_abs >= 0 ? "text-green-200" : "text-red-200"}`}
        >
          ({summary!.total_pnl_pct >= 0 ? "+" : ""}
          {summary!.total_pnl_pct.toFixed(2)}%)
        </p>
      </div>

      {/* Motion: RevealStagger entrance for the KPI tiles + NumberFlip
          on the numeric values so the Invested/Holdings/Winners-Losers
          counters acknowledge any holdings-feed refresh. */}
      <RevealStagger
        staggerMs={80}
        className="grid grid-cols-1 sm:grid-cols-4 gap-3 mt-4 pt-4 border-t border-white/20 text-xs"
      >
        <div>
          <p className="opacity-80">Invested</p>
          <p className="font-bold text-sm">
            <NumberFlip
              value={summary!.total_invested}
              format={fmtRsCompact}
            />
          </p>
        </div>
        <div>
          <p className="opacity-80">Holdings</p>
          <p className="font-bold text-sm" data-testid="portfolio-hero-count">
            <NumberFlip value={summary!.count} />
          </p>
        </div>
        <div>
          <p className="opacity-80">Winners / Losers</p>
          {/* Winners/Losers kept as a single text node (no NumberFlip
              wrapper) so `getByText(/2 \/ 1/)` continues to match the
              combined "n / m" string in PortfolioHero.test.tsx. */}
          <p className="font-bold text-sm">
            {winners} / {losers}
          </p>
        </div>
        {topMover && (
          <div>
            <p className="opacity-80">Top mover</p>
            <p
              className="font-bold text-sm truncate"
              data-testid="portfolio-hero-top-mover"
              title={`${displayTicker(topMover.display_ticker || topMover.ticker)} ${topMover.pnl_pct >= 0 ? "+" : ""}${topMover.pnl_pct.toFixed(2)}%`}
            >
              {displayTicker(topMover.display_ticker || topMover.ticker)}{" "}
              <span
                className={topMover.pnl_pct >= 0 ? "text-green-200" : "text-red-200"}
              >
                {topMover.pnl_pct >= 0 ? "+" : ""}
                {topMover.pnl_pct.toFixed(1)}%
              </span>
            </p>
          </div>
        )}
      </RevealStagger>
    </section>
  )
}
