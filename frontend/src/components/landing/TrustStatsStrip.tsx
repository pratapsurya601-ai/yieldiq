"use client"
/**
 * TrustStatsStrip — 4-tile horizontal coverage strip on the
 * logged-out landing page. Sits below the hero (search +
 * Recently Viewed chips) and above the pricing teaser.
 *
 * Each tile renders an icon, a tabular-number value, and a small
 * caption. Hover lifts the card and clicking navigates to the
 * relevant deeper page (Stocks → /discover, Logo → /methodology,
 * Updates → /changelog, Sectors → /sector).
 *
 * Loading state shows "—" with a skeleton pulse — NEVER "0",
 * which would look broken on a first-impression surface. If the
 * API omits a particular field (back-end couldn't resolve it),
 * we render the same "—" placeholder for that tile.
 *
 * SEBI: every tile is descriptive coverage data (counts, %,
 * "Daily" cadence label). NO field implies pick quality or
 * trade outcome. The disclaimer microtype below the strip
 * names the data sources and points to /methodology.
 */
import { useEffect, useState } from "react"
import Link from "next/link"
import { BarChart3, Image as ImageIcon, RefreshCw, Layers } from "lucide-react"
import { getCoverageStats, type CoverageStatsResponse } from "@/lib/api"

type TileKey = "stocks" | "logo" | "updates" | "sectors"

type Tile = {
  key: TileKey
  icon: React.ComponentType<{ className?: string }>
  /** Display value — string so we can format the number our way
   *  (Indian commas, % suffix) and the "Daily" literal. */
  value: string | null
  caption: string
  href: string | null
  /** Lets per-tile test selectors pick exactly one node. */
  testId: string
}

function formatIndianInt(n: number): string {
  // toLocaleString("en-IN") gives 5,247 / 12,48,300 — the
  // canonical Indian comma grouping retail visitors expect.
  // formatNumberWithSuffix from @/lib/utils is no use here: it
  // forces a decimal and doesn't do Indian comma grouping, which
  // is the whole point of the tile.
  // eslint-disable-next-line no-restricted-syntax
  return n.toLocaleString("en-IN", { maximumFractionDigits: 0 })
}

function buildTiles(stats: CoverageStatsResponse | null): Tile[] {
  return [
    {
      key: "stocks",
      icon: BarChart3,
      value:
        stats && typeof stats.stocks_covered === "number"
          ? formatIndianInt(stats.stocks_covered)
          : null,
      caption: "Stocks Covered",
      href: "/discover",
      testId: "trust-tile-stocks",
    },
    {
      key: "logo",
      icon: ImageIcon,
      value:
        stats && typeof stats.nifty500_logo_coverage_pct === "number"
          ? `${stats.nifty500_logo_coverage_pct}%`
          : null,
      caption: "Real-logo Coverage",
      href: "/methodology",
      testId: "trust-tile-logo",
    },
    {
      key: "updates",
      // "Daily" is a cadence label, not a count — value is a literal
      // string set unconditionally as long as the strip itself
      // renders (the engine runs nightly regardless of stats payload).
      icon: RefreshCw,
      value: "Daily",
      caption: "Engine Updates",
      href: "/methodology",
      testId: "trust-tile-updates",
    },
    {
      key: "sectors",
      icon: Layers,
      value:
        stats && typeof stats.sectors_covered === "number"
          ? `${stats.sectors_covered}`
          : null,
      caption: "NSE Sectors",
      href: "/sector",
      testId: "trust-tile-sectors",
    },
  ]
}

export default function TrustStatsStrip() {
  // useState + useEffect (not React Query) so this component has
  // zero extra deps and the SSR snapshot is deterministic. The
  // network round-trip is a single cached GET; React Query's
  // memoisation buys nothing on a one-shot mount.
  const [stats, setStats] = useState<CoverageStatsResponse | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let cancelled = false
    getCoverageStats()
      .then((data) => {
        if (!cancelled) {
          setStats(data)
          setLoaded(true)
        }
      })
      .catch(() => {
        // Network failure → leave stats null and mark loaded so the
        // skeleton stops pulsing. Each tile then falls through to
        // "—" via its own value-presence check.
        if (!cancelled) setLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const tiles = buildTiles(stats)

  return (
    <section
      data-testid="trust-stats-strip"
      aria-label="YieldIQ coverage statistics"
      className="bg-bg dark:bg-surface border-y border-gray-100 py-10"
    >
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {tiles.map((t) => {
            const Icon = t.icon
            const hasValue = t.value !== null
            const valueClass = `font-display text-2xl md:text-3xl font-black text-ink font-mono tabular-nums ${
              hasValue ? "" : (loaded ? "" : "animate-pulse")
            }`
            const inner = (
              <div
                className={`flex flex-col items-center justify-center rounded-2xl border border-gray-100 bg-white dark:bg-surface p-5 h-full transition-all ${
                  t.href
                    ? "hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md cursor-pointer"
                    : ""
                }`}
              >
                <Icon className="w-5 h-5 text-blue-600 mb-2" />
                <span data-testid={`${t.testId}-value`} className={valueClass}>
                  {hasValue ? t.value : "—"}
                </span>
                <span className="text-caption text-xs mt-1 text-center tracking-wide">
                  {t.caption}
                </span>
              </div>
            )
            if (t.href) {
              return (
                <Link
                  key={t.key}
                  href={t.href}
                  data-testid={t.testId}
                  className="block h-full"
                >
                  {inner}
                </Link>
              )
            }
            return (
              <div key={t.key} data-testid={t.testId} className="h-full">
                {inner}
              </div>
            )
          })}
        </div>

        {/* Disclaimer microtype. Required for SEBI — names the data
            sources, points to /methodology, and includes the
            "Not investment advice" line. */}
        <p
          data-testid="trust-stats-disclaimer"
          className="text-caption text-[11px] mt-4 text-center max-w-3xl mx-auto leading-relaxed"
        >
          Sourced from public BSE/NSE filings + yfinance. Updated continuously.
          Not investment advice &mdash;{" "}
          <Link href="/methodology" className="underline hover:text-gray-700 transition">
            see methodology
          </Link>
          .
        </p>
      </div>
    </section>
  )
}
