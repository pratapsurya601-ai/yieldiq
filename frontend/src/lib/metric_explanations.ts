/**
 * metric_explanations.ts — TRANSITION FILE
 * ----------------------------------------------------------------------
 * For metrics with a backend FormulaSpec
 * (`backend/services/analysis/formulas.py`), the rendered tooltip
 * `formula` and `oneLine` MUST come from `data.formulas[key]` on the
 * analysis response — never from the strings below. The fields here
 * are the FALLBACK rendering path used only when:
 *   (a) the response predates this PR (legacy cached payload), or
 *   (b) the metric has no backend FormulaSpec yet (most of this file).
 *
 * Source-of-truth precedence inside <MetricTooltip />:
 *   1. data.formulas[metricKey].formula      (backend, always wins)
 *   2. METRIC_EXPLANATIONS[metricKey].formula (this file, fallback)
 *
 * Wired metrics (do NOT edit `formula` here without also updating the
 * corresponding FormulaSpec — the consistency test will fail):
 *   margin_of_safety / mos, fair_value, roe, roce, piotroski_score,
 *   moat_score, yieldiq_score, grade, eps_diluted, debt_to_equity.
 *
 * TODO(post-cache-rollover): once every cached payload carries
 * `formulas`, delete the `formula` and `oneLine` fields below for
 * those 10 metrics and rely entirely on the backend.
 *
 * Plain-English copy for every metric surfaced on the analysis page.
 *
 * Target reader: a retail investor with ~2 years of experience — they
 * recognise "P/E" but have never computed ROCE from an annual report.
 *
 * Copy rules (enforced by review, not by types):
 *   1. `oneLine` — ONE sentence. What this number measures, in English.
 *   2. `formula`  — the textbook definition, one line, no prose.
 *   3. `good`     — concrete numeric benchmarks ("above 20% is excellent")
 *                   — never vague language like "higher is better".
 *   4. `sectorNote` — optional. Used when the "good" range differs
 *                   meaningfully by sector (e.g. IT vs banks vs cement).
 *
 * Keep entries to 3-4 sentences total. Tooltip popovers are small;
 * users scan, they don't read.
 *
 * Adding a new entry?
 *   - Use a snake_case key that matches the backend field name where
 *     possible (e.g. `debt_ebitda`, not `debtToEbitda`).
 *   - If the metric is bank-specific, set `sectorNote` to explain the
 *     Indian-bank cohort baseline (PSU vs private vs top-private).
 */

export interface MetricExplanation {
  /** Full human title — used as the popover heading. */
  title: string
  /** One sentence: what this number represents, in English. */
  oneLine: string
  /** The textbook formula — one line, no prose. */
  formula?: string
  /** Numeric benchmarks: what counts as good, okay, weak. */
  good: string
  /** Optional note — only when the good range differs by sector. */
  sectorNote?: string
}

export const METRIC_EXPLANATIONS: Record<string, MetricExplanation> = {
  // ───────────────────────────────────────────────────────────────────
  // Valuation — the core "what's it worth?" bucket
  // ───────────────────────────────────────────────────────────────────
  fair_value: {
    title: "Fair Value (Intrinsic Value)",
    oneLine:
      "Our estimate of what one share is actually worth based on the cash the business is likely to generate in the future.",
    formula: "Discounted Cash Flow (DCF) — future FCF discounted back at WACC",
    good:
      "Compare to current price: fair value well above price = below fair value, fair value well below price = above fair value. A DCF is only as good as its assumptions — treat it as a centre of gravity, not a precise number.",
  },
  current_price: {
    title: "Current Price",
    oneLine:
      "The last traded price on NSE/BSE, used as the baseline to compute margin of safety against our fair-value estimate.",
    good:
      "Price is what you pay, value is what you get. The gap between price and fair value is the margin of safety.",
  },
  mos: {
    title: "Margin of Safety",
    oneLine:
      "How much of a discount (or premium) the current price offers versus our fair-value estimate.",
    // Fixed 2026-04-25: was "÷ Fair Value", backend has always
    // computed "÷ Current Price". See docs/FORMULA_SOURCE_OF_TRUTH.md.
    formula: "(Fair Value − Current Price) ÷ Current Price × 100",
    good:
      "Above +30% is a deep discount to model fair value, +10-30% is a moderate discount, -10% to +10% is roughly at model fair value, below -20% is well above model fair value. Benjamin Graham documented a ~33% discount-to-FV threshold in The Intelligent Investor as the historical hurdle for value-investing methodology.",
  },
  bear_case: {
    title: "Bear Case",
    oneLine:
      "The low end of our fair-value range — what the stock is worth if growth disappoints and margins compress.",
    good:
      "If current price is above bear case, you're paying a premium for things going right. If current price is below bear case, the market may be pricing in the worst outcome already.",
  },
  base_case: {
    title: "Base Case",
    oneLine:
      "Our central fair-value estimate assuming the business grows at its recent trend and maintains current margins.",
    good:
      "This is the number to anchor on. Bull/bear cases show the spread; base case is our best single-point estimate.",
  },
  bull_case: {
    title: "Bull Case",
    oneLine:
      "The high end of our fair-value range — what the stock is worth if growth accelerates and margins expand.",
    good:
      "Current price above bull case = market is euphoric; below bull case but above base = priced for modest upside; below base = priced for disappointment.",
  },
  verdict: {
    title: "Verdict",
    oneLine:
      "Our one-word summary of where the stock sits relative to its fair value.",
    good:
      "Below Fair Value (MoS > +15%), Near Fair Value (-10% to +15%), Above Fair Value (< -10%). A verdict is a valuation label — not a registered-advisor trade call.",
  },

  // ───────────────────────────────────────────────────────────────────
  // YieldIQ proprietary signals
  // ───────────────────────────────────────────────────────────────────
  yieldiq_score: {
    title: "YieldIQ Score",
    oneLine:
      "A 0-100 composite score that blends our valuation, quality, growth, and safety axes into a single descriptive number. Reflects the model's view of a business's fundamentals at a point in time. Not investment advice.",
    good:
      "Above 75 = high across the board, 55-75 = mixed with trade-offs, 35-55 = several factors to consider, below 35 = multiple model concerns. The score rewards both below-fair-value AND high-quality fundamentals — a stock can score low simply by being priced above its model fair value.",
  },
  grade: {
    title: "Grade",
    oneLine:
      "Letter grade (A/B/C/D/F) mapped from the YieldIQ Score — a shorthand you can scan in a watchlist.",
    good:
      "A-tier: top decile, rare. B-tier: healthy composite. C-tier: mixed — read the pillar breakdown. D/F: one or more pillars failing badly.",
  },
  moat: {
    title: "Moat",
    oneLine:
      "How durable the company's competitive advantage is — can it defend its profit margins from competitors over 5-10 years?",
    good:
      "Wide: proven pricing power (TCS, Asian Paints, HUL). Narrow: some moat but eroding. None: commodity business, margin at mercy of competition. Wide-moat businesses compound; moatless ones don't.",
  },
  moat_score: {
    title: "Moat Score",
    oneLine:
      "A 0-100 score for the durability of the company's competitive advantage, derived from ROCE consistency, margin stability, and market share.",
    good:
      "Above 70 = wide moat territory (top 10% of listed Indian companies). 40-70 = narrow moat. Below 40 = no structural advantage, returns will mean-revert.",
  },

  // ───────────────────────────────────────────────────────────────────
  // Profitability — can they actually make money?
  // ───────────────────────────────────────────────────────────────────
  roe: {
    title: "Return on Equity",
    oneLine:
      "How much profit the company generates for every rupee of shareholder equity — the ultimate test of capital efficiency for equity owners.",
    formula: "Net Income ÷ Shareholder Equity × 100",
    good:
      "Above 20% is excellent, 15-20% solid, 10-15% average, below 10% limited. Sustained 20%+ ROE is the hallmark of a compounder.",
    sectorNote:
      "Beware ROE juiced by leverage — a bank with 15% ROE and 15x leverage is not the same as a consumer company with 15% ROE and zero debt.",
  },
  roce: {
    title: "Return on Capital Employed",
    oneLine:
      "How much operating profit the business generates per rupee of capital deployed, regardless of how that capital is financed.",
    formula: "EBIT ÷ (Total Assets − Current Liabilities) × 100",
    good:
      "Above 20% is excellent, 15-20% solid, 10-15% average, below 10% limited. Unlike ROE, ROCE can't be faked with leverage — it's the purest measure of operating quality.",
    sectorNote:
      "Asset-light IT services routinely hit 30-50%+ (TCS, Infosys). Capital-heavy cement/steel sees 12-18% as healthy. Compare within a sector, not across.",
  },
  roa: {
    title: "Return on Assets (Banks)",
    oneLine:
      "The clearest single measure of how profitably a bank runs its balance sheet — profit earned for every rupee of assets held.",
    formula: "Net Income ÷ Total Assets × 100",
    good:
      "For Indian banks: above 1.4% is healthy, around 1.0% is average, below 0.6% is limited. Top private banks (HDFC, Kotak) run 1.8-2.0%; PSU banks typically sit at 0.6-1.0%.",
  },

  // ───────────────────────────────────────────────────────────────────
  // Balance-sheet health
  // ───────────────────────────────────────────────────────────────────
  debt_ebitda: {
    title: "Debt ÷ EBITDA",
    oneLine:
      "How many years of operating cash flow it would take to repay all debt — the cleanest single measure of leverage risk.",
    formula: "Total Debt ÷ EBITDA",
    good:
      "Below 1x is excellent, 1-3x is healthy, 3-5x is leveraged, above 5x is risky. Below 2x is generally safe through a mild downturn.",
    sectorNote:
      "Not applicable to banks — deposits aren't debt. Infrastructure and utilities tolerate higher leverage (3-5x) because cash flows are regulated and predictable.",
  },
  interest_coverage: {
    title: "Interest Coverage",
    oneLine:
      "How many times operating profit covers interest payments — how much cushion the company has before it struggles to service debt.",
    formula: "EBIT ÷ Interest Expense",
    good:
      "Above 5x is safe, 2-5x is adequate, 1-2x is stretched, below 1x means EBIT isn't covering interest at all (a distress signal).",
  },
  current_ratio: {
    title: "Current Ratio",
    oneLine:
      "Whether the company has enough short-term assets (cash, receivables, inventory) to cover what it owes in the next 12 months.",
    formula: "Current Assets ÷ Current Liabilities",
    good:
      "Above 1.5 is comfortable, 1.0-1.5 is adequate, below 1.0 is a short-term liquidity risk. Too high (>3.0) can mean idle working capital.",
  },
  asset_turnover: {
    title: "Asset Turnover",
    oneLine:
      "How many rupees of revenue the company generates per rupee of assets — high turnover = capital-efficient business.",
    formula: "Revenue ÷ Total Assets",
    good:
      "Above 1.0 is high, 0.5-1.0 is typical, below 0.3 means the business is capital-heavy (infra, utilities).",
    sectorNote:
      "FMCG and IT services hit 1.5-2.0+; banks and infrastructure structurally run below 0.5. Compare within sector only.",
  },

  // ───────────────────────────────────────────────────────────────────
  // Valuation multiples
  // ───────────────────────────────────────────────────────────────────
  ev_ebitda: {
    title: "EV ÷ EBITDA",
    oneLine:
      "A capital-structure-neutral valuation multiple — better than P/E for debt-heavy businesses because it includes net debt in the price.",
    formula: "Enterprise Value ÷ EBITDA",
    good:
      "Below 10x typically prices below fair value, 10-15x reasonable, 15-25x full, above 25x rich. Durable compounders often trade at 20-30x and still compound.",
  },
  pe_ratio: {
    title: "Price ÷ Earnings (P/E)",
    oneLine:
      "How many rupees you're paying for every rupee of annual profit — the most widely-quoted valuation shortcut.",
    formula: "Share Price ÷ EPS (trailing 12 months)",
    good:
      "Below 15x typically prices below fair value for Indian large caps, 15-25x normal, 25-40x premium, above 40x rich. Nifty 50 long-run average is ~22x.",
    sectorNote:
      "P/E is misleading for banks (use P/B), cyclicals at peak/trough earnings, and loss-makers. Don't compare a 40x FMCG stock with a 12x cement stock at face value.",
  },
  pb_ratio: {
    title: "Price ÷ Book (P/B)",
    oneLine:
      "How many rupees you're paying for every rupee of net assets — the preferred valuation multiple for banks, NBFCs, and asset-heavy businesses.",
    formula: "Share Price ÷ Book Value per Share",
    good:
      "Below 1x means buying below accounting net worth (rare, often distressed). 1-3x normal, above 4x rich. For private banks: 3-5x is standard for high-ROE names like HDFC/Kotak.",
  },
  market_cap: {
    title: "Market Capitalisation",
    oneLine:
      "The total market value of all shares — size matters because large caps are more liquid, mid/small caps more volatile but higher return potential.",
    formula: "Share Price × Shares Outstanding",
    good:
      "Large cap: >₹20,000 Cr (SEBI definition). Mid cap: ₹5,000-20,000 Cr. Small cap: <₹5,000 Cr. Liquidity, analyst coverage, and governance generally improve with size.",
  },

  // ───────────────────────────────────────────────────────────────────
  // Growth & shareholders
  // ───────────────────────────────────────────────────────────────────
  revenue_cagr_3y: {
    title: "Revenue CAGR (3-year)",
    oneLine:
      "Annualised growth in top-line revenue over the last three years — captures near-term momentum more than long-term trend.",
    formula: "(Revenue_now / Revenue_3y_ago)^(1/3) − 1",
    good:
      "Above 15% is high growth, 8-15% solid, 3-8% modest, below 3% stagnant. Compare to nominal GDP growth (~10-12%) as a baseline.",
  },
  revenue_cagr_5y: {
    title: "Revenue CAGR (5-year)",
    oneLine:
      "Annualised top-line growth over five years — a better indicator of the underlying trend than 3-year numbers.",
    formula: "(Revenue_now / Revenue_5y_ago)^(1/5) − 1",
    good:
      "Above 15% is high-growth, 10-15% solid, 5-10% modest, below 5% mature/slow. 5-year CAGR is the anchor — 3-year can flatter a cyclical peak.",
  },
  dividend_yield: {
    title: "Dividend Yield",
    oneLine:
      "Annual dividend per share as a percentage of the current price — the cash income you get just for holding the stock.",
    formula: "Annual DPS ÷ Share Price × 100",
    good:
      "Above 4% is high-yield (often value/PSU names), 2-4% decent, below 1% typical for growth stocks. High yield isn't automatically good — check if it's sustainable or signalling distress.",
  },
  promoter_holding: {
    title: "Promoter Holding",
    oneLine:
      "Percent of total shares held by the founders/promoter group — higher generally means more aligned interests with minority shareholders.",
    good:
      "Above 50% is high promoter control, 25-50% moderate, below 25% low stake. Watch promoter pledge separately — pledged shares can be force-sold in a crunch.",
  },
  piotroski_score: {
    title: "Piotroski F-Score",
    oneLine:
      "A 0-9 scorecard designed by Joseph Piotroski that checks nine fundamental-health signals (profitability, leverage trend, operating efficiency).",
    formula: "Sum of 9 pass/fail checks on profitability, leverage, efficiency",
    good:
      "7-9 = fundamentally durable, 4-6 = mixed, 0-3 = deteriorating. The F-score filters out value traps — below-fair-value stocks with 7+ F-score historically outpaced below-fair-value stocks with a low F-score.",
  },

  // ───────────────────────────────────────────────────────────────────
  // Model inputs — users occasionally ask "what's WACC?"
  // ───────────────────────────────────────────────────────────────────
  wacc: {
    title: "Weighted Average Cost of Capital (WACC)",
    oneLine:
      "The blended return investors expect for funding this company — we use it to discount future cash flows back to today's rupees.",
    formula: "(E/V × Re) + (D/V × Rd × (1 − tax))",
    good:
      "Typical Indian equities: 10-14%. Higher for small caps or leveraged businesses (14-18%), lower for utilities or regulated businesses (9-11%). A higher WACC reduces fair value.",
  },

  // ───────────────────────────────────────────────────────────────────
  // Bank-specific metrics — displayed only on banking tickers
  // ───────────────────────────────────────────────────────────────────
  cost_to_income: {
    title: "Cost-to-Income Ratio (Banks)",
    oneLine:
      "Operating expense as a percentage of total income — how efficiently a bank is running. Lower is better.",
    formula: "Operating Expenses ÷ (Net Interest Income + Other Income) × 100",
    good:
      "Indian benchmarks: below 45% is excellent (HDFC, Kotak), 45-55% healthy, 55-65% typical for PSUs, above 70% is structurally inefficient.",
  },
  nim: {
    title: "Net Interest Margin (Banks)",
    oneLine:
      "The spread a bank earns between what it charges on loans and what it pays on deposits — the core profit engine of banking.",
    formula: "(Interest Earned − Interest Paid) ÷ Avg. Interest-Earning Assets",
    good:
      "Indian banks: above 4% is high (top private banks, small-finance banks), 3-4% healthy, 2.5-3% average for PSUs, below 2.5% compressed.",
  },
  car: {
    title: "Capital Adequacy Ratio (Banks)",
    oneLine:
      "The buffer of capital a bank holds against its risk-weighted loans — the regulator's main lever for ensuring banks can absorb losses.",
    formula: "(Tier 1 + Tier 2 Capital) ÷ Risk-Weighted Assets × 100",
    good:
      "RBI minimum: 11.5% (including buffer). Above 16% is comfortable, 13-16% healthy, 11.5-13% tight, below 11.5% regulatory breach. Private banks typically run 16-20%.",
  },
  nnpa: {
    title: "Net NPA Ratio (Banks)",
    oneLine:
      "Non-performing loans (net of provisions) as a percentage of net advances — the purest measure of a bank's asset quality.",
    formula: "(Gross NPA − Provisions) ÷ Net Advances × 100",
    good:
      "Below 1% is excellent (top private banks), 1-2% healthy, 2-4% stressed, above 4% a red flag. PSUs historically ran 4-8%; post-clean-up now 1-3%.",
  },
  casa: {
    title: "CASA Ratio (Banks)",
    oneLine:
      "Current Account + Savings Account deposits as a share of total deposits — these are low-cost, sticky funds that drive NIM.",
    formula: "(Current + Savings Deposits) ÷ Total Deposits × 100",
    good:
      "Above 45% is excellent (SBI, HDFC, Kotak), 35-45% healthy, 25-35% typical for mid-sized banks, below 25% costly funding profile.",
  },
  advances_yoy: {
    title: "Advances YoY (Banks)",
    oneLine:
      "Year-on-year growth in the loan book — how fast the bank is expanding credit relative to the prior year.",
    good:
      "Indian system credit grows ~10-12% long-term. Above 15% is fast (watch underwriting quality), 10-15% healthy, below 8% slow and potentially losing share.",
  },
  deposits_yoy: {
    title: "Deposits YoY (Banks)",
    oneLine:
      "Year-on-year growth in total deposits — the fuel that funds advances. Deposit growth typically keeps pace with advances.",
    good:
      "10-14% is typical for well-run banks. When advances grow much faster than deposits, the bank is borrowing more expensively in wholesale markets — watch NIM.",
  },
  pat_yoy_bank: {
    title: "PAT YoY (Banks)",
    oneLine:
      "Year-on-year growth in net profit (Profit After Tax) — the bottom-line scorecard of how well a bank turned its advances into earnings.",
    good:
      "Above 20% is high, 12-20% healthy, 5-12% modest, below 5% stagnant. In a clean credit cycle, well-run banks compound PAT at 15-25% for years.",
  },
}

/**
 * Convenience helper — returns explanation or null. Components should
 * treat null as "no tooltip; render children as-is."
 */
export function getExplanation(key: string): MetricExplanation | null {
  return METRIC_EXPLANATIONS[key] ?? null
}
