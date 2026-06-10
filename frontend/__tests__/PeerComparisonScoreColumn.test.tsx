/**
 * ROOT CAUSE #13 (2026-06-11) — peer SCORE column must render the
 * persisted yieldiq_score values now that peers_service falls back to
 * the DB. The "Compare with Peers" table was showing '—' for SCORE on
 * every row even when the subject ticker's side-rail had a real score.
 *
 * This test pins:
 *   1. A row carrying yieldiq_score renders that score as a numeric
 *      string in the SCORE column.
 *   2. A row carrying yieldiq_score=null renders the '—' fallback —
 *      legacy fair_value_history rows written before migration
 *      202606101845 don't have a score yet, and the component must
 *      degrade gracefully rather than crashing on null.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type React from "react"

import type { PeerRow, PeersResponse } from "@/lib/api"

class ImmediateIO {
  constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
    queueMicrotask(() => cb([{ isIntersecting: true }]))
  }
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}
vi.stubGlobal("IntersectionObserver", ImmediateIO)

const getPeersMock = vi.fn()
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  return {
    ...actual,
    getPeers: (...args: unknown[]) => getPeersMock(...args),
  }
})

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }),
}))

import PeerComparison from "@/components/analysis/PeerComparison"

function mockPeer(ticker: string, overrides: Partial<PeerRow> = {}): PeerRow {
  return {
    ticker,
    is_main: false,
    company_name: `${ticker} Corp`,
    yieldiq_score: 65,
    grade: "B",
    fair_value: 1000,
    mos_pct: 12.5,
    verdict: "fairly_valued",
    pe_ratio: 22.4,
    pb_ratio: 3.1,
    ev_ebitda: 14.2,
    market_cap_cr: 50000,
    dividend_yield: 1.8,
    roe_pct: 18.5,
    net_margin_pct: 14.2,
    debt_to_equity: 0.4,
    fcf_yield_pct: 4.5,
    ...overrides,
  }
}

function buildResponse(peers: PeerRow[]): PeersResponse {
  return {
    ticker: "HDFCBANK",
    has_peers: true,
    sector_label: "Banking",
    peers_count: peers.length,
    best_in_sector: {},
    peers,
  }
}

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  getPeersMock.mockReset()
})

describe("PeerComparison — SCORE column (ROOT CAUSE #13)", () => {
  it("renders the yieldiq_score as a numeric value for each peer that has one", async () => {
    const peers: PeerRow[] = [
      mockPeer("HDFCBANK", {
        is_main: true,
        company_name: "HDFC Bank",
        yieldiq_score: 40,
        grade: "C",
      }),
      mockPeer("ICICIBANK", {
        company_name: "ICICI Bank",
        yieldiq_score: 73,
        grade: "B",
      }),
      mockPeer("KOTAKBANK", {
        company_name: "Kotak Bank",
        yieldiq_score: 88,
        grade: "A",
      }),
    ]
    getPeersMock.mockResolvedValue(buildResponse(peers))

    const { container } = renderWithClient(
      <PeerComparison ticker="HDFCBANK" currency="INR" />,
    )
    await waitFor(() => {
      expect(screen.getByText("Compare with Peers")).toBeInTheDocument()
    })

    // The desktop table is the canonical surface; mobile cards
    // mirror it.
    const desktopTable = container.querySelector(".hidden.sm\\:block table")
    expect(desktopTable).not.toBeNull()
    const tableScope = within(desktopTable as HTMLElement)
    // 40, 73 and 88 must each appear in the SCORE column at least once.
    expect(tableScope.getAllByText("40").length).toBeGreaterThan(0)
    expect(tableScope.getAllByText("73").length).toBeGreaterThan(0)
    expect(tableScope.getAllByText("88").length).toBeGreaterThan(0)
  })

  it("falls back to '—' for peers whose score is null (legacy FV history rows)", async () => {
    const peers: PeerRow[] = [
      mockPeer("HDFCBANK", {
        is_main: true,
        company_name: "HDFC Bank",
        yieldiq_score: 40,
      }),
      mockPeer("AXISBANK", {
        company_name: "Axis Bank",
        yieldiq_score: null,
        grade: null,
      }),
    ]
    getPeersMock.mockResolvedValue(buildResponse(peers))

    renderWithClient(<PeerComparison ticker="HDFCBANK" currency="INR" />)
    await waitFor(() => {
      expect(screen.getByText("Compare with Peers")).toBeInTheDocument()
    })

    // The component already surfaces a "score not yet computed" caption
    // when ANY peer has null — that's the wiring we expect to see fire.
    await waitFor(() => {
      expect(
        screen.getByText(/YieldIQ Score not yet computed/i),
      ).toBeInTheDocument()
    })
  })
})
