"use client"

/**
 * StockHeroImage — dark identity band for /analysis/[ticker]
 * (feat/alphaspread-style-opening, 2026-06-11).
 *
 * Reference design: AlphaSpread's /security/* opening. A compact deep
 * navy/ink band — NOT a tall lifestyle photo — carrying, top to bottom:
 *
 *   1. DATA ROW: "Price:" + delayed quote + (optional intraday change)
 *      + "Market Open/Closed" dot-pill (NSE regular hours; holiday
 *      blind spot disclosed via title) + the "Price quote Xh ago"
 *      freshness stamp on the left; "Market Cap: ₹X Lakh Cr" right.
 *   2. IDENTITY ROW (inside the same band): 48px TickerAvatar chip +
 *      company name (the page h1) + EXCHANGE:TICKER in mono +
 *      WatchlistButton (bordered hero variant) on the right.
 *
 * The sector photo from the previous revision survives as a dim
 * texture layer (≈10% opacity under a navy wash) so the band keeps a
 * per-sector personality without competing with the numbers —
 * "Bloomberg meets Apple", data first. The photo pipeline
 * (sectorToHeroImagePath → /hero-sectors/{slug}.webp, default.webp
 * floor, onError belt-and-braces) is unchanged.
 *
 * Retired in this restyle:
 *   - 280-440px photo-dominant hero block
 *   - floating verdict pill (verdict now lives ONLY in the
 *     "1. INTRINSIC VALUE" section below — single verdict surface
 *     above the fold, no contradiction window)
 *   - identity row below the band (now inside it)
 *
 * SEBI discipline: the quote is always presented with the "Price
 * quote …" freshness stamp; the market-hours pill describes the
 * exchange session window, never the quote itself.
 */

import { useState, type ReactNode } from "react"

import FreshnessStamp from "@/components/common/FreshnessStamp"
import TickerAvatar from "@/components/common/TickerAvatar"
import WatchlistButton from "@/components/watchlist/WatchlistButton"
import { formatCurrency } from "@/lib/utils"
import { formatMarketCap } from "@/lib/formatters"
import { sectorToHeroImagePath } from "@/lib/sectorHeroImage"

export interface StockHeroImageProps {
  ticker: string
  /** Display ticker (without .NS / .BO suffix). Falls back to `ticker`. */
  displayTicker?: string
  companyName: string
  /** Raw backend sector string. Drives the texture photo + avatar hue. */
  sector?: string | null
  /** "NSE" / "BSE" — rendered as part of the EXCHANGE:TICKER line. */
  exchange?: string | null
  currentPrice: number
  currency: string
  marketCapCr?: number | null
  /** ISO-8601 timestamp of the quote freshness ("Price quote Xm ago"). */
  asOf?: string | null
  /** Optional intraday change % — hidden when null (no fake zeros). */
  intradayChangePct?: number | null
  /** Drives the "Market Open/Closed" dot-pill. Omitted → no pill. */
  marketOpen?: boolean | null
  /** Caption surfaced on the market pill's title (holiday blind spot). */
  marketStatusCaption?: string | null
  /** Extra chips next to the ticker line (e.g. UnlockBadge). */
  identityExtra?: ReactNode
}

export default function StockHeroImage({
  ticker,
  displayTicker,
  companyName,
  sector,
  exchange,
  currentPrice,
  currency,
  marketCapCr,
  asOf,
  intradayChangePct,
  marketOpen,
  marketStatusCaption,
  identityExtra,
}: StockHeroImageProps) {
  const safeTicker = (displayTicker ?? ticker).replace(/\.(NS|BO)$/i, "")
  const exchangeLabel = (exchange || "NSE").toUpperCase()

  // Sector → photo slug → on-disk path. Always resolves to a real asset
  // (`default.webp` is the floor); onError hides the texture and lets
  // the solid ink base show through.
  const heroSrc = sectorToHeroImagePath(sector)
  const [heroOk, setHeroOk] = useState(true)

  const showIntraday =
    intradayChangePct != null && Number.isFinite(intradayChangePct)
  const intradayUp = (intradayChangePct ?? 0) >= 0

  return (
    <section
      aria-label={`${companyName} hero summary`}
      data-testid="stock-hero-section"
      className="relative w-full overflow-hidden rounded-2xl bg-slate-950"
    >
      {/* Sector texture — dim photo layer under the navy wash. Plain
          <img> (assets are pre-sized WebP shipped in-repo; the Next
          optimizer adds latency without a size win at this scale). */}
      {heroOk && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={heroSrc}
          data-testid="stock-hero-photo"
          data-sector-slug={heroSrc.replace(/^.*\/(.+)\.webp$/, "$1")}
          alt=""
          aria-hidden
          loading="eager"
          decoding="async"
          onError={() => setHeroOk(false)}
          className="absolute inset-0 w-full h-full object-cover opacity-10"
        />
      )}
      {/* Deep navy/ink wash so text contrast never depends on the photo. */}
      <div
        aria-hidden
        className="absolute inset-0 bg-gradient-to-br from-slate-950/95 via-slate-900/90 to-slate-950/95"
      />

      {/* ── Row 1: price + market status (left) · market cap (right) ── */}
      <div
        data-testid="hero-glass-panel"
        className="relative flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3 md:px-6 border-b border-white/10 text-white"
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm min-w-0">
          <span className="text-xs text-slate-400">Price:</span>
          <span className="font-mono tabular-nums font-bold text-lg md:text-xl">
            {currentPrice > 0 ? formatCurrency(currentPrice, currency, ticker) : "—"}
          </span>
          {showIntraday && (
            <span
              className={[
                "font-mono tabular-nums text-sm font-semibold",
                intradayUp ? "text-emerald-300" : "text-rose-300",
              ].join(" ")}
              aria-label={`Intraday change ${intradayChangePct!.toFixed(2)} percent`}
            >
              {intradayUp ? "+" : ""}
              {intradayChangePct!.toFixed(2)}%
            </span>
          )}
          {marketOpen != null && (
            <span
              data-testid="market-status-pill"
              data-open={marketOpen ? "true" : "false"}
              title={marketStatusCaption ?? undefined}
              className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/5 px-2.5 py-0.5 text-[11px] font-medium text-slate-200"
            >
              <span
                aria-hidden
                className={[
                  "inline-block h-1.5 w-1.5 rounded-full",
                  marketOpen ? "bg-emerald-400" : "bg-slate-500",
                ].join(" ")}
              />
              Market {marketOpen ? "Open" : "Closed"}
            </span>
          )}
          <FreshnessStamp
            timestamp={asOf}
            prefix="Price quote"
            fallback="Quote freshness unknown"
            className="text-xs text-slate-400"
          />
        </div>
        {marketCapCr != null && marketCapCr > 0 && (
          <div className="text-xs md:text-sm shrink-0">
            <span className="text-slate-400">Market Cap:</span>{" "}
            <span className="font-mono tabular-nums font-semibold">
              {formatMarketCap(marketCapCr)}
            </span>
          </div>
        )}
      </div>

      {/* ── Row 2: identity — logo chip + name + exchange:ticker + watchlist ── */}
      <div
        data-testid="hero-identity-row"
        className="relative flex flex-col gap-3 px-4 py-4 md:px-6 md:py-5 sm:flex-row sm:items-center"
      >
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <TickerAvatar
            ticker={safeTicker}
            size="lg"
            sector={sector ?? undefined}
          />
          <div className="min-w-0">
            <h1 className="font-editorial text-xl md:text-2xl font-semibold text-white leading-tight truncate">
              {companyName}
            </h1>
            <div className="mt-0.5 flex items-center gap-2 flex-wrap">
              <span className="text-xs md:text-sm font-mono text-slate-400">
                {exchangeLabel}:{safeTicker}
              </span>
              {identityExtra}
            </div>
          </div>
        </div>
        {/* Bordered hero watchlist button. WatchlistButton itself is a
            shared component — the dark-band contrast overrides are
            applied from outside via arbitrary variants. */}
        <div className="shrink-0 sm:ml-auto [&_button]:w-full sm:[&_button]:w-auto [&_button]:border-white/25 [&_button]:text-white [&_button:hover]:bg-white/10 [&_a]:text-slate-200">
          <WatchlistButton
            ticker={safeTicker}
            companyName={companyName}
            variant="default"
          />
        </div>
      </div>
    </section>
  )
}
