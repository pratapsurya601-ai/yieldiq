/**
 * logoUrl — resolve a real company logo URL for a given NSE ticker.
 *
 * 2026-06-07 HOTFIX: Clearbit's free Logo API (`logo.clearbit.com`) was
 * decommissioned. Bare-domain Brandfetch (`cdn.brandfetch.io/{domain}`)
 * now returns an HTML preview page rather than an image, so it is no
 * longer usable as an `<img src>` either. The chain has been rebuilt
 * around two free, stable, image-returning endpoints:
 *
 *   PRIMARY:  Google s2/favicons — `https://www.google.com/s2/favicons?domain={d}&sz={n}`
 *             Always-on, no key, real PNG (~32-128px). Lower fidelity
 *             than the old Clearbit hop but bulletproof.
 *   FALLBACK: DuckDuckGo icons — `https://icons.duckduckgo.com/ip3/{d}.ico`
 *             Independent source, sidesteps the rare case where Google's
 *             favicon crawler hasn't indexed the domain.
 *
 * If both resolve to null OR the <img onError> fires past the last
 * stage, the caller MUST fall through to the existing giant-letter
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
