/**
 * Phase 1 — Fair-Value History TS client smoke test (Agent D).
 *
 * Verifies `getValuationHistory("TCS")` returns the empty-shape
 * contract from Agent B's stub. The axios instance is intercepted
 * via `vi.mock("axios")` so the test is hermetic (no network).
 *
 * SEBI-clean: this file contains no banned vocabulary in
 * comments, docstrings, or test data.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"

const getMock = vi.fn()

vi.mock("axios", () => {
  const instance = {
    get: (...args: unknown[]) => getMock(...args),
    post: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    defaults: { headers: { common: {} } },
  }
  const axios = {
    create: () => instance,
    get: instance.get,
    post: instance.post,
    delete: instance.delete,
    patch: instance.patch,
  }
  return { default: axios, ...axios }
})

describe("getValuationHistory", () => {
  beforeEach(() => {
    getMock.mockReset()
  })

  it("returns the empty-shape contract from the stub", async () => {
    const mockResp = {
      ticker: "TCS",
      points: [],
      annotations: [],
      starts_at: null,
      points_count: 0,
      is_sparse: true,
    }
    getMock.mockResolvedValue({ data: mockResp })

    const { getValuationHistory } = await import("@/lib/api")
    const out = await getValuationHistory("TCS")

    expect(out.ticker).toBe("TCS")
    expect(out.points).toEqual([])
    expect(out.annotations).toEqual([])
    expect(out.starts_at).toBeNull()
    expect(out.points_count).toBe(0)
    expect(out.is_sparse).toBe(true)
    expect(getMock).toHaveBeenCalledWith("/api/valuation-history/TCS")
  })

  it("hits the canonical path for any ticker", async () => {
    getMock.mockResolvedValue({
      data: {
        ticker: "INFY",
        points: [],
        annotations: [],
        starts_at: null,
        points_count: 0,
        is_sparse: true,
      },
    })

    const { getValuationHistory } = await import("@/lib/api")
    await getValuationHistory("INFY")

    expect(getMock).toHaveBeenCalledWith("/api/valuation-history/INFY")
  })
})
