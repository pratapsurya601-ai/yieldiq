/**
 * logoUrl — resolve a real company logo URL for a given NSE ticker.
 *
 * Two-source chain (in StockHeroImage.tsx):
 *   1. Brandfetch CDN — highest fidelity (SVG/transparent PNG), but
 *      requires a per-tenant client ID. Gated on the
 *      `NEXT_PUBLIC_BRANDFETCH_CLIENT_ID` env var; returns null when
 *      unset so callers fall straight through to the favicon.
 *      (The "public demo" client id is rate-limited / 403s in practice.)
 *   2. Google favicon CDN (`s2/favicons`) — always-on, no key needed,
 *      returns a small PNG (~32-128px). Lower fidelity but bulletproof.
 *
 * If both resolve to null OR the <Image> onError fires twice, the
 * caller MUST fall through to the existing giant-letter fallback —
 * see StockHeroImage.tsx. Never throw from here.
 *
 * Domain lookups are case-insensitive on the ticker. Tickers absent
 * from `ticker_domains.json` return null at the first hop (so we never
 * fire a request we know will 404).
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

export function getBrandfetchUrl(
  ticker: string,
  size: 64 | 128 | 256 = 128,
): string | null {
  const domain = getCompanyDomain(ticker)
  if (!domain) return null
  const clientId = process.env.NEXT_PUBLIC_BRANDFETCH_CLIENT_ID
  if (!clientId) return null
  return `https://cdn.brandfetch.io/${domain}/w/${size}/h/${size}?c=${clientId}`
}

export function getFaviconUrl(
  ticker: string,
  size: 64 | 128 | 256 = 128,
): string | null {
  const domain = getCompanyDomain(ticker)
  if (!domain) return null
  return `https://www.google.com/s2/favicons?domain=${domain}&sz=${size}`
}

/**
 * Primary logo URL — Brandfetch when configured, else favicon. Returns
 * null when the ticker isn't in the domain map at all (giant-letter
 * fallback path).
 */
export function getLogoUrl(
  ticker: string,
  size: 64 | 128 | 256 = 128,
): string | null {
  return getBrandfetchUrl(ticker, size) ?? getFaviconUrl(ticker, size)
}

/**
 * Fallback logo URL — used by the <Image onError> handler in
 * StockHeroImage to swap from Brandfetch to favicon. Returns null when
 * the primary was already favicon (no further fallback to try).
 */
export function getLogoFallbackUrl(
  ticker: string,
  size: 64 | 128 | 256 = 128,
): string | null {
  // If Brandfetch is configured and we tried it first, fall back to
  // the favicon. Otherwise there is no further URL to try — the caller
  // should render the letter.
  if (!process.env.NEXT_PUBLIC_BRANDFETCH_CLIENT_ID) return null
  return getFaviconUrl(ticker, size)
}
