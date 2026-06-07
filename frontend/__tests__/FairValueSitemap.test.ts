/**
 * Sitemap test for the programmatic SEO content experiment.
 *
 * Asserts that all 12 curated fair-value URLs are emitted by the
 * sitemap builder so Search Console picks them up on the next
 * fetch. Network calls in the builder are mocked to return empty
 * payloads — we are only asserting the static-list contribution.
 */

import { describe, it, expect, beforeEach, vi } from "vitest"

import { FAIR_VALUE_TICKERS } from "@/app/(marketing)/fair-value/tickers"

describe("sitemap — fair-value content-experiment URLs", () => {
  beforeEach(() => {
    // Stub fetch so the tickers / funds API calls don't fan out to
    // the live backend in CI.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [],
      } as unknown as Response),
    )
  })

  it("emits every curated fair-value ticker as a sitemap entry", async () => {
    const mod = await import("@/app/sitemap")
    const entries = await mod.default()
    const urls = new Set(entries.map((e) => e.url))
    for (const config of FAIR_VALUE_TICKERS) {
      const expected = `https://yieldiq.in/fair-value/${encodeURIComponent(config.ticker)}`
      expect(urls.has(expected)).toBe(true)
    }
  })

  it("flags the fair-value entries with weekly cadence + 0.7 priority", async () => {
    const mod = await import("@/app/sitemap")
    const entries = await mod.default()
    const fvEntries = entries.filter((e) =>
      e.url.startsWith("https://yieldiq.in/fair-value/"),
    )
    expect(fvEntries.length).toBeGreaterThanOrEqual(FAIR_VALUE_TICKERS.length)
    for (const e of fvEntries) {
      expect(e.changeFrequency).toBe("weekly")
      expect(e.priority).toBe(0.7)
    }
  })
})
