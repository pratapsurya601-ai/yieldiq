/**
 * Phase I-frontend (Block II) -- BankKpiPanel smoke tests.
 *
 * Pins four behaviours required by the phase brief:
 *   1. Populated path: 3x3 grid renders with formatted values and
 *      sparklines for the six quarterly metrics.
 *   2. Partial path: missing fields render "—" placeholders; the
 *      cells that DO have values still render.
 *   3. Non-bank ticker: panel renders nothing (response carries
 *      is_bank=false).
 *   4. Empty bank: ticker is_bank=true but the table has no rows;
 *      panel renders nothing rather than a half-empty shell.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import BankKpiPanel, {
  type BankKpisResponse,
} from "@/components/banks/BankKpiPanel"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const FULL_PAYLOAD: BankKpisResponse = {
  ticker: "HDFCBANK",
  is_bank: true,
  latest_annual: {
    period_end: "2024-03-31",
    period_type: "annual",
    branches_total: 7821,
    branches_tier1: 3100,
    branches_tier2: 2700,
    branches_tier3: 2021,
    atms_total: 19500,
    customers_millions: 92.0,
    gnpa_pct: 1.2,
    nnpa_pct: 0.3,
    pcr_pct: 72.5,
    casa_pct: 38.0,
    cost_to_income_pct: 40.1,
    credit_deposit_pct: 87.0,
    sources: ["bse_xbrl", "ar_anthropic"],
  },
  quarterly_trend: {
    gnpa_pct: [
      { period_end: "2024-12-31", value: 1.10 },
      { period_end: "2024-09-30", value: 1.15 },
      { period_end: "2024-06-30", value: 1.18 },
      { period_end: "2024-03-31", value: 1.20 },
    ],
    nnpa_pct: [
      { period_end: "2024-12-31", value: 0.25 },
      { period_end: "2024-09-30", value: 0.28 },
    ],
    pcr_pct: [],
    casa_pct: [
      { period_end: "2024-12-31", value: 37.5 },
      { period_end: "2024-09-30", value: 38.0 },
      { period_end: "2024-06-30", value: 38.2 },
    ],
    cost_to_income_pct: [],
    credit_deposit_pct: [],
  },
}

const PARTIAL_PAYLOAD: BankKpisResponse = {
  ticker: "SBIN",
  is_bank: true,
  latest_annual: {
    period_end: "2024-03-31",
    period_type: "annual",
    branches_total: 22500,
    branches_tier1: null,
    branches_tier2: null,
    branches_tier3: null,
    atms_total: null,
    customers_millions: null,
    gnpa_pct: 2.24,
    nnpa_pct: 0.57,
    pcr_pct: null,
    casa_pct: null,
    cost_to_income_pct: null,
    credit_deposit_pct: null,
    sources: ["bse_xbrl"],
  },
  quarterly_trend: {
    gnpa_pct: [
      { period_end: "2024-12-31", value: 2.10 },
      { period_end: "2024-09-30", value: 2.20 },
    ],
    nnpa_pct: [],
    pcr_pct: [],
    casa_pct: [],
    cost_to_income_pct: [],
    credit_deposit_pct: [],
  },
}

const NON_BANK_PAYLOAD: BankKpisResponse = {
  ticker: "RELIANCE",
  is_bank: false,
  latest_annual: null,
  quarterly_trend: {
    gnpa_pct: [],
    nnpa_pct: [],
    pcr_pct: [],
    casa_pct: [],
    cost_to_income_pct: [],
    credit_deposit_pct: [],
  },
}

const EMPTY_BANK_PAYLOAD: BankKpisResponse = {
  ticker: "FINCABK",
  is_bank: true,
  latest_annual: null,
  quarterly_trend: {
    gnpa_pct: [],
    nnpa_pct: [],
    pcr_pct: [],
    casa_pct: [],
    cost_to_income_pct: [],
    credit_deposit_pct: [],
  },
}

describe("BankKpiPanel", () => {
  it("renders the full 3x3 grid with formatted values + sparklines", () => {
    renderWithClient(
      <BankKpiPanel ticker="HDFCBANK" initialData={FULL_PAYLOAD} />,
    )

    // Header.
    expect(screen.getByText("Bank operational KPIs")).toBeInTheDocument()

    // Row 1 -- annual snapshots.
    expect(screen.getByTestId("kpi-branches")).toHaveTextContent("7,821")
    expect(screen.getByTestId("kpi-atms")).toHaveTextContent("19,500")
    expect(screen.getByTestId("kpi-customers")).toHaveTextContent("92.0 M")

    // Row 2 -- asset quality, % formatted to 2 dp.
    expect(screen.getByTestId("kpi-gnpa")).toHaveTextContent("1.20%")
    expect(screen.getByTestId("kpi-nnpa")).toHaveTextContent("0.30%")
    expect(screen.getByTestId("kpi-pcr")).toHaveTextContent("72.50%")

    // Row 3.
    expect(screen.getByTestId("kpi-casa")).toHaveTextContent("38.00%")
    expect(screen.getByTestId("kpi-cost-to-income")).toHaveTextContent("40.10%")
    expect(screen.getByTestId("kpi-credit-deposit")).toHaveTextContent("87.00%")

    // Sparklines: gnpa (4 pts), nnpa (2 pts), casa (3 pts) all
    // qualify (>=2 points); pcr / c2i / c2d have 0 points -> no
    // sparkline. So we expect exactly 3 sparklines.
    expect(screen.getAllByTestId("bank-kpi-sparkline")).toHaveLength(3)

    // Branch tier breakdown renders under the grid.
    const tiers = screen.getByTestId("bank-kpi-branch-tiers")
    expect(tiers).toHaveTextContent(/Tier 1.*3,100/)
    expect(tiers).toHaveTextContent(/Tier 2.*2,700/)
    expect(tiers).toHaveTextContent(/Tier 3.*2,021/)

    // Sources caption.
    expect(screen.getByTestId("bank-kpi-sources")).toHaveTextContent(
      /bse_xbrl, ar_anthropic/,
    )
  })

  it("renders dashes for missing fields without bailing on the row", () => {
    renderWithClient(
      <BankKpiPanel ticker="SBIN" initialData={PARTIAL_PAYLOAD} />,
    )

    // Branches populated, ATMs / customers blank.
    expect(screen.getByTestId("kpi-branches")).toHaveTextContent("22,500")
    expect(screen.getByTestId("kpi-atms")).toHaveTextContent("—")
    expect(screen.getByTestId("kpi-customers")).toHaveTextContent("—")

    // GNPA + NNPA populated, PCR blank.
    expect(screen.getByTestId("kpi-gnpa")).toHaveTextContent("2.24%")
    expect(screen.getByTestId("kpi-nnpa")).toHaveTextContent("0.57%")
    expect(screen.getByTestId("kpi-pcr")).toHaveTextContent("—")

    // All of row 3 blank.
    expect(screen.getByTestId("kpi-casa")).toHaveTextContent("—")
    expect(screen.getByTestId("kpi-cost-to-income")).toHaveTextContent("—")
    expect(screen.getByTestId("kpi-credit-deposit")).toHaveTextContent("—")

    // Only the gnpa sparkline qualifies (2 points).
    expect(screen.getAllByTestId("bank-kpi-sparkline")).toHaveLength(1)

    // No branch-tier breakdown because tier1/2/3 are all null.
    expect(screen.queryByTestId("bank-kpi-branch-tiers")).toBeNull()
  })

  it("renders nothing for a non-bank ticker", () => {
    const { container } = renderWithClient(
      <BankKpiPanel ticker="RELIANCE" initialData={NON_BANK_PAYLOAD} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders nothing for a bank with no ingested rows yet", () => {
    const { container } = renderWithClient(
      <BankKpiPanel ticker="FINCABK" initialData={EMPTY_BANK_PAYLOAD} />,
    )
    expect(container.firstChild).toBeNull()
  })
})
