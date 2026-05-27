// frontend/src/lib/personalization.ts
//
// Phase 4 (2026-05-25) — investing-style personalization layer.
//
// Each user picks one of five investing styles (or skips). The pick is
// stored in localStorage and changes:
//   • Summary-tab section ORDER
//   • Which sections start EXPANDED
//   • Accent colour on numbered section headers / dividers / chrome only
//     (verdict cascade still wins on the hero — see CollapsibleSection)
//   • Whether per-section explainer notes show under each header
//     (Beginner mode only)
//
// IMPORTANT: existing users (no style picked) must see zero behaviour
// change. CONFIGS[null] is not a thing — the AnalysisBody falls back to
// the legacy hard-coded ordering and starts every section expanded.
//
// SEBI-safe vocabulary: no directive verbs, no "guaranteed", no
// performance promises. Beginner explainers are educational only.

export type InvestingStyle =
  | "value"
  | "growth"
  | "income"
  | "beginner"
  | "speculator"

export type SectionKey =
  | "insight_cards"
  | "red_flags"
  | "bulls_bears"
  | "honest_card"
  | "scenarios"
  | "compounded_growth"
  | "financials_chart"
  | "reverse_dcf"
  | "dividends"
  | "news"
  | "earnings_calls"
  | "community"
  | "peers"

export interface PersonalizationConfig {
  sectionOrder: SectionKey[]
  defaultExpanded: SectionKey[]
  accentHue: "slate" | "emerald" | "amber" | "sky" | "rose"
  showSectionExplainers: boolean // Beginner only
  showTechnicals: boolean // forward-looking, currently no-op
}

// Legacy / "no style picked" canonical order. Mirrors the order rendered
// today in AnalysisBody.tsx Summary tab so existing users see zero diff.
export const DEFAULT_SECTION_ORDER: SectionKey[] = [
  "insight_cards",
  "red_flags",
  "scenarios",
  "bulls_bears",
  "honest_card",
  "peers",
  "compounded_growth",
  "financials_chart",
  "reverse_dcf",
  "dividends",
  "news",
  "earnings_calls",
  "community",
]

// Plain-English, SEBI-safe explainers. Shown only in Beginner mode under
// each section header via the [ⓘ What this means] expander. Keep these
// educational ("what is this metric") not directive.
export const SECTION_EXPLAINERS: Record<SectionKey, string> = {
  insight_cards:
    "These cards summarise the company's key signals — valuation, quality, growth, and dividends — at a glance. Each card pulls from the same audited data shown deeper on the page.",
  red_flags:
    "Red flags are automated warnings — promoter pledge above thresholds, declining margins, audit notes — surfaced from the company's own filings. They are signals, not verdicts.",
  bulls_bears:
    "Bulls Say lists arguments for the company's long-term durability. Bears Say lists the counter-arguments. Both are auto-generated from the company's own fundamentals so you can weigh them yourself.",
  honest_card:
    "A transparency panel showing what we are confident about, our best estimate, where the model could be wrong, and three conditions that would change the verdict. No hidden assumptions.",
  scenarios:
    "Bear, base, and bull scenarios show the range of fair values our DCF model produces under different assumptions. The spread tells you how sensitive the valuation is to inputs.",
  compounded_growth:
    "Compounded annual growth rate (CAGR) shows the average yearly rate at which Revenue, Profit, or ROE grew over time. Higher numbers mean faster expansion; consistency matters as much as the rate.",
  financials_chart:
    "A 10-year view of revenue, net profit, and free cash flow side-by-side. Reading the three series together shows whether top-line growth is translating into earnings and cash, or stalling at one of the steps.",
  reverse_dcf:
    "Reverse DCF inverts the question: instead of asking what the stock is worth, it asks what growth rate the current price implies. Compare that to historical growth to judge whether expectations are reasonable.",
  dividends:
    "Dividend yield = annual dividend per share ÷ current stock price. Payout ratio shows what percentage of profit is paid as dividends. Consecutive-years count signals dividend discipline.",
  news:
    "Recent filings and news, source-tiered by relevance. Use these to check whether the headline numbers have been overtaken by events since the last filing.",
  earnings_calls:
    "Management commentary from the latest earnings call — guidance, capital-allocation tone, and analyst pushback. Tone often matters more than the prepared remarks.",
  community:
    "How other YieldIQ users are reading this name. Aggregated views from the community — not investment advice, just a sentiment signal.",
  peers:
    "A sortable comparison against the closest cohort by sector and market-cap band. Use it to see how price, fair value, discount-to-FV, P/E and ROE line up across comparable names.",
}

// Reading-style → display number for the numbered section header. The
// header retains its uppercase numeric prefix ("1. VALUATION SCENARIOS")
// but the count is dynamic based on the personalised order so users
// never see "5." before "1.".
//
// Mapping is content-derived: each SectionKey carries its canonical
// uppercase title + caption. CollapsibleSection consumes these.
export const SECTION_TITLES: Record<SectionKey, { title: string; caption: string }> = {
  insight_cards: {
    title: "AT-A-GLANCE",
    caption: "Key valuation, quality, and growth signals at the top of the page.",
  },
  red_flags: {
    title: "RED FLAGS",
    caption: "Automated warnings surfaced from the company's own filings.",
  },
  bulls_bears: {
    title: "BULL / BEAR THESIS",
    caption: "Auto-generated thesis bullets pulled from the company's fundamentals.",
  },
  honest_card: {
    title: "THE HONEST CARD",
    caption:
      "What we're confident about, our best estimate, where we could be wrong, and what would change our mind.",
  },
  scenarios: {
    title: "VALUATION SCENARIOS",
    caption:
      "Bear, base and bull fair value scenarios from a discounted cash flow model with three sensitivity profiles.",
  },
  compounded_growth: {
    title: "COMPOUNDED GROWTH",
    caption: "Annualised growth rates over the trailing 3, 5 and 10 years.",
  },
  financials_chart: {
    title: "FINANCIAL STATEMENTS — 10-YEAR",
    caption: "Revenue, profit, and free cash flow side-by-side across the last 10 years.",
  },
  reverse_dcf: {
    title: "REVERSE DCF",
    caption:
      "What growth rate is the current price implying? Compare to history to gauge expectations.",
  },
  dividends: {
    title: "DIVIDENDS",
    caption: "Dividend per share history and yield context.",
  },
  news: {
    title: "RECENT NEWS",
    caption: "Latest filings and news, source-tiered for relevance.",
  },
  earnings_calls: {
    title: "EARNINGS CALLS",
    caption: "Management commentary from the latest call.",
  },
  community: {
    title: "COMMUNITY VIEW",
    caption:
      "How the YieldIQ community is reading this name. Your view, not investment advice.",
  },
  peers: {
    title: "PEERS IN THIS COHORT",
    caption:
      "How this name compares to its closest cohort on price, fair value, discount-to-FV, P/E and ROE.",
  },
}

export const CONFIGS: Record<InvestingStyle, PersonalizationConfig> = {
  value: {
    sectionOrder: [
      "insight_cards",
      "scenarios",
      "honest_card",
      "peers",
      "bulls_bears",
      "compounded_growth",
      "financials_chart",
      "reverse_dcf",
      "dividends",
      "red_flags",
      "news",
      "earnings_calls",
      "community",
    ],
    defaultExpanded: ["scenarios", "honest_card", "bulls_bears"],
    accentHue: "emerald",
    showSectionExplainers: false,
    showTechnicals: false,
  },
  growth: {
    sectionOrder: [
      "insight_cards",
      "bulls_bears",
      "scenarios",
      "compounded_growth",
      "financials_chart",
      "peers",
      "news",
      "earnings_calls",
      "honest_card",
      "reverse_dcf",
      "dividends",
      "red_flags",
      "community",
    ],
    defaultExpanded: ["bulls_bears", "compounded_growth"],
    accentHue: "amber",
    showSectionExplainers: false,
    showTechnicals: false,
  },
  income: {
    sectionOrder: [
      "insight_cards",
      "dividends",
      "honest_card",
      "scenarios",
      "peers",
      "compounded_growth",
      "financials_chart",
      "bulls_bears",
      "news",
      "red_flags",
      "reverse_dcf",
      "earnings_calls",
      "community",
    ],
    defaultExpanded: ["dividends", "honest_card"],
    accentHue: "emerald",
    showSectionExplainers: false,
    showTechnicals: false,
  },
  beginner: {
    sectionOrder: [
      "insight_cards",
      "honest_card",
      "bulls_bears",
      "peers",
      "scenarios",
      "compounded_growth",
      "financials_chart",
      "dividends",
      "red_flags",
      "news",
      "reverse_dcf",
      "earnings_calls",
      "community",
    ],
    defaultExpanded: ["honest_card", "bulls_bears"],
    accentHue: "sky",
    showSectionExplainers: true,
    showTechnicals: false,
  },
  speculator: {
    sectionOrder: [
      "insight_cards",
      "news",
      "scenarios",
      "peers",
      "bulls_bears",
      "compounded_growth",
      "financials_chart",
      "earnings_calls",
      "honest_card",
      "red_flags",
      "reverse_dcf",
      "dividends",
      "community",
    ],
    defaultExpanded: ["news", "scenarios"],
    accentHue: "rose",
    showSectionExplainers: false,
    showTechnicals: false,
  },
}

// localStorage keys — namespaced under "yq:" by convention.
const STORAGE_KEY = "yq:investing-style"
const SKIP_SENTINEL = "__skipped__"
const BANNER_KEY = "yq:personalization-banner-dismissed"

export function getStyleFromStorage(): InvestingStyle | null {
  if (typeof window === "undefined") return null
  try {
    const v = window.localStorage.getItem(STORAGE_KEY)
    if (!v || v === SKIP_SENTINEL) return null
    if (v === "value" || v === "growth" || v === "income" || v === "beginner" || v === "speculator") {
      return v
    }
    return null
  } catch {
    return null
  }
}

/** True only when the user has interacted with the picker at least once
 *  (picked a style OR explicitly skipped). Drives whether the first-visit
 *  modal opens automatically. */
export function hasUserSeenPicker(): boolean {
  if (typeof window === "undefined") return true // SSR: don't pop modal
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== null
  } catch {
    return true
  }
}

export function setStyleInStorage(style: InvestingStyle): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(STORAGE_KEY, style)
  } catch {
    /* quota / safari private mode — silently no-op */
  }
}

export function markPickerSkipped(): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(STORAGE_KEY, SKIP_SENTINEL)
  } catch {
    /* no-op */
  }
}

export function clearStyle(): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.removeItem(STORAGE_KEY)
    window.localStorage.removeItem(BANNER_KEY)
  } catch {
    /* no-op */
  }
}

export function isBannerDismissed(): boolean {
  if (typeof window === "undefined") return true
  try {
    return window.localStorage.getItem(BANNER_KEY) === "1"
  } catch {
    return true
  }
}

export function dismissBanner(): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(BANNER_KEY, "1")
  } catch {
    /* no-op */
  }
}

// User-facing labels for the picker modal + preferences page. Kept here
// so the modal and the preferences screen never drift.
export const STYLE_META: Record<
  InvestingStyle,
  { emoji: string; label: string; description: string }
> = {
  value: {
    emoji: "🧮",
    label: "Value",
    description: "Focus on margin of safety and discounted cash flow.",
  },
  growth: {
    emoji: "🚀",
    label: "Growth",
    description: "Lead with compounding, recent momentum, and forward catalysts.",
  },
  income: {
    emoji: "💰",
    label: "Income",
    description: "Dividends, payout consistency, and yield context first.",
  },
  beginner: {
    emoji: "🧭",
    label: "Beginner",
    description:
      "Plain-English explainers under every section. Honest Card and thesis on top.",
  },
  speculator: {
    emoji: "⚡",
    label: "Active",
    description: "News and scenarios lead — for users tracking short-term catalysts.",
  },
}

// Accent palette → Tailwind class fragments. Verdict cascade wins on
// the hero; these classes apply only to the numbered numeral, the
// section divider line, and personalisation chrome. Keep contained.
export const ACCENT_CLASSES: Record<
  PersonalizationConfig["accentHue"],
  { numeral: string; divider: string; chip: string }
> = {
  slate: {
    numeral: "text-slate-500",
    divider: "border-slate-300 dark:border-slate-700",
    chip: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
  },
  emerald: {
    numeral: "text-emerald-600 dark:text-emerald-400",
    divider: "border-emerald-300 dark:border-emerald-800",
    chip: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200",
  },
  amber: {
    numeral: "text-amber-600 dark:text-amber-400",
    divider: "border-amber-300 dark:border-amber-800",
    chip: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-200",
  },
  sky: {
    numeral: "text-sky-600 dark:text-sky-400",
    divider: "border-sky-300 dark:border-sky-800",
    chip: "bg-sky-50 text-sky-700 dark:bg-sky-950 dark:text-sky-200",
  },
  rose: {
    numeral: "text-rose-600 dark:text-rose-400",
    divider: "border-rose-300 dark:border-rose-800",
    chip: "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-200",
  },
}
