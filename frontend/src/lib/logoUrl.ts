/**
 * logoUrl — resolve a real company logo URL for a given NSE ticker.
 *
 * 2026-06-09 UPGRADE: self-hosted retina-sharp 192px PNGs from Logo.dev
 * are now stage 0. We mass-fetched the full 261-entry domain map via
 * `frontend/scripts/fetch-logos-logodev.mjs` and committed the PNGs to
 * `frontend/public/logos/{TICKER}.png`. Served directly from the CDN
 * edge — no per-render hop to a third-party favicon endpoint, and
 * sharper than the 64-128px Google s2/favicons we were using.
 *
 * 2026-06-07 HOTFIX (still relevant for stages 1+): Clearbit's free
 * Logo API was decommissioned. Bare-domain Brandfetch returns HTML
 * now, not an image. The remaining fallback chain is built around two
 * free, stable, image-returning endpoints:
 *
 *   STAGE 0:  Self-hosted /logos/{TICKER}.png — Logo.dev mass-fetched
 *             at build time, 192px PNG, ~10-30KB each.
 *   STAGE 1:  Google s2/favicons — `https://www.google.com/s2/favicons?domain={d}&sz={n}`
 *             Always-on, no key, real PNG (~32-128px). Bulletproof
 *             long-tail fallback for any ticker whose Logo.dev fetch
 *             missed (placeholder or fail).
 *   STAGE 2:  DuckDuckGo icons — `https://icons.duckduckgo.com/ip3/{d}.ico`
 *             Independent source, sidesteps the rare case where Google's
 *             favicon crawler hasn't indexed the domain.
 *
 * If every stage resolves to null OR the <img onError> fires past the
 * last stage, the caller MUST fall through to the existing giant-letter
 * fallback — see StockHeroImage.tsx / TickerAvatar.tsx. Never throw
 * from here.
 *
 * Domain lookups are case-insensitive on the ticker. Tickers absent
 * from `ticker_domains.json` return null at the first hop (so we never
 * fire a request we know will resolve to a generic globe).
 */

import tickerDomains from "@/data/ticker_domains.json"

// The JSON has a "_meta" key alongside the ticker entries — strip it
// from the lookup so a ticker named "_META" couldn't ever collide.
const DOMAINS = tickerDomains as unknown as Record<string, string>

export function getCompanyDomain(ticker: string): string | null {
  if (!ticker) return null
  const key = ticker.toUpperCase().replace(/\.(NS|BO)$/i, "")
  const domain = DOMAINS[key]
  if (!domain || key === "_META") return null
  return domain
}

/**
 * Convert a clean NSE ticker to the on-disk filename used by the
 * mass-fetched `frontend/public/logos/` corpus. Mirrors the
 * `tickerToFsSafe` helper in `frontend/scripts/fetch-logos-logodev.mjs`
 * — both sides MUST apply identical transformations or the chip will
 * 404 and skip past the self-hosted stage even when the file exists.
 */
export function tickerToLogoFilename(ticker: string): string {
  return ticker.replace(/&/g, "_AND_").replace(/-/g, "_")
}

/**
 * Self-hosted logo URL — first hop in the chain. Returns a relative
 * path that Next.js / Vercel serves from `frontend/public/logos/` with
 * an edge cache. On 404 the `<img onError>` cascade advances to the
 * Google favicon stage; we deliberately do NOT pre-check `Map`-style
 * existence here because (a) the file list would have to be regenerated
 * each build, (b) a per-render check costs more than a single 404.
 *
 * Returns null when the ticker has no curated domain — that ticker
 * never had a Logo.dev fetch attempt, so there's no point asking the
 * CDN for a file we know doesn't exist.
 */
export function getSelfHostedLogoUrl(ticker: string): string | null {
  if (!ticker) return null
  const key = ticker.toUpperCase().replace(/\.(NS|BO)$/i, "")
  if (key === "_META" || !DOMAINS[key]) return null
  return `/logos/${tickerToLogoFilename(key)}.png`
}

/**
 * Primary logo URL — Google's s2/favicons endpoint. Always returns a
 * real PNG for a valid domain (or a generic globe at 404, which the
 * `<img onError>` chain in the consumer will treat as a failure and
 * advance to the DuckDuckGo fallback).
 */
export function getFaviconUrl(
  ticker: string,
  size: 64 | 128 | 256 = 128,
): string | null {
  const domain = getCompanyDomain(ticker)
  if (!domain) return null
  return `https://www.google.com/s2/favicons?domain=${domain}&sz=${size}`
}

/**
 * Fallback logo URL — DuckDuckGo icons. Independent crawler than
 * Google's, so often saves the day when Google's favicon entry is
 * missing or stale.
 */
export function getDuckDuckGoIconUrl(ticker: string): string | null {
  const domain = getCompanyDomain(ticker)
  if (!domain) return null
  return `https://icons.duckduckgo.com/ip3/${domain}.ico`
}

/**
 * Primary logo URL — Google s2/favicons. Returns null when the ticker
 * isn't in the domain map at all (giant-letter fallback path).
 */
export function getLogoUrl(
  ticker: string,
  size: 64 | 128 | 256 = 128,
): string | null {
  return getFaviconUrl(ticker, size)
}

/**
 * Fallback logo URL — used by the <Image onError> handler in
 * StockHeroImage to swap from Google favicon to DuckDuckGo icons.
 * Returns null when we've already exhausted the chain.
 */
export function getLogoFallbackUrl(ticker: string): string | null {
  // DuckDuckGo's `ip3` endpoint serves a single fixed size, so unlike
  // the primary `getLogoUrl` we don't take a size argument.
  return getDuckDuckGoIconUrl(ticker)
}
