/**
 * ValuationDrivers — sector-aware driver resolution + self-hide rule
 * (feat/intrinsic-value-thesis-redesign).
 *
 * Pins:
 *   1. `resolveDrivers` walks the documented per-slot fallback chains:
 *      banks read advances → deposits → revenue YoY, ROE → ROA, and
 *      NIM → CASA → cost-to-income; non-banks read revenue CAGR
 *      (decimal on the wire ×100), ROE-with-sector-context → ROCE,
 *      and FCF yield → ROCE-as-capital-efficiency.
 *   2. Null discipline: a null metric drops its card; null quality
 *      resolves to [].
 *   3. The component self-hides entirely when fewer than 2 drivers
 *      survive — never an em-dash card, never a fabricated zero.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"

import ValuationDrivers, {
  resolveDrivers,
} from "@/components/analysis/intrinsic/ValuationDrivers"
import type { QualityOutput } from "@/types/api"

function stubMatchMedia() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

beforeEach(() => {
  stubMatchMedia()
})

/** Minimal QualityOutput stub — only the fields resolveDrivers reads. */
function quality(over: Partial<QualityOutput>): QualityOutput {
  return {
    roe: null,
    de_ratio: null,
    ...over,
  } as QualityOutput
}

const MEDIANS = {
  pe: 24.1,
  pb: 3.2,
  roe: 14.2,
  div_yield: 1.1,
  op_margin: 18.4,
}

describe("resolveDrivers — null discipline", () => {
  it("returns [] when quality is null or undefined", () => {
    expect(resolveDrivers({ quality: null })).toEqual([])
    expect(resolveDrivers({})).toEqual([])
  })

  it("drops a card when its whole fallback chain is null", () => {
    // Non-bank with only ROE usable → exactly one driver.
    const drivers = resolveDrivers({ quality: quality({ roe: 17.2 }) })
    expect(drivers.map((d) => d.key)).toEqual(["returns"])
  })
})

describe("resolveDrivers — bank chains", () => {
  it("reads advances / ROE / NIM when all bank-native fields are present", () => {
    const drivers = resolveDrivers({
      quality: quality({
        is_bank: true,
        advances_yoy: 12.3,
        deposits_yoy: 9.1,
        roe: 8.8,
        roa: 1.9,
        nim: 3.6,
        casa: 41.0,
      }),
    })
    expect(drivers.map((d) => d.key)).toEqual(["growth", "returns", "margin"])
    expect(drivers[0].value).toBe("+12.3%")
    expect(drivers[0].context).toBe("Advances read +12.3% year over year.")
    expect(drivers[1].value).toBe("8.8%")
    expect(drivers[2].label).toBe("Margin")
    expect(drivers[2].value).toBe("3.6%")
  })

  it("falls back advances → deposits → revenue YoY for the growth slot", () => {
    const viaDeposits = resolveDrivers({
      quality: quality({ is_bank: true, deposits_yoy: 9.1, roe: 8.8 }),
    })
    expect(viaDeposits[0].context).toBe("Deposits read +9.1% year over year.")

    const viaRevenue = resolveDrivers({
      quality: quality({ is_bank: true, revenue_yoy_bank: -2.4, roe: 8.8 }),
    })
    expect(viaRevenue[0].value).toBe("-2.4%")
    expect(viaRevenue[0].context).toBe("Revenue reads -2.4% year over year.")
  })

  it("falls back ROE → ROA for the returns slot", () => {
    const drivers = resolveDrivers({
      quality: quality({ is_bank: true, roa: 1.9 }),
    })
    expect(drivers.map((d) => d.key)).toEqual(["returns"])
    expect(drivers[0].context).toContain("Return on assets reads 1.9%")
  })

  it("falls back NIM → CASA → cost-to-income for the margin slot", () => {
    const viaCasa = resolveDrivers({
      quality: quality({ is_bank: true, casa: 41.0 }),
    })
    expect(viaCasa[0].label).toBe("Deposit mix")
    expect(viaCasa[0].value).toBe("41.0%")

    const viaCti = resolveDrivers({
      quality: quality({ is_bank: true, cost_to_income: 38.2 }),
    })
    expect(viaCti[0].label).toBe("Efficiency")
    expect(viaCti[0].context).toBe("Cost-to-income runs at 38.2%.")
  })
})

describe("resolveDrivers — non-bank chains", () => {
  it("converts the decimal revenue CAGR to percent and carries sector ROE context", () => {
    const drivers = resolveDrivers({
      quality: quality({ revenue_cagr_3y: 0.124, roe: 17.2 }),
      sectorMedians: MEDIANS,
      fcfYield: 4.8,
    })
    expect(drivers.map((d) => d.key)).toEqual(["growth", "returns", "cash"])
    // 0.124 on the wire → 12.4% displayed.
    expect(drivers[0].value).toBe("12.4%")
    expect(drivers[1].context).toContain("against a sector median of 14.2%")
    expect(drivers[2].label).toBe("Cash generation")
    expect(drivers[2].value).toBe("4.8%")
  })

  it("falls back ROE → ROCE for the returns slot", () => {
    const drivers = resolveDrivers({
      quality: quality({ revenue_cagr_3y: 0.08, roce: 21.0 }),
    })
    expect(drivers.map((d) => d.key)).toEqual(["growth", "returns"])
    expect(drivers[1].context).toBe("Return on capital employed reads 21.0%.")
  })

  it("re-uses ROCE as the capital-efficiency card when ROE took the returns slot", () => {
    const drivers = resolveDrivers({
      quality: quality({ roe: 17.2, roce: 21.0 }),
      fcfYield: null,
    })
    expect(drivers.map((d) => d.key)).toEqual(["returns", "cash"])
    expect(drivers[1].label).toBe("Capital efficiency")
  })

  it("omits sector context when the median is unavailable", () => {
    const drivers = resolveDrivers({ quality: quality({ roe: 17.2 }) })
    expect(drivers[0].context).toBe("Return on equity reads 17.2%.")
  })
})

describe("ValuationDrivers — render + self-hide", () => {
  it("self-hides when fewer than 2 drivers survive", () => {
    render(<ValuationDrivers quality={quality({ roe: 17.2 })} />)
    expect(screen.queryByTestId("iv-drivers")).toBeNull()
  })

  it("renders one card per resolved driver when 2+ survive", () => {
    render(
      <ValuationDrivers
        quality={quality({ revenue_cagr_3y: 0.124, roe: 17.2 })}
        sectorMedians={MEDIANS}
        fcfYield={4.8}
      />,
    )
    expect(screen.getByTestId("iv-drivers")).toBeInTheDocument()
    expect(screen.getByTestId("iv-driver-growth").textContent).toContain(
      "12.4%",
    )
    expect(screen.getByTestId("iv-driver-returns").textContent).toContain(
      "17.2%",
    )
    expect(screen.getByTestId("iv-driver-cash").textContent).toContain("4.8%")
  })
})
