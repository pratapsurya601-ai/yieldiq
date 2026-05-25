/**
 * Phase 4 personalization — configuration + storage smoke tests.
 *
 * Pins:
 *   1. Every InvestingStyle has a CONFIG with all required fields.
 *   2. sectionOrder covers every SectionKey exactly once (no dupes / drops)
 *      so the dynamic renderer never silently skips a section.
 *   3. defaultExpanded is a strict subset of sectionOrder.
 *   4. getStyleFromStorage round-trips through setStyleInStorage.
 *   5. markPickerSkipped / hasUserSeenPicker semantics: skip counts as
 *      "seen" so the picker doesn't re-prompt.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import {
  CONFIGS,
  DEFAULT_SECTION_ORDER,
  SECTION_EXPLAINERS,
  STYLE_META,
  clearStyle,
  dismissBanner,
  getStyleFromStorage,
  hasUserSeenPicker,
  isBannerDismissed,
  markPickerSkipped,
  setStyleInStorage,
  type InvestingStyle,
  type SectionKey,
} from "@/lib/personalization"

const STYLES: InvestingStyle[] = [
  "value",
  "growth",
  "income",
  "beginner",
  "speculator",
]

const ALL_KEYS: SectionKey[] = [
  "insight_cards",
  "red_flags",
  "bulls_bears",
  "honest_card",
  "scenarios",
  "compounded_growth",
  "reverse_dcf",
  "dividends",
  "news",
  "earnings_calls",
  "community",
]

describe("personalization CONFIGS", () => {
  for (const style of STYLES) {
    it(`config for "${style}" covers every SectionKey exactly once`, () => {
      const cfg = CONFIGS[style]
      expect(cfg).toBeDefined()
      expect(new Set(cfg.sectionOrder).size).toBe(cfg.sectionOrder.length)
      expect(cfg.sectionOrder.slice().sort()).toEqual(ALL_KEYS.slice().sort())
    })

    it(`defaultExpanded for "${style}" is non-empty and a subset of sectionOrder`, () => {
      const cfg = CONFIGS[style]
      expect(cfg.defaultExpanded.length).toBeGreaterThan(0)
      for (const k of cfg.defaultExpanded) {
        expect(cfg.sectionOrder).toContain(k)
      }
    })

    it(`STYLE_META has a label + description for "${style}"`, () => {
      const meta = STYLE_META[style]
      expect(meta.label.length).toBeGreaterThan(0)
      expect(meta.description.length).toBeGreaterThan(0)
    })
  }

  it("Beginner enables section explainers", () => {
    expect(CONFIGS.beginner.showSectionExplainers).toBe(true)
  })

  it("non-Beginner styles do NOT enable section explainers", () => {
    for (const style of STYLES) {
      if (style === "beginner") continue
      expect(CONFIGS[style].showSectionExplainers).toBe(false)
    }
  })

  it("SECTION_EXPLAINERS covers every SectionKey", () => {
    for (const k of ALL_KEYS) {
      expect(SECTION_EXPLAINERS[k]).toBeDefined()
      expect(SECTION_EXPLAINERS[k].length).toBeGreaterThan(0)
    }
  })

  it("DEFAULT_SECTION_ORDER covers every SectionKey exactly once", () => {
    expect(new Set(DEFAULT_SECTION_ORDER).size).toBe(
      DEFAULT_SECTION_ORDER.length,
    )
    expect(DEFAULT_SECTION_ORDER.slice().sort()).toEqual(ALL_KEYS.slice().sort())
  })
})

describe("style-specific section orders (smoke)", () => {
  it("Value puts scenarios + honest_card + bulls_bears at the top", () => {
    const order = CONFIGS.value.sectionOrder
    // insight_cards is always #1 (at-a-glance row), so check positions 2-4.
    expect(order.slice(1, 4)).toEqual(["scenarios", "honest_card", "bulls_bears"])
  })

  it("Income leads with dividends after insight_cards", () => {
    expect(CONFIGS.income.sectionOrder[1]).toBe("dividends")
  })

  it("Growth leads with bulls_bears + compounded_growth", () => {
    const order = CONFIGS.growth.sectionOrder
    expect(order.slice(1, 5)).toContain("bulls_bears")
    expect(order.slice(1, 5)).toContain("compounded_growth")
  })

  it("Speculator promotes news above scenarios", () => {
    const order = CONFIGS.speculator.sectionOrder
    expect(order.indexOf("news")).toBeLessThan(order.indexOf("scenarios"))
  })

  it("Beginner places honest_card immediately after insight_cards", () => {
    expect(CONFIGS.beginner.sectionOrder[0]).toBe("insight_cards")
    expect(CONFIGS.beginner.sectionOrder[1]).toBe("honest_card")
  })
})

describe("localStorage storage helpers", () => {
  beforeEach(() => {
    window.localStorage.clear()
  })
  afterEach(() => {
    window.localStorage.clear()
  })

  it("getStyleFromStorage returns null when nothing is stored", () => {
    expect(getStyleFromStorage()).toBeNull()
    expect(hasUserSeenPicker()).toBe(false)
  })

  it("setStyleInStorage round-trips through getStyleFromStorage", () => {
    setStyleInStorage("value")
    expect(getStyleFromStorage()).toBe("value")
    expect(hasUserSeenPicker()).toBe(true)
  })

  it("markPickerSkipped flips hasUserSeenPicker without setting a style", () => {
    markPickerSkipped()
    expect(getStyleFromStorage()).toBeNull()
    expect(hasUserSeenPicker()).toBe(true)
  })

  it("clearStyle removes the stored style and the banner-dismissed flag", () => {
    setStyleInStorage("growth")
    dismissBanner()
    expect(isBannerDismissed()).toBe(true)
    clearStyle()
    expect(getStyleFromStorage()).toBeNull()
    expect(hasUserSeenPicker()).toBe(false)
    expect(isBannerDismissed()).toBe(false)
  })

  it("rejects garbage values in localStorage", () => {
    window.localStorage.setItem("yq:investing-style", "not-a-real-style")
    expect(getStyleFromStorage()).toBeNull()
  })
})
