/**
 * MutualFundHoldersPanel smoke tests.
 *
 * Pins these behaviours:
 *   1. Empty path (the current production state — MF Phase 2 of
 *      the pipeline has not landed): when the endpoint returns
 *      ``{available: false, top_mf_holders: []}``, the panel
 *      renders the documented empty-state copy and does NOT
 *      render the holders table.
 *   2. Populated path: when the endpoint returns rows, the table
 *      renders one row per scheme with scheme name, AMC, AUM,
 *      pct of fund AUM, and a QoQ change badge.
 *   3. Trend insight: a net-positive QoQ delta produces an
 *      "added net INR ..." sentence; net-negative produces a
 *      "reducing position" sentence.
 *
 * The component fetches via the global ``fetch`` so tests stub
 * window.fetch per-case.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"

import MutualFundHoldersPanel from "@/components/analysis/MutualFundHoldersPanel"

function mockFetchOnce(payload: unknown, ok = true) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok,
    json: async () => payload,
  })
  // @ts-expect-error — test override of the global fetch is intentional.
  global.fetch = fetchMock
  return fetchMock
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("MutualFundHoldersPanel", () => {
  it("renders the documented empty state when available=false", async () => {
    mockFetchOnce({
      ticker: "RELIANCE",
      top_mf_holders: [],
      total_mf_holding_cr: null,
      total_mf_holding_pct: null,
      net_qoq_change_cr: null,
      as_of: null,
      available: false,
    })

    render(<MutualFundHoldersPanel ticker="RELIANCE" />)

    await waitFor(() => {
      expect(
        screen.getByText(/MF holding data refreshes monthly/i),
      ).toBeTruthy()
    })
    // No table rendered in the empty path.
    expect(screen.queryByRole("table")).toBeNull()
  })

  it("renders ranked holders with trend insight when populated (net positive)", async () => {
    mockFetchOnce({
      ticker: "RELIANCE",
      top_mf_holders: [
        {
          scheme_code: "118989",
          scheme_name: "HDFC Flexi Cap",
          amc: "HDFC Mutual Fund",
          aum_in_stock_cr: 1240,
          pct_of_aum: 4.2,
          qoq_change_cr: 80,
          qoq_change_label: "added",
          as_of: "2026-04-30",
        },
        {
          scheme_code: "118990",
          scheme_name: "SBI Bluechip",
          amc: "SBI Mutual Fund",
          aum_in_stock_cr: 980,
          pct_of_aum: 3.1,
          qoq_change_cr: 420,
          qoq_change_label: "added",
          as_of: "2026-04-30",
        },
      ],
      total_mf_holding_cr: 2220,
      total_mf_holding_pct: 5.8,
      net_qoq_change_cr: 500,
      as_of: "2026-04-30",
      available: true,
    })

    render(<MutualFundHoldersPanel ticker="RELIANCE" />)

    await waitFor(() => {
      expect(screen.getByRole("table")).toBeTruthy()
    })

    // Scheme rows render.
    expect(screen.getByText("HDFC Flexi Cap")).toBeTruthy()
    expect(screen.getByText("SBI Bluechip")).toBeTruthy()
    // AMC labels render under scheme names.
    expect(screen.getByText("HDFC Mutual Fund")).toBeTruthy()
    // Trend insight: net positive → "added net ..." phrasing.
    expect(
      screen.getByText(/MFs added net/i),
    ).toBeTruthy()
    // Empty-state copy must NOT appear.
    expect(
      screen.queryByText(/MF holding data refreshes monthly/i),
    ).toBeNull()
  })

  it("renders 'reducing position' trend when net QoQ is negative", async () => {
    mockFetchOnce({
      ticker: "TCS",
      top_mf_holders: [
        {
          scheme_code: "200001",
          scheme_name: "Mirae Asset Large Cap",
          amc: "Mirae Asset",
          aum_in_stock_cr: 600,
          pct_of_aum: 2.0,
          qoq_change_cr: -150,
          qoq_change_label: "reduced",
          as_of: "2026-04-30",
        },
      ],
      total_mf_holding_cr: 600,
      total_mf_holding_pct: 3.1,
      net_qoq_change_cr: -300,
      as_of: "2026-04-30",
      available: true,
    })

    render(<MutualFundHoldersPanel ticker="TCS" />)

    await waitFor(() => {
      expect(
        screen.getByText(/reducing position/i),
      ).toBeTruthy()
    })
  })

  it("renders empty state on fetch error", async () => {
    // @ts-expect-error — test override
    global.fetch = vi.fn().mockRejectedValue(new Error("network"))

    render(<MutualFundHoldersPanel ticker="RELIANCE" />)

    await waitFor(() => {
      expect(
        screen.getByText(/MF holding data refreshes monthly/i),
      ).toBeTruthy()
    })
  })
})
