/**
 * Smoke test for the self-hosted logo corpus under
 * `frontend/public/logos/`.
 *
 * Locks two invariants that would otherwise silently regress:
 *   1. A handful of bellwether tickers (HDFCBANK, TCS, RELIANCE,
 *      M_AND_M, BAJAJ_AUTO) ALWAYS have a real PNG on disk. If
 *      someone deletes `/public/logos/HDFCBANK.png` we want the
 *      build to fail, not the avatar chip to silently fall back to
 *      the lower-res Google favicon.
 *   2. `_manifest.json` exists, is valid JSON, and records at least
 *      700 saved entries (post NIFTY 501-1000 expansion the Logo.dev
 *      fetch lands ~720-820/980; the 700 threshold leaves headroom for
 *      tickers flipping in and out of placeholder coverage over
 *      time).
 *
 * This test reads `public/` directly rather than fetching over HTTP,
 * so it's a pure-Node check that runs fast in CI without a live
 * server.
 */
import { describe, it, expect } from "vitest"
import { existsSync, readFileSync, statSync } from "node:fs"
import { resolve } from "node:path"

const LOGOS_DIR = resolve(__dirname, "../public/logos")

describe("self-hosted logo corpus", () => {
  it.each(["HDFCBANK", "TCS", "RELIANCE", "INFY", "M_AND_M", "BAJAJ_AUTO"])(
    "has a real PNG on disk for %s",
    (fsSafeTicker) => {
      const path = resolve(LOGOS_DIR, `${fsSafeTicker}.png`)
      expect(existsSync(path)).toBe(true)
      // Must exceed the 2KB min that the fetch script enforced.
      const size = statSync(path).size
      expect(size).toBeGreaterThan(2048)
    },
  )

  it("has a valid _manifest.json with at least 700 saved entries", () => {
    const manifestPath = resolve(LOGOS_DIR, "_manifest.json")
    expect(existsSync(manifestPath)).toBe(true)
    const raw = readFileSync(manifestPath, "utf8")
    const parsed = JSON.parse(raw)
    expect(parsed._meta).toBeDefined()
    expect(parsed._meta.source).toMatch(/logo\.dev/i)
    expect(parsed._meta.summary.saved).toBeGreaterThanOrEqual(700)
  })
})
