/**
 * companyLogo — server-side helper for the 5 OG image routes under
 * `frontend/src/app/api/og/**`. Resolves a curated NSE ticker to a
 * corporate domain, fetches the Google favicon with a tight 2s timeout,
 * and returns it as a base64 data URL suitable for embedding directly
 * inside a Satori `<img src=...>` element.
 *
 * 2026-06-07 HOTFIX: was Clearbit; Clearbit's free Logo API was
 * decommissioned (returns HTTP 000 / connection refused). Switched to
 * Google's s2/favicons endpoint — same call shape, same timeout, same
 * data-URL conversion, same graceful-null contract.
 *
 * Why a curated 50-entry map instead of the wider
 * `frontend/src/data/ticker_domains.json` dict used by `lib/logoUrl.ts`
 * (the analysis hero)?
 *
 * The OG share surfaces are the highest-leverage social-share artefact;
 * a broken or wrong logo on a WhatsApp / Twitter preview is hard to
 * roll back (scrapers cache aggressively). The 50 entries below are
 * the user-approved superset used by the sibling sitewide TickerAvatar
 * work — same provenance, same vetting, same logos rendering on chip
 * surfaces. Keeping the two lists aligned avoids a "ticker has a logo
 * on the chip but a letter-mark on the OG card" mismatch.
 *
 * After the sibling PR (`feat/ticker-avatar-sitewide-v2`) lands the
 * shared module at `frontend/src/components/common/tickerDomains.ts`,
 * THIS file's NSE_TICKER_DOMAINS literal can be deleted and the
 * import switched to that shared module. The de-dupe is a follow-up
 * cleanup; both lists are byte-identical so it's a mechanical change.
 *
 * Fallback chain (per brief):
 *   1. Ticker not in curated map               → return null (letter mark)
 *   2. Google favicon fails / 404 / >2s        → return null (letter mark)
 *   3. Google favicon OK                       → base64 data URL
 *
 * Edge-runtime constraints respected:
 *   - No Node `Buffer` import (uses `btoa` + `Uint8Array`).
 *   - `AbortSignal.timeout(2000)` (Web API, edge-safe).
 *   - No throws — callers can blindly trust the return shape.
 *
 * Performance: first call per (ticker, edge-pop) pays a one-shot
 * Google-favicon latency; subsequent calls inside the 30-minute
 * `s-maxage` window of the OG routes are served from Vercel's edge
 * cache (the buffer is folded into the PNG, so caching the PNG caches
 * the logo too).
 */

// USER-APPROVED top-50 NSE ticker → corporate domain map.
// Mirrors `frontend/src/components/common/tickerDomains.ts` (sibling
// TickerAvatar PR); see header comment for the de-dupe plan.
//
// IMPORTANT: do NOT silently extend this list. Adding entries requires
// explicit operator approval — an earlier agent shipped an unreviewed
// curated list and the task was rolled back.
export const NSE_TICKER_DOMAINS: Record<string, string> = {
  // Banks & Financials
  HDFCBANK: "hdfcbank.com",
  ICICIBANK: "icicibank.com",
  SBIN: "sbi.co.in",
  KOTAKBANK: "kotak.com",
  AXISBANK: "axisbank.com",
  BAJFINANCE: "bajajfinserv.in",
  BAJAJFINSV: "bajajfinserv.in",
  HDFCLIFE: "hdfclife.com",
  SBILIFE: "sbilife.co.in",
  LICI: "licindia.in",
  // IT Services
  TCS: "tcs.com",
  INFY: "infosys.com",
  WIPRO: "wipro.com",
  HCLTECH: "hcltech.com",
  TECHM: "techmahindra.com",
  // FMCG / Consumer
  HINDUNILVR: "hul.co.in",
  ITC: "itcportal.com",
  NESTLEIND: "nestle.in",
  BRITANNIA: "britannia.co.in",
  DABUR: "dabur.com",
  TATACONSUM: "tataconsumer.com",
  // Energy / Oil & Gas / Power
  RELIANCE: "ril.com",
  ONGC: "ongcindia.com",
  NTPC: "ntpc.co.in",
  POWERGRID: "powergrid.in",
  COALINDIA: "coalindia.in",
  ADANIPOWER: "adanipower.com",
  // Auto
  MARUTI: "marutisuzuki.com",
  "M&M": "mahindra.com",
  TATAMOTORS: "tatamotors.com",
  "BAJAJ-AUTO": "bajajauto.com",
  EICHERMOT: "eichermotors.com",
  HEROMOTOCO: "heromotocorp.com",
  // Pharma
  SUNPHARMA: "sunpharma.com",
  DRREDDY: "drreddys.com",
  CIPLA: "cipla.com",
  DIVISLAB: "divislabs.com",
  // Metals / Cement / Industrials
  TATASTEEL: "tatasteel.com",
  JSWSTEEL: "jsw.in",
  HINDALCO: "hindalco.com",
  LT: "larsentoubro.com",
  ULTRACEMCO: "ultratechcement.com",
  GRASIM: "grasim.com",
  // Telecom / Retail / Other
  BHARTIARTL: "airtel.in",
  TITAN: "titan.co.in",
  ASIANPAINT: "asianpaints.com",
  DMART: "dmartindia.com",
  ADANIPORTS: "adaniports.com",
  ADANIENT: "adanienterprises.com",
  INDUSINDBK: "indusind.com",
}

/** Strip `.NS`, `.BO`, `.NSE`, `.BSE` suffixes and uppercase. */
export function cleanTickerForLogo(ticker: string): string {
  return (ticker || "").toUpperCase().replace(/\.(NS|BO|NSE|BSE)$/i, "")
}

/** Look up corporate domain for the cleaned ticker. Null if not curated. */
export function getCuratedDomain(ticker: string): string | null {
  const key = cleanTickerForLogo(ticker)
  return NSE_TICKER_DOMAINS[key] ?? null
}

// Edge-runtime safe base64 encoder. `btoa` is available in the edge
// runtime; we feed it the raw bytes one char at a time to avoid the
// "invalid character" you'd get from passing a UTF-8 string.
function bytesToBase64(bytes: Uint8Array): string {
  let binary = ""
  // Chunk the loop so 100KB+ payloads don't blow the call stack via
  // String.fromCharCode(...spread). 8KB chunks are conservative.
  const CHUNK = 8192
  for (let i = 0; i < bytes.length; i += CHUNK) {
    const slice = bytes.subarray(i, Math.min(i + CHUNK, bytes.length))
    binary += String.fromCharCode(...slice)
  }
  return btoa(binary)
}

/**
 * Fetch the Google s2/favicons logo for a ticker and return it as a
 * base64 data URL. Never throws. Returns null when:
 *   - ticker is not in the curated NSE_TICKER_DOMAINS map
 *   - Google returns a non-2xx (rare; the endpoint usually serves a
 *     generic globe rather than 404, but we still guard)
 *   - the request exceeds the 2s timeout
 *   - the response body is empty or unreadable
 *   - the response content-type isn't an image (defends against the
 *     "served an HTML preview page" failure mode that killed the old
 *     bare-domain Brandfetch URL)
 *
 * Caller pattern:
 *
 *   const logo = await fetchCompanyLogoDataUrl(ticker)
 *   ...
 *   {logo ? <img src={logo} width={80} height={80} /> : <LetterMark />}
 */
export async function fetchCompanyLogoDataUrl(
  ticker: string,
): Promise<string | null> {
  const domain = getCuratedDomain(ticker)
  if (!domain) return null

  try {
    // 2026-06-07 HOTFIX: was `https://logo.clearbit.com/${domain}` —
    // Clearbit shut down its free Logo API and that endpoint now
    // refuses connections. Google s2/favicons is the always-on free
    // replacement, returns ~32-128px PNG.
    const url = `https://www.google.com/s2/favicons?domain=${domain}&sz=128`
    const res = await fetch(url, {
      signal: AbortSignal.timeout(2000),
      // Identify ourselves so the dashboards see a real referrer.
      headers: { "User-Agent": "YieldIQ-OG/1.0 (+https://yieldiq.in)" },
    })
    if (!res.ok) return null

    const ct = res.headers.get("content-type") || "image/png"
    // Defence-in-depth: reject HTML/text bodies so we never accidentally
    // embed a preview page as the OG logo (the Brandfetch failure mode).
    if (!ct.startsWith("image/")) return null

    const buf = await res.arrayBuffer()
    if (!buf || buf.byteLength === 0) return null

    const b64 = bytesToBase64(new Uint8Array(buf))
    return `data:${ct};base64,${b64}`
  } catch {
    // Timeout, network error, malformed response — fall through to the
    // letter-mark fallback. OG generation must NEVER 500 on a logo
    // hop; scrapers cache failures aggressively.
    return null
  }
}
