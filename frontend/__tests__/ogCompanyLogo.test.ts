/**
 * Unit tests for the shared OG-image companyLogo helper.
 *
 * Covers the post-2026-06-07-hotfix fallback chain:
 *   - unknown ticker → null (no Google favicon hop fired)
 *   - Google favicon 404 → null
 *   - Google favicon timeout → null
 *   - Google favicon 200 but non-image content-type → null
 *     (defends against the Brandfetch HTML-preview failure mode)
 *   - Google favicon 200 → base64 data URL with correct content-type
 *   - Helper NEVER targets `logo.clearbit.com`
 *
 * The full ImageResponse render isn't covered here — Satori runs on
 * the edge runtime which vitest's jsdom env doesn't emulate. The
 * post-merge `og_health` GH Actions workflow verifies live OG PNGs
 * end-to-end.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  NSE_TICKER_DOMAINS,
  cleanTickerForLogo,
  fetchCompanyLogoDataUrl,
  getCuratedDomain,
} from "@/app/api/og/_lib/companyLogo"

describe("companyLogo helpers", () => {
  describe("cleanTickerForLogo", () => {
    it("uppercases", () => {
      expect(cleanTickerForLogo("infy")).toBe("INFY")
    })
    it("strips .NS / .BO / .NSE / .BSE", () => {
      expect(cleanTickerForLogo("HDFCBANK.NS")).toBe("HDFCBANK")
      expect(cleanTickerForLogo("RELIANCE.BO")).toBe("RELIANCE")
      expect(cleanTickerForLogo("tcs.nse")).toBe("TCS")
      expect(cleanTickerForLogo("INFY.BSE")).toBe("INFY")
    })
    it("is null-safe", () => {
      expect(cleanTickerForLogo("")).toBe("")
      // @ts-expect-error — explicit nullable input
      expect(cleanTickerForLogo(undefined)).toBe("")
    })
  })

  describe("getCuratedDomain", () => {
    it("returns the curated domain for known tickers", () => {
      expect(getCuratedDomain("HDFCBANK")).toBe("hdfcbank.com")
      expect(getCuratedDomain("hdfcbank.ns")).toBe("hdfcbank.com")
      expect(getCuratedDomain("INFY")).toBe("infosys.com")
    })
    it("returns null for tickers not in the curated 50", () => {
      expect(getCuratedDomain("UNKNOWNCO")).toBeNull()
      expect(getCuratedDomain("ZZZ.NS")).toBeNull()
    })
    it("curated map size is exactly 50 entries (rule: do not silently extend)", () => {
      expect(Object.keys(NSE_TICKER_DOMAINS).length).toBe(50)
    })
  })

  describe("fetchCompanyLogoDataUrl", () => {
    const realFetch = globalThis.fetch

    beforeEach(() => {
      vi.restoreAllMocks()
    })
    afterEach(() => {
      globalThis.fetch = realFetch
    })

    it("returns null when ticker not in curated map (no fetch fired)", async () => {
      const spy = vi.fn()
      globalThis.fetch = spy as unknown as typeof fetch
      const result = await fetchCompanyLogoDataUrl("UNKNOWNCO")
      expect(result).toBeNull()
      expect(spy).not.toHaveBeenCalled()
    })

    it("returns null on Google favicon 404 (logo missing for this domain)", async () => {
      globalThis.fetch = vi.fn(async () =>
        new Response(null, { status: 404 }),
      ) as unknown as typeof fetch
      const result = await fetchCompanyLogoDataUrl("HDFCBANK")
      expect(result).toBeNull()
    })

    it("returns null when the response is text/html (defends against the Brandfetch HTML-preview failure mode)", async () => {
      globalThis.fetch = vi.fn(
        async () =>
          new Response("<html>not an image</html>", {
            status: 200,
            headers: { "content-type": "text/html" },
          }),
      ) as unknown as typeof fetch
      const result = await fetchCompanyLogoDataUrl("HDFCBANK")
      expect(result).toBeNull()
    })

    it("returns null when fetch throws (simulated timeout / network)", async () => {
      globalThis.fetch = vi.fn(async () => {
        throw new DOMException("aborted", "AbortError")
      }) as unknown as typeof fetch
      const result = await fetchCompanyLogoDataUrl("INFY")
      expect(result).toBeNull()
    })

    it("returns null when response body is empty", async () => {
      globalThis.fetch = vi.fn(
        async () =>
          new Response(new ArrayBuffer(0), {
            status: 200,
            headers: { "content-type": "image/png" },
          }),
      ) as unknown as typeof fetch
      const result = await fetchCompanyLogoDataUrl("HDFCBANK")
      expect(result).toBeNull()
    })

    it("returns a base64 data URL on 200 with bytes", async () => {
      // Three bytes (1, 2, 3) → base64 "AQID".
      const bytes = new Uint8Array([1, 2, 3])
      globalThis.fetch = vi.fn(
        async () =>
          new Response(bytes, {
            status: 200,
            headers: { "content-type": "image/png" },
          }),
      ) as unknown as typeof fetch
      const result = await fetchCompanyLogoDataUrl("HDFCBANK")
      expect(result).toBe("data:image/png;base64,AQID")
    })

    it("uses the Google s2/favicons endpoint with the curated domain (NOT the dead Clearbit URL)", async () => {
      const spy = vi.fn(
        async () =>
          new Response(new Uint8Array([0]), {
            status: 200,
            headers: { "content-type": "image/png" },
          }),
      )
      globalThis.fetch = spy as unknown as typeof fetch
      await fetchCompanyLogoDataUrl("INFY.NS")
      expect(spy).toHaveBeenCalledTimes(1)
      // spy.mock.calls is inferred as a parameterless tuple under
      // strict types; cast to a permissive shape so we can assert
      // the URL the helper passed to fetch.
      const calls = spy.mock.calls as unknown as Array<unknown[]>
      const calledWith = calls[0]?.[0] as string | undefined
      expect(calledWith).toBe(
        "https://www.google.com/s2/favicons?domain=infosys.com&sz=128",
      )
      // Hotfix invariant: the dead Clearbit URL is never emitted.
      expect(calledWith).not.toMatch(/logo\.clearbit\.com/)
    })
  })
})
