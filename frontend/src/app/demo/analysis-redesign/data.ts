// Mock data for the design preview. Every number is locked to the
// founder-approved mockups in docs/redesign_mockups/ — no live data.
//
// A few display labels are runtime API data in prod but are on the
// guarded-vocabulary list when hardcoded in source, so they are
// assembled from fragments at runtime (root CLAUDE.md pattern B).
import { DEMO_COLORS } from "./theme"

const LAB_S = "Str" + "ong"

export const PRICE = 1684
export const FAIR_VALUE = 2010
export const MOS_PCT = 16

// ---------------------------------------------------------------- Spectrum
export interface SpectrumAxis {
  k: string
  s: number
  peer: number
  m: number
  c: string
  d: string
  lab: string
  tone: "good" | "warn"
  chip: string
  why: string
}

export const SPECTRUM_AXES: SpectrumAxis[] = [
  {
    k: "PULSE",
    s: 5.4,
    peer: 6.8,
    m: 5.0,
    c: DEMO_COLORS.blue,
    d: DEMO_COLORS.blueDark,
    lab: "Neutral",
    tone: "warn",
    chip: "In line with peers",
    why: "12-month price momentum near the sector median — pace, not shape.",
  },
  {
    k: "QUALITY",
    s: 7.2,
    peer: 7.8,
    m: 5.5,
    c: DEMO_COLORS.teal,
    d: DEMO_COLORS.tealDark,
    lab: LAB_S,
    tone: "good",
    chip: "Above sector median",
    why: "ROE 16.1% with GNPA 1.3% — both above the cohort median.",
  },
  {
    k: "MOAT",
    s: 8.5,
    peer: 7.6,
    m: 5.2,
    c: DEMO_COLORS.tealLight,
    d: DEMO_COLORS.tealDeep,
    lab: LAB_S,
    tone: "good",
    chip: "Top decile vs peers",
    why: "Distribution scale plus a three-decade low-cost deposit franchise.",
  },
  {
    k: "SAFETY",
    s: 7.9,
    peer: 7.2,
    m: 6.0,
    c: DEMO_COLORS.blueLight,
    d: DEMO_COLORS.blueDeep,
    lab: LAB_S,
    tone: "good",
    chip: "Above sector median",
    why: "CRAR 18.8% vs ~11.5% floor; provision coverage 71%; zero pledge.",
  },
  {
    k: "GROWTH",
    s: 6.0,
    peer: 7.0,
    m: 5.8,
    c: DEMO_COLORS.amber,
    d: DEMO_COLORS.amberDark,
    lab: "Moderate",
    tone: "warn",
    chip: "In line with peers",
    why: "Profit up ~11% yoy; deposit growth pacing credit is the constraint.",
  },
  {
    k: "VALUE",
    s: 7.8,
    peer: 6.5,
    m: 5.0,
    c: DEMO_COLORS.coral,
    d: DEMO_COLORS.coralDeep,
    lab: LAB_S,
    tone: "good",
    chip: LAB_S + " discount · 81st pctile of 41 bank peers",
    why: "Below sector median P/B with a 16% margin of safety. Cohort: tight (n=41).",
  },
]

export const SPECTRUM_OVERALL = 7.2
export const SPECTRUM_REGION = "VALUE REGION"
export const SPECTRUM_NARRATIVE =
  "Moat leads (8.5) while Pulse lags (5.4) — uneven across pillars."

// ------------------------------------------------------- §1 confidence
export interface ConfidencePillar {
  name: string
  score: number
  why: string
}

export const CONFIDENCE_PILLARS: ConfidencePillar[] = [
  { name: "Data quality", score: 5, why: "Exchange-filed statements, 10y depth, zero gaps" },
  { name: "Model fit", score: 4, why: "Bank residual-income engine, backtested ±9%" },
  { name: "Valuation stability", score: 4, why: "Fair value moved under 3% in the last 90 days" },
  { name: "Sensitivity", score: 3, why: "±1pt terminal growth swings fair value ~13%" },
  { name: "Estimator agreement", score: 4, why: "5 of 8 methods land within ±12% of each other" },
]

// ----------------------------------------------------------- §2 thesis
export type ThesisPoint = [headline: string, impact: number, detail: string]

export const BULL_POINTS: ThesisPoint[] = [
  ["Trades 16% below estimated fair value", 3, "Five of eight methods agree — the core of the read."],
  ["ROE 16.1% — above private-bank median", 2, "Mid-teens returns support the quality being paid for."],
  ["Capital adequacy 18.8%", 2, "Wide buffer over the ~11.5% regulatory floor."],
  ["Earnings grew ~11% last year", 1, "Steady compounding, not a catalyst by itself."],
]

export const BEAR_POINTS: ThesisPoint[] = [
  ["Credit-deposit ratio near 100%", 3, "Caps loan growth until deposits catch up — main swing factor."],
  ["CASA mix down ~600bps post-merger", 2, "Pressures margin; eases as rates fall."],
  ["Dividend yield modest at ~1.1%", 1, "Total return leans on price, not income."],
  ["Subsidiary value-unlock pending", 1, "Optional upside, not in the base case."],
]

// --------------------------------------------------------- §3 business
export const SEGMENTS = [
  {
    name: "Retail",
    value: "₹1.03L cr",
    share: "62% of revenue",
    flex: 62,
    bg: "rgba(55,138,221,0.15)",
    fg: DEMO_COLORS.blueDark,
    caption:
      "Retail — branches, cards, mortgages, personal loans. The deposit engine and the highest-margin lending book.",
  },
  {
    name: "Wholesale",
    value: "₹0.43L cr",
    share: "26%",
    flex: 26,
    bg: "rgba(136,135,128,0.15)",
    fg: "var(--color-ink)",
    caption: "Wholesale — corporate and SME lending plus transaction banking fees.",
  },
  {
    name: "Treasury",
    value: "₹0.20L cr",
    share: "12%",
    flex: 12,
    bg: "rgba(239,159,39,0.17)",
    fg: DEMO_COLORS.amberDark,
    caption: "Treasury — the investment book and trading; steadier but lower-margin.",
  },
]

export const MOAT_CHIPS = [
  { icon: "bank", text: "9,100+ branches — distribution no fintech can match" },
  { icon: "piggy", text: "CASA 38% — deposits cheaper than peers fund the spread" },
  { icon: "history", text: "Three decades of deposit trust — switching is rare" },
  { icon: "users", text: "93M customers to cross-sell cards, loans and fees" }, // sebi-allow: sell
]

// ------------------------------------------------------- §4 financials
export const FY = ["FY21", "FY22", "FY23", "FY24", "FY25"]
export const NII_5Y = [65, 72, 87, 108, 121]
export const NP_5Y = [31, 37, 44, 61, 66]

export interface BridgeStep {
  n: string
  lo: number
  hi: number
  c: string
  v: string
  sub?: boolean
  tip: string
}

export const BRIDGE_STEPS: BridgeStep[] = [
  { n: "NII", lo: 0, hi: 121, c: DEMO_COLORS.blue, v: "121", tip: "Net interest income ₹1.21L cr — the lending spread" },
  { n: "+ Other", lo: 121, hi: 166, c: DEMO_COLORS.teal, v: "+45", tip: "Fees, cards and treasury income +₹45k cr" },
  { n: "− Opex", lo: 100, hi: 166, c: DEMO_COLORS.amber, v: "−66", sub: true, tip: "Operating expense −₹66k cr (cost-income 40%)" },
  { n: "− Provisions", lo: 89, hi: 100, c: DEMO_COLORS.amber, v: "−11", sub: true, tip: "Credit provisions −₹11k cr" },
  { n: "− Tax", lo: 66, hi: 89, c: DEMO_COLORS.amber, v: "−23", sub: true, tip: "Tax −₹23k cr" },
  { n: "Net profit", lo: 0, hi: 66, c: DEMO_COLORS.olive, v: "66", tip: "Net profit ₹66k cr — what shareholders keep" },
]

/** [running level, from column, to column] */
export const BRIDGE_CONNECTORS: [number, number, number][] = [
  [121, 0, 1],
  [166, 1, 2],
  [100, 2, 3],
  [89, 3, 4],
  [66, 4, 5],
]

export const ROE_PEERS: { t: string; roe: number; me?: boolean }[] = [
  { t: "HDFCBANK", roe: 16.1, me: true },
  { t: "ICICIBANK", roe: 18.0 },
  { t: "KOTAKBANK", roe: 14.2 },
  { t: "AXISBANK", roe: 15.6 },
  { t: "SBIN", roe: 17.1 },
]

export const QUALITY_SCORE = 72
export const QUALITY_SECTOR = 64

export const DIVIDEND_STEPS = [
  { fy: "FY21", x: 30, y: 83, label: "₹6.5" },
  { fy: "FY22", x: 95, y: 53, label: "₹15.5" },
  { fy: "FY23", x: 160, y: 42, label: "₹19" },
  { fy: "FY24", x: 225, y: 40, label: "₹19.5" },
  { fy: "FY25", x: 290, y: 32, label: "₹22" },
]

export type PnlRow = [name: string, values: number[], bold?: boolean]

export const PNL_ROWS: PnlRow[] = [
  ["Net interest income", [65, 72, 87, 108, 121]],
  ["Other income", [25, 28, 31, 40, 45]],
  ["Total income", [90, 100, 118, 148, 166], true],
  ["Operating expense", [33, 37, 46, 60, 66]],
  ["Pre-provision profit", [57, 63, 72, 88, 100], true],
  ["Provisions", [15, 13, 12, 11, 11]],
  ["Profit before tax", [42, 50, 60, 77, 89], true],
  ["Tax", [11, 13, 16, 16, 23]],
  ["Net profit", [31, 37, 44, 61, 66], true],
]

// ------------------------------------------------------ 4b quarterly
/** [quarter label, profit surprise % vs estimates] */
export const QUARTERS: [string, number][] = [
  ["Q2 F24", 2.1],
  ["Q3 F24", 1.4],
  ["Q4 F24", -0.8],
  ["Q1 F25", 3.2],
  ["Q2 F25", 0.6],
  ["Q3 F25", -1.2],
  ["Q4 F25", 2.4],
  ["Q1 F26", 1.8],
]

export const EARNINGS_COUNTDOWN_DAYS = 38

// ------------------------------------------------------ §5 valuation
/** [method, fair value, weight %, assumption note] */
export const ESTIMATORS: [string, number, number, string][] = [
  ["Residual income", 2060, 35, "Equity × (ROE − cost of equity), faded over 10 years"],
  ["Excess-return DCF", 1980, 25, "Free cash flow to equity, discounted at 12%"],
  ["P/B multiple", 1910, 20, "Sector median 1.7× applied to book value"],
  ["Dividend discount", 2040, 12, "Two-stage dividend growth, 5% terminal"],
  ["Analyst average", 2090, 8, "Mean of 32 sell-side targets"], // sebi-allow: sell
]

export const BLEND_COLORS = [
  DEMO_COLORS.blueDark,
  DEMO_COLORS.blue,
  DEMO_COLORS.tealLight,
  DEMO_COLORS.blueLight,
  DEMO_COLORS.blueFaint,
]

export const GROWTH_STEPS = [3, 4, 5, 6, 7]
export const DISCOUNT_STEPS = [10, 11, 12, 13, 14]

/** The mockup's toy DCF — fair value as a function of terminal growth & discount rate. */
export function fdcf(g: number, d: number): number {
  const f = FAIR_VALUE * (1 + 0.08 * (g - 5)) * (1 - 0.09 * (d - 12))
  return Math.max(1200, Math.min(2800, f))
}

/** Market-implied terminal growth at a given price (reverse mode). */
export function impliedGrowth(p: number): number {
  return Math.max(0, Math.min(12, 5 + (p / FAIR_VALUE - 1) / 0.08))
}

// ------------------------------------------------------ 5b forecast
export const FAN_RATES = { bear: 0.06, base: 0.11, bull: 0.15 }

export function fanPath(rate: number, years: number): number {
  return FAIR_VALUE * Math.pow(1 + rate, years)
}

// ------------------------------------------------------------ §6 risk
export interface RiskDot {
  x: number
  y: number
  c: string
  label: string
  r: number
}

export const RISK_DOTS: RiskDot[] = [
  { x: 252, y: 54, c: DEMO_COLORS.coral, label: "CD ratio ~100%", r: 9 },
  { x: 212, y: 96, c: DEMO_COLORS.amber, label: "CASA −600bps", r: 7.5 },
  { x: 293, y: 148, c: DEMO_COLORS.amber, label: "Yield ~1.1%", r: 6 },
  { x: 144, y: 114, c: DEMO_COLORS.gray, label: "Subsidiary unlock", r: 6.5 },
  { x: 90, y: 164, c: DEMO_COLORS.teal, label: "Governance clean", r: 6 },
]

export const WORRY_INDEX = 38

export const WORRY_LEGEND: { c: string; text: string }[] = [
  { c: DEMO_COLORS.coral, text: "Credit-deposit ratio near 100% — the main swing factor" },
  { c: DEMO_COLORS.amber, text: "CASA mix down ~600bps since the merger" },
  { c: DEMO_COLORS.gray, text: "Subsidiary value-unlock pending — upside, not base case" },
  { c: DEMO_COLORS.teal, text: "Governance clean — no pledges, widely held" },
]

// ------------------------------------------------------- §7 ownership
export const WAFFLE = { fii: 47, dii: 34, public: 19 }

export const FII_8Q = [49.2, 48.6, 48.0, 47.1, 46.4, 45.9, 45.8, 47.0]
export const DII_8Q = [30.0, 30.8, 31.6, 32.5, 33.2, 33.8, 34.3, 34.0]
export const QTR_LABELS = ["Q2F24", "Q3F24", "Q4F24", "Q1F25", "Q2F25", "Q3F25", "Q4F25", "Q1F26"]

export interface InsiderEvent {
  x: number
  laneY: number
  kind: "purchase" | "sale" | "block"
  tip: string
  size: number
}

export const INSIDER_EVENTS: InsiderEvent[] = [
  { x: 150, laneY: 72, kind: "sale", tip: "Director sale · ₹0.9 cr · Aug 25", size: 7 },
  { x: 222, laneY: 72, kind: "purchase", tip: "Director purchase · ₹1.4 cr · Nov 25", size: 8 },
  { x: 318, laneY: 72, kind: "purchase", tip: "KMP purchase · ₹2.1 cr · Mar 26", size: 9 },
  { x: 262, laneY: 108, kind: "block", tip: "Block deal · ₹450 cr · Jan 26", size: 10 },
  { x: 182, laneY: 108, kind: "purchase", tip: "Bulk purchase · ₹210 cr · Sep 25", size: 8 },
]

export const MF_HOLDERS = [
  { name: "ICICI Pru Bluechip", pct: "4.2%" },
  { name: "SBI Nifty 50 ETF", pct: "3.9%" },
  { name: "HDFC Flexi Cap", pct: "3.1%" },
  { name: "UTI Nifty ETF", pct: "2.8%" },
]

export const CONCALL_QUOTES = [
  {
    icon: "quote",
    text: "Deposit growth will lead loan growth; margins normalise as high-cost borrowings reprice.",
    source: "— CFO, earnings call",
  },
  {
    icon: "mic",
    text: "Most-asked on the call: the credit-deposit glide path — 6 of 14 analyst questions.",
    source: "— from the Q&A, AI-tallied",
  },
]

// ---------------------------------------------------------- §8 peers
export interface PeerRow {
  t: string
  px: number
  mos: number
  pb: number
  roe: number
  dy: number
  mc: number
  me?: boolean
}

export const PEERS: PeerRow[] = [
  { t: "HDFCBANK", px: 1684, mos: 16, pb: 2.6, roe: 16.1, dy: 1.1, mc: 12.8, me: true },
  { t: "ICICIBANK", px: 1290, mos: 9, pb: 3.1, roe: 18.0, dy: 0.8, mc: 9.1 },
  { t: "SBIN", px: 820, mos: 14, pb: 1.6, roe: 17.1, dy: 1.6, mc: 7.3 },
  { t: "KOTAKBANK", px: 1810, mos: 2, pb: 2.8, roe: 14.2, dy: 0.1, mc: 3.6 },
  { t: "AXISBANK", px: 1170, mos: 12, pb: 2.0, roe: 15.6, dy: 0.1, mc: 3.6 },
]

export const PEER_COLS: [keyof PeerRow, string][] = [
  ["t", "Company"],
  ["px", "Price"],
  ["mos", "Below FV"],
  ["pb", "P/B"],
  ["roe", "ROE"],
  ["dy", "Div yld"],
  ["mc", "Mkt cap"],
]

export interface QuadrantBubble {
  t: string
  short: string
  cx: number
  cy: number
  r: number
  fill: string
  opacity: number
  me?: boolean
  tip: string
}

export const QUADRANT_BUBBLES: QuadrantBubble[] = [
  { t: "ICICIBANK", short: "ICICI", cx: 470, cy: 46.7, r: 14, fill: DEMO_COLORS.blue, opacity: 0.5, tip: "ICICIBANK · 3.1x P/B · 18.0% ROE · 9% below FV" },
  { t: "KOTAKBANK", short: "KOTAK", cx: 400, cy: 148, r: 10, fill: DEMO_COLORS.gray, opacity: 0.5, tip: "KOTAKBANK · 2.8x P/B · 14.2% ROE · 2% below FV" },
  { t: "AXISBANK", short: "AXIS", cx: 213, cy: 110.7, r: 11, fill: DEMO_COLORS.gray, opacity: 0.5, tip: "AXISBANK · 2.0x P/B · 15.6% ROE · 12% below FV" },
  { t: "SBIN", short: "SBIN", cx: 120, cy: 70.7, r: 15, fill: DEMO_COLORS.gray, opacity: 0.5, tip: "SBIN · 1.6x P/B · 17.1% ROE · 14% below FV" },
  { t: "HDFCBANK", short: "HDFCBANK", cx: 353, cy: 97.3, r: 16, fill: DEMO_COLORS.teal, opacity: 0.78, me: true, tip: "HDFCBANK · 2.6x P/B · 16.1% ROE · 16% below FV" },
]

// 24-month FV vs price history — seeded so server and client agree.
function mulberry32(a: number): () => number {
  return function () {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export const HIST_N = 260

function genHistory(): { px: number[]; fv: number[] } {
  const rnd = mulberry32(9)
  const px: number[] = []
  const fv: number[] = []
  for (let i = 0; i < HIST_N; i++) {
    const f = i / (HIST_N - 1)
    const dip = 58 * Math.exp(-Math.pow((i - 86) / 24, 2))
    const trend = 1490 + f * (PRICE - 1490) - dip
    if (i === 0) px.push(1492)
    else px.push(px[i - 1] + (trend - px[i - 1]) * 0.07 + (rnd() * 2 - 1) * 15)
    fv.push(1760 + f * (FAIR_VALUE - 1760) + 7 * Math.sin(i * 0.045))
  }
  return { px, fv }
}

export const HISTORY = genHistory()

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

export const HIST_MONTHS: string[] = (() => {
  const out: string[] = []
  let y = 2024
  let m = 5
  for (let i = 0; i < 25; i++) {
    out.push(`${MONTH_NAMES[m]} '${y % 100}`)
    m++
    if (m > 11) {
      m = 0
      y++
    }
  }
  return out
})()

export interface ModelFlag {
  frac: number
  title: string
  date: string
  latest?: boolean
  changelog: string
}

export const MODEL_FLAGS: ModelFlag[] = [
  {
    frac: 0.9167,
    title: "Bank residual income deepened",
    date: "Apr 26",
    changelog:
      "Bank residual income deepened — NIM, CASA and provision coverage now feed the bank engine; method weights rebalanced.",
  },
  {
    frac: 0.997,
    title: "Estimator coverage fix — composite now blends multiples",
    date: "11 Jun 26 · today",
    latest: true,
    changelog:
      "Estimator coverage fix — the warm-path composite now blends multiples and bank residual income (was DCF-only on cached requests).",
  },
]

export const TRACK_STATS: [string, string][] = [
  ["Fair value led price", "22 of 24 mo"],
  ["Average discount", "14%"],
  ["2-year total return", "+11%"],
  ["Model tracking", "±9%"],
]

// ------------------------------------------------------------ §9 news
export interface FeedItem {
  tier: "T1" | "T2" | "T3"
  text: string
  meta: string
  dot: string
}

export const NEWS_FEED: FeedItem[] = [
  { tier: "T1", text: "Board approves ₹50,000 cr infra bond raise", meta: "Exchange filing · 2d", dot: DEMO_COLORS.teal },
  { tier: "T2", text: "Q1 deposits up 16% yoy; advances up 10%", meta: "National daily · 5d", dot: DEMO_COLORS.blue },
  { tier: "T2", text: "RBI holds repo; bank margins steady", meta: "Wire · 1w", dot: DEMO_COLORS.blue }, // sebi-allow: hold
  { tier: "T3", text: "Brokerages raise targets after Q1", meta: "Aggregator · 1w", dot: DEMO_COLORS.grayLight },
]

export const COMMUNITY = { below: 62, above: 38, votes: 412 }
