/**
 * Phase G-intel-phase1 (c) — ConcallSignalsPanel smoke tests.
 *
 * Pins three behaviours required by the phase brief:
 *   1. Happy path: when the endpoint returns a populated `signals`
 *      object, all five sections (tone, guidance, capex, margin,
 *      quotes) render.
 *   2. Withheld path: when the endpoint returns
 *      {signals: null, withheld: true}, a neutral
 *      "Withheld pending review" placeholder renders — never any
 *      free text from the LLM.
 *   3. Empty path: when the endpoint returns {signals: null} without
 *      the withheld flag (no extraction yet for the ticker), the
 *      component renders nothing — the sibling ConcallsPanel handles
 *      the empty affordance below it.
 *
 * The component uses @tanstack/react-query; tests inject a fresh
 * QueryClient per case to keep them isolated.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import ConcallSignalsPanel, {
  type ConcallSignalsResponse,
} from "@/components/concall/ConcallSignalsPanel"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const FULL_PAYLOAD: ConcallSignalsResponse = {
  signals: {
    fiscal_period: "Q4FY26",
    concall_date: "2026-05-10",
    transcript_source: "nse_pdf",
    guidance_changes: [
      {
        metric: "revenue_growth_fy27",
        previous: "10-12%",
        new: "12-14%",
        direction: "raised",
        quote: "We see a clear runway into next year.",
      },
    ],
    capex_commitments: [
      {
        amount_cr: 1500,
        horizon: "FY27-FY28",
        purpose: "New plant in Gujarat",
        quote: "We will commit fifteen hundred crore.",
      },
    ],
    margin_commentary: [
      {
        segment: "consumer",
        direction: "expansion",
        drivers: ["mix improvement", "input cost easing"],
        quote: "Margins expanded 80-100 bps in the quarter.",
      },
    ],
    management_tone: "bullish",
    key_quotes: [
      {
        speaker: "CFO",
        topic: "working capital",
        quote: "Working capital intensity is at multi-year lows.",
      },
    ],
    extractor_version: "concall-intel-v1-anthropic-2026-05-23",
  },
  withheld: false,
  ticker: "RELIANCE",
  fiscal_period: "Q4FY26",
  transcript_id: 1234,
  quality_flag: "ok",
  generated_at: "2026-05-23T12:00:00+00:00",
}

const WITHHELD_PAYLOAD: ConcallSignalsResponse = {
  signals: null,
  withheld: true,
  ticker: "RELIANCE",
  fiscal_period: "Q4FY26",
  transcript_id: 1234,
  quality_flag: "sebi_withheld",
  generated_at: "2026-05-23T12:00:00+00:00",
}

const EMPTY_PAYLOAD: ConcallSignalsResponse = {
  signals: null,
  withheld: false,
  ticker: null,
  fiscal_period: null,
  transcript_id: null,
  quality_flag: null,
  generated_at: null,
}

describe("ConcallSignalsPanel", () => {
  it("renders all five sections when signals are present", () => {
    renderWithClient(
      <ConcallSignalsPanel ticker="RELIANCE" initialData={FULL_PAYLOAD} />,
    )

    // Header.
    expect(screen.getByText("Concall Signals")).toBeInTheDocument()
    expect(screen.getByText("Q4FY26")).toBeInTheDocument()

    // 1. tone
    expect(screen.getByTestId("signals-section-tone")).toBeInTheDocument()
    expect(screen.getByText("bullish")).toBeInTheDocument()

    // 2. guidance
    expect(screen.getByTestId("signals-section-guidance")).toBeInTheDocument()
    expect(screen.getByText("revenue_growth_fy27")).toBeInTheDocument()
    expect(
      screen.getByText(/We see a clear runway into next year/),
    ).toBeInTheDocument()

    // 3. capex
    expect(screen.getByTestId("signals-section-capex")).toBeInTheDocument()
    expect(screen.getByText(/Rs 1500 Cr/)).toBeInTheDocument()
    expect(screen.getByText(/New plant in Gujarat/)).toBeInTheDocument()

    // 4. margin
    expect(screen.getByTestId("signals-section-margin")).toBeInTheDocument()
    expect(screen.getByText("consumer")).toBeInTheDocument()
    expect(screen.getByText(/Margins expanded 80-100 bps in the quarter/)).toBeInTheDocument()

    // 5. key quotes
    expect(screen.getByTestId("signals-section-quotes")).toBeInTheDocument()
    expect(
      screen.getByText(/Working capital intensity is at multi-year lows/),
    ).toBeInTheDocument()
  })

  it("renders a neutral 'Withheld pending review' placeholder when withheld=true", () => {
    renderWithClient(
      <ConcallSignalsPanel ticker="RELIANCE" initialData={WITHHELD_PAYLOAD} />,
    )

    expect(screen.getByTestId("concall-signals-withheld")).toBeInTheDocument()
    expect(screen.getByText(/Withheld pending review/i)).toBeInTheDocument()
    // None of the five structured sections render in this branch.
    expect(screen.queryByTestId("signals-section-tone")).toBeNull()
    expect(screen.queryByTestId("signals-section-guidance")).toBeNull()
    expect(screen.queryByTestId("signals-section-capex")).toBeNull()
    expect(screen.queryByTestId("signals-section-margin")).toBeNull()
    expect(screen.queryByTestId("signals-section-quotes")).toBeNull()
  })

  it("renders nothing when signals are null without the withheld flag", () => {
    const { container } = renderWithClient(
      <ConcallSignalsPanel ticker="UNKNOWN" initialData={EMPTY_PAYLOAD} />,
    )
    // The panel must produce no output — the sibling ConcallsPanel
    // already shows an empty-state below.
    expect(container.firstChild).toBeNull()
  })
})
