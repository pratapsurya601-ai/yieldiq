/**
 * Programmatic SEO content experiment — tickers + per-ticker company
 * metadata for /fair-value/[TICKER] pages.
 *
 * 12 NIFTY-50 large-caps chosen as a proxy for organic search demand
 * (no paid SEO tooling). ADR cohort tickers (TCS / INFY / WIPRO /
 * HCLTECH / TECHM) are deliberately excluded — the TCS-class
 * compute-error risk on those is high enough that we do not want a
 * programmatic content surface amplifying any vocab leak.
 *
 * The hypothesis under test (4-week window from Search-Console
 * submission): impressions add up on `[ticker] fair value` /
 * `[ticker] intrinsic value` / `[ticker] dcf analysis` queries on
 * multiple tickers. If yes → programmatic content is a real growth
 * lever and we extend. If no → SEO is not the channel and we pivot.
 *
 * Per-ticker `moatPhrase` is a hand-authored, descriptive sentence
 * about the firm's economic moat in factual terms (no advisory
 * language, none of the banned-vocabulary qualifiers). The DCF /
 * quality numbers come from the live /api/v1/prism payload at SSR
 * time — only the prose framing is static here.
 */

export interface FairValueTickerConfig {
  /** API + display ticker (NSE suffix included where applicable). */
  ticker: string
  /** Bare display ticker (no `.NS` / `.BO` suffix), used in copy. */
  displayTicker: string
  /** Plain-English company name as used in headings + meta. */
  companyName: string
  /** Short factual sentence about the firm's economic moat. */
  moatPhrase: string
  /** Per-ticker peer-comparison list (bare display tickers). */
  peers: string[]
}

export const FAIR_VALUE_TICKERS: FairValueTickerConfig[] = [
  {
    ticker: "RELIANCE.NS",
    displayTicker: "RELIANCE",
    companyName: "Reliance Industries",
    moatPhrase:
      "Reliance's moat rests on integrated scale across refining and petrochemicals, a national 4G/5G subscriber base in Jio, and a national retail footprint that few peers can match on capex alone.",
    peers: ["ONGC", "BPCL", "IOC"],
  },
  {
    ticker: "HDFCBANK.NS",
    displayTicker: "HDFCBANK",
    companyName: "HDFC Bank",
    moatPhrase:
      "HDFC Bank's moat comes from a low-cost current-and-savings deposit franchise, switching costs that keep retail accounts sticky, and an underwriting record that has produced one of the lowest credit-cost cycles in Indian private banking.",
    peers: ["ICICIBANK", "KOTAKBANK", "AXISBANK"],
  },
  {
    ticker: "ICICIBANK.NS",
    displayTicker: "ICICIBANK",
    companyName: "ICICI Bank",
    moatPhrase:
      "ICICI Bank's moat is anchored in its digital channel reach, a diversified retail and corporate book, and a deposit cost structure that has converged toward the best private-bank peers over the last credit cycle.",
    peers: ["HDFCBANK", "KOTAKBANK", "AXISBANK"],
  },
  {
    ticker: "BHARTIARTL.NS",
    displayTicker: "BHARTIARTL",
    companyName: "Bharti Airtel",
    moatPhrase:
      "Bharti Airtel's moat is structural — Indian telecom is a three-player market after consolidation, spectrum holdings are a regulated barrier to entry, and the firm's premium subscriber mix supports higher ARPU than its national peers.",
    peers: ["IDEA", "RELIANCE"],
  },
  {
    ticker: "ITC.NS",
    displayTicker: "ITC",
    companyName: "ITC",
    moatPhrase:
      "ITC's moat is brand and distribution density in cigarettes, a category protected by regulatory entry barriers, alongside a diversified FMCG / hotels / agri portfolio built on the same national distribution backbone.",
    peers: ["HINDUNILVR", "NESTLEIND", "BRITANNIA"],
  },
  {
    ticker: "SBIN.NS",
    displayTicker: "SBIN",
    companyName: "State Bank of India",
    moatPhrase:
      "SBI's moat is reach — the largest branch and ATM network in the country, a deposit franchise underwritten by sovereign perception, and a government-banking relationship pipeline that private peers cannot replicate.",
    peers: ["HDFCBANK", "ICICIBANK", "AXISBANK"],
  },
  {
    ticker: "LT.NS",
    displayTicker: "LT",
    companyName: "Larsen & Toubro",
    moatPhrase:
      "Larsen & Toubro's moat is project-execution capability at scale, a domestic infrastructure order book that compounds with public capex, and an engineering services arm that has matured into a meaningful recurring-revenue contributor.",
    peers: ["RELIANCE"],
  },
  {
    ticker: "HINDUNILVR.NS",
    displayTicker: "HINDUNILVR",
    companyName: "Hindustan Unilever",
    moatPhrase:
      "Hindustan Unilever's moat is decades of brand investment across home / personal care / foods categories, a rural-and-urban distribution depth few FMCG peers can match, and a Unilever-parent R&D pipeline that lowers product-development cost.",
    peers: ["ITC", "NESTLEIND", "DABUR"],
  },
  {
    ticker: "BAJFINANCE.NS",
    displayTicker: "BAJFINANCE",
    companyName: "Bajaj Finance",
    moatPhrase:
      "Bajaj Finance's moat is its consumer-finance origination engine — a multi-million-customer base that supports cross-product distribution, a digital onboarding stack built over a decade, and an underwriting record that has so far navigated retail credit cycles without large slippage.",
    peers: ["HDFCBANK", "ICICIBANK"],
  },
  {
    ticker: "AXISBANK.NS",
    displayTicker: "AXISBANK",
    companyName: "Axis Bank",
    moatPhrase:
      "Axis Bank's moat is a national branch and digital franchise that lands it in the third spot among Indian private banks, with retail credit growth converging toward the leading peers and a corporate book that has been cleaned up over recent cycles.",
    peers: ["HDFCBANK", "ICICIBANK", "KOTAKBANK"],
  },
  {
    ticker: "KOTAKBANK.NS",
    displayTicker: "KOTAKBANK",
    companyName: "Kotak Mahindra Bank",
    moatPhrase:
      "Kotak Mahindra Bank's moat is a conservatively underwritten loan book, an affluent customer mix that supports a low cost of deposits, and a diversified financial-services group spanning lending, broking and asset management.",
    peers: ["HDFCBANK", "ICICIBANK", "AXISBANK"],
  },
  {
    ticker: "MARUTI.NS",
    displayTicker: "MARUTI",
    companyName: "Maruti Suzuki",
    moatPhrase:
      "Maruti Suzuki's moat is the largest passenger-vehicle dealer and service network in India, a parent-Suzuki technology pipeline, and a small-car cost structure that competitors have repeatedly tried and failed to displace at price.",
    peers: ["TATAMOTORS", "M%26M"],
  },
]

/**
 * Bare-display-ticker lookup. Used by the page route handler to map
 * the URL segment (which we accept as either `HDFCBANK` or
 * `HDFCBANK.NS`) onto the canonical config entry.
 */
export function findFairValueConfig(
  routeParam: string,
): FairValueTickerConfig | null {
  const upper = routeParam.toUpperCase()
  const bare = upper.replace(/\.(NS|BO)$/i, "")
  return (
    FAIR_VALUE_TICKERS.find(
      (c) => c.displayTicker === bare || c.ticker.toUpperCase() === upper,
    ) ?? null
  )
}
