/**
 * Unit tests for `frontend/scripts/fetch-logos-logodev.mjs`.
 *
 * We do NOT hit the real Logo.dev endpoint here — that would be flaky
 * and would burn the user's free-tier quota on every CI run. Instead we
 * inject a fake `fetchImpl` and capture every call the orchestrator
 * makes, then assert on:
 *
 *   - the URL shape (token + size + format)
 *   - filename sanitisation (`&`→`_AND_`, `-`→`_`)
 *   - the retry-once-on-500 behaviour
 *   - per-status classification (saved / placeholder / too_small)
 *   - manifest contents
 *
 * Per `vitest.config.ts`, the include pattern is `__tests__/**` so this
 * file lives next to the React component tests rather than under
 * `scripts/__tests__/`.
 */
import { describe, it, expect, vi } from "vitest"

// .mjs export has no .d.ts; relax the inferred types here so the
// helper assertions don't fight strict TS.
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore - .mjs export, no .d.ts
import * as fetchLogos from "../scripts/fetch-logos-logodev.mjs"

/* eslint-disable @typescript-eslint/no-explicit-any */
const runFetch: any = fetchLogos.runFetch
const fetchOne: any = fetchLogos.fetchOne
const tickerToFsSafe: (s: string) => string = fetchLogos.tickerToFsSafe
/* eslint-enable @typescript-eslint/no-explicit-any */

/** Build a fake `Response` that matches the bits of the Fetch API we use. */
function fakeResponse({
  status = 200,
  contentType = "image/png",
  bodyBytes = 4096,
} = {}) {
  const buf = new Uint8Array(bodyBytes).fill(42).buffer
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (k: string) => (k.toLowerCase() === "content-type" ? contentType : null) },
    arrayBuffer: async () => buf,
  }
}

describe("tickerToFsSafe", () => {
  it("rewrites & to _AND_", () => {
    expect(tickerToFsSafe("M&M")).toBe("M_AND_M")
    expect(tickerToFsSafe("M&MFIN")).toBe("M_AND_MFIN")
  })

  it("rewrites - to _", () => {
    expect(tickerToFsSafe("BAJAJ-AUTO")).toBe("BAJAJ_AUTO")
    expect(tickerToFsSafe("NAM-INDIA")).toBe("NAM_INDIA")
  })

  it("leaves plain tickers untouched", () => {
    expect(tickerToFsSafe("HDFCBANK")).toBe("HDFCBANK")
    expect(tickerToFsSafe("TCS")).toBe("TCS")
  })
})

describe("fetchOne", () => {
  it("hits the canonical Logo.dev URL with size=192 and format=png", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(fakeResponse())
    await fetchOne("hdfcbank.com", { fetchImpl })
    expect(fetchImpl).toHaveBeenCalledOnce()
    const url = fetchImpl.mock.calls[0][0]
    expect(url).toContain("https://img.logo.dev/hdfcbank.com")
    expect(url).toContain("size=192")
    expect(url).toContain("format=png")
    expect(url).toContain("token=pk_")
  })

  it("classifies HTTP 200 + image/png + >2KB as saved", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(fakeResponse({ bodyBytes: 8000 }))
    const r = await fetchOne("tcs.com", { fetchImpl })
    expect(r.ok).toBe(true)
    expect(r.status).toBe("saved")
    expect(r.bytes).toBe(8000)
  })

  it("classifies HTTP 202 as placeholder and does not retry", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(fakeResponse({ status: 202 }))
    const r = await fetchOne("unknown.example", { fetchImpl })
    expect(r.ok).toBe(false)
    expect(r.status).toBe("placeholder")
    expect(fetchImpl).toHaveBeenCalledOnce()
  })

  it("classifies HTTP 200 + image/png + <2KB as too_small", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(fakeResponse({ bodyBytes: 512 }))
    const r = await fetchOne("tiny.example", { fetchImpl })
    expect(r.ok).toBe(false)
    expect(r.status).toBe("too_small")
  })

  it("retries once on HTTP 500 and succeeds on the second attempt", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(fakeResponse({ status: 500 }))
      .mockResolvedValueOnce(fakeResponse({ bodyBytes: 5000 }))
    const r = await fetchOne("flaky.example", { fetchImpl })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(r.ok).toBe(true)
  })

  it("retries once on a thrown network error and gives up after the second attempt", async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new Error("ECONNRESET"))
      .mockRejectedValueOnce(new Error("ECONNRESET"))
    const r = await fetchOne("broken.example", { fetchImpl })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(r.ok).toBe(false)
    expect(r.status).toBe("network")
  })

  it("rejects responses with a non-image content-type", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(fakeResponse({ contentType: "text/html" }))
    const r = await fetchOne("html.example", { fetchImpl })
    expect(r.ok).toBe(false)
    expect(r.status).toBe("bad_type")
  })
})

describe("runFetch", () => {
  it("iterates the domain map, skips _meta, writes sanitised filenames, and produces a manifest summary", async () => {
    const domains = {
      _meta: { ignored: true },
      HDFCBANK: "hdfcbank.com",
      "M&M": "mahindra.com",
      "BAJAJ-AUTO": "bajajauto.com",
      PLACEHOLDER: "no-logo.example",
    }
    const fetchImpl = vi.fn(async (url: string) => {
      if (url.includes("no-logo.example")) return fakeResponse({ status: 202 })
      return fakeResponse({ bodyBytes: 5000 })
    })
    const writeFileImpl = vi.fn(async () => undefined)
    const mkdirImpl = vi.fn(async () => undefined)

    const { manifest, summary } = await runFetch({
      domains,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      writeFileImpl,
      mkdirImpl,
      outDir: "/tmp/logos",
      manifestPath: "/tmp/logos/_manifest.json",
      rateLimitMs: 0,
      logger: { log: () => undefined } as unknown as Console,
    })

    // Three real fetches (HDFCBANK, M&M, BAJAJ-AUTO, PLACEHOLDER), four total.
    expect(summary.total).toBe(4)
    expect(summary.saved).toBe(3)
    expect(summary.placeholder).toBe(1)

    // _meta was skipped from iteration.
    expect(manifest._meta).toBeUndefined()

    // Filename sanitisation reached the writer. `mock.calls` typing
    // varies by vi version; cast to a permissive shape we control.
    const calls = writeFileImpl.mock.calls as unknown as Array<[unknown, unknown]>
    const writePaths = calls.map((c) => String(c[0]))
    expect(writePaths.some((p) => p.endsWith("HDFCBANK.png"))).toBe(true)
    expect(writePaths.some((p) => p.endsWith("M_AND_M.png"))).toBe(true)
    expect(writePaths.some((p) => p.endsWith("BAJAJ_AUTO.png"))).toBe(true)

    // Manifest was written last with the right shape.
    const manifestCall = calls.find((c) =>
      String(c[0]).endsWith("_manifest.json"),
    )
    expect(manifestCall).toBeDefined()
    const written = JSON.parse(String(manifestCall![1]))
    expect(written._meta.summary.saved).toBe(3)
    expect(written.logos.HDFCBANK.status).toBe("saved")
    expect(written.logos.HDFCBANK.filename).toBe("HDFCBANK.png")
    expect(written.logos.PLACEHOLDER.status).toBe("placeholder")
    expect(written.logos["M&M"].filename).toBe("M_AND_M.png")
  })

  it("retries on the first 500 then writes the PNG when the retry succeeds", async () => {
    const domains = { HDFCBANK: "hdfcbank.com" }
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(fakeResponse({ status: 500 }))
      .mockResolvedValueOnce(fakeResponse({ bodyBytes: 5000 }))
    const writeFileImpl = vi.fn(async () => undefined)

    const { summary } = await runFetch({
      domains,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      writeFileImpl,
      mkdirImpl: async () => undefined,
      outDir: "/tmp/logos",
      manifestPath: "/tmp/logos/_manifest.json",
      rateLimitMs: 0,
      logger: { log: () => undefined } as unknown as Console,
    })

    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(summary.saved).toBe(1)
  })
})
