/**
 * tickerDomains — sector classification + small helpers for TickerAvatar.
 *
 * NOTE: The actual ticker → corporate-domain lookup lives in the
 * canonical 261-entry map at `src/data/ticker_domains.json`, exposed
 * via `getCompanyDomain()` in `src/lib/logoUrl.ts`. This file does NOT
 * duplicate that map — earlier iterations of this task tried to ship
 * a 50-entry subset and would have regressed coverage. Always source
 * domains from the JSON; this file owns only the things the JSON
 * doesn't carry (sector tags + ticker-cleaning conventions).
 *
 * Consumed by `TickerAvatar.tsx`:
 *   - sectorForTicker(ticker) → drives the letter-mark fallback color
 *   - cleanTicker(ticker)     → strips .NS/.BO/.NSE/.BSE before lookups
 *
 * Sector coverage is best-effort and intentionally smaller than the
 * 261-entry domain map — tickers without a sector entry simply fall
 * back to "default" coloring, which is fine.
 */

// Sector hint used to color the letter-mark fallback when neither the
// Clearbit, Brandfetch, nor favicon hops produce a usable logo.
export type TickerSector =
  | "banking"
  | "tech"
  | "fmcg"
  | "auto"
  | "pharma"
  | "energy"
  | "industrials"
  | "telecom"
  | "default"

// Sector classification for the letter-mark fallback coloring. Keyed
// by the cleaned ticker (no .NS/.BO suffix). Tickers absent from this
// map render with the neutral "default" color.
export const NSE_TICKER_SECTORS: Record<string, TickerSector> = {
  // Banking & Financials
  HDFCBANK: "banking",
  ICICIBANK: "banking",
  SBIN: "banking",
  KOTAKBANK: "banking",
  AXISBANK: "banking",
  BAJFINANCE: "banking",
  BAJAJFINSV: "banking",
  HDFCLIFE: "banking",
  SBILIFE: "banking",
  LICI: "banking",
  INDUSINDBK: "banking",
  // Tech / IT Services
  TCS: "tech",
  INFY: "tech",
  WIPRO: "tech",
  HCLTECH: "tech",
  TECHM: "tech",
  // FMCG / Consumer
  HINDUNILVR: "fmcg",
  ITC: "fmcg",
  NESTLEIND: "fmcg",
  BRITANNIA: "fmcg",
  DABUR: "fmcg",
  TATACONSUM: "fmcg",
  TITAN: "fmcg",
  ASIANPAINT: "fmcg",
  DMART: "fmcg",
  // Auto
  MARUTI: "auto",
  "M&M": "auto",
  TATAMOTORS: "auto",
  "BAJAJ-AUTO": "auto",
  EICHERMOT: "auto",
  HEROMOTOCO: "auto",
  // Pharma
  SUNPHARMA: "pharma",
  DRREDDY: "pharma",
  CIPLA: "pharma",
  DIVISLAB: "pharma",
  // Energy / Oil & Gas / Power
  RELIANCE: "energy",
  ONGC: "energy",
  NTPC: "energy",
  POWERGRID: "energy",
  COALINDIA: "energy",
  ADANIPOWER: "energy",
  // Industrials / Metals / Cement
  TATASTEEL: "industrials",
  JSWSTEEL: "industrials",
  HINDALCO: "industrials",
  LT: "industrials",
  ULTRACEMCO: "industrials",
  GRASIM: "industrials",
  ADANIPORTS: "industrials",
  ADANIENT: "industrials",
  // Telecom
  BHARTIARTL: "telecom",
}

/** Strip `.NS`, `.BO`, `.NSE`, `.BSE` suffixes and uppercase. */
export function cleanTicker(ticker: string): string {
  return (ticker || "").toUpperCase().replace(/\.(NSE|BSE|NS|BO)$/i, "")
}

/** Sector lookup keyed by raw or cleaned ticker. */
export function sectorForTicker(ticker: string): TickerSector {
  return NSE_TICKER_SECTORS[cleanTicker(ticker)] ?? "default"
}
