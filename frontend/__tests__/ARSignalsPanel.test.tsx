/**
 * Phase H-frontend (Block II) — ARSignalsPanel smoke tests.
 *
 * Pins three behaviours required by the phase brief:
 *   1. Populated path: when the endpoint returns a populated
 *      `signals` object, all six sections render (segments,
 *      capex, RPT, auditor flags, contingent liabilities,
 *      management outlook).
 *   2. Withheld path: when the endpoint returns
 *      {signals: null, withheld: true}, a neutral
 *      "Withheld pending review" placeholder renders — never any
 *      free text from the LLM.
 *   3. Empty path: when the endpoint returns {signals: null}
 *      without the withheld flag (no extraction yet for the
 *      ticker), the component renders nothing — the sibling
 *      AnnualReportsPanel handles the empty affordance below it.
 *
 * The component uses @tanstack/react-query; tests inject a fresh
 * QueryClient per case to keep them isolated.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import ARSignalsPanel, {
  type ARSignalsResponse,
} from "@/components/annual-reports/ARSignalsPanel"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const FULL_PAYLOAD: ARSignalsResponse = {
  signals: {
    segment_data: [
      {
        segment: "Consumer",
        revenue_cr: 8000,
        ebit_cr: 1100,
        fy: "FY24",
        quote: "Consumer segment revenue grew 18 percent.",
      },
    ],
    capex_commitments: [
      {
        amount_cr: 800,
        fy: "FY25",
        project: "Sanand fab",
        quote: "Capex of Rs 800 Cr planned over FY25.",
      },
    ],
    related_party_transactions: [
      {
        counterparty: "Acme Subsidiary",
        relationship: "subsidiary",
        nature: "sales",
        amount_cr: 12.3,
        fy: "FY24",
      },
    ],
    auditor_flags: [
      {
        type: "emphasis_of_matter",
        description: "Pending tax matter.",
        as_of: "2024-03-31",
      },
    ],
    contingent_liabilities: [
      {
        description: "Tax disputes.",
        amount_cr: 234,
        as_of: "2024-03-31",
      },
    ],
    management_outlook:
      "The year ahead is constructive across the consumer franchise.",
    model_version: "ar-intel-v1-anthropic-2026-05-26",
    prompt_version: 1,
  },
  withheld: false,
  ticker: "RELIANCE",
  fiscal_year: 2024,
  annual_report_id: 999,
  quality_flag: "ok",
  generated_at: "2026-05-26T12:00:00+00:00",
  ar_url: "https://example.invalid/RELIANCE-AR-2024.pdf",
  published_at: "2024-08-10",
}

const WITHHELD_PAYLOAD: ARSignalsResponse = {
  signals: null,
  withheld: true,
  ticker: "RELIANCE",
  fiscal_year: 2024,
  annual_report_id: 999,
  quality_flag: "sebi_withheld",
  generated_at: "2026-05-26T12:00:00+00:00",
  ar_url: null,
  published_at: null,
}

const EMPTY_PAYLOAD: ARSignalsResponse = {
  signals: null,
  withheld: false,
  ticker: null,
  fiscal_year: null,
  annual_report_id: null,
  quality_flag: null,
  generated_at: null,
  ar_url: null,
  published_at: null,
}

describe("ARSignalsPanel", () => {
  it("renders all six sections when signals are present", () => {
    renderWithClient(
      <ARSignalsPanel ticker="RELIANCE" initialData={FULL_PAYLOAD} />,
    )

    // Header.
    expect(screen.getByText("Annual Report Signals")).toBeInTheDocument()
    // FY badge derived from fiscal_year=2024 -> "FY24" (also present
    // in the segment row's fy field, hence getAllByText).
    expect(screen.getAllByText("FY24").length).toBeGreaterThan(0)

    // 1. segments
    expect(screen.getByTestId("ar-section-segments")).toBeInTheDocument()
    expect(screen.getByText("Consumer")).toBeInTheDocument()
    expect(
      screen.getByText(/Consumer segment revenue grew 18 percent/),
    ).toBeInTheDocument()

    // 2. capex — scope queries inside the section to avoid bleed
    // from the segment row (which has Rs 8000 Cr revenue).
    const capexSection = screen.getByTestId("ar-section-capex")
    expect(capexSection).toBeInTheDocument()
    expect(capexSection).toHaveTextContent(/Rs 800 Cr/)
    expect(capexSection).toHaveTextContent(/Sanand fab/)

    // 3. RPTs
    expect(screen.getByTestId("ar-section-rpt")).toBeInTheDocument()
    expect(screen.getByText("Acme Subsidiary")).toBeInTheDocument()
    expect(screen.getByText("subsidiary")).toBeInTheDocument()

    // 4. auditor flags
    expect(screen.getByTestId("ar-section-auditor")).toBeInTheDocument()
    expect(screen.getByText("emphasis_of_matter")).toBeInTheDocument()
    expect(screen.getByText(/Pending tax matter/)).toBeInTheDocument()

    // 5. contingent liabilities
    expect(screen.getByTestId("ar-section-liabilities")).toBeInTheDocument()
    expect(screen.getByText(/Rs 234 Cr/)).toBeInTheDocument()
    expect(screen.getByText(/Tax disputes/)).toBeInTheDocument()

    // 6. management outlook
    expect(screen.getByTestId("ar-section-outlook")).toBeInTheDocument()
    expect(
      screen.getByText(/The year ahead is constructive/),
    ).toBeInTheDocument()
  })

  it("renders a neutral 'Withheld pending review' placeholder when withheld=true", () => {
    renderWithClient(
      <ARSignalsPanel ticker="RELIANCE" initialData={WITHHELD_PAYLOAD} />,
    )

    expect(screen.getByTestId("ar-signals-withheld")).toBeInTheDocument()
    expect(screen.getByText(/Withheld pending review/i)).toBeInTheDocument()
    // None of the six structured sections render in this branch.
    expect(screen.queryByTestId("ar-section-segments")).toBeNull()
    expect(screen.queryByTestId("ar-section-capex")).toBeNull()
    expect(screen.queryByTestId("ar-section-rpt")).toBeNull()
    expect(screen.queryByTestId("ar-section-auditor")).toBeNull()
    expect(screen.queryByTestId("ar-section-liabilities")).toBeNull()
    expect(screen.queryByTestId("ar-section-outlook")).toBeNull()
  })

  it("renders nothing when signals are null without the withheld flag", () => {
    const { container } = renderWithClient(
      <ARSignalsPanel ticker="UNKNOWN" initialData={EMPTY_PAYLOAD} />,
    )
    // The panel must produce no output — the sibling AnnualReportsPanel
    // already shows the AR link list below.
    expect(container.firstChild).toBeNull()
  })

  // ---------------------------------------------------------------
  // Follow-on to PR #614 — pins the four label/render bugs that were
  // visible on /analysis/HDFCBANK.NS after the canonical-field rename:
  //   - segment label rendered literal "segment" instead of `name`
  //   - RPT label rendered literal "counterparty" instead of `party`
  //   - capex rows hid `description`, showed only amount
  //   - contingent liabilities rendered "Rs Cr" with no amount when
  //     `amount_cr` was null
  // The fixture below matches the live backend payload shape exactly
  // (name/party/timeline/description, with one null amount_cr).
  // ---------------------------------------------------------------
  const CANONICAL_PAYLOAD: ARSignalsResponse = {
    signals: {
      segment_data: [
        {
          name: "Treasury",
          revenue_cr: 62227.48,
          ebit_cr: 4605.36,
          yoy_growth_pct: null,
        },
      ],
      capex_commitments: [
        {
          description:
            "Aggregate capital expenditure FY2024-25 (across all segments)",
          amount_cr: 5704.01,
          timeline: "FY25 actual",
        },
      ],
      related_party_transactions: [
        {
          party: "HDB Financial Services Limited (subsidiary)",
          nature:
            "Receiving of services + interest received + dividend received",
          amount_cr: 2132.35,
        },
      ],
      auditor_flags: [],
      contingent_liabilities: [
        {
          description:
            "See Schedule 18 notes for full disclosure of contingent liabilities.",
          amount_cr: null,
        },
      ],
      management_outlook: null,
    },
    withheld: false,
    ticker: "HDFCBANK.NS",
    fiscal_year: 2025,
    annual_report_id: 1234,
    quality_flag: "ok",
    generated_at: "2026-05-23T12:00:00+00:00",
    ar_url: "https://example.invalid/HDFCBANK-AR-2025.pdf",
    published_at: "2025-08-10",
  }

  it("renders segment `name` field (not the literal placeholder 'segment')", () => {
    renderWithClient(
      <ARSignalsPanel ticker="HDFCBANK.NS" initialData={CANONICAL_PAYLOAD} />,
    )
    const segSection = screen.getByTestId("ar-section-segments")
    expect(segSection).toHaveTextContent("Treasury")
    // Lower-case placeholder must NOT leak through as a label.
    expect(segSection.textContent ?? "").not.toMatch(/\bsegment\b(?! data)/)
  })

  it("renders RPT `party` field (not the literal placeholder 'counterparty')", () => {
    renderWithClient(
      <ARSignalsPanel ticker="HDFCBANK.NS" initialData={CANONICAL_PAYLOAD} />,
    )
    const rptSection = screen.getByTestId("ar-section-rpt")
    expect(rptSection).toHaveTextContent(/HDB Financial Services/)
    expect(rptSection.textContent ?? "").not.toMatch(/\bcounterparty\b/i)
  })

  it("renders capex `description` as the row title alongside the amount", () => {
    renderWithClient(
      <ARSignalsPanel ticker="HDFCBANK.NS" initialData={CANONICAL_PAYLOAD} />,
    )
    const capexSection = screen.getByTestId("ar-section-capex")
    // Description (the primary title) must render.
    expect(capexSection).toHaveTextContent(
      /Aggregate capital expenditure FY2024-25/,
    )
    // Amount must still render as a secondary line.
    expect(capexSection).toHaveTextContent(/Rs 5,704\.01 Cr/)
    // Timeline badge must also render.
    expect(capexSection).toHaveTextContent(/FY25 actual/)
  })

  it("omits the 'Rs Cr' amount line for contingent liabilities when amount_cr is null", () => {
    renderWithClient(
      <ARSignalsPanel ticker="HDFCBANK.NS" initialData={CANONICAL_PAYLOAD} />,
    )
    const clSection = screen.getByTestId("ar-section-liabilities")
    // Description still renders.
    expect(clSection).toHaveTextContent(/See Schedule 18 notes/)
    // Empty "Rs Cr" placeholder must not leak through.
    expect(clSection.textContent ?? "").not.toMatch(/Rs\s+Cr/)
  })
})
