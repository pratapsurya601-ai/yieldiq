/**
 * Regression tests for PeerComparisonCard.
 *
 * These guard against the 2026-04-29 hotfix:
 *   1. Backend `/api/v1/public/peers/{t}` originally returned `{ ticker,
 *      peers: [...] }` with NO `has_peers` field, but the (then-future)
 *      stricter consumers expected `data.has_peers`. As a result every
 *      ticker rendered an empty placeholder.
 *   2. Each peer row used `peer_ticker` while newer code paths assumed
 *      `ticker` — silently breaking rendering on shape drift.
 *
 * The tests render two fixtures:
 *   • Legacy shape (no `has_peers`, `peer_ticker` only) — must STILL render.
 *   • New shape (`has_peers: true`, both `ticker` + `peer_ticker`) — must
 *     render and prefer the canonical `ticker`.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import PeerComparisonCard from "@/components/analysis/PeerComparisonCard"
import type { PublicPeersResponse } from "@/lib/api"

const PEER_LEGACY: PublicPeersResponse = {
  ticker: "CAPLIPOINT.NS",
  // NB: no `has_peers`, no `sector_label` — mirrors the pre-fix backend.
  peers: [
    {
      peer_ticker: "ALIVUS",
      rank: 1,
      sector: "Healthcare",
      sub_sector: null,
      mcap_ratio: 1.1,
      company_name: "Alivus Life Sciences",
      fair_value: 850,
      current_price: 720,
      margin_of_safety: 15.3,
      verdict: "undervalued",
      score: 71,
      moat: "Narrow",
      roe: 18.4,
      pe_ratio: 22.1,
    },
    {
      peer_ticker: "COHANCE",
      rank: 2,
      sector: "Healthcare",
      sub_sector: null,
      mcap_ratio: 0.9,
      company_name: "Cohance Lifesciences",
      fair_value: 1200,
      current_price: 1100,
      margin_of_safety: 8.3,
      verdict: "fairly_valued",
      score: 64,
      moat: "Narrow",
      roe: 15.7,
      pe_ratio: 28.4,
    },
  ],
}

const PEER_NEW: PublicPeersResponse = {
  ticker: "CAPLIPOINT.NS",
  has_peers: true,
  sector_label: "Healthcare",
  peers: [
    {
      ticker: "ALIVUS",
      peer_ticker: "ALIVUS",
      rank: 1,
      sector: "Healthcare",
      sub_sector: null,
      mcap_ratio: 1.1,
      company_name: "Alivus Life Sciences",
      fair_value: 850,
      current_price: 720,
      margin_of_safety: 15.3,
      verdict: "undervalued",
      score: 71,
      moat: "Narrow",
      roe: 18.4,
      pe_ratio: 22.1,
    },
  ],
}

describe("PeerComparisonCard", () => {
  it("renders peers when backend omits has_peers (legacy shape)", () => {
    render(<PeerComparisonCard ticker="CAPLIPOINT" data={PEER_LEGACY} />)
    // Real peer rows — not the "Peers not yet ranked" placeholder.
    expect(screen.getByText("ALIVUS")).toBeInTheDocument()
    expect(screen.getByText("COHANCE")).toBeInTheDocument()
    expect(screen.queryByText(/not yet ranked/i)).toBeNull()
  })

  it("renders peers using canonical `ticker` field when present", () => {
    render(<PeerComparisonCard ticker="CAPLIPOINT" data={PEER_NEW} />)
    expect(screen.getByText("ALIVUS")).toBeInTheDocument()
    expect(screen.queryByText(/not yet ranked/i)).toBeNull()
  })

  it("renders the placeholder when peers array is empty", () => {
    render(
      <PeerComparisonCard
        ticker="CAPLIPOINT"
        data={{ ticker: "CAPLIPOINT.NS", has_peers: false, peers: [] }}
      />,
    )
    expect(screen.getByText(/not yet ranked/i)).toBeInTheDocument()
  })

  it("renders the placeholder when data is null (under_review / network error)", () => {
    render(<PeerComparisonCard ticker="CAPLIPOINT" data={null} />)
    expect(screen.getByText(/not yet ranked/i)).toBeInTheDocument()
  })
})
