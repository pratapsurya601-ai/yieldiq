/**
 * marketHours.ts — client-side NSE regular-hours helper.
 *
 * NSE equities trade Monday-Friday, 09:15-15:30 IST (Asia/Kolkata).
 * This helper answers "is the exchange inside its regular session right
 * now?" deterministically from any Date, using Intl with an explicit
 * Asia/Kolkata time zone so the answer is identical regardless of the
 * viewer's locale or device clock zone.
 *
 * KNOWN LIMITATION (by design): exchange holidays are NOT tracked.
 * A trading holiday that falls on a weekday will read as "Market Open"
 * during session hours. Callers must label the signal as "regular
 * hours" (tooltip/caption) rather than presenting it as an authoritative
 * live-session indicator — pair it with the quote-age stamp
 * (valuation.as_of) which IS authoritative about data freshness.
 *
 * SEBI discipline: this signal describes the exchange session window
 * only. It never upgrades a delayed quote to "Live".
 */

/** Session bounds in minutes-from-midnight IST. 09:15 → 555, 15:30 → 930. */
const NSE_OPEN_MIN = 9 * 60 + 15
const NSE_CLOSE_MIN = 15 * 60 + 30

interface IstParts {
  /** "Mon" | "Tue" | ... per en-US short weekday. */
  weekday: string
  minutesOfDay: number
}

function istParts(date: Date): IstParts {
  // formatToParts with an explicit timeZone is the only zone-safe way
  // to read wall-clock fields client-side without a tz library.
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
  let weekday = ""
  let hour = 0
  let minute = 0
  for (const part of fmt.formatToParts(date)) {
    if (part.type === "weekday") weekday = part.value
    else if (part.type === "hour") hour = Number(part.value) % 24
    else if (part.type === "minute") minute = Number(part.value)
  }
  return { weekday, minutesOfDay: hour * 60 + minute }
}

const NSE_TRADING_DAYS = new Set(["Mon", "Tue", "Wed", "Thu", "Fri"])

/**
 * True while the NSE regular session window is open in IST:
 * Mon-Fri, 09:15 (inclusive) to 15:30 (exclusive). Ignores exchange
 * holidays — see module doc.
 *
 * `now` is injectable so tests (and SSR snapshots) are deterministic.
 */
export function isNseMarketOpen(now: Date = new Date()): boolean {
  const { weekday, minutesOfDay } = istParts(now)
  if (!NSE_TRADING_DAYS.has(weekday)) return false
  return minutesOfDay >= NSE_OPEN_MIN && minutesOfDay < NSE_CLOSE_MIN
}

export interface NseMarketStatus {
  open: boolean
  /** User-facing pill label. */
  label: "Market Open" | "Market Closed"
  /** Caption for the title/tooltip — declares the holiday blind spot. */
  caption: string
}

/** Resolved status bundle for UI pills. */
export function nseMarketStatus(now: Date = new Date()): NseMarketStatus {
  const open = isNseMarketOpen(now)
  return {
    open,
    label: open ? "Market Open" : "Market Closed",
    caption:
      "NSE regular hours: Mon-Fri 09:15-15:30 IST. Exchange holidays are not tracked.",
  }
}
