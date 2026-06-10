/**
 * Render-layer pin for FinancialBars on bank tickers.
 *
 *   - HDFCBANK: the revenue card label reads "Net Interest Income"
 *     (not "Revenue"), and the FCF card is replaced with a
 *     "not meaningful — banks use NIM/loan-growth instead" caption
 *     rather than a column of flat-zero bars.
 *   - TCS: revenue label reads "Revenue" and the FCF card renders
 *     normally.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import FinancialBars from "@/components/analysis/FinancialBars"

vi.mock("recharts", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("recharts")
  return {
    ...actual,
    // ResponsiveContainer measures its parent which is 0x0 in JSDOM;
    // collapse to a passthrough so the chart actually mounts.
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="rc-passthrough">{children}</div>
    ),
  }
})

const REVENUE = [
  { year: "2022", value: 120_000_00_00_000 }, // 12,000 Cr
  { year: "2023", value: 132_000_00_00_000 },
  { year: "2024", value: 145_000_00_00_000 },
]
const FCF = [
  { year: "2022", value: 18_000_00_00_000 },
  { year: "2023", value: 21_000_00_00_000 },
]

describe("FinancialBars bank-cohort behaviour", () => {
  it("renders Net Interest Income label and hides FCF chart for HDFCBANK", () => {
    render(
      <FinancialBars
        ticker="HDFCBANK"
        currency="INR"
        sector="Banking"
        revenue={REVENUE}
        fcf={FCF}
      />,
    )
    expect(screen.getByTestId("financial-bars-revenue-label")).toHaveTextContent(
      "Net Interest Income",
    )
    expect(screen.queryByText("Free Cash Flow")).toBeNull()
    expect(
      screen.getByTestId("financial-bars-fcf-not-applicable"),
    ).toBeInTheDocument()
  })

  it("renders Revenue + FCF chart for a non-bank ticker", () => {
    render(
      <FinancialBars
        ticker="TCS"
        currency="INR"
        sector="IT Services"
        revenue={REVENUE}
        fcf={FCF}
      />,
    )
    expect(screen.getByTestId("financial-bars-revenue-label")).toHaveTextContent(
      "Revenue",
    )
    expect(screen.getByText("Free Cash Flow")).toBeInTheDocument()
    expect(
      screen.queryByTestId("financial-bars-fcf-not-applicable"),
    ).toBeNull()
  })

  it("falls back to ticker-based bank detection when sector is missing", () => {
    render(
      <FinancialBars
        ticker="ICICIBANK"
        currency="INR"
        revenue={REVENUE}
      />,
    )
    expect(screen.getByTestId("financial-bars-revenue-label")).toHaveTextContent(
      "Net Interest Income",
    )
  })
})
