/**
 * /funds/[scheme_code] — Phase 3-slim render-shape tests.
 *
 * Focus: the graceful-degradation contract. The page must render
 * cleanly when Phase 2's returns cache is empty (metrics === null)
 * AND when the benchmark series is missing. Both states are the
 * actually-shipped state on day 1.
 */
import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"

import FundJsonLd from "@/app/(app)/funds/[scheme_code]/JsonLd"
import NavBenchmarkChart from "@/app/(app)/funds/[scheme_code]/NavBenchmarkChart"
import type { Fund, FundNavPoint } from "@/types/api"

const FUND: Fund = {
  scheme_code: "118989",
  isin_growth: "INF179K01158",
  isin_div: null,
  scheme_name: "HDFC Top 100 Fund - Direct Plan - Growth",
  amc: "HDFC Mutual Fund",
  plan: "Direct",
  option: "Growth",
  category: "Equity",
  sub_category: "Large Cap",
  benchmark_index_code: "NIFTY_100_TRI",
  inception_date: "1996-10-11",
  riskometer_level: "VeryHigh",
  is_active: true,
}

function navSeries(): FundNavPoint[] {
  return [
    { nav_date: "2024-06-30", nav: 100, aum_cr: null },
    { nav_date: "2024-07-31", nav: 102, aum_cr: null },
    { nav_date: "2024-08-30", nav: 105, aum_cr: null },
    { nav_date: "2024-09-30", nav: 103, aum_cr: null },
  ]
}

describe("FundJsonLd", () => {
  it("emits FinancialProduct schema with the scheme name and AMC", () => {
    const { container } = render(<FundJsonLd fund={FUND} metrics={null} />)
    const fp = container.querySelector(
      '[data-testid="jsonld-fund-financialproduct"]',
    )
    expect(fp).not.toBeNull()
    const json = JSON.parse(fp!.textContent || "{}")
    expect(json["@type"]).toBe("FinancialProduct")
    expect(json.name).toContain("HDFC Top 100")
    const props = (json.additionalProperty as Array<{ name: string; value: string }>) || []
    const amcProp = props.find((p) => p.name === "AMC")
    expect(amcProp?.value).toBe("HDFC Mutual Fund")
    const risk = props.find((p) => p.name === "SEBI Riskometer")
    expect(risk?.value).toBe("VeryHigh")
  })

  it("omits the YieldIQ Fund Score entry when metrics is null", () => {
    const { container } = render(<FundJsonLd fund={FUND} metrics={null} />)
    const fp = container.querySelector(
      '[data-testid="jsonld-fund-financialproduct"]',
    )
    const json = JSON.parse(fp!.textContent || "{}")
    const props = (json.additionalProperty as Array<{ name: string }>) || []
    expect(props.find((p) => p.name.includes("YieldIQ Fund Score"))).toBeUndefined()
  })

  it("emits a BreadcrumbList rooted at Mutual Funds", () => {
    const { container } = render(<FundJsonLd fund={FUND} metrics={null} />)
    const bc = container.querySelector(
      '[data-testid="jsonld-fund-breadcrumb"]',
    )
    expect(bc).not.toBeNull()
    const json = JSON.parse(bc!.textContent || "{}")
    expect(json["@type"]).toBe("BreadcrumbList")
    expect(json.itemListElement[0].name).toBe("Mutual Funds")
  })
})

describe("NavBenchmarkChart", () => {
  it("renders the empty-state message when navHistory is empty", () => {
    render(<NavBenchmarkChart navHistory={[]} benchmarkHistory={[]} />)
    expect(
      screen.getByText(/NAV history is not available/i),
    ).toBeInTheDocument()
  })

  it("renders the chart shell and window toggle when NAV data exists", () => {
    const { container } = render(
      <NavBenchmarkChart navHistory={navSeries()} benchmarkHistory={[]} />,
    )
    expect(screen.getByText(/NAV vs Benchmark/)).toBeInTheDocument()
    expect(screen.getByText("1Y")).toBeInTheDocument()
    expect(screen.getByText("5Y")).toBeInTheDocument()
    // Benchmark-absent disclosure is the second graceful path.
    expect(
      screen.getByText(/Benchmark TRI series is not available/i),
    ).toBeInTheDocument()
    // Recharts renders a ResponsiveContainer wrapper element.
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull()
  })
})
