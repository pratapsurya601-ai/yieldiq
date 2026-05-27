import { describe, it, expect } from "vitest"
import {
  metricTone,
  metricToneClass,
  metricToneTextClass,
} from "@/lib/metricTone"

describe("metricTone — relative metrics (PE / PB)", () => {
  it("returns neutral when sectorMedian is missing", () => {
    expect(metricTone({ metric: "pe", value: 17 })).toBe("neutral")
    expect(metricTone({ metric: "pb", value: 5, sectorMedian: null })).toBe(
      "neutral",
    )
  })

  it("scores PE relative to sector median", () => {
    // TCS PE 17 vs sector 22 -> ratio 0.77 -> neutral
    expect(metricTone({ metric: "pe", value: 17, sectorMedian: 22 })).toBe(
      "neutral",
    )
    // PE 10 vs sector 22 -> 0.45 -> good
    expect(metricTone({ metric: "pe", value: 10, sectorMedian: 22 })).toBe(
      "good",
    )
    // PE 22 vs sector 22 -> 1.0 -> warn
    expect(metricTone({ metric: "pe", value: 22, sectorMedian: 22 })).toBe(
      "warn",
    )
    // PE 35 vs sector 22 -> 1.59 -> bad
    expect(metricTone({ metric: "pe", value: 35, sectorMedian: 22 })).toBe(
      "bad",
    )
  })

  it("treats non-positive values as neutral for PE/PB", () => {
    expect(metricTone({ metric: "pe", value: 0, sectorMedian: 20 })).toBe(
      "neutral",
    )
    expect(metricTone({ metric: "pe", value: -3, sectorMedian: 20 })).toBe(
      "neutral",
    )
  })
})

describe("metricTone — ROE", () => {
  it("places TCS-style 45% in good", () => {
    expect(metricTone({ metric: "roe", value: 45.9 })).toBe("good")
  })
  it("returns neutral / warn / bad on stepped values", () => {
    expect(metricTone({ metric: "roe", value: 15 })).toBe("neutral")
    expect(metricTone({ metric: "roe", value: 7 })).toBe("warn")
    expect(metricTone({ metric: "roe", value: 1 })).toBe("bad")
  })
})

describe("metricTone — Payout", () => {
  it("flags >100% payout as bad (unsustainable)", () => {
    expect(metricTone({ metric: "payout", value: 104 })).toBe("bad")
  })
  it("scores healthy 30-70% as good", () => {
    expect(metricTone({ metric: "payout", value: 45 })).toBe("good")
  })
  it("scores rich 70-100% as warn", () => {
    expect(metricTone({ metric: "payout", value: 85 })).toBe("warn")
  })
  it("returns neutral for lean (<30) and missing", () => {
    expect(metricTone({ metric: "payout", value: 12 })).toBe("neutral")
    expect(metricTone({ metric: "payout", value: 0 })).toBe("neutral")
    expect(metricTone({ metric: "payout", value: null })).toBe("neutral")
  })
})

describe("metricTone — Dividend Yield", () => {
  it("scores stepped bands", () => {
    expect(metricTone({ metric: "div_yield", value: 5 })).toBe("good")
    expect(metricTone({ metric: "div_yield", value: 2.5 })).toBe("neutral")
    expect(metricTone({ metric: "div_yield", value: 0.5 })).toBe("warn")
    expect(metricTone({ metric: "div_yield", value: 0 })).toBe("bad")
  })
})

describe("metricTone — Piotroski F-Score", () => {
  it("scores 8-9 as good, 6-7 neutral, 4-5 warn, 0-3 bad", () => {
    expect(metricTone({ metric: "fscore", value: 9 })).toBe("good")
    expect(metricTone({ metric: "fscore", value: 7 })).toBe("neutral")
    expect(metricTone({ metric: "fscore", value: 4 })).toBe("warn")
    expect(metricTone({ metric: "fscore", value: 2 })).toBe("bad")
  })
})

describe("metricTone — Worry Index", () => {
  it("treats lower as calmer", () => {
    expect(metricTone({ metric: "worry", value: 24 })).toBe("good")
    expect(metricTone({ metric: "worry", value: 45 })).toBe("neutral")
    expect(metricTone({ metric: "worry", value: 60 })).toBe("warn")
    expect(metricTone({ metric: "worry", value: 80 })).toBe("bad")
  })
})

describe("metricTone — Debt/Equity and Op Margin", () => {
  it("debt_equity steps from good to bad as leverage rises", () => {
    expect(metricTone({ metric: "debt_equity", value: 0.2 })).toBe("good")
    expect(metricTone({ metric: "debt_equity", value: 0.8 })).toBe("neutral")
    expect(metricTone({ metric: "debt_equity", value: 1.5 })).toBe("warn")
    expect(metricTone({ metric: "debt_equity", value: 3 })).toBe("bad")
  })
  it("op_margin uses the same bands as ROE", () => {
    expect(metricTone({ metric: "op_margin", value: 25 })).toBe("good")
    expect(metricTone({ metric: "op_margin", value: 15 })).toBe("neutral")
    expect(metricTone({ metric: "op_margin", value: 7 })).toBe("warn")
    expect(metricTone({ metric: "op_margin", value: 1 })).toBe("bad")
  })
})

describe("metricTone — null / NaN safety", () => {
  it("returns neutral for null / undefined / NaN / Infinity", () => {
    expect(metricTone({ metric: "roe", value: null })).toBe("neutral")
    expect(metricTone({ metric: "roe", value: undefined })).toBe("neutral")
    expect(metricTone({ metric: "roe", value: NaN })).toBe("neutral")
    expect(metricTone({ metric: "roe", value: Infinity })).toBe("neutral")
  })
})

describe("metricToneClass / metricToneTextClass — Tailwind tokens", () => {
  it("emits the documented light+dark Tailwind classes", () => {
    expect(metricToneTextClass("good")).toBe(
      "text-green-600 dark:text-green-400",
    )
    expect(metricToneTextClass("neutral")).toBe(
      "text-slate-700 dark:text-slate-300",
    )
    expect(metricToneTextClass("warn")).toBe(
      "text-amber-600 dark:text-amber-400",
    )
    expect(metricToneTextClass("bad")).toBe("text-red-600 dark:text-red-400")
  })
  it("metricToneClass composes tone + class in one call", () => {
    expect(metricToneClass({ metric: "payout", value: 104 })).toBe(
      "text-red-600 dark:text-red-400",
    )
    expect(metricToneClass({ metric: "fscore", value: 7 })).toBe(
      "text-slate-700 dark:text-slate-300",
    )
  })
})
