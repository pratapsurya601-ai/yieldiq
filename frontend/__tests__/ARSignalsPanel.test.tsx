/**
 * ARSignalsPanel smoke tests.
 *
 * Pins these behaviours:
 *   1. Populated path: all six original sub-panels render (segments
 *      default-expanded; the others render their headers and their
 *      bodies after a click).
 *   2. Withheld path: when the endpoint returns
 *      {signals: null, withheld: true}, a neutral
 *      "Withheld pending review" placeholder renders — never any
 *      free text from the LLM.
 *   3. Empty path: when the endpoint returns {signals: null}
 *      without the withheld flag (no extraction yet for the
 *      ticker), the component renders nothing.
 *   4. PR #613 extended fields:
 *      a. All 10 new fields populated -> all 10 new sub-panels
 *         render their section headers (and bodies after a click).
 *      b. All 10 new fields null/empty -> none of the 10 new
 *         section headers render.
 *      c. Partial (only esg_metrics + governance) -> only those
 *         two new sub-panels render.
 *
 * The component uses @tanstack/react-query; tests inject a fresh
 * QueryClient per case to keep them isolated.
 */
import { describe, it, expect } from "vitest"
import { render, screen, within, fireEvent } from "@testing-library/react"
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

// Click the header button inside a collapsible section to expand it.
function expandSection(testId: string) {
  const section = screen.getByTestId(testId)
  const header = within(section).getByRole("button")
  fireEvent.click(header)
  return section
}

const FULL_PAYLOAD: ARSignalsResponse = {
  signals: {
    segment_data: [
      {
        name: "Consumer",
        revenue_cr: 8000,
        ebit_cr: 1100,
        fy: "FY24",
        quote: "Consumer segment revenue grew 18 percent.",
      },
    ],
    capex_commitments: [
      {
        amount_cr: 800,
        timeline: "FY25",
        description: "Sanand fab",
        quote: "Capex of Rs 800 Cr planned over FY25.",
      },
    ],
    related_party_transactions: [
      {
        party: "Acme Subsidiary",
        relationship: "subsidiary",
        nature: "sales",
        amount_cr: 12.3,
        fy: "FY24",
      },
    ],
    auditor_flags: [
      {
        type: "emphasis_of_matter",
        summary: "Pending tax matter.",
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
  quality_flag: "withheld",
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

// PR #613 extended fields — all 10 populated.
const EXTENDED_FULL: ARSignalsResponse = {
  ...FULL_PAYLOAD,
  signals: {
    ...FULL_PAYLOAD.signals!,
    risk_factors: [
      {
        category: "Regulatory",
        description: "Pending GST circular on input credit.",
        mitigation: "Engaged external counsel; provisioned.",
      },
    ],
    esg_metrics: {
      scope1_emissions_tco2e: 12000,
      scope2_emissions_tco2e: 24000,
      scope3_emissions_tco2e: 80000,
      water_withdrawal_kl: 500000,
      renewable_energy_pct: 34.5,
      gender_ratio_pct_female_workforce: 28.2,
      lost_time_injury_frequency_rate: 0.34,
      csr_spend_cr: 18.5,
      note: "Verified by BRSR.",
    },
    governance: {
      promoter_pledge_pct: 0,
      promoter_shareholding_pct: 51.2,
      board_independence_pct: 60,
      auditor_remuneration_cr: 4.5,
      whistleblower_complaints_count: 7,
      sexual_harassment_complaints_count: 2,
      regulatory_penalties_cr: 0.3,
      note: "All complaints resolved.",
    },
    workforce_metrics: {
      total_headcount: 45000,
      attrition_pct: 14.2,
      gender_ratio_pct_female: 28.2,
      training_hours_per_employee: 28,
      employee_cost_pct_revenue: 12.5,
      note: "Voluntary attrition basis.",
    },
    customer_concentration: {
      top_10_customer_pct_revenue: 22,
      geographic_split: [
        { region: "India", pct_revenue: 65 },
        { region: "North America", pct_revenue: 25 },
      ],
      channel_split: [
        { channel: "Direct", pct_revenue: 70 },
        { channel: "Distributors", pct_revenue: 30 },
      ],
      note: "Based on segment disclosures.",
    },
    operational_kpis: {
      industry: "Cement",
      metrics: {
        capacity_utilisation_pct: 78,
        clinker_factor: 0.72,
        blended_realisation_per_tonne: 5400,
      },
      note: "Capacity weighted.",
    },
    subsidiary_summary: [
      {
        name: "Acme Logistics Pvt Ltd",
        country: "India",
        revenue_cr: 220,
        pat_cr: 18,
        networth_cr: 95,
        ownership_pct: 100,
      },
    ],
    dividend_history: [
      {
        fiscal_year: 2024,
        interim_dps_rs: 4,
        final_dps_rs: 6,
        special_dps_rs: 0,
        total_dps_rs: 10,
        payout_ratio_pct: 28.4,
      },
    ],
    capital_actions: [
      {
        type: "Buyback",
        date: "2024-09-15",
        ratio_or_price: "Rs 4200/share",
        amount_cr: 1500,
      },
    ],
    strategic_priorities: [
      {
        priority: "Premiumisation",
        target: "Lift premium mix to 30%",
        timeline: "FY27",
      },
    ],
  },
}

// PR #613 extended fields — all 10 explicitly null.
const EXTENDED_ALL_NULL: ARSignalsResponse = {
  ...FULL_PAYLOAD,
  signals: {
    ...FULL_PAYLOAD.signals!,
    risk_factors: null,
    esg_metrics: null,
    governance: null,
    workforce_metrics: null,
    customer_concentration: null,
    operational_kpis: null,
    subsidiary_summary: null,
    dividend_history: null,
    capital_actions: null,
    strategic_priorities: null,
  },
}

// PR #613 extended fields — partial (only esg + governance).
const EXTENDED_PARTIAL: ARSignalsResponse = {
  ...FULL_PAYLOAD,
  signals: {
    ...FULL_PAYLOAD.signals!,
    risk_factors: [],
    esg_metrics: {
      renewable_energy_pct: 40,
      csr_spend_cr: 12,
    },
    governance: {
      promoter_pledge_pct: 0,
      board_independence_pct: 50,
    },
    workforce_metrics: null,
    customer_concentration: null,
    operational_kpis: null,
    subsidiary_summary: [],
    dividend_history: [],
    capital_actions: [],
    strategic_priorities: [],
  },
}

describe("ARSignalsPanel — original six sub-panels", () => {
  it("renders all six section headers when signals are present", () => {
    renderWithClient(
      <ARSignalsPanel ticker="RELIANCE" initialData={FULL_PAYLOAD} />,
    )

    // Header.
    expect(screen.getByText("Annual Report Signals")).toBeInTheDocument()
    // FY badge derived from fiscal_year=2024 -> "FY24".
    expect(screen.getAllByText("FY24").length).toBeGreaterThan(0)

    // All six section wrappers render.
    expect(screen.getByTestId("ar-section-segments")).toBeInTheDocument()
    expect(screen.getByTestId("ar-section-capex")).toBeInTheDocument()
    expect(screen.getByTestId("ar-section-rpt")).toBeInTheDocument()
    expect(screen.getByTestId("ar-section-auditor")).toBeInTheDocument()
    expect(screen.getByTestId("ar-section-liabilities")).toBeInTheDocument()
    expect(screen.getByTestId("ar-section-outlook")).toBeInTheDocument()

    // Segments is default-expanded — its body content is visible.
    expect(screen.getByText("Consumer")).toBeInTheDocument()
    expect(
      screen.getByText(/Consumer segment revenue grew 18 percent/),
    ).toBeInTheDocument()

    // Other sections expand on click and reveal their body content.
    const capexSection = expandSection("ar-section-capex")
    expect(capexSection).toHaveTextContent(/Rs 800 Cr/)
    expect(capexSection).toHaveTextContent(/Sanand fab/)

    const rptSection = expandSection("ar-section-rpt")
    expect(within(rptSection).getByText("Acme Subsidiary")).toBeInTheDocument()
    expect(within(rptSection).getByText("subsidiary")).toBeInTheDocument()

    const auditorSection = expandSection("ar-section-auditor")
    expect(within(auditorSection).getByText("emphasis_of_matter")).toBeInTheDocument()
    expect(within(auditorSection).getByText(/Pending tax matter/)).toBeInTheDocument()

    const liabSection = expandSection("ar-section-liabilities")
    expect(liabSection).toHaveTextContent(/Rs 234 Cr/)
    expect(liabSection).toHaveTextContent(/Tax disputes/)

    const outlookSection = expandSection("ar-section-outlook")
    expect(
      within(outlookSection).getByText(/The year ahead is constructive/),
    ).toBeInTheDocument()
  })

  it("renders a neutral 'Withheld pending review' placeholder when withheld=true", () => {
    renderWithClient(
      <ARSignalsPanel ticker="RELIANCE" initialData={WITHHELD_PAYLOAD} />,
    )

    expect(screen.getByTestId("ar-signals-withheld")).toBeInTheDocument()
    expect(screen.getByText(/Withheld pending review/i)).toBeInTheDocument()
    // None of the structured sections render in this branch.
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
    expect(container.firstChild).toBeNull()
  })
})

describe("ARSignalsPanel — PR #613 extended fields", () => {
  const EXTENDED_TESTIDS = [
    "ar-section-risk-factors",
    "ar-section-esg",
    "ar-section-governance",
    "ar-section-workforce",
    "ar-section-customer",
    "ar-section-operational-kpis",
    "ar-section-subsidiaries",
    "ar-section-dividends",
    "ar-section-capital-actions",
    "ar-section-strategic-priorities",
  ] as const

  it("renders all 10 new sub-panels when every extended field is populated", () => {
    renderWithClient(
      <ARSignalsPanel ticker="RELIANCE" initialData={EXTENDED_FULL} />,
    )
    for (const id of EXTENDED_TESTIDS) {
      expect(screen.getByTestId(id)).toBeInTheDocument()
    }

    // Spot-check a handful of bodies expand and reveal known content.
    const risk = expandSection("ar-section-risk-factors")
    expect(risk).toHaveTextContent(/Regulatory/)
    expect(risk).toHaveTextContent(/GST circular/)

    const esg = expandSection("ar-section-esg")
    expect(esg).toHaveTextContent(/Scope 1/)
    expect(esg).toHaveTextContent(/Renewable energy/)

    const customer = expandSection("ar-section-customer")
    expect(customer).toHaveTextContent(/Top 10 customers/)
    expect(customer).toHaveTextContent(/India/)
    expect(customer).toHaveTextContent(/Direct/)

    const subs = expandSection("ar-section-subsidiaries")
    expect(subs).toHaveTextContent(/Acme Logistics/)

    const divs = expandSection("ar-section-dividends")
    expect(divs).toHaveTextContent(/2024/)

    const cap = expandSection("ar-section-capital-actions")
    expect(cap).toHaveTextContent(/Buyback/)

    const strat = expandSection("ar-section-strategic-priorities")
    expect(strat).toHaveTextContent(/Premiumisation/)
  })

  it("renders none of the 10 new sub-panels when every extended field is null/empty", () => {
    renderWithClient(
      <ARSignalsPanel ticker="RELIANCE" initialData={EXTENDED_ALL_NULL} />,
    )
    // Component itself still mounts (original six sub-panels render).
    expect(screen.getByTestId("ar-signals-panel")).toBeInTheDocument()
    // No extended sub-panel headers — not even empty ones.
    for (const id of EXTENDED_TESTIDS) {
      expect(screen.queryByTestId(id)).toBeNull()
    }
  })

  it("renders only the populated sub-panels when extended fields are partial", () => {
    renderWithClient(
      <ARSignalsPanel ticker="RELIANCE" initialData={EXTENDED_PARTIAL} />,
    )
    // The two populated ones render.
    expect(screen.getByTestId("ar-section-esg")).toBeInTheDocument()
    expect(screen.getByTestId("ar-section-governance")).toBeInTheDocument()
    // The other eight do NOT render — empty arrays and all-null
    // objects must collapse to no section header.
    expect(screen.queryByTestId("ar-section-risk-factors")).toBeNull()
    expect(screen.queryByTestId("ar-section-workforce")).toBeNull()
    expect(screen.queryByTestId("ar-section-customer")).toBeNull()
    expect(screen.queryByTestId("ar-section-operational-kpis")).toBeNull()
    expect(screen.queryByTestId("ar-section-subsidiaries")).toBeNull()
    expect(screen.queryByTestId("ar-section-dividends")).toBeNull()
    expect(screen.queryByTestId("ar-section-capital-actions")).toBeNull()
    expect(screen.queryByTestId("ar-section-strategic-priorities")).toBeNull()
  })
})
