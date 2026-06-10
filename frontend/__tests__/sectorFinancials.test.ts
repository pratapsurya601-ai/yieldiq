/**
 * Sector-aware financial-field resolver tests.
 *
 * Pins the bank-cohort behaviour described in
 * frontend/src/lib/sectorFinancials.ts:
 *
 *   - Bank ticker -> getDisplayRevenue() falls back to interest_earned
 *     / net_interest_income / total_income when `revenue` is null.
 *   - Bank ticker -> getDisplayFCF() returns null (FCF not meaningful
 *     for the cohort) regardless of whether the row carries a value.
 *   - Bank ticker -> getDisplayRevenueLabel() returns
 *     "Net Interest Income", not "Revenue".
 *   - Insurance ticker -> getDisplayRevenueLabel() returns
 *     "Net Premium Income".
 *   - Generic ticker -> resolvers fall through to the conventional
 *     `revenue` / `free_cash_flow` fields with the "Revenue" / "Free
 *     Cash Flow" labels.
 */
import { describe, it, expect } from "vitest"
import {
  getDisplayRevenue,
  getDisplayRevenueLabel,
  getDisplayFCF,
  getDisplayFCFLabel,
  getFCFNotApplicableNote,
  isBankSector,
  isFinancialCohort,
} from "@/lib/sectorFinancials"

describe("sectorFinancials cohort detection", () => {
  it("identifies HDFCBANK as a bank via the canonical ticker list", () => {
    expect(isBankSector(null, "HDFCBANK")).toBe(true)
    expect(isFinancialCohort(null, "HDFCBANK")).toBe(true)
  })
  it("identifies sector strings case-insensitively", () => {
    expect(isBankSector("Banking", null)).toBe(true)
    expect(isBankSector("private bank", null)).toBe(true)
    expect(isBankSector("PSU Bank", null)).toBe(true)
  })
  it("returns false for non-bank tickers and sectors", () => {
    expect(isBankSector("IT Services", "TCS")).toBe(false)
    expect(isBankSector("FMCG", "ITC")).toBe(false)
    expect(isFinancialCohort("Pharma", "SUNPHARMA")).toBe(false)
  })
})

describe("getDisplayRevenue", () => {
  it("uses interest_earned for HDFCBANK when revenue is null", () => {
    const row = {
      revenue: null,
      interest_earned: 132_034,
      net_interest_income: 89_780,
      total_income: 198_005,
      free_cash_flow: null,
    }
    expect(getDisplayRevenue(row, "Banking", "HDFCBANK")).toBe(132_034)
  })
  it("falls back to net_interest_income when interest_earned is missing", () => {
    const row = {
      revenue: null,
      interest_earned: null,
      net_interest_income: 89_780,
      total_income: 198_005,
    }
    expect(getDisplayRevenue(row, null, "HDFCBANK")).toBe(89_780)
  })
  it("falls back to total_income when only that is present", () => {
    const row = { revenue: null, total_income: 11_500 }
    expect(getDisplayRevenue(row, "Banking", null)).toBe(11_500)
  })
  it("returns conventional revenue for a non-bank row", () => {
    const row = { revenue: 65_400, interest_earned: null, free_cash_flow: 12_000 }
    expect(getDisplayRevenue(row, "FMCG", "ITC")).toBe(65_400)
  })
  it("returns null when nothing usable is on the row", () => {
    expect(getDisplayRevenue({ revenue: null }, "Banking", "HDFCBANK")).toBe(null)
    expect(getDisplayRevenue(null, "FMCG", "ITC")).toBe(null)
  })
})

describe("getDisplayRevenueLabel", () => {
  it("labels bank revenue as Net Interest Income", () => {
    expect(getDisplayRevenueLabel("Banking", "HDFCBANK")).toBe("Net Interest Income")
    expect(getDisplayRevenueLabel(null, "HDFCBANK")).toBe("Net Interest Income")
    expect(getDisplayRevenueLabel("Private Bank", null)).toBe("Net Interest Income")
  })
  it("labels insurance revenue as Net Premium Income", () => {
    expect(getDisplayRevenueLabel("Insurance", "ICICIPRULI")).toBe(
      "Net Premium Income",
    )
  })
  it("returns the generic 'Revenue' label for everything else", () => {
    expect(getDisplayRevenueLabel("IT Services", "TCS")).toBe("Revenue")
    expect(getDisplayRevenueLabel("FMCG", "ITC")).toBe("Revenue")
    expect(getDisplayRevenueLabel(null, "RELIANCE")).toBe("Revenue")
  })
})

describe("getDisplayFCF / getDisplayFCFLabel / getFCFNotApplicableNote", () => {
  it("returns null FCF for the bank cohort even when the row carries a value", () => {
    const row = { revenue: null, free_cash_flow: 1234 }
    expect(getDisplayFCF(row, "Banking", "HDFCBANK")).toBe(null)
  })
  it("returns the conventional FCF on a non-bank row", () => {
    const row = { revenue: 50000, free_cash_flow: 7800 }
    expect(getDisplayFCF(row, "FMCG", "ITC")).toBe(7800)
    expect(getDisplayFCF({ fcf: 7800 }, "FMCG", "ITC")).toBe(7800)
  })
  it("emits a not-applicable note for the bank cohort", () => {
    const note = getFCFNotApplicableNote("Banking", "HDFCBANK")
    expect(note).not.toBeNull()
    expect(note).toContain("not meaningful")
    expect(getFCFNotApplicableNote("FMCG", "ITC")).toBeNull()
  })
  it("relabels the FCF chart axis for the bank cohort", () => {
    expect(getDisplayFCFLabel("Banking", "HDFCBANK")).toContain("n/a")
    expect(getDisplayFCFLabel("IT Services", "TCS")).toBe("Free Cash Flow")
  })
})
