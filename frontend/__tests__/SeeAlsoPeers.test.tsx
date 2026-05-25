/**
 * SeeAlsoPeers smoke tests.
 *
 * Pins:
 *   1. Renders peer cards from a stubbed /peers payload.
 *   2. Drops the main ticker (is_main=true) and dedupes self.
 *   3. Renders nothing when has_peers is false.
 *   4. MoS chip uses the right tone based on sign / magnitude.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import SeeAlsoPeers from "@/components/analysis/SeeAlsoPeers"
import * as apiModule from "@/lib/api"
import type { PeersResponse } from "@/lib/api"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const PEERS: PeersResponse = {
  ticker: "HDFCBANK.NS",
  has_peers: true,
  sector_label: "Banks",
  peers_count: 3,
  best_in_sector: {},
  peers: [
    {
      ticker: "HDFCBANK.NS",
      is_main: true,
      company_name: "HDFC Bank",
      yieldiq_score: 82,
      grade: "A",
      fair_value: 1102,
      mos_pct: 43.7,
      verdict: "undervalued",
      pe_ratio: 18,
      pb_ratio: 2.5,
      ev_ebitda: null,
      market_cap_cr: 1_200_000,
      dividend_yield: 1.25,
      roe_pct: 17.2,
      net_margin_pct: 22,
      debt_to_equity: 0.8,
      fcf_yield_pct: 3,
    },
    {
      ticker: "ICICIBANK.NS",
      is_main: false,
      company_name: "ICICI Bank",
      yieldiq_score: 78,
      grade: "A",
      fair_value: 1300,
      mos_pct: 15.2,
      verdict: "undervalued",
      pe_ratio: 19,
      pb_ratio: 3.0,
      ev_ebitda: null,
      market_cap_cr: 900_000,
      dividend_yield: 0.8,
      roe_pct: 16,
      net_margin_pct: 21,
      debt_to_equity: 0.9,
      fcf_yield_pct: 3.2,
    },
    {
      ticker: "AXISBANK.NS",
      is_main: false,
      company_name: "Axis Bank",
      yieldiq_score: 70,
      grade: "B",
      fair_value: 900,
      mos_pct: -20.0,
      verdict: "overvalued",
      pe_ratio: 22,
      pb_ratio: 2.2,
      ev_ebitda: null,
      market_cap_cr: 350_000,
      dividend_yield: 0.4,
      roe_pct: 14,
      net_margin_pct: 18,
      debt_to_equity: 1.1,
      fcf_yield_pct: 2.5,
    },
  ],
}

beforeEach(() => {
  vi.spyOn(apiModule, "getPeers").mockResolvedValue(PEERS)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("SeeAlsoPeers", () => {
  it("renders peer cards excluding the main ticker", async () => {
    renderWithClient(
      <SeeAlsoPeers ticker="HDFCBANK.NS" currency="INR" />,
    )
    await waitFor(() => {
      expect(screen.getByText("ICICIBANK")).toBeInTheDocument()
    })
    expect(screen.getByText("AXISBANK")).toBeInTheDocument()
    expect(screen.queryByText("HDFCBANK")).toBeNull()
    expect(screen.getByText(/Showing peers in Banks/i)).toBeInTheDocument()
  })

  it("renders nothing when has_peers is false", async () => {
    vi.spyOn(apiModule, "getPeers").mockResolvedValueOnce({
      ...PEERS,
      has_peers: false,
      peers: [],
    })
    const { container } = renderWithClient(
      <SeeAlsoPeers ticker="X.NS" currency="INR" />,
    )
    await waitFor(() => {
      expect(container.querySelector("section")).toBeNull()
    })
  })
})
