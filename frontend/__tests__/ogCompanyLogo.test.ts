/**
 * Unit tests for the shared OG-image companyLogo helper.
 *
 * Covers the fallback chain:
 *   - unknown ticker → null (no Clearbit hop fired)
 *   - Clearbit 404 → null
 *   - Clearbit timeout → null
 *   - Clearbit 200 → base64 data URL with correct content-type
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

    it("returns null on Clearbit 404 (logo missing for this domain)", async () => {
      globalThis.fetch = vi.fn(async () =>
        new Response(null, { status: 404 }),
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

    it("uses the Clearbit endpoint with the curated domain", async () => {
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
      expect(calledWith).toBe("https://logo.clearbit.com/infosys.com")
    })
  })
})
