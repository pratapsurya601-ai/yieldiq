// educational-content.ts — Educational Content Layer.
//
// Library of finance metric mini-lessons. Drives:
//   1. The MetricExplainer modal (analysis page "?" icon → rich expander).
//   2. The /learn index + /learn/<topic> per-metric SEO page.
//   3. The "Learn more" link inside the existing inline MetricTooltip
//      (lib/metric-explainers.ts), which is intentionally a separate,
//      tighter copy budget for hover popovers.
//
// Why a third copy file? metric_explanations.ts is the backend-mirrored
// "?" tooltip surface (one-liner copy from FormulaSpec).
// metric-explainers.ts is the AlphaSpread-style hover popover (~40
// words). THIS file is the long-form "Learn finance" surface —
// retail-friendly mini-lessons with definition + why-it-matters +
// good/bad ranges + worked example. Three surfaces, three copy budgets,
// one shared content model.
//
// SEBI vocabulary discipline: every string in this file is scanned by
// scripts/check_sebi_words.py on PR. The banned tokens (buy, sell, hold,
// recommend, attractive, cheap, expensive, concern, strength, weakness,
// outperform, underperform, accumulate, poor, strong, weak, appears,
// should, investable, investability) NEVER appear in user-facing copy.
// Use neutral descriptive framing:
//   - "trades at a premium / discount to peers"
//   - "above / below the sector median"
//   - "a high-quality cash-generating business" (not "strong" cash gen)
//   - "potential signal" (not "should consider")
//   - "in the top decile" / "in the bottom quartile"
//
// Copy budget per topic:
//   - definition:    1 short paragraph, 40-80 words
//   - whyItMatters:  1 short paragraph, 40-80 words
//   - ranges:        2-4 typed band entries (label + description)
//   - example:       1 worked numerical example, 40-80 words
//   - relatedTopics: 2-4 keys (other topics in this file)
//
// The example field uses INR / Indian-equity conventions (₹, crore, NIFTY)
// because the audience is Indian retail.

export type DifficultyTier = "beginner" | "intermediate" | "advanced"

export interface MetricRange {
  /** Band label, e.g. "Top decile" or "Sector median". */
  label: string
  /** What that band signals about the underlying business. */
  description: string
}

export interface EducationalTopic {
  /** URL slug — kebab-case, used as /learn/<slug>. */
  slug: string
  /** Display title — full name + acronym. */
  title: string
  /** Short subtitle used in cards + meta description. */
  subtitle: string
  /** Difficulty tier — beginner / intermediate / advanced. */
  difficulty: DifficultyTier
  /** Coarse category for the /learn index page grouping. */
  category:
    | "Profitability"
    | "Valuation"
    | "Balance Sheet"
    | "Cash Flow"
    | "Growth"
    | "Risk"
    | "Banking"
    | "Quality Score"
    | "DCF Inputs"
  /** Plain-English 1-paragraph definition (40-80 words). */
  definition: string
  /** Why this metric matters to an investor (40-80 words). */
  whyItMatters: string
  /** Typical / good / bad bands. 2-4 entries. */
  ranges: MetricRange[]
  /** A worked numerical example (40-80 words). */
  example: string
  /** Optional textbook formula. */
  formula?: string
  /**
   * Optional caveat — what this metric does NOT tell you. Mirrors the
   * existing MetricTooltip "caveat" pattern so the rich modal stays
   * consistent with the inline hover copy.
   */
  caveat?: string
  /** Related topic slugs, for "Read next" suggestions. */
  relatedTopics: string[]
}

// ─────────────────────────────────────────────────────────────────────
// The library — 30+ entries grouped by category.
// ─────────────────────────────────────────────────────────────────────

export const EDUCATIONAL_TOPICS: Record<string, EducationalTopic> = {
  // ═════════════════════════════ Profitability ════════════════════════
  roe: {
    slug: "roe",
    title: "Return on Equity (ROE)",
    subtitle: "How efficiently a company turns shareholder equity into profit.",
    difficulty: "beginner",
    category: "Profitability",
    definition:
      "Return on Equity measures the profit a company generates for every rupee of shareholder equity. It is the headline number for equity-capital efficiency — a 20% ROE means the business earns ₹20 of net profit per ₹100 of equity it holds.",
    whyItMatters:
      "ROE tells you how productively the management is deploying the capital you have entrusted to them. Two businesses with the same profit can have very different ROEs depending on how much equity sits on the balance sheet. Persistently high ROE over a decade is a hallmark of compounding businesses with durable economics.",
    formula: "Net Income ÷ Shareholder Equity × 100",
    ranges: [
      { label: "Above 20%", description: "Top decile of listed Indian large-caps; often a sign of a high-quality franchise." },
      { label: "15-20%", description: "Above the long-run median for established large-caps." },
      { label: "10-15%", description: "In line with the sector median for most diversified businesses." },
      { label: "Below 10%", description: "Below the sector median; check whether the business is asset-heavy or in a cyclical trough." },
    ],
    example:
      "TCS reported net profit of ₹46,000 crore on shareholder equity of ₹95,000 crore in a recent fiscal year. ROE = 46,000 ÷ 95,000 × 100 = 48%. That is well above the listed-large-cap median and reflects the asset-light services model.",
    caveat:
      "Leverage inflates ROE — a highly levered company can post the same ROE as a debt-free one with very different risk. Always read ROE alongside D/E and interest coverage.",
    relatedTopics: ["roa", "roce", "de_ratio", "pe"],
  },

  roa: {
    slug: "roa",
    title: "Return on Assets (ROA)",
    subtitle: "Profit earned per rupee of total assets — the cleanest read on capital productivity.",
    difficulty: "beginner",
    category: "Profitability",
    definition:
      "Return on Assets measures profit earned for every rupee of total assets, regardless of how those assets are funded. It is the cleanest single read on how productively management is running the entire balance sheet — debt-funded or equity-funded alike.",
    whyItMatters:
      "ROA is the right lens for banks and capital-heavy businesses, where deposits and debt make ROE misleading. A bank with 14% ROE and 0.6% ROA is running a very different machine than one with 14% ROE and 1.6% ROA — the second is fundamentally more productive per rupee of balance sheet.",
    formula: "Net Income ÷ Total Assets × 100",
    ranges: [
      { label: "Banks: above 1.4%", description: "Top quartile of Indian private banks." },
      { label: "Banks: 0.8-1.4%", description: "In line with the listed-bank median." },
      { label: "Non-banks: above 10%", description: "Asset-light services businesses; in the top decile." },
      { label: "Non-banks: 3-8%", description: "Typical for industrials and consumer businesses." },
    ],
    example:
      "HDFC Bank reported net profit of ₹65,000 crore on total assets of ₹35 lakh crore. ROA = 65,000 ÷ 35,00,000 × 100 = 1.85%. That sits in the top quartile for Indian banks and is one reason the market awards it a premium price-to-book multiple.",
    relatedTopics: ["roe", "nim", "casa", "de_ratio"],
  },

  roce: {
    slug: "roce",
    title: "Return on Capital Employed (ROCE)",
    subtitle: "Pre-tax return on the full capital base — debt and equity together.",
    difficulty: "intermediate",
    category: "Profitability",
    definition:
      "Return on Capital Employed measures the pre-tax operating profit earned on the total capital deployed in the business — both debt and equity. It strips out the tax rate and the funding mix, isolating the underlying economic productivity of the operations.",
    whyItMatters:
      "ROCE is the metric of choice when comparing capital allocation across businesses with different debt loads or tax regimes. A 25% ROCE that holds for ten years implies the business reinvests every rupee at a 25% pre-tax yield — the engine of long-term compounding.",
    formula: "EBIT ÷ (Total Equity + Total Debt − Cash) × 100",
    ranges: [
      { label: "Above 25%", description: "Top decile of Indian listed equities; durable compounding economics." },
      { label: "15-25%", description: "Above the long-run sector median for most asset-light businesses." },
      { label: "10-15%", description: "In line with the sector median for capital-intensive industrials." },
      { label: "Below 10%", description: "Below the cost of capital for most businesses; check sector and cycle position." },
    ],
    example:
      "Asian Paints reported EBIT of ₹6,400 crore on capital employed of ₹16,000 crore. ROCE = 6,400 ÷ 16,000 × 100 = 40%. That is one of the highest in Indian FMCG and is why the market historically awards the business a premium multiple.",
    caveat:
      "ROCE rewards capital-light models and penalises capex-heavy businesses early in an investment cycle. Read it alongside the capex / depreciation ratio to spot businesses mid-investment.",
    relatedTopics: ["roe", "roa", "ebitda", "fcf"],
  },

  ebitda: {
    slug: "ebitda",
    title: "EBITDA",
    subtitle: "Earnings before interest, taxes, depreciation, and amortisation.",
    difficulty: "beginner",
    category: "Profitability",
    definition:
      "EBITDA is operating profit before the non-cash depreciation and amortisation charges, and before interest and taxes. It approximates the cash that the operating business generates before capital-structure and accounting choices distort the picture.",
    whyItMatters:
      "EBITDA lets you compare the operating engines of two businesses regardless of how they are funded or how their accountants depreciate assets. It is the denominator in EV/EBITDA, the most-used cross-sector valuation multiple after P/E.",
    formula: "Net Income + Interest + Taxes + Depreciation + Amortisation",
    ranges: [
      { label: "EBITDA margin above 25%", description: "Above the sector median for most consumer and services businesses." },
      { label: "EBITDA margin 15-25%", description: "Typical for industrials and diversified manufacturing." },
      { label: "EBITDA margin below 10%", description: "Below the sector median; check whether commodity or volume-driven." },
    ],
    example:
      "Reliance Industries reported revenue of ₹9 lakh crore and EBITDA of ₹1.6 lakh crore in a recent fiscal. EBITDA margin = 1,60,000 ÷ 9,00,000 × 100 = 17.8%, in line with the diversified energy-and-retail median.",
    caveat:
      "EBITDA ignores the very real cost of replacing assets (capex) and the interest bill. Charlie Munger famously called it 'bullshit earnings' — always cross-check EBITDA with FCF for capital-intensive businesses.",
    relatedTopics: ["ev_ebitda", "fcf", "operating_margin", "roce"],
  },

  operating_margin: {
    slug: "operating-margin",
    title: "Operating Margin",
    subtitle: "Operating profit as a percentage of revenue.",
    difficulty: "beginner",
    category: "Profitability",
    definition:
      "Operating margin is the percentage of revenue that survives as operating profit (EBIT) after the cost of goods, employees, and overheads. It is the cleanest single measure of how much of every rupee of sales the operating business keeps.",
    whyItMatters:
      "Operating margin trends reveal pricing power, scale economics, and cost discipline. A 10-year rising trend often signals a business that is widening its competitive moat; a falling trend often signals competition, commodity inputs, or operating deleverage.",
    formula: "Operating Profit (EBIT) ÷ Revenue × 100",
    ranges: [
      { label: "Above 25%", description: "Above the sector median for high-moat consumer and IT services." },
      { label: "10-25%", description: "Typical for industrials, healthcare, and diversified manufacturing." },
      { label: "Below 5%", description: "Below the sector median; common in commodities and pure distribution." },
    ],
    example:
      "Infosys reported operating profit of ₹32,000 crore on revenue of ₹1,53,000 crore. Operating margin = 32,000 ÷ 1,53,000 × 100 = 20.9%, in line with the listed IT-services median of ~21%.",
    relatedTopics: ["ebitda", "fcf_revenue", "pe", "roce"],
  },

  // ═════════════════════════════ Valuation ════════════════════════════
  pe: {
    slug: "pe",
    title: "Price ÷ Earnings (P/E)",
    subtitle: "How many rupees you pay today for every rupee of annual profit.",
    difficulty: "beginner",
    category: "Valuation",
    definition:
      "The Price-to-Earnings ratio measures how many rupees the market pays today for every rupee of the company's annual profit. A P/E of 25 means you pay ₹25 for every ₹1 the business earns in a year — or, looked at differently, a 4% earnings yield.",
    whyItMatters:
      "P/E is the most widely-quoted valuation shortcut on earth. It rolls growth expectations, perceived business quality, and prevailing interest rates into one number. Reading a P/E in isolation tells you very little; reading it against history, peers, and the bond yield is where the signal lives.",
    formula: "Share Price ÷ EPS (trailing 12 months)",
    ranges: [
      { label: "Below 15x", description: "Below the long-run Indian large-cap average of around 18x." },
      { label: "15-25x", description: "In line with the NIFTY 50 historical median." },
      { label: "25-40x", description: "Trading at a premium to the index — typically growth or quality." },
      { label: "Above 40x", description: "Deep premium — the market is pricing in many years of compounding ahead." },
    ],
    example:
      "Nestlé India trades at ₹2,400 with EPS of ₹40. P/E = 2,400 ÷ 40 = 60x. That is a premium to the NIFTY median of around 22x; the market is pricing in many years of high-quality compounding from a defensive consumer brand.",
    caveat:
      "P/E reads misleadingly for banks (use P/B instead), for cyclicals near peak earnings (use a normalised P/E), and for loss-makers (undefined). PEG adjusts for growth — see related.",
    relatedTopics: ["peg", "pb", "ev_ebitda", "earnings_yield"],
  },

  peg: {
    slug: "peg",
    title: "PEG Ratio (P/E ÷ Growth)",
    subtitle: "P/E adjusted for the pace of earnings growth.",
    difficulty: "intermediate",
    category: "Valuation",
    definition:
      "PEG divides the P/E ratio by the annual earnings growth rate, in percent. It answers the question: is the multiple I'm paying for this business justified by how fast the profits are compounding? A PEG of 1.0 implies the multiple matches the growth rate one-for-one.",
    whyItMatters:
      "Two businesses with the same 30x P/E can be very different propositions if one is growing earnings at 25% a year and the other at 8%. PEG normalises for that. Peter Lynch popularised the rule of thumb: PEG below 1.0 is fairly priced for the growth on offer, above 2.0 is a growth premium.",
    formula: "P/E Ratio ÷ Annual EPS Growth Rate (%)",
    ranges: [
      { label: "Below 1.0", description: "Below fair value on a growth-adjusted basis." },
      { label: "1.0 - 2.0", description: "In line with the long-run median for quality growth businesses." },
      { label: "Above 2.0", description: "Trading at a growth premium — the multiple is ahead of the growth on offer." },
    ],
    example:
      "Bajaj Finance at 35x P/E and 25% historical EPS growth has a PEG of 35 ÷ 25 = 1.4. That sits in the typical growth-business range, suggesting the multiple is broadly in line with the historical growth trajectory.",
    caveat:
      "PEG breaks down when growth is negative, lumpy, or extrapolated from a single bumper year. Always verify the denominator — a normalised 3-5 year CAGR is more honest than a peak-year number.",
    relatedTopics: ["pe", "earnings_growth", "pb", "ev_ebitda"],
  },

  pb: {
    slug: "pb",
    title: "Price ÷ Book (P/B)",
    subtitle: "Market price relative to the company's accounting net worth.",
    difficulty: "beginner",
    category: "Valuation",
    definition:
      "Price-to-Book divides the current share price by the per-share book value (shareholder equity ÷ shares outstanding). A P/B of 3 means the market values the business at three times the accountant's net worth — the gap is the market's premium for intangibles, brand, and future earnings.",
    whyItMatters:
      "P/B is the right lens for banks, insurers, and balance-sheet-driven businesses where book value is a real, mark-to-market number. Outside finance, P/B is increasingly noisy because intangibles (brand, IP, software) are rarely capitalised on the balance sheet.",
    formula: "Share Price ÷ Book Value per Share",
    ranges: [
      { label: "Banks: above 3.0x", description: "Top-quartile private banks with ROE above 17%." },
      { label: "Banks: 1.5-3.0x", description: "In line with the listed private-bank median." },
      { label: "Banks: below 1.0x", description: "Trading below book value — often public-sector banks or specific credit stress." },
      { label: "Non-banks: above 5.0x", description: "Premium to book — typical for high-ROE asset-light businesses." },
    ],
    example:
      "Kotak Mahindra Bank trades at ₹1,800 with book value of ₹530 per share. P/B = 1,800 ÷ 530 = 3.4x. That sits at the top of the private-bank range and reflects sustained ROE above 15% over many years.",
    caveat:
      "Book value understates value for asset-light businesses (IT services, FMCG, software) and overstates it for capital-stranded businesses (telecom legacy assets). P/B is most informative for financials.",
    relatedTopics: ["roe", "roa", "pe", "ev_ebitda"],
  },

  ev_ebitda: {
    slug: "ev-ebitda",
    title: "EV ÷ EBITDA",
    subtitle: "Enterprise value relative to cash operating profit.",
    difficulty: "intermediate",
    category: "Valuation",
    definition:
      "EV/EBITDA divides Enterprise Value (market cap + net debt) by EBITDA. It is a capital-structure-neutral multiple — two businesses with the same operating cash but different debt loads will have the same EV/EBITDA but different P/E ratios.",
    whyItMatters:
      "EV/EBITDA is the multiple of choice for cross-sector and cross-border comparisons because it neutralises both leverage and the tax rate. It is also the standard multiple used in M&A — most deal headlines quote it.",
    formula: "(Market Cap + Net Debt) ÷ EBITDA",
    ranges: [
      { label: "Below 8x", description: "Below the long-run Indian large-cap median of around 12x." },
      { label: "8-15x", description: "In line with the listed sector median for most diversified businesses." },
      { label: "Above 20x", description: "Trading at a premium — typical for high-growth or high-quality businesses." },
    ],
    example:
      "Hindustan Unilever has a market cap of ₹6 lakh crore, net debt of ₹0, and EBITDA of ₹13,000 crore. EV/EBITDA = (6,00,000 + 0) ÷ 13,000 = 46x. That is a premium to the NIFTY median, reflecting durable brand economics.",
    caveat:
      "Not meaningful for banks and insurers (use P/B instead). Watch for businesses with heavy lease obligations — IFRS-16 capitalised leases inflate EBITDA without changing economic reality.",
    relatedTopics: ["pe", "pb", "ebitda", "enterprise_value"],
  },

  enterprise_value: {
    slug: "enterprise-value",
    title: "Enterprise Value (EV)",
    subtitle: "The full takeover price of the business — equity plus debt minus cash.",
    difficulty: "intermediate",
    category: "Valuation",
    definition:
      "Enterprise Value is the price a hypothetical acquirer would pay to take over the entire business — market capitalisation plus net debt (debt minus cash). It represents the full claim on the operating business, not just the equity slice.",
    whyItMatters:
      "EV is the right numerator when you want to compare the operating business itself, independent of how it is funded. Two identical businesses — one debt-free, one levered — have the same EV but very different market caps. EV-based multiples (EV/EBITDA, EV/Sales) are the cleanest cross-business comparison.",
    formula: "Market Cap + Total Debt − Cash & Equivalents",
    ranges: [
      { label: "EV > Market Cap", description: "Net debt on the balance sheet; common for capital-intensive sectors." },
      { label: "EV ≈ Market Cap", description: "Debt-free with minimal cash; typical for IT services." },
      { label: "EV < Market Cap", description: "Net cash on the balance sheet; common for cash-rich franchises." },
    ],
    example:
      "TCS has a market cap of ₹15 lakh crore, debt of ₹0, and cash of ₹50,000 crore. EV = 15,00,000 + 0 − 50,000 = ₹14.5 lakh crore. The cash buffer means EV sits below market cap.",
    relatedTopics: ["ev_ebitda", "market_cap", "pe", "pb"],
  },

  earnings_yield: {
    slug: "earnings-yield",
    title: "Earnings Yield",
    subtitle: "The inverse of P/E — earnings as a percentage of share price.",
    difficulty: "beginner",
    category: "Valuation",
    definition:
      "Earnings yield is 1 ÷ P/E, expressed as a percentage. A P/E of 25 implies an earnings yield of 4%. It is the share-price equivalent of a bond yield — what fraction of the share price the business earns in a year.",
    whyItMatters:
      "Earnings yield lets you compare an equity to a bond on a common denominator. When the 10-year G-Sec yields 7% and the NIFTY earnings yield is 5%, the equity market is being priced for growth — the gap is the implied growth premium.",
    formula: "EPS ÷ Share Price × 100  (or  100 ÷ P/E)",
    ranges: [
      { label: "Above 8%", description: "Above the prevailing 10-year G-Sec yield; equity is yielding more than bonds." },
      { label: "5-7%", description: "In line with the NIFTY 50 long-run earnings yield." },
      { label: "Below 4%", description: "Below the bond yield; the market is pricing in earnings growth ahead." },
    ],
    example:
      "If the NIFTY 50 trades at a P/E of 22, the earnings yield is 100 ÷ 22 = 4.5%. With the 10-year G-Sec at ~7%, the equity-to-bond yield gap is -2.5% — the market is pricing in roughly that much earnings growth.",
    relatedTopics: ["pe", "peg", "dividend_yield", "wacc"],
  },

  // ═════════════════════════════ Balance Sheet ════════════════════════
  de_ratio: {
    slug: "de-ratio",
    title: "Debt ÷ Equity (D/E)",
    subtitle: "How much of the balance sheet is funded by lenders vs shareholders.",
    difficulty: "beginner",
    category: "Balance Sheet",
    definition:
      "Debt-to-Equity divides total debt by shareholder equity. A D/E of 0.5 means the business is funded ₹50 from lenders for every ₹100 from equity holders. It is the headline measure of how levered the balance sheet is.",
    whyItMatters:
      "Debt amplifies returns in good times and losses in bad times. A 1.5 D/E business that delivers 12% ROCE will deliver more than 20% ROE — but a downturn hits it disproportionately. Reading D/E alongside interest coverage tells you both the size and the serviceability of the debt.",
    formula: "Total Debt ÷ Shareholder Equity",
    ranges: [
      { label: "Below 0.3", description: "Lightly levered or net cash; typical for IT and consumer." },
      { label: "0.3 - 1.0", description: "In line with the sector median for most diversified businesses." },
      { label: "1.0 - 2.0", description: "Above the sector median; typical for infrastructure and utilities." },
      { label: "Above 2.0", description: "Levered balance sheet; check the interest coverage trend." },
    ],
    example:
      "Larsen & Toubro reported total debt of ₹1.1 lakh crore and shareholder equity of ₹70,000 crore. D/E = 1,10,000 ÷ 70,000 = 1.57x. That is in the typical range for diversified infrastructure businesses, which carry working-capital debt.",
    caveat:
      "Not meaningful for banks (deposits are not debt) or for insurers (float is liabilities, not borrowings). Use the regulator's leverage ratio instead.",
    relatedTopics: ["interest_coverage", "current_ratio", "roe", "wacc"],
  },

  current_ratio: {
    slug: "current-ratio",
    title: "Current Ratio",
    subtitle: "Short-term assets vs short-term liabilities — near-term liquidity.",
    difficulty: "beginner",
    category: "Balance Sheet",
    definition:
      "The current ratio divides current assets (cash, receivables, inventory, anything turning into cash within 12 months) by current liabilities (anything due within 12 months). A ratio above 1.0 means the business can cover its near-term obligations from near-term assets.",
    whyItMatters:
      "Liquidity ratios catch businesses that are profitable on paper but cash-stretched in the next 90 days. A current ratio below 1.0 is not by itself a red flag — many high-quality businesses run on negative working capital — but the trend matters more than the level.",
    formula: "Current Assets ÷ Current Liabilities",
    ranges: [
      { label: "Above 2.0", description: "Comfortable — but also check whether working capital is sitting idle." },
      { label: "1.0 - 1.5", description: "In line with the manufacturing and industrials median." },
      { label: "Below 1.0", description: "Negative net working capital — common in FMCG; concerning elsewhere." },
    ],
    example:
      "Tata Consumer reported current assets of ₹6,800 crore and current liabilities of ₹4,200 crore. Current ratio = 6,800 ÷ 4,200 = 1.62x, in the comfortable range for a consumer business that collects from distributors before paying suppliers.",
    relatedTopics: ["de_ratio", "interest_coverage", "fcf", "working_capital"],
  },

  interest_coverage: {
    slug: "interest-coverage",
    title: "Interest Coverage Ratio (ICR)",
    subtitle: "How many times operating profit covers the interest bill.",
    difficulty: "intermediate",
    category: "Balance Sheet",
    definition:
      "Interest Coverage divides EBIT by the annual interest expense. It tells you how many times the operating profit can cover the interest bill — a coverage ratio of 5 means the business earns ₹5 of operating profit for every ₹1 of interest it pays.",
    whyItMatters:
      "Interest coverage is the single best read on whether a levered business can survive a downturn. A 1.5x coverage in a good year becomes 0.7x in a bad year — at which point the business eats into equity to service its debt. Bond covenants typically trigger at 2.0x or 2.5x.",
    formula: "EBIT ÷ Interest Expense",
    ranges: [
      { label: "Above 5x", description: "Comfortable cushion; debt is serviceable through a downturn." },
      { label: "2 - 5x", description: "Adequate — but check the cyclicality of EBIT." },
      { label: "1 - 2x", description: "Stretched; covenant pressure builds in any earnings dip." },
      { label: "Below 1x", description: "EBIT does not cover the interest bill — debt is being serviced from equity or refinancing." },
    ],
    example:
      "Adani Ports reported EBIT of ₹9,500 crore and interest expense of ₹2,300 crore. ICR = 9,500 ÷ 2,300 = 4.1x. That is adequate for an infrastructure business with annuity-like port revenues but leaves limited cushion in a deep downturn.",
    relatedTopics: ["de_ratio", "ebitda", "fcf", "current_ratio"],
  },

  working_capital: {
    slug: "working-capital",
    title: "Working Capital Cycle",
    subtitle: "How many days the business funds its own operations.",
    difficulty: "intermediate",
    category: "Balance Sheet",
    definition:
      "The working capital cycle measures the days between paying suppliers and collecting from customers, adjusted for inventory holding. A cycle of 60 days means the business funds 60 days of operations from its own cash before sales convert.",
    whyItMatters:
      "Negative working capital — common in FMCG, e-commerce, and subscription models — means customers and float fund the business. That is a structural moat. A lengthening working-capital cycle, on the other hand, is often the first sign of channel stuffing or credit-quality stress.",
    formula: "Days Inventory + Days Receivables − Days Payables",
    ranges: [
      { label: "Negative", description: "Customers/float fund operations — common in FMCG and e-commerce." },
      { label: "0 - 30 days", description: "Tight cycle; typical for asset-light services." },
      { label: "60 - 120 days", description: "In line with the manufacturing median." },
      { label: "Above 180 days", description: "Long cycle; common in infrastructure, EPC, and seasonal businesses." },
    ],
    example:
      "Dabur reports inventory days of 40, receivables days of 25, and payables days of 90. Cycle = 40 + 25 − 90 = -25 days. Suppliers effectively fund 25 days of Dabur's operations — a textbook FMCG structural advantage.",
    relatedTopics: ["current_ratio", "fcf", "fcf_revenue", "operating_margin"],
  },

  // ═════════════════════════════ Cash Flow ════════════════════════════
  fcf: {
    slug: "fcf",
    title: "Free Cash Flow (FCF)",
    subtitle: "Cash left after operations and capex — what's available to shareholders.",
    difficulty: "intermediate",
    category: "Cash Flow",
    definition:
      "Free Cash Flow is operating cash flow minus capital expenditure — the cash a business throws off after funding the assets needed to keep running. It is the cleanest single read on whether the accounting profit is real, durable cash or paper.",
    whyItMatters:
      "FCF is what the business can actually return to shareholders — through dividends, buybacks, or reinvestment at high returns. Many businesses report rising net income while FCF flatlines or turns negative; that gap is where accounting choices and capex appetite hide. Warren Buffett's 'owner earnings' is essentially FCF.",
    formula: "Operating Cash Flow − Capital Expenditure",
    ranges: [
      { label: "FCF > Net Income", description: "Cash conversion above 100% — high-quality earnings." },
      { label: "FCF ≈ 80-100% of Net Income", description: "Typical for established large-caps in steady state." },
      { label: "FCF < 50% of Net Income", description: "Below median cash conversion; check working-capital and capex trends." },
      { label: "FCF negative", description: "Reinvestment phase or operating cash struggle; context-dependent." },
    ],
    example:
      "Infosys reported net profit of ₹26,000 crore, operating cash flow of ₹28,500 crore, and capex of ₹2,000 crore. FCF = 28,500 − 2,000 = ₹26,500 crore. Cash conversion of 102% reflects the asset-light services model.",
    caveat:
      "Year-to-year FCF can swing on working-capital and capex timing — always read the 3-5 year average. A single capex-heavy year does not mean the business is structurally cash-light.",
    relatedTopics: ["fcf_revenue", "ebitda", "operating_margin", "roce"],
  },

  fcf_revenue: {
    slug: "fcf-revenue",
    title: "FCF ÷ Revenue",
    subtitle: "What fraction of every rupee of sales becomes free cash.",
    difficulty: "intermediate",
    category: "Cash Flow",
    definition:
      "FCF-to-Revenue divides free cash flow by total revenue. It tells you what fraction of every rupee of sales survives as cash after operating costs and capex — a single, normalised read on cash-generation quality across businesses of different sizes.",
    whyItMatters:
      "Two businesses with the same operating margin can have very different FCF/Revenue ratios depending on capex intensity. A 25% operating margin in IT services translates almost fully to FCF; the same margin in a capex-heavy cement business may convert at half the rate.",
    formula: "Free Cash Flow ÷ Revenue × 100",
    ranges: [
      { label: "Above 20%", description: "High cash-conversion business; in the top decile." },
      { label: "10-20%", description: "In line with the sector median for services and consumer." },
      { label: "5-10%", description: "Typical for manufacturing and industrials." },
      { label: "Below 5%", description: "Below the sector median; most revenue is consumed by operations or capex." },
    ],
    example:
      "TCS reported FCF of ₹42,000 crore on revenue of ₹2,40,000 crore. FCF/Revenue = 42,000 ÷ 2,40,000 × 100 = 17.5%, in the top quartile of the listed-services universe.",
    relatedTopics: ["fcf", "operating_margin", "ebitda", "dividend_payout"],
  },

  dividend_payout: {
    slug: "dividend-payout",
    title: "Dividend Payout Ratio",
    subtitle: "Share of earnings paid out as dividends rather than reinvested.",
    difficulty: "beginner",
    category: "Cash Flow",
    definition:
      "The dividend payout ratio divides total dividends paid by net profit. A 40% payout means 40 paise of every rupee earned is returned to shareholders as dividend; the remaining 60 paise is reinvested in the business or held on the balance sheet.",
    whyItMatters:
      "Payout policy signals management's view of internal reinvestment opportunities. A 90% payout from a mature utility says 'we have no better use for this cash'; a 10% payout from a fast-growing business says 'we can compound this internally at high returns'. Either can be the right answer.",
    formula: "Total Dividends ÷ Net Income × 100",
    ranges: [
      { label: "Above 80%", description: "Mature businesses returning most of earnings; typical for utilities and PSUs." },
      { label: "40-60%", description: "In line with the large-cap median; balanced reinvestment and payout." },
      { label: "Below 25%", description: "Heavy reinvestment phase; typical for high-ROE growth businesses." },
      { label: "Above 100%", description: "Paying out of reserves or borrowed cash; check sustainability." },
    ],
    example:
      "ITC reported net profit of ₹19,000 crore and total dividends of ₹15,500 crore. Payout = 15,500 ÷ 19,000 × 100 = 81.6%, reflecting a mature cash-rich business with limited large-scale reinvestment needs.",
    caveat:
      "A payout above 100% is sustainable only as long as cash reserves or fresh debt allow. Look for repeated 100%+ years against falling FCF as a quality flag.",
    relatedTopics: ["dividend_yield", "fcf", "roe", "earnings_yield"],
  },

  dividend_yield: {
    slug: "dividend-yield",
    title: "Dividend Yield",
    subtitle: "Annual dividend as a percentage of current share price.",
    difficulty: "beginner",
    category: "Cash Flow",
    definition:
      "Dividend yield is the annual dividend per share divided by the current share price, expressed as a percentage. A ₹20 dividend on a ₹500 share is a 4% yield — the income return you earn on the share at today's price, before any capital appreciation.",
    whyItMatters:
      "Dividend yield is the equity equivalent of a bond coupon. For income-focused investors, a sustainable 5-6% yield from a stable business can rival the post-tax return on a fixed deposit. Yield is most informative when read alongside payout-ratio sustainability.",
    formula: "Annual Dividend per Share ÷ Share Price × 100",
    ranges: [
      { label: "Above 6%", description: "High yield; verify payout sustainability and earnings trajectory." },
      { label: "3-5%", description: "In line with the dividend-paying large-cap median." },
      { label: "1-2%", description: "Typical for high-growth businesses reinvesting most of earnings." },
      { label: "0%", description: "No dividend — common for early-growth or capex-heavy businesses." },
    ],
    example:
      "Coal India trades at ₹400 with an annual dividend of ₹25 per share. Yield = 25 ÷ 400 × 100 = 6.25%, in the high-yield bracket typical of mature PSUs with limited reinvestment needs.",
    relatedTopics: ["dividend_payout", "earnings_yield", "fcf", "roe"],
  },

  // ═════════════════════════════ Growth ═══════════════════════════════
  earnings_growth: {
    slug: "earnings-growth",
    title: "Earnings Growth (EPS CAGR)",
    subtitle: "The compounded annual rate at which earnings per share are growing.",
    difficulty: "beginner",
    category: "Growth",
    definition:
      "EPS CAGR (Compound Annual Growth Rate) is the annualised rate at which earnings per share grow over a window — typically 3, 5, or 10 years. A 5-year CAGR of 20% means EPS has roughly 2.5x'd over five years on a smoothed basis.",
    whyItMatters:
      "Long-run share price returns track long-run earnings growth more closely than any other variable. A business that compounds EPS at 15% for a decade typically delivers double-digit annualised returns, even with no multiple expansion. CAGR over 5-10 years smooths out the cycle.",
    formula: "((EPS_end ÷ EPS_start)^(1/years)) − 1",
    ranges: [
      { label: "Above 20%", description: "Top-decile compounder; typical for high-quality growth franchises." },
      { label: "10-15%", description: "In line with the NIFTY 50 long-run EPS CAGR." },
      { label: "5-10%", description: "Below the index median; check whether sector mature or cyclical." },
      { label: "Negative", description: "Earnings shrinking; cyclical trough or structural decline." },
    ],
    example:
      "Asian Paints grew EPS from ₹15 to ₹38 over 10 years. CAGR = (38 ÷ 15)^(1/10) − 1 = 9.7%. That is below the long-run Indian-large-cap compounder average but is steady through cycle.",
    caveat:
      "EPS CAGR can be inflated by buybacks (lower share count) and depressed by dilution. Compare against revenue and FCF CAGR to spot whether earnings growth is operating or financial.",
    relatedTopics: ["peg", "pe", "revenue_growth", "fcf"],
  },

  revenue_growth: {
    slug: "revenue-growth",
    title: "Revenue Growth",
    subtitle: "The top-line growth rate — the cleanest read on business momentum.",
    difficulty: "beginner",
    category: "Growth",
    definition:
      "Revenue growth measures how fast the top line is expanding, year-over-year or as a CAGR. Unlike earnings, revenue cannot easily be manufactured through cost cuts or buybacks — it reflects underlying demand and pricing power.",
    whyItMatters:
      "Sustained revenue growth is the precondition for long-term earnings growth. A business growing revenue at 15% can usually grow earnings at 18-20% via operating leverage; the reverse is rarely sustainable. Five-year revenue CAGR is the single most honest momentum number.",
    formula: "((Revenue_end ÷ Revenue_start)^(1/years)) − 1",
    ranges: [
      { label: "Above 20%", description: "Top-decile growth; typical for early-stage compounders." },
      { label: "12-18%", description: "In line with the high-growth large-cap median." },
      { label: "8-12%", description: "Aligns with nominal Indian GDP growth." },
      { label: "Below 5%", description: "Below GDP growth; check sector maturity or cyclical position." },
    ],
    example:
      "DMart grew revenue from ₹12,000 crore to ₹42,000 crore over 5 years. CAGR = (42,000 ÷ 12,000)^(1/5) − 1 = 28.5%, in the top decile of Indian listed-retail growth.",
    relatedTopics: ["earnings_growth", "operating_margin", "fcf", "peg"],
  },

  terminal_growth: {
    slug: "terminal-growth",
    title: "Terminal Growth Rate",
    subtitle: "The perpetual growth rate assumed beyond the explicit forecast window.",
    difficulty: "advanced",
    category: "DCF Inputs",
    definition:
      "Terminal growth is the rate at which a DCF model assumes a business compounds forever, after the explicit forecast window (typically 5-10 years) ends. It is the engine of the 'terminal value' chunk of a DCF, which usually accounts for 60-80% of the total fair value.",
    whyItMatters:
      "A 0.5 percentage point change in terminal growth often moves DCF fair value by 10-20%. Because terminal value dominates the total, this tiny number drives the entire fair value figure more than the explicit forecast does. Choosing terminal growth honestly is the single biggest DCF discipline.",
    formula: "Long-run nominal GDP growth (typically 3-5% in INR terms)",
    ranges: [
      { label: "2.5-3.5%", description: "Below long-run nominal Indian GDP; conservative anchor." },
      { label: "4-5%", description: "In line with long-run nominal Indian GDP and inflation." },
      { label: "Above 6%", description: "Implies the firm outgrows the economy forever — rarely realistic." },
    ],
    example:
      "A DCF with WACC 12%, terminal growth 4%, and steady-state FCF of ₹1,000 crore generates terminal value of 1,000 × 1.04 ÷ (0.12 − 0.04) = ₹13,000 crore. Bumping terminal growth to 5% lifts that to ₹15,000 crore — a 15% jump in the terminal anchor.",
    caveat:
      "Terminal growth above WACC produces an infinite fair value (mathematical break). Any DCF with terminal growth within 1 percentage point of WACC is being driven by terminal-value mechanics, not business economics.",
    relatedTopics: ["wacc", "fcf", "pe", "earnings_growth"],
  },

  // ═════════════════════════════ Risk ═════════════════════════════════
  beta: {
    slug: "beta",
    title: "Beta",
    subtitle: "How much the stock moves relative to the broader market.",
    difficulty: "intermediate",
    category: "Risk",
    definition:
      "Beta is the statistical slope of the stock's returns plotted against the market's returns. A beta of 1.0 means the stock moves one-for-one with the index; 1.5 means it amplifies index moves by 50%; 0.7 means it moves only 70% of the index's swing.",
    whyItMatters:
      "Beta is the standard input to the Capital Asset Pricing Model (CAPM), which sets the cost of equity used in DCF models. A higher beta lifts the cost of equity, which raises WACC, which lowers DCF fair value. Defensive (low-beta) businesses are typically valued at higher multiples.",
    formula: "Covariance(stock returns, market returns) ÷ Variance(market returns)",
    ranges: [
      { label: "0.5 - 0.8", description: "Defensive — typical for FMCG, utilities, and pharma." },
      { label: "0.9 - 1.1", description: "Market-like; typical for diversified large-caps." },
      { label: "1.2 - 1.6", description: "Above market — typical for cyclicals and high-growth tech." },
      { label: "Above 1.8", description: "Highly cyclical or small-cap; large swings around index moves." },
    ],
    example:
      "Hindustan Unilever has a 5-year beta of 0.6, while Tata Motors carries a beta of 1.7. In a 10% market correction, HUL is statistically expected to fall 6%, Tata Motors 17%. Cost of equity for HUL is therefore lower than for Tata Motors.",
    caveat:
      "Historical beta is backward-looking — it can shift sharply when the business mix changes, after major capital events, or in regime changes (e.g. post-COVID).",
    relatedTopics: ["wacc", "alpha", "volatility", "terminal_growth"],
  },

  alpha: {
    slug: "alpha",
    title: "Alpha",
    subtitle: "Returns above what beta would predict — the manager skill measure.",
    difficulty: "intermediate",
    category: "Risk",
    definition:
      "Alpha is the excess return earned above what the stock's beta and the market return would predict. A +3% alpha means the stock delivered 3 percentage points more than CAPM expected; a -2% alpha means it underdelivered by that much.",
    whyItMatters:
      "Alpha is the standard report-card metric for active mutual fund managers and PMS schemes — the answer to 'did this manager add value beyond the risk they took?'. For individual stocks, sustained positive alpha is the statistical fingerprint of a high-quality compounder.",
    formula: "Actual Return − [Risk-free Rate + Beta × (Market Return − Risk-free Rate)]",
    ranges: [
      { label: "Above +2%", description: "Sustained positive alpha across multi-year windows is rare." },
      { label: "-1% to +1%", description: "In line with risk-adjusted expectation." },
      { label: "Below -2%", description: "Underdelivered versus the risk taken." },
    ],
    example:
      "If the NIFTY returned 12%, the risk-free rate is 7%, and a stock with beta 1.2 returned 18%, then expected return = 7 + 1.2 × (12 − 7) = 13%. Alpha = 18 − 13 = +5%, a clear beat versus the risk taken.",
    relatedTopics: ["beta", "volatility", "wacc", "sharpe"],
  },

  volatility: {
    slug: "volatility",
    title: "Volatility (Standard Deviation)",
    subtitle: "The statistical swing in the stock's returns.",
    difficulty: "intermediate",
    category: "Risk",
    definition:
      "Volatility — measured as the annualised standard deviation of daily returns — captures how much a stock's price swings around its mean. A 30% annualised volatility means roughly two-thirds of yearly returns fall within ±30% of the mean.",
    whyItMatters:
      "Volatility is the risk axis on the standard mean-variance frontier. For passive investors, higher volatility means a wider distribution of outcomes; for option pricing, it is the single most important input. NIFTY 50 long-run volatility sits at around 18%.",
    formula: "Annualised standard deviation of log returns",
    ranges: [
      { label: "Below 18%", description: "Low-volatility; typical for FMCG and utilities." },
      { label: "20-30%", description: "In line with the NIFTY 50 long-run volatility." },
      { label: "Above 40%", description: "High-volatility; typical for cyclicals and small-caps." },
    ],
    example:
      "If a stock has daily returns with standard deviation 1.8%, annualised volatility = 1.8% × √252 = 28.6%. In a typical year, returns will fall within ±29% of the mean roughly two-thirds of the time.",
    relatedTopics: ["beta", "alpha", "wacc", "sharpe"],
  },

  sharpe: {
    slug: "sharpe",
    title: "Sharpe Ratio",
    subtitle: "Excess return per unit of total risk taken.",
    difficulty: "advanced",
    category: "Risk",
    definition:
      "The Sharpe ratio divides the excess return over the risk-free rate by the standard deviation of returns. A Sharpe of 1.0 means the portfolio earned one unit of return for every unit of total volatility taken — a benchmark for solid risk-adjusted performance.",
    whyItMatters:
      "Sharpe is the standard cross-asset measure for risk-adjusted returns. It lets you compare a low-vol bond fund with a high-vol equity strategy on the same axis. Sustained Sharpe above 1.0 across 5+ year windows is hard to achieve and is a marker of genuine manager skill.",
    formula: "(Return − Risk-free Rate) ÷ Standard Deviation of Return",
    ranges: [
      { label: "Above 1.0", description: "Above the long-run NIFTY median; solid risk-adjusted returns." },
      { label: "0.5 - 1.0", description: "In line with the diversified equity-fund median." },
      { label: "Below 0.5", description: "Below the sector median; risk-adjusted returns underwhelm." },
    ],
    example:
      "A fund returned 16% with 20% standard deviation, against a 7% risk-free rate. Sharpe = (16 − 7) ÷ 20 = 0.45. That sits below the NIFTY 50 long-run Sharpe of around 0.5 — adequate but not above the index on a risk-adjusted basis.",
    relatedTopics: ["alpha", "beta", "volatility", "wacc"],
  },

  // ═════════════════════════════ Banking ══════════════════════════════
  nim: {
    slug: "nim",
    title: "Net Interest Margin (NIM)",
    subtitle: "The spread between what a bank earns on assets and pays on funds.",
    difficulty: "intermediate",
    category: "Banking",
    definition:
      "Net Interest Margin is the difference between a bank's interest income (on loans, bonds, and other earning assets) and its interest expense (on deposits and borrowings), divided by the average earning-asset base. It is the bank's gross operating spread.",
    whyItMatters:
      "NIM is the single best read on a bank's structural profitability. A 1 percentage point NIM advantage compounds into a meaningful ROA gap over time. Banks with low-cost CASA deposits and high-yielding loan books — like HDFC Bank historically — sustain higher NIMs through rate cycles.",
    formula: "(Interest Income − Interest Expense) ÷ Average Earning Assets",
    ranges: [
      { label: "Above 4%", description: "Top-quartile NIM; typical for retail-led private banks." },
      { label: "3.0 - 3.5%", description: "In line with the listed-private-bank median." },
      { label: "2.0 - 2.5%", description: "In line with the listed-PSU-bank median." },
      { label: "Below 2%", description: "Below the sector median; check the deposit mix and yield spread." },
    ],
    example:
      "HDFC Bank reported interest income of ₹1.6 lakh crore, interest expense of ₹95,000 crore, and average earning assets of ₹17 lakh crore. NIM = (1,60,000 − 95,000) ÷ 17,00,000 = 3.8%, in line with its long-run record.",
    caveat:
      "NIM expands in rising-rate environments (yields reset faster than deposits) and contracts in falling-rate environments. Read the NIM trend alongside the rate cycle, not in isolation.",
    relatedTopics: ["casa", "gnpa", "pcr", "roa"],
  },

  casa: {
    slug: "casa",
    title: "CASA Ratio",
    subtitle: "Share of bank deposits in low-cost current and savings accounts.",
    difficulty: "intermediate",
    category: "Banking",
    definition:
      "CASA stands for Current Account, Savings Account — the cheapest deposits a bank holds, paying minimal or zero interest. CASA ratio is the share of total deposits sitting in these low-cost accounts. A 45% CASA ratio means nearly half the deposit base costs the bank close to nothing.",
    whyItMatters:
      "CASA is structural pricing power for a bank. A bank with 45% CASA funds itself far more cheaply than a bank with 30% CASA — which translates directly to a wider NIM. Building CASA requires retail branch reach and brand trust, both of which are slow-built moats.",
    formula: "(Current Account Deposits + Savings Account Deposits) ÷ Total Deposits",
    ranges: [
      { label: "Above 45%", description: "Top-quartile CASA; typical for retail-led private banks." },
      { label: "35-40%", description: "In line with the listed-private-bank median." },
      { label: "25-30%", description: "In line with the listed-PSU-bank median." },
      { label: "Below 20%", description: "Below the sector median; reliance on bulk and term deposits." },
    ],
    example:
      "Kotak Mahindra Bank reported CASA deposits of ₹2.4 lakh crore against total deposits of ₹4.8 lakh crore. CASA ratio = 2,40,000 ÷ 4,80,000 = 50%, one of the highest in the listed-bank cohort.",
    relatedTopics: ["nim", "gnpa", "pcr", "roa"],
  },

  gnpa: {
    slug: "gnpa",
    title: "Gross NPA Ratio (GNPA)",
    subtitle: "Share of the bank's loan book classified as non-performing.",
    difficulty: "intermediate",
    category: "Banking",
    definition:
      "Gross Non-Performing Assets ratio is the percentage of a bank's gross loan book where the borrower has missed interest or principal for 90+ days. It is the headline credit-quality number — a 2% GNPA means ₹2 of every ₹100 lent is currently stressed.",
    whyItMatters:
      "GNPA is the asset-quality axis of bank analysis. A rising GNPA trend usually precedes credit losses by 2-4 quarters; a falling trend reflects successful resolution or recoveries. The Net NPA number (after provisioning) is the residual the bank is still carrying after writedowns.",
    formula: "Gross Non-Performing Assets ÷ Gross Advances × 100",
    ranges: [
      { label: "Below 1.5%", description: "Top quartile; tight underwriting and clean book." },
      { label: "2-3%", description: "In line with the listed-private-bank median." },
      { label: "3-5%", description: "Above the private-bank median; check sectoral concentration." },
      { label: "Above 6%", description: "Above the sector median; typical of restructured PSU books." },
    ],
    example:
      "ICICI Bank reported GNPAs of ₹28,000 crore against gross advances of ₹13 lakh crore. GNPA ratio = 28,000 ÷ 13,00,000 × 100 = 2.15%, in line with the listed-private-bank median.",
    relatedTopics: ["pcr", "nim", "casa", "roa"],
  },

  pcr: {
    slug: "pcr",
    title: "Provision Coverage Ratio (PCR)",
    subtitle: "How much of the bad-loan book is already provisioned against.",
    difficulty: "advanced",
    category: "Banking",
    definition:
      "Provision Coverage Ratio is the percentage of gross NPAs the bank has already written off as expected losses. A 75% PCR means the bank has set aside 75 paise of provisions for every ₹1 of stressed loan — the residual 25 paise is what the bank still expects to recover.",
    whyItMatters:
      "PCR is the conservatism axis on bank balance-sheet quality. A higher PCR means future earnings face less hit from credit costs because the bank already absorbed them. RBI typically pushes Indian banks to keep PCR above 70%.",
    formula: "Total Provisions ÷ Gross NPAs × 100",
    ranges: [
      { label: "Above 80%", description: "Conservative provisioning; future earnings less exposed." },
      { label: "65-75%", description: "In line with the RBI floor for listed banks." },
      { label: "Below 50%", description: "Below the regulatory comfort zone; provisioning catch-up likely." },
    ],
    example:
      "SBI reported gross NPAs of ₹85,000 crore and provisions of ₹70,000 crore. PCR = 70,000 ÷ 85,000 × 100 = 82%, well above the RBI floor and reflective of conservative provisioning policy.",
    relatedTopics: ["gnpa", "nim", "roa", "casa"],
  },

  // ═════════════════════════════ DCF Inputs ═══════════════════════════
  wacc: {
    slug: "wacc",
    title: "Weighted Average Cost of Capital (WACC)",
    subtitle: "The blended return investors expect for funding the business.",
    difficulty: "advanced",
    category: "DCF Inputs",
    definition:
      "WACC is the blended return that the business has to earn to satisfy both debt and equity providers, weighted by their share of the capital structure. It is the standard discount rate used to bring future cash flows back to present-day rupees in a DCF.",
    whyItMatters:
      "WACC sits at the heart of any DCF — a 1 percentage point change in WACC typically moves fair value by 8-15%. Choosing the right WACC is one of the most consequential analyst judgments. Too low and every DCF reads as undervalued; too high and every business looks overvalued.",
    formula: "(E/V × Re) + (D/V × Rd × (1 − tax))",
    ranges: [
      { label: "9-11%", description: "Typical for regulated utilities and high-grade infrastructure." },
      { label: "11-14%", description: "In line with the diversified large-cap WACC median." },
      { label: "14-18%", description: "Typical for small-caps and levered cyclicals." },
      { label: "Above 18%", description: "Typical for early-stage growth or distressed credit." },
    ],
    example:
      "A business with 70% equity (Re = 14%) and 30% debt (Rd = 9%, tax = 25%) has WACC = 0.7 × 14% + 0.3 × 9% × (1 − 0.25) = 9.8% + 2.0% = 11.8% — in the middle of the typical Indian large-cap range.",
    caveat:
      "A higher WACC shrinks DCF fair value. The choice of WACC matters as much as the cash-flow forecast itself — many DCF disagreements turn out to be WACC disagreements in disguise.",
    relatedTopics: ["terminal_growth", "beta", "de_ratio", "fcf"],
  },

  // ═════════════════════════════ Quality Scores ═══════════════════════
  piotroski: {
    slug: "piotroski",
    title: "Piotroski F-Score",
    subtitle: "A 0-9 scorecard of fundamental health.",
    difficulty: "intermediate",
    category: "Quality Score",
    definition:
      "The Piotroski F-Score, developed by Stanford accounting professor Joseph Piotroski in 2000, runs nine pass/fail checks across profitability, leverage trend, and operating efficiency. Each pass scores 1 point; the total ranges from 0 (all fail) to 9 (all pass).",
    whyItMatters:
      "Piotroski's original research showed that high-F-Score value stocks delivered ~7.5% annual excess returns relative to low-F-Score value stocks over 1976-1996. The score is a single-number distillation of accounting quality — useful as a coarse screen alongside valuation.",
    formula: "Sum of 9 pass/fail tests (4 profitability, 3 leverage/liquidity, 2 efficiency)",
    ranges: [
      { label: "8-9", description: "All checks passing; clean accounting and improving fundamentals." },
      { label: "5-7", description: "Mixed; profitability solid but some leverage or efficiency flags." },
      { label: "0-4", description: "Multiple checks failing; deteriorating fundamentals on the F-Score lens." },
    ],
    example:
      "A business with: positive net income (+1), positive operating cash flow (+1), rising ROA (+1), OCF > Net Income (+1), falling debt (+1), rising current ratio (+1), no share dilution (+1), rising gross margin (+1), rising asset turnover (+1) scores 9 — the maximum Piotroski rating.",
    caveat:
      "F-Score reads the most recent fiscal year only — it does not capture forward-looking risks like sector shock or management change.",
    relatedTopics: ["roe", "roa", "fcf", "de_ratio"],
  },

  yieldiq_score: {
    slug: "yieldiq-score",
    title: "YieldIQ Score",
    subtitle: "A 0-100 composite that blends valuation, quality, growth, and safety.",
    difficulty: "beginner",
    category: "Quality Score",
    definition:
      "The YieldIQ Score is a 0-100 composite that blends our valuation, quality, growth, and safety axes into one descriptive number. Higher means more of those axes are reading favourably at the time of measurement.",
    whyItMatters:
      "The score gives a single-number snapshot that you can use as a coarse filter when scanning many tickers. It is descriptive — it summarises what the underlying numbers say today — not predictive of returns.",
    ranges: [
      { label: "Above 75", description: "High across the board on our model axes." },
      { label: "55-75", description: "Mixed with trade-offs across the pillars." },
      { label: "35-55", description: "Multiple factors are reading below the sector median." },
      { label: "Below 35", description: "Multiple model flags; review the per-pillar breakdown." },
    ],
    example:
      "A business with valuation pillar 60, quality 78, growth 55, and safety 70, weighted equally, scores (60 + 78 + 55 + 70) ÷ 4 = 65.8 — landing in the mixed-with-trade-offs band.",
    caveat:
      "Not a prediction of returns and not investment advice. A business can score low simply by trading above our model fair value, even if the underlying fundamentals are durable.",
    relatedTopics: ["mos", "confidence", "piotroski", "pe"],
  },

  confidence: {
    slug: "confidence",
    title: "Confidence Score",
    subtitle: "Our model's data-quality signal.",
    difficulty: "intermediate",
    category: "Quality Score",
    definition:
      "The Confidence Score is a weighted blend of input completeness, peer cohort size, data freshness, and model fit. It is a 0-100 number that tells you how much input data the model had to work with — higher means more inputs were available.",
    whyItMatters:
      "A high confidence score means the model had complete inputs; a low one means it inferred or skipped fields. Confidence below 40 surfaces an 'Under Review' banner instead of a fair value, because the inputs are too sparse to make a reliable single-point estimate.",
    formula: "weighted(financials_completeness, peer_cohort_size, data_freshness, model_fit)",
    ranges: [
      { label: "Above 70", description: "Most inputs present; standard fair-value display." },
      { label: "40-70", description: "Partial inputs; fair value shown alongside a partial-data caption." },
      { label: "Below 40", description: "Sparse inputs; Under Review banner shown in place of fair value." },
    ],
    example:
      "If financials completeness = 80, peer cohort size = 60, freshness = 90, model fit = 70 (each weighted 0.25), the confidence score = 0.25 × (80 + 60 + 90 + 70) = 75 — in the standard-display range.",
    caveat:
      "Confidence reflects what we know about the inputs — NOT a probability that the fair value is correct. A high-confidence model can still be wrong about the future.",
    relatedTopics: ["yieldiq_score", "mos", "wacc", "piotroski"],
  },

  mos: {
    slug: "mos",
    title: "Margin of Safety (MoS)",
    subtitle: "The gap between current price and the model's fair-value estimate.",
    difficulty: "beginner",
    category: "Valuation",
    definition:
      "Margin of Safety is the percentage gap between the current market price and our DCF-based fair-value estimate. A +30% MoS means the model values the business 30% above the current price; a -20% MoS means the current price sits 20% above the model fair value.",
    whyItMatters:
      "Benjamin Graham coined 'margin of safety' as the discount you demand to protect yourself from being wrong about the inputs. A larger gap gives the model room to be wrong while still leaving you above water. It is the central concept of value investing.",
    formula: "(Fair Value − Current Price) ÷ Current Price × 100",
    ranges: [
      { label: "Above +30%", description: "Deep discount to our model fair value; verify the data behind it." },
      { label: "-10% to +10%", description: "Roughly at our model fair value." },
      { label: "Below -20%", description: "Trading at a premium to our model fair value." },
    ],
    example:
      "If our DCF estimates fair value at ₹2,000 and the share trades at ₹1,500, MoS = (2,000 − 1,500) ÷ 1,500 × 100 = +33.3% — a deep discount to the model's central estimate.",
    caveat:
      "MoS is only as honest as the DCF inputs — treat it as a centre of gravity, not a precise number. A discount paired with deteriorating quality often indicates a value trap.",
    relatedTopics: ["wacc", "terminal_growth", "fcf", "yieldiq_score"],
  },

  // ═════════════════════════════ Misc ═════════════════════════════════
  market_cap: {
    slug: "market-cap",
    title: "Market Capitalisation",
    subtitle: "The market's total valuation of the company's equity.",
    difficulty: "beginner",
    category: "Valuation",
    definition:
      "Market capitalisation is the share price multiplied by the number of shares outstanding. A ₹500 share with 100 crore shares outstanding has a market cap of ₹50,000 crore. It is the headline 'size of the company' number for equity investors.",
    whyItMatters:
      "Market cap is the standard size classifier — SEBI defines large-cap as top 100 by market cap, mid-cap as 101-250, small-cap as 251+. It drives index inclusion, mutual fund mandate fit, and institutional flow patterns.",
    formula: "Share Price × Total Shares Outstanding",
    ranges: [
      { label: "Above ₹50,000 crore", description: "SEBI large-cap definition (top 100 by market cap)." },
      { label: "₹10,000 - 50,000 crore", description: "SEBI mid-cap definition (rank 101-250)." },
      { label: "Below ₹10,000 crore", description: "SEBI small-cap definition (rank 251+)." },
    ],
    example:
      "Reliance Industries with a share price of ₹2,800 and 676 crore shares outstanding has market cap = 2,800 × 676 = ₹18.9 lakh crore. That sits at the top of the Indian-large-cap universe.",
    relatedTopics: ["enterprise_value", "pe", "pb", "free_float"],
  },

  free_float: {
    slug: "free-float",
    title: "Free Float",
    subtitle: "The share of equity actually available to trade in the market.",
    difficulty: "intermediate",
    category: "Risk",
    definition:
      "Free float is the percentage of total shares that are publicly tradable — excluding promoter holdings, government stakes, and other locked-in blocks. A 30% free float means only 30% of the equity actually changes hands in the market.",
    whyItMatters:
      "Low free float means thin liquidity, wider bid-ask spreads, and amplified price volatility around index inclusions, large block trades, or ownership changes. SEBI mandates a minimum 25% free float for continued listing on the main board.",
    formula: "(Total Shares − Promoter & Locked Shares) ÷ Total Shares × 100",
    ranges: [
      { label: "Above 50%", description: "Liquid float; tight spreads and lower idiosyncratic volatility." },
      { label: "25-50%", description: "Typical for promoter-led Indian companies." },
      { label: "Below 25%", description: "Below SEBI minimum; listing-status flag." },
    ],
    example:
      "A company with 100 crore shares, of which 65 crore are held by the promoter group, has a free float of (100 − 65) ÷ 100 × 100 = 35% — typical of promoter-led Indian listed companies.",
    relatedTopics: ["market_cap", "volatility", "beta", "enterprise_value"],
  },
}

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────

/** Returns the topic by slug, or null if not in the library. */
export function getEducationalTopic(slug: string): EducationalTopic | null {
  return EDUCATIONAL_TOPICS[slug] ?? null
}

/** Returns every topic slug. Used by /learn index + sitemap. */
export function getAllTopicSlugs(): string[] {
  return Object.keys(EDUCATIONAL_TOPICS)
}

/** Returns topics grouped by category, in display order. */
export function getTopicsByCategory(): Record<string, EducationalTopic[]> {
  const groups: Record<string, EducationalTopic[]> = {}
  for (const topic of Object.values(EDUCATIONAL_TOPICS)) {
    if (!groups[topic.category]) groups[topic.category] = []
    groups[topic.category].push(topic)
  }
  // Sort within each category by difficulty: beginner → advanced.
  const order: Record<DifficultyTier, number> = {
    beginner: 0,
    intermediate: 1,
    advanced: 2,
  }
  for (const cat of Object.keys(groups)) {
    groups[cat].sort((a, b) => order[a.difficulty] - order[b.difficulty])
  }
  return groups
}

/**
 * Resolve a topic by a flexible key — accepts the canonical slug
 * ("pe"), the kebab variant ("pe-ratio"), or a known metric alias
 * mapped through ALIASES below. Returns null when nothing matches.
 *
 * The aliases let the inline MetricTooltip pass its own metric key
 * (which mirrors `lib/metric-explainers.ts`) without rewriting
 * every call site.
 */
const ALIASES: Record<string, string> = {
  "pe-ratio": "pe",
  "p-e": "pe",
  "pb-ratio": "pb",
  "p-b": "pb",
  "debt-to-equity": "de_ratio",
  "icr": "interest_coverage",
  "ev-ebitda": "ev_ebitda",
  "fcf-yield": "fcf_revenue",
  "fcf-margin": "fcf_revenue",
  "div-yield": "dividend_yield",
  "div-payout": "dividend_payout",
  "eps-growth": "earnings_growth",
  "rev-growth": "revenue_growth",
  "margin-of-safety": "mos",
  "f-score": "piotroski",
}

export function resolveTopic(key: string): EducationalTopic | null {
  const direct = EDUCATIONAL_TOPICS[key]
  if (direct) return direct
  const aliased = ALIASES[key]
  if (aliased) return EDUCATIONAL_TOPICS[aliased] ?? null
  // Try slug-form lookup as last resort.
  for (const topic of Object.values(EDUCATIONAL_TOPICS)) {
    if (topic.slug === key) return topic
  }
  return null
}
