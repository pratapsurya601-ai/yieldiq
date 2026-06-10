/**
 * PeerComparison — mobile-card fallback pin.
 *
 * Mobile audit Issue 6 (P1): PeerComparison had no mobile branch, so a
 * 9-column wide table forced horizontal scroll on phones (whereas its
 * sibling InlinePeerComparison already shipped a sm:hidden stacked-card
 * fallback). This file pins that PeerComparison now renders BOTH:
 *
 *   1. A mobile container (sm:hidden) with one button per peer row.
 *   2. The existing table container hidden behind hidden sm:block.
 *
 * Both containers receive the same `rows` so on a layout-test pass
 * each peer's ticker symbol is rendered in the DOM twice (once per
 * container) — that's the cheapest invariant to assert on without
 * brittle layout-class plumbing.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type React from "react"

import type { PeerRow, PeersResponse } from "@/lib/api"

// jsdom IntersectionObserver stub — fire immediately so the deferred
// fetch path doesn't strand the test in the skeleton.
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

describe("PeerComparison — mobile card fallback", () => {
  it("renders both a mobile-card container (sm:hidden) and the desktop table (hidden sm:block)", async () => {
    const peers: PeerRow[] = [
      mockPeer("HDFCBANK", { is_main: true, company_name: "HDFC Bank" }),
      mockPeer("ICICIBANK", { company_name: "ICICI Bank", mos_pct: 8.4 }),
      mockPeer("KOTAKBANK", { company_name: "Kotak Bank", mos_pct: -5.1 }),
    ]
    getPeersMock.mockResolvedValue(buildResponse(peers))

    const { container } = renderWithClient(
      <PeerComparison ticker="HDFCBANK" currency="INR" />,
    )

    // Wait for the "Compare with Peers" heading to settle, i.e. the
    // success branch.
    await waitFor(() => {
      expect(screen.getByText("Compare with Peers")).toBeInTheDocument()
    })

    // Mobile container — first child div with `sm:hidden` and the
    // stacked button rows.
    const mobileContainer = container.querySelector(".sm\\:hidden.space-y-2")
    expect(mobileContainer).not.toBeNull()
    const mobileButtons = mobileContainer?.querySelectorAll("button")
    expect(mobileButtons?.length).toBe(3)

    // Desktop table container.
    const desktopContainer = container.querySelector(".hidden.sm\\:block")
    expect(desktopContainer).not.toBeNull()
    expect(desktopContainer?.querySelector("table")).not.toBeNull()

    // Subject row's main-ticker disabled state on the mobile card.
    const mainBtn = mobileContainer?.querySelector("button[disabled]")
    expect(mainBtn).not.toBeNull()
    expect(mainBtn?.textContent).toContain("HDFCBANK")
  })
})
