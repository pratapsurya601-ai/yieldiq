import { describe, it, expect } from "vitest"
import {
  formatINR,
  formatCrore,
  formatPct,
  formatMultiple,
  formatCompactCount,
} from "@/lib/formatNumbers"

const DASH = "—" // em-dash fallback

describe("formatINR — per-share / absolute rupee amounts", () => {
  it("formats per-share prices with Indian grouping and 2 decimals max", () => {
    expect(formatINR(1147.77)).toBe("₹1,147.77")
    expect(formatINR(746)).toBe("₹746")
    expect(formatINR(123456.5)).toBe("₹1,23,456.5")
  })

  it("places the minus sign before the rupee symbol", () => {
    expect(formatINR(-980.5)).toBe("-₹980.5")
  })

  it("handles zero", () => {
    expect(formatINR(0)).toBe("₹0")
  })

  it("compacts huge amounts to Lakh Cr / Cr / L tiers", () => {
    expect(formatINR(1.15e13, { compact: true })).toBe("₹11.50 Lakh Cr")
    expect(formatINR(6.2227e11, { compact: true })).toBe("₹62,227 Cr")
    expect(formatINR(2.5e5, { compact: true })).toBe("₹2.50 L")
    expect(formatINR(-1.44e11, { compact: true })).toBe("-₹14,400 Cr")
    expect(formatINR(1.44e12, { compact: true })).toBe("₹1.44 Lakh Cr")
  })

  it("leaves small amounts un-compacted even in compact mode", () => {
    expect(formatINR(99_999, { compact: true })).toBe("₹99,999")
  })

  it("returns em-dash for null / undefined / NaN / Infinity", () => {
    expect(formatINR(null)).toBe(DASH)
    expect(formatINR(undefined)).toBe(DASH)
    expect(formatINR(NaN)).toBe(DASH)
    expect(formatINR(Infinity)).toBe(DASH)
  })
})

describe("formatCrore — crore-denominated amounts", () => {
  it("formats the three compaction tiers", () => {
    expect(formatCrore(1_150_000)).toBe("₹11.50 Lakh Cr")
    expect(formatCrore(62_227)).toBe("₹62,227 Cr")
    expect(formatCrore(850.44)).toBe("₹850.4 Cr")
    expect(formatCrore(0.42)).toBe("₹0.42 Cr")
  })

  it("keeps Indian digit grouping on the plain-Cr tier", () => {
    expect(formatCrore(14_400)).toBe("₹14,400 Cr")
    expect(formatCrore(123_456 / 10)).toBe("₹12,346 Cr")
  })

  it("supports negatives with the sign before the rupee symbol", () => {
    expect(formatCrore(-14_400)).toBe("-₹14,400 Cr")
    expect(formatCrore(-0.5)).toBe("-₹0.50 Cr")
  })

  it("handles zero and huge values", () => {
    expect(formatCrore(0)).toBe("₹0.00 Cr")
    expect(formatCrore(98_700_000)).toBe("₹987.00 Lakh Cr")
  })

  it("returns em-dash for unusable input", () => {
    expect(formatCrore(null)).toBe(DASH)
    expect(formatCrore(undefined)).toBe(DASH)
    expect(formatCrore(NaN)).toBe(DASH)
    expect(formatCrore(-Infinity)).toBe(DASH)
  })
})

describe("formatPct — percentage values", () => {
  it("is unsigned by default (ratios like payout)", () => {
    expect(formatPct(26)).toBe("26.0%")
    expect(formatPct(26, { decimals: 0 })).toBe("26%")
  })

  it("adds explicit sign for deltas when signed", () => {
    expect(formatPct(53.7, { signed: true })).toBe("+53.7%")
    expect(formatPct(-12.34, { signed: true })).toBe("-12.3%")
    expect(formatPct(0, { signed: true })).toBe("+0.0%")
  })

  it("keeps the minus sign on unsigned negatives", () => {
    expect(formatPct(-3.9)).toBe("-3.9%")
  })

  it("returns em-dash for unusable input", () => {
    expect(formatPct(null)).toBe(DASH)
    expect(formatPct(undefined, { signed: true })).toBe(DASH)
    expect(formatPct(NaN)).toBe(DASH)
    expect(formatPct(Infinity)).toBe(DASH)
  })
})

describe("formatMultiple — valuation multiples", () => {
  it("formats with one decimal and x suffix", () => {
    expect(formatMultiple(16.7)).toBe("16.7x")
    expect(formatMultiple(0)).toBe("0.0x")
    expect(formatMultiple(2.345, 2)).toBe("2.35x")
    expect(formatMultiple(-0.8)).toBe("-0.8x")
  })

  it("returns em-dash for unusable input", () => {
    expect(formatMultiple(null)).toBe(DASH)
    expect(formatMultiple(undefined)).toBe(DASH)
    expect(formatMultiple(NaN)).toBe(DASH)
  })
})

describe("formatCompactCount — plain counts", () => {
  it("rounds and applies Indian grouping", () => {
    expect(formatCompactCount(13_982)).toBe("13,982")
    expect(formatCompactCount(123_456)).toBe("1,23,456")
    expect(formatCompactCount(12.7)).toBe("13")
    expect(formatCompactCount(0)).toBe("0")
    expect(formatCompactCount(-2_500)).toBe("-2,500")
  })

  it("returns em-dash for unusable input", () => {
    expect(formatCompactCount(null)).toBe(DASH)
    expect(formatCompactCount(undefined)).toBe(DASH)
    expect(formatCompactCount(NaN)).toBe(DASH)
  })
})
