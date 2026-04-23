"use client"

/**
 * PriceTimestamp — a tiny, reusable caption that renders the
 * "as of" time for a displayed quote.
 *
 * SEBI guidance (and plain honesty) expects that whenever we surface
 * a live-looking price we tell the reader how fresh it is. Yahoo/NSE
 * feeds can be 15-minute-delayed; market-closed prices can be a day
 * old; cached responses can be older still. A single, visually muted
 * "As of 15:27 IST" line under every price clears that up without
 * adding noise.
 *
 * Behaviour:
 *   - Renders nothing when `as_of` is null / undefined / unparsable.
 *     Callers can therefore include it unconditionally next to a
 *     price without guard-clauses — a page that doesn't yet have
 *     the field propagated from the backend simply shows nothing.
 *   - Formats in IST (Asia/Kolkata) because our entire audience is
 *     the Indian retail investor. HH:MM only; the date is implicit
 *     for intraday prices. If the timestamp is from a prior day
 *     the component still renders HH:MM IST — upstream callers
 *     should consider showing a "closed" badge in that case.
 *
 * Wiring status (2026-04-23, PR-A of SEBI hardening):
 *   The backend has `as_of` on every row returned by
 *   `backend/services/market_data_service.py`, but it is NOT yet
 *   propagated through:
 *     - /api/v1/analysis/{ticker}          (ValuationOutput)
 *     - /api/v1/public/stock-summary/{t}   (StockSummary)
 *     - portfolio / watchlist / screener / movers endpoints
 *   So at time of PR-A the component is defined and imported, but
 *   every integration site renders `as_of={null}` with a `TODO`
 *   comment pointing at the backend plumbing needed for PR-B.
 */

interface PriceTimestampProps {
  /** ISO-8601 string (UTC or with TZ offset) or null. */
  as_of: string | null | undefined
  /** Optional extra classes for positioning / layout. */
  className?: string
}

function formatIST(iso: string): string | null {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  try {
    return d.toLocaleTimeString("en-IN", {
      timeZone: "Asia/Kolkata",
      hour: "2-digit",
      minute: "2-digit",
    })
  } catch {
    // Some older Node / Edge runtimes reject timeZone — fall back
    // to a plain locale string rather than blowing up the page.
    return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })
  }
}

export default function PriceTimestamp({ as_of, className }: PriceTimestampProps) {
  if (!as_of) return null
  const hhmm = formatIST(as_of)
  if (!hhmm) return null
  const cls = ["text-caption text-[11px] leading-snug", className].filter(Boolean).join(" ")
  return <span className={cls}>As of {hhmm} IST</span>
}
