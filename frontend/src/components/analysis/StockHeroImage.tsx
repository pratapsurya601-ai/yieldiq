"use client"

/**
 * StockHeroImage — contextual-sector photo hero for /analysis/[ticker].
 *
 * Reference design: AlphaSpread's /security/* hero. The background is a
 * sector-appropriate lifestyle photo (a bank lobby for HDFCBANK, an open
 * workspace for TCS, a refinery for RELIANCE), NOT a stretched company
 * logo. The company's logo is shown separately as a small 48px chip in
 * the identity row BELOW the hero, never as the hero image itself.
 *
 * Layout (rendered inside this single component):
 *   1. Full-bleed 420-480px photo background with bottom-darkening gradient
 *   2. Verdict pill — floating top-right with backdrop-blur
 *   3. Glass info panel pinned to the bottom: price, change %, market
 *      status (left) and market cap (right)
 *   4. Identity row IMMEDIATELY below the photo: TickerAvatar chip +
 *      company name + EXCHANGE:TICKER + WatchlistButton
 *
 * Photo sources: 18 sector slugs under /hero-sectors/{slug}.webp,
 * downloaded from Unsplash by scripts/fetch_sector_heroes.py and shipped
 * in-repo (no third-party hop at runtime). The raw backend sector string
 * is mapped to a slug by `sectorToHeroImagePath`; unmapped values fall
 * through to `default.webp`. The image asset is always present —
 * `onError` is a belt-and-braces fallback only.
 *
 * Retired in this refactor:
 *   - `/hero/{TICKER}.jpg` marquee path (45 stretched Wikipedia infobox
 *     photos that read as low-resolution at 1200x600)
 *   - `/api/v1/public/company-image/{ticker}` backend endpoint probe
 *     (Phase 1 always returned 204; the gradient fallback was the
 *     de-facto experience for every ticker)
 *   - Giant centered company logo as the hero anchor (replaced by the
 *     contextual photo; the logo now lives only in the identity row
 *     chip via TickerAvatar)
 *   - "Image: Wikipedia (CC-BY-SA)" credit (Unsplash License is
 *     attribution-optional; per-photo credits live in
 *     /hero-sectors/CREDITS.md instead)
 */

import { useState } from "react"

import FreshnessStamp from "@/components/common/FreshnessStamp"
import TickerAvatar from "@/components/common/TickerAvatar"
import WatchlistButton from "@/components/watchlist/WatchlistButton"
import { formatCurrency } from "@/lib/utils"
import { formatMarketCap } from "@/lib/formatters"
import { sectorToHeroImagePath } from "@/lib/sectorHeroImage"
import {
  VERDICT_COLORS,
  verdictTierFromMos,
  verdictTierLabel,
} from "@/lib/verdict-colors"

export interface StockHeroImageProps {
  ticker: string
  /** Display ticker (without .NS / .BO suffix). Falls back to `ticker`. */
  displayTicker?: string
  companyName: string
  /** Raw backend sector string. Drives the hero photo selection. */
  sector?: string | null
  /** "NSE" / "BSE" — rendered as part of the EXCHANGE:TICKER chip. */
  exchange?: string | null
  currentPrice: number
  currency: string
  marginOfSafetyPct?: number | null
  verdict?: string | null
  marketCapCr?: number | null
  /** ISO-8601 timestamp of the quote freshness ("delayed, as of Xm ago"). */
  asOf?: string | null
  /** Optional intraday change % — hidden when null. */
  intradayChangePct?: number | null
  /** Optional flag — when present, drives the "Market Open/Closed" tag
   *  in the bottom glass panel. Omitted when caller has no signal. */
  marketOpen?: boolean | null
}

export default function StockHeroImage({
  ticker,
  displayTicker,
  companyName,
  sector,
  exchange,
  currentPrice,
  currency,
  marginOfSafetyPct,
  verdict,
  marketCapCr,
  asOf,
  intradayChangePct,
  marketOpen,
}: StockHeroImageProps) {
  const tier = verdictTierFromMos(marginOfSafetyPct, verdict)
  const palette = VERDICT_COLORS[tier]
  const tierLabel = verdictTierLabel(tier)
  const safeTicker = (displayTicker ?? ticker).replace(/\.(NS|BO)$/i, "")
  const exchangeLabel = (exchange || "NSE").toUpperCase()

  // Sector → photo slug → on-disk path. Always resolves to a real asset
  // (`default.webp` is the floor) so the rendered <img> tag always has
  // a valid src; the onError handler is a defence-in-depth no-op
  // wrapper that hides the photo and lets the verdict gradient show
  // through if a future asset move ever breaks the path.
  const heroSrc = sectorToHeroImagePath(sector)
  const [heroOk, setHeroOk] = useState(true)

  // Intraday change chip — only render when the backend actually sent a
  // number. No fake zeros.
  const showIntraday =
    intradayChangePct != null && Number.isFinite(intradayChangePct)
  const intradayUp = (intradayChangePct ?? 0) >= 0

  return (
    <div className="w-full">
      <section
        aria-label={`${companyName} hero summary`}
        data-testid="stock-hero-section"
        className={[
          "relative w-full overflow-hidden rounded-2xl",
          // Reference design uses a taller hero than the prior 220/320
          // pair so the contextual photo reads as the dominant surface.
          "h-[280px] sm:h-[360px] md:h-[440px]",
          // Solid gradient base — only ever visible if the photo asset
          // fails to load (defence in depth; the photo is in-repo).
          "bg-gradient-to-br",
          palette.from,
          palette.to,
        ].join(" ")}
      >
        {/* Sector-contextual photo background. Plain <img> rather than
            next/image: the WebP assets are pre-sized at build time
            (1600x600) and Next's optimizer would re-encode them at
            request time without a width/height advantage at hero scale,
            while competing with the verdict pill for LCP slot.
            eslint-disable-next-line @next/next/no-img-element */}
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
            className="absolute inset-0 w-full h-full object-cover"
          />
        )}

        {/* Top-to-bottom darkening so the bottom glass panel reads. */}
        <div
          aria-hidden
          className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent"
        />

        {/* Verdict pill — floating top-right with backdrop-blur. */}
        <div className="absolute top-3 right-3 md:top-4 md:right-4 flex items-center gap-2">
          <span
            data-testid="hero-verdict-pill"
            className={[
              "inline-flex items-center gap-1.5 rounded-full",
              "px-3 py-1 text-[11px] md:text-xs font-semibold uppercase tracking-wider",
              "bg-black/40 backdrop-blur-md border border-white/25",
              "text-white",
            ].join(" ")}
          >
            <span
              aria-hidden
              className={`inline-block w-1.5 h-1.5 rounded-full ${palette.bar}`}
            />
            {tierLabel}
          </span>
        </div>

        {/* Bottom glass panel — price + change + market status (left),
            market cap (right). Mirrors AlphaSpread's hero footer. */}
        <div
          data-testid="hero-glass-panel"
          className={[
            "absolute bottom-0 left-0 right-0",
            "px-4 py-3 md:px-6 md:py-4",
            "bg-white/10 dark:bg-black/30 backdrop-blur-md",
            "border-t border-white/10",
            "flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2",
            "text-white",
          ].join(" ")}
        >
          <div className="flex items-baseline gap-3 md:gap-4 text-sm flex-wrap">
            <span className="font-mono tabular-nums font-bold text-lg md:text-xl">
              {currentPrice > 0 ? formatCurrency(currentPrice, currency) : "—"}
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
              <span className="text-xs md:text-sm text-zinc-200">
                Market {marketOpen ? "Open" : "Closed"}
              </span>
            )}
            {/* 2026-06-09 fix/analysis-ux-fixbatch: prefix re-labelled
                from "Delayed, as of" to "Price quote" so this stamp is
                visibly distinct from the toolbar's "Model recomputed"
                stamp. Prior copy and the toolbar copy were near-
                identical ("Delayed, as of 13h ago" vs "Delayed, as of
                23h ago") which read as a single stamp rendered twice
                with two different ages. */}
            <FreshnessStamp
              timestamp={asOf}
              prefix="Price quote"
              fallback="Quote freshness unknown"
              className="text-xs text-zinc-300"
            />
          </div>
          {marketCapCr != null && marketCapCr > 0 && (
            <div className="text-xs md:text-sm">
              <span className="text-zinc-300">Market Cap:</span>{" "}
              <span className="font-mono tabular-nums font-semibold">
                {formatMarketCap(marketCapCr)}
              </span>
            </div>
          )}
        </div>
      </section>

      {/* Identity row — sits BELOW the photo, not inside it. The 48px
          TickerAvatar chip is the ONLY surface the company logo
          renders on; the hero photo above is sector-contextual. */}
      <div
        data-testid="hero-identity-row"
        className="px-4 md:px-6 py-3 md:py-4 flex items-center gap-3 border-b border-border"
      >
        <TickerAvatar
          ticker={safeTicker}
          size="lg"
          sector={sector ?? undefined}
        />
        <div className="min-w-0">
          <div className="font-semibold text-base md:text-lg text-ink truncate">
            {companyName}
          </div>
          <div className="text-xs md:text-sm text-caption font-mono">
            {exchangeLabel}:{safeTicker}
          </div>
        </div>
        <div className="ml-auto">
          <WatchlistButton
            ticker={safeTicker}
            companyName={companyName}
            variant="default"
          />
        </div>
      </div>
    </div>
  )
}
