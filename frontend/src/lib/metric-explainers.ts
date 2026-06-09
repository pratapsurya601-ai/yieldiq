// metric-explainers.ts — Premium Feel R2.
//
// Single source of truth for the inline `<MetricTooltip metric=...>` copy
// mounted across the analysis page. Independent from
// `metric_explanations.ts` (which feeds the older "?" icon tooltip and
// is wired to the backend FormulaSpec contract).
//
// Why two files? See the brief: R2 ships AlphaSpread-style
// label+value-as-trigger hover popovers on top of the existing
// "?" icon system, not as a replacement. Keeping the copy files
// separate lets us tune the AlphaSpread layer without touching the
// backend-mirrored older surface.
//
// SEBI vocabulary discipline: every string in this file is scanned by
// scripts/check_sebi_words.py on PR. The authoritative banned-vocabulary
// list lives in that script. Acceptable replacements: prefer "above the
// sector median" over directional adjectives, "trading at a premium" for
// rich multiples, "currently above the model's value estimate" for
// above-fair-value descriptions, and "potential signal" for any phrase
// that would otherwise be advisory.
//
// Copy budget per entry: under 60 words total (description + threshold
// + caveat). Users scan, they don't read.

export interface MetricExplainer {
  /** Popover heading — full name + acronym where the label is short. */
  title: string
  /**
   * 1-2 sentence plain-English description, under 40 words.
   * Says WHAT the number measures, in retail-investor English.
   */
  description: string
  /** Optional textbook formula, one line, no prose. */
  formula?: string
  /** Optional typical-range / context line. */
  threshold?: string
  /** Optional caveat — what this metric does NOT tell you. */
  caveat?: string
}

export const METRIC_EXPLAINERS: Record<string, MetricExplainer> = {
  // ───────────────────────────────────────────────────────────────────
  // Profitability
  // ───────────────────────────────────────────────────────────────────
  roe: {
    title: "Return on Equity (ROE)",
    description:
      "Profit generated for every rupee of shareholder equity — the headline measure of capital efficiency for equity owners.",
    formula: "Net Income ÷ Shareholder Equity × 100",
    threshold: "Above 15% is typical for established large-caps; above 20% is in the top decile.",
    caveat:
      "Leverage inflates ROE — a highly levered company can post the same ROE as a debt-free one with very different risk.",
  },
  roa: {
    title: "Return on Assets (ROA)",
    description:
      "Profit earned per rupee of total assets — the cleanest single measure of how productively a bank or asset-heavy business runs its balance sheet.",
    formula: "Net Income ÷ Total Assets × 100",
    threshold: "Indian banks: above 1.4% is healthy, around 1.0% is typical, below 0.6% is well below the sector median.",
    caveat:
      "ROA is the right lens for banks and capital-heavy businesses; for asset-light firms, ROE / ROCE reads more cleanly.",
  },

  // ───────────────────────────────────────────────────────────────────
  // Valuation multiples
  // ───────────────────────────────────────────────────────────────────
  pe: {
    title: "Price ÷ Earnings (P/E)",
    description:
      "How many rupees you pay today for every rupee of the company's annual profit — the most widely-quoted valuation shortcut.",
    formula: "Share Price ÷ EPS (trailing 12 months)",
    threshold: "Indian large-caps: below 15x is below the long-run average, 15-25x is typical, above 40x is a premium.",
    caveat:
      "P/E reads misleadingly for banks (use P/B), for cyclicals near peak earnings, and for loss-makers (where it is undefined).",
  },
  peg: {
    title: "PEG Ratio (P/E ÷ Growth)",
    description:
      "Adjusts P/E for earnings growth — answers whether a high multiple is justified by the pace at which profits are compounding.",
    formula: "P/E Ratio ÷ Annual EPS Growth Rate (%)",
    threshold: "Below 1.0 is below fair value on growth-adjusted terms; 1.0-2.0 is typical; above 2.0 is a growth premium.",
    caveat:
      "PEG breaks down when growth is negative, lumpy, or extrapolated from one bumper year — verify the denominator before reading the ratio.",
  },
  mos: {
    title: "Margin of Safety (MoS)",
    description:
      "The gap between the current price and our fair-value estimate, in percent. A larger gap leaves more room for the model to be wrong.",
    formula: "(Fair Value − Current Price) ÷ Current Price × 100",
    threshold: "Above +30% is a deep discount to our model fair value; -10% to +10% sits roughly at fair value; below -20% is well above it.",
    caveat:
      "MoS is only as honest as the DCF inputs — treat it as a centre of gravity, not a precise number. A discount with deteriorating quality often indicates a value trap.",
  },

  // ───────────────────────────────────────────────────────────────────
  // Quality scores
  // ───────────────────────────────────────────────────────────────────
  piotroski: {
    title: "Piotroski F-Score",
    description:
      "A 0-9 scorecard that checks nine fundamental health signals: profitability, leverage trend, and operating efficiency.",
    formula: "Sum of 9 pass/fail checks (profitability, leverage, efficiency)",
    threshold: "7-9 reads as fundamentally durable, 4-6 as mixed, 0-3 as deteriorating fundamentals.",
    caveat:
      "F-Score reads the last fiscal year only — it does not capture forward-looking risks like a pending sector shock or management change.",
  },
  confidence: {
    title: "Confidence Score",
    description:
      "Our model's data-quality signal — a weighted blend of input completeness, peer cohort size, freshness, and model fit. Higher means more inputs are available.",
    formula:
      "weighted(financials_completeness, peer_cohort_size, data_freshness, model_fit)",
    threshold:
      "Above 70 means most inputs are present; 40-70 means partial data; below 40 surfaces an Under Review banner instead of a fair value.",
    caveat:
      "Confidence reflects what we know about the inputs — NOT a probability that the fair value is correct. A high-confidence model can still be wrong about the future.",
  },
  yieldiq_score: {
    title: "YieldIQ Score",
    description:
      "A 0-100 composite score that blends our valuation, quality, growth, and safety axes into one descriptive number. Reflects the model's view of fundamentals at a point in time.",
    threshold: "Above 75 is high across the board; 55-75 is mixed with trade-offs; 35-55 has multiple factors to read; below 35 surfaces multiple model flags.",
    caveat:
      "Not a prediction of returns and not investment advice. A business can score low simply by trading above our model fair value, even if the underlying fundamentals are durable.",
  },

  // ───────────────────────────────────────────────────────────────────
  // DCF model inputs
  // ───────────────────────────────────────────────────────────────────
  wacc: {
    title: "Weighted Average Cost of Capital (WACC)",
    description:
      "The blended return investors expect for funding this company — we use it as the discount rate to bring future cash flows back to today's rupees.",
    formula: "(E/V × Re) + (D/V × Rd × (1 − tax))",
    threshold: "Typical Indian equities: 10-14%. Small-caps or levered businesses sit at 14-18%; regulated utilities at 9-11%.",
    caveat:
      "A higher WACC shrinks the DCF fair value — the choice of WACC matters as much as the cash-flow forecast itself.",
  },
  terminal_growth: {
    title: "Terminal Growth Rate",
    description:
      "The perpetual growth rate we assume after the explicit forecast window ends — the rate at which the business compounds forever in the model.",
    formula: "Long-run nominal growth rate (e.g. 3-5% in INR terms)",
    threshold: "Typical range: 3-5% for Indian equities, roughly long-run nominal GDP. Above 6% implies the firm outgrows the economy in perpetuity (rarely realistic).",
    caveat:
      "Terminal value often makes up 60-80% of total DCF value, so this tiny number drives the entire fair-value figure more than you would guess.",
  },
  beta: {
    title: "Beta",
    description:
      "A statistical measure of how much the stock moves relative to the broader market. 1.0 means it moves in lock-step; higher means it amplifies market moves.",
    formula: "Covariance(stock returns, market returns) ÷ Variance(market returns)",
    threshold: "Defensive names (FMCG, utilities): 0.6-0.9. Market-like: 0.9-1.1. High-beta cyclicals and small-caps: 1.2-1.8+.",
    caveat:
      "Historical beta is a backward-looking statistical fit — it can shift sharply when the business mix changes or after a major capital event.",
  },

  // ───────────────────────────────────────────────────────────────────
  // Balance-sheet health
  // ───────────────────────────────────────────────────────────────────
  de_ratio: {
    title: "Debt ÷ Equity (D/E)",
    description:
      "Total debt relative to shareholder equity — measures how much the business is funded by lenders versus equity holders.",
    formula: "Total Debt ÷ Shareholder Equity",
    threshold: "Below 0.5 is lightly levered; 0.5-1.0 is moderate; above 1.5 is a levered balance sheet.",
    caveat:
      "Not meaningful for banks (deposits are not debt). Capital-intensive businesses (infra, utilities) tolerate higher D/E because cash flows are more predictable.",
  },
  current_ratio: {
    title: "Current Ratio",
    description:
      "Short-term assets versus short-term liabilities — measures whether the company can cover what it owes in the next 12 months.",
    formula: "Current Assets ÷ Current Liabilities",
    threshold: "Above 1.5 is comfortable, 1.0-1.5 is adequate, below 1.0 means a near-term liquidity squeeze is possible.",
    caveat:
      "Very high readings (above 3.0) can also mean idle working capital that the business is not deploying productively.",
  },
  interest_coverage: {
    title: "Interest Coverage",
    description:
      "How many times operating profit covers the interest bill — the cushion before the company struggles to service its debt.",
    formula: "EBIT ÷ Interest Expense",
    threshold: "Above 5x is comfortable, 2-5x is adequate, 1-2x is stretched, below 1x means EBIT does not cover the interest bill.",
    caveat:
      "A single down year can drop coverage sharply — read it in trend with the debt level, not as a one-period snapshot.",
  },

  // ───────────────────────────────────────────────────────────────────
  // Efficiency & cash flow
  // ───────────────────────────────────────────────────────────────────
  asset_turnover: {
    title: "Asset Turnover",
    description:
      "Revenue generated per rupee of total assets — high readings indicate a capital-efficient business model.",
    formula: "Revenue ÷ Total Assets",
    threshold: "FMCG / IT services: 1.5-2.0+. Industrials: 0.5-1.0. Banks and infrastructure: below 0.5 by design.",
    caveat:
      "Compare within the same sector only — cross-sector comparison is misleading because business models structurally differ in capital intensity.",
  },
  fcf_revenue: {
    title: "Free Cash Flow ÷ Revenue",
    description:
      "The share of every rupee of revenue that converts into cash after operating costs and capex — the cleanest single measure of cash-generation quality.",
    formula: "Free Cash Flow ÷ Revenue × 100",
    threshold: "Above 15% is a high cash-conversion business; 5-15% is typical; below 5% means most revenue is consumed by operations or reinvestment.",
    caveat:
      "Year-to-year FCF can swing on working-capital and capex timing — read the 3-5 year average rather than the latest year alone.",
  },

  // ───────────────────────────────────────────────────────────────────
  // Optional YieldIQ extras
  // ───────────────────────────────────────────────────────────────────
  bull_case: {
    title: "Bull Case Fair Value",
    description:
      "The high end of our DCF range — what the stock is worth if growth accelerates and margins expand from here.",
    threshold: "Current price above bull case = market is pricing in the upside scenario in full; below base case = market is pricing in disappointment.",
    caveat:
      "Bull / bear cases are sensitivity scenarios from the same DCF engine, not separate forecasts — they share the same input bias the base case has.",
  },
  bear_case: {
    title: "Bear Case Fair Value",
    description:
      "The low end of our DCF range — what the stock is worth if growth disappoints and margins compress from here.",
    threshold: "Current price below bear case = the market may already be pricing in the downside scenario. Above bear case = there is room for things to go wrong.",
    caveat:
      "A bear case is not a forecast of where the price will go — it is a downside boundary of our model assumptions only.",
  },
}

// Convenience helper. Returns the explainer or null. Components treat
// null as "no tooltip; render the value plainly."
export function getMetricExplainer(key: string): MetricExplainer | null {
  return METRIC_EXPLAINERS[key] ?? null
}
