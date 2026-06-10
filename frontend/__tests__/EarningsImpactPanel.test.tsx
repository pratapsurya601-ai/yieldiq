/**
 * EarningsImpactPanel — ROOT CAUSE #8 suppression tests.
 *
 * Covers the M&A-distortion path added 2026-06-11:
 *   * When the backend returns `ma_distortion_flag=true`, the panel
 *     renders the suppression copy (testid
 *     `earnings-impact-ma-suppressed-body`) and hides the surprise %
 *     + range numbers.
 *   * When the backend returns a normal payload, the legacy numeric
 *     surprise / range path renders.
 *
 * Strategy: monkeypatch the global `fetch` so the panel resolves with
 * deterministic payloads. The component does its own
 * useEffect-driven fetch, so we don't need to mock the React Query
 * cache.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"

import EarningsImpactPanel from "@/components/analysis/EarningsImpactPanel"

const SUPPRESSED_PAYLOAD = {
  ticker: "HDFCBANK",
  impact: {
    latest_quarter: {
      period_end: "2024-03-31",
      revenue_cr: 87_183,
      net_profit_cr: 16_512,
    },
    baseline: {
      kind: "yoy",
      period_end: "2023-03-31",
      revenue_cr: 41_000,
    },
    expected_revenue_cr: 102_400,
    surprise_pct: null,
    sector: "Bank",
    sector_multiplier: 0.7,
    implied_growth_used: 0.1,
    fv_delta_estimate: null,
    fv_delta_range: null,
    notes: [],
    method: "heuristic_v1",
    is_heuristic: true,
    ma_distortion_flag: true,
  },
  is_heuristic: true,
  ma_distortion_flag: true,
  ma_event: {
    event_date: "2023-07-01",
    event_type: "REVERSE_MERGER",
    magnitude_pct: 100,
    multiplier: 2.0,
    normalization_window_quarters: 8,
    quarters_since_event: 3,
    description:
      "Reverse merger — HDFC Ltd parent absorbed into HDFC Bank.",
    source_url: "https://example.sebi.gov.in/filing",
    source_doc: "RBI/SEBI joint approval",
    is_within_normalization_window: true,
  },
  suppression_copy:
    "Baseline distorted by structural M&A event on 2023-07-01. YoY comparison resumes Q1 FY26 (8 quarters post-event).",
}

const NORMAL_PAYLOAD = {
  ticker: "TCS",
  impact: {
    latest_quarter: {
      period_end: "2024-03-31",
      revenue_cr: 62_613,
      net_profit_cr: 12_434,
    },
    baseline: {
      kind: "yoy",
      period_end: "2023-03-31",
      revenue_cr: 59_162,
    },
    expected_revenue_cr: 65_078,
    surprise_pct: -0.0379,
    sector: "IT Services",
    sector_multiplier: 1.2,
    implied_growth_used: 0.1,
    fv_delta_estimate: -0.0136,
    fv_delta_range: { low: -0.0336, high: 0.0064 },
    notes: [],
    method: "heuristic_v1",
    is_heuristic: true,
  },
  is_heuristic: true,
  ma_distortion_flag: false,
  ma_event: null,
  suppression_copy: null,
}

function mockFetch(payload: unknown) {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(payload),
  } as unknown as Response)
}

describe("EarningsImpactPanel — ROOT CAUSE #8 suppression", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it("renders the suppression body when ma_distortion_flag=true", async () => {
    mockFetch(SUPPRESSED_PAYLOAD)
    render(<EarningsImpactPanel ticker="HDFCBANK" />)

    // Wait until the suppression body lands.
    const body = await screen.findByTestId(
      "earnings-impact-ma-suppressed-body",
    )
    expect(body).toBeInTheDocument()
    expect(body.textContent).toMatch(/Baseline distorted by M&A/i)
    expect(body.textContent).toMatch(/Q1 FY26/i)

    // Surprise + range labels render but show dashes, not numbers.
    expect(screen.queryByText(/^-14\.9%/)).toBeNull()
    expect(screen.queryByText(/^\+14\.9%/)).toBeNull()

    // Heuristic chip still displays since the panel is still
    // showing the latest quarter print.
    expect(screen.getByText(/Heuristic/i)).toBeInTheDocument()
  })

  it("renders the legacy numeric path when ma_distortion_flag=false", async () => {
    mockFetch(NORMAL_PAYLOAD)
    render(<EarningsImpactPanel ticker="TCS" />)

    // Legacy range row surfaces with the formatted percent string.
    await waitFor(() => {
      expect(
        screen.getByText(/Likely FV impact at next recompute/i),
      ).toBeInTheDocument()
    })
    // No suppression body rendered for non-M&A path.
    expect(
      screen.queryByTestId("earnings-impact-ma-suppressed-body"),
    ).toBeNull()
    // Surprise label rendered: surprise_pct = -0.0379 → "-3.8%"
    expect(screen.getByText(/-3\.8%/)).toBeInTheDocument()
  })
})
