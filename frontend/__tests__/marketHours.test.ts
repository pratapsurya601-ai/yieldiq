/**
 * marketHours — deterministic NSE regular-hours checks
 * (feat/alphaspread-style-opening).
 *
 * All fixtures are UTC instants chosen for their IST wall-clock value
 * (IST = UTC+05:30, no DST):
 *   03:44Z → 09:14 IST (one minute before open)
 *   03:45Z → 09:15 IST (session open, inclusive)
 *   06:30Z → 12:00 IST (mid-session)
 *   09:59Z → 15:29 IST (last open minute)
 *   10:00Z → 15:30 IST (session close, exclusive)
 */
import { describe, it, expect } from "vitest"

import { isNseMarketOpen, nseMarketStatus } from "@/lib/marketHours"

// 2026-06-10 is a Wednesday; 2026-06-13 a Saturday; 2026-06-14 a Sunday.
const WED = "2026-06-10"
const SAT = "2026-06-13"
const SUN = "2026-06-14"

describe("isNseMarketOpen — weekday session window (IST)", () => {
  it("is closed one minute before the 09:15 IST open", () => {
    expect(isNseMarketOpen(new Date(`${WED}T03:44:00Z`))).toBe(false)
  })

  it("opens exactly at 09:15 IST (inclusive)", () => {
    expect(isNseMarketOpen(new Date(`${WED}T03:45:00Z`))).toBe(true)
  })

  it("is open mid-session (12:00 IST)", () => {
    expect(isNseMarketOpen(new Date(`${WED}T06:30:00Z`))).toBe(true)
  })

  it("is open during the last session minute (15:29 IST)", () => {
    expect(isNseMarketOpen(new Date(`${WED}T09:59:00Z`))).toBe(true)
  })

  it("closes exactly at 15:30 IST (exclusive)", () => {
    expect(isNseMarketOpen(new Date(`${WED}T10:00:00Z`))).toBe(false)
  })

  it("is closed late evening IST", () => {
    expect(isNseMarketOpen(new Date(`${WED}T16:00:00Z`))).toBe(false)
  })
})

describe("isNseMarketOpen — weekends", () => {
  it("is closed on Saturday even during session hours", () => {
    expect(isNseMarketOpen(new Date(`${SAT}T06:30:00Z`))).toBe(false)
  })

  it("is closed on Sunday even during session hours", () => {
    expect(isNseMarketOpen(new Date(`${SUN}T06:30:00Z`))).toBe(false)
  })
})

describe("isNseMarketOpen — zone independence", () => {
  it("answers from the IST wall clock, not the UTC date", () => {
    // 2026-06-09T20:00Z is still Tuesday in UTC but already
    // 01:30 IST Wednesday — outside the session either way; the
    // key check is that a UTC-evening instant never reads as an
    // IST-morning session.
    expect(isNseMarketOpen(new Date("2026-06-09T20:00:00Z"))).toBe(false)
    // 2026-06-10T04:30Z = 10:00 IST Wednesday — inside the session
    // even though it is early morning UTC.
    expect(isNseMarketOpen(new Date("2026-06-10T04:30:00Z"))).toBe(true)
  })
})

describe("nseMarketStatus — pill bundle", () => {
  it("labels the open state 'Market Open'", () => {
    const s = nseMarketStatus(new Date(`${WED}T06:30:00Z`))
    expect(s.open).toBe(true)
    expect(s.label).toBe("Market Open")
  })

  it("labels the closed state 'Market Closed'", () => {
    const s = nseMarketStatus(new Date(`${SAT}T06:30:00Z`))
    expect(s.open).toBe(false)
    expect(s.label).toBe("Market Closed")
  })

  it("discloses the holiday blind spot in the caption", () => {
    const s = nseMarketStatus(new Date(`${WED}T06:30:00Z`))
    expect(s.caption).toMatch(/holidays are not tracked/i)
    expect(s.caption).toMatch(/09:15-15:30 IST/)
  })
})
