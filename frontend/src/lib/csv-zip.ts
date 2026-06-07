/**
 * CSV-bundle export — multiple flat CSVs zipped together (Pro tier).
 * --------------------------------------------------------------------------
 * For users who prefer raw tables over a formatted workbook. Each CSV is
 * a single denormalised slice — summary, annual financials, quarterly,
 * ratios, peers, dividends — accompanied by a README.txt explaining the
 * file map and source attribution.
 *
 * Library choice: jszip (~115KB minified) — well-established, no
 * server-side dependency, runs synchronously in the browser.
 */
import JSZip from "jszip"
import type {
  StockSummary,
  HistoricalFinancialsResponse,
  RatioHistoryResponse,
  PublicPeersResponse,
  DividendHistoryResponse,
} from "@/lib/api"
import { SEBI_DISCLAIMER } from "@/lib/excel-detailed"

export interface CSVBundle {
  ticker: string
  summary: StockSummary
  annualFinancials: HistoricalFinancialsResponse | null
  quarterlyFinancials: HistoricalFinancialsResponse | null
  ratios: RatioHistoryResponse | null
  peers: PublicPeersResponse | null
  dividends: DividendHistoryResponse | null
}

// ── helpers ──────────────────────────────────────────────────────
function csvEscape(v: unknown): string {
  if (v == null) return ""
  if (typeof v === "number") return isFinite(v) ? String(v) : ""
  const s = String(v)
  // RFC 4180: if cell contains comma, quote, or newline → wrap in quotes
  // and double any internal quotes.
  if (/[",\n\r]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`
  }
  return s
}

function toCSV(header: string[], rows: (string | number | null | undefined)[][]): string {
  const lines = [header.map(csvEscape).join(",")]
  for (const r of rows) {
    lines.push(r.map(csvEscape).join(","))
  }
  return lines.join("\r\n") + "\r\n"
}

// ── builders ─────────────────────────────────────────────────────
function buildSummaryCSV(s: StockSummary): string {
  const header = [
    "ticker",
    "company_name",
    "sector",
    "industry",
    "exchange",
    "currency",
    "current_price",
    "fair_value",
    "bear_case",
    "base_case",
    "bull_case",
    "mos_pct",
    "verdict",
    "score",
    "grade",
    "moat",
    "piotroski",
    "confidence_pct",
    "wacc_pct",
    "roe_pct",
    "roce_pct",
    "de_ratio",
    "debt_ebitda",
    "interest_coverage",
    "current_ratio",
    "asset_turnover",
    "ev_ebitda",
    "revenue_cagr_3y",
    "revenue_cagr_5y",
    "market_cap_cr",
    "last_updated",
  ]
  const row = [
    s.ticker,
    s.company_name,
    s.sector,
    s.industry,
    s.exchange,
    s.currency,
    s.current_price,
    s.fair_value,
    s.bear_case,
    s.base_case,
    s.bull_case,
    s.mos,
    s.verdict,
    s.score,
    s.grade,
    s.moat,
    s.piotroski,
    s.confidence,
    s.wacc != null ? s.wacc * 100 : null,
    s.roe,
    s.roce,
    s.de_ratio,
    s.debt_ebitda,
    s.interest_coverage,
    s.current_ratio,
    s.asset_turnover,
    s.ev_ebitda,
    s.revenue_cagr_3y,
    s.revenue_cagr_5y,
    s.market_cap,
    s.last_updated ?? "",
  ]
  return toCSV(header, [row])
}

function buildFinancialsCSV(f: HistoricalFinancialsResponse | null): string {
  const header = [
    "period_end",
    "period_type",
    "revenue",
    "ebitda",
    "ebit",
    "pat",
    "eps_diluted",
    "cfo",
    "capex",
    "free_cash_flow",
    "total_assets",
    "total_equity",
    "total_debt",
    "cash_and_equivalents",
    "shares_outstanding",
    "roe",
    "roa",
    "de_ratio",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf_margin",
    "revenue_yoy",
    "pat_yoy",
  ]
  if (!f || !f.periods?.length) return toCSV(header, [])
  const rows = f.periods.map((p) => [
    p.period_end,
    p.period_type,
    p.revenue,
    p.ebitda,
    p.ebit,
    p.pat,
    p.eps_diluted,
    p.cfo,
    p.capex,
    p.free_cash_flow,
    p.total_assets,
    p.total_equity,
    p.total_debt,
    p.cash_and_equivalents,
    p.shares_outstanding,
    p.roe,
    p.roa,
    p.debt_to_equity,
    p.gross_margin,
    p.operating_margin,
    p.net_margin,
    p.fcf_margin,
    p.revenue_growth_yoy,
    p.pat_growth_yoy,
  ])
  return toCSV(header, rows)
}

function buildRatiosCSV(r: RatioHistoryResponse | null): string {
  const header = [
    "period_end",
    "period_type",
    "roe",
    "roce",
    "roa",
    "de_ratio",
    "debt_ebitda",
    "interest_cov",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf_margin",
    "revenue_yoy",
    "ebitda_yoy",
    "pat_yoy",
    "fcf_yoy",
    "pe_ratio",
    "pb_ratio",
    "ev_ebitda",
    "dividend_yield",
    "market_cap_cr",
    "current_ratio",
    "asset_turnover",
  ]
  if (!r || !r.periods?.length) return toCSV(header, [])
  const rows = r.periods.map((p) => [
    p.period_end,
    p.period_type,
    p.roe,
    p.roce,
    p.roa,
    p.de_ratio,
    p.debt_ebitda,
    p.interest_cov,
    p.gross_margin,
    p.operating_margin,
    p.net_margin,
    p.fcf_margin,
    p.revenue_yoy,
    p.ebitda_yoy,
    p.pat_yoy,
    p.fcf_yoy,
    p.pe_ratio,
    p.pb_ratio,
    p.ev_ebitda,
    p.dividend_yield,
    p.market_cap_cr,
    p.current_ratio,
    p.asset_turnover,
  ])
  return toCSV(header, rows)
}

function buildPeersCSV(p: PublicPeersResponse | null): string {
  const header = [
    "rank",
    "ticker",
    "company_name",
    "sector",
    "sub_sector",
    "mcap_ratio",
    "current_price",
    "fair_value",
    "margin_of_safety",
    "pe_ratio",
    "roe",
    "score",
    "moat",
    "verdict",
  ]
  if (!p || !p.peers?.length) return toCSV(header, [])
  const rows = p.peers.map((pr) => [
    pr.rank,
    pr.ticker ?? pr.peer_ticker,
    pr.company_name,
    pr.sector,
    pr.sub_sector,
    pr.mcap_ratio,
    pr.current_price,
    pr.fair_value,
    pr.margin_of_safety,
    pr.pe_ratio,
    pr.roe,
    pr.score,
    pr.moat,
    pr.verdict,
  ])
  return toCSV(header, rows)
}

function buildDividendsCSV(d: DividendHistoryResponse | null): string {
  const header = ["ex_date", "amount_inr", "source_format"]
  if (!d || !d.dividends?.length) return toCSV(header, [])
  const rows = d.dividends.map((ev) => [ev.ex_date, ev.amount, ev.source_format ?? ""])
  return toCSV(header, rows)
}

function buildReadme(ticker: string): string {
  const today = new Date().toISOString().slice(0, 10)
  return [
    `YieldIQ detailed export — ${ticker}`,
    `Generated: ${today}`,
    "",
    "Files",
    "-----",
    "  summary.csv               One row, all summary fields (current price, fair value, score, moat, ...)",
    "  financials_annual.csv     10 most recent annual periods, full income / cashflow / balance fields.",
    "  financials_quarterly.csv  8 most recent quarterly periods.",
    "  ratios.csv                10 years of ratios (ROE, ROCE, D/E, P/E, ...).",
    "  peers.csv                 Sub-sector peer cohort with FV, score, moat.",
    "  dividends.csv             10 years of dividend events.",
    "",
    "Conventions",
    "-----------",
    "  - Currency: INR. Revenue / earnings figures are in INR Cr unless suffixed otherwise.",
    "  - Per-cent fields are in absolute percent (e.g. 12.3 = 12.3%).",
    "  - Period_end is ISO YYYY-MM-DD. period_type is 'annual' or 'quarterly'.",
    "  - Missing / null values render as empty cells.",
    "",
    "Sources",
    "-------",
    "  - Financials: BSE XBRL filings (primary), yfinance (fallback for missing periods).",
    "  - Prices: NSE / BSE close-of-day.",
    "  - Dividends: BSE corporate-action filings.",
    "  - Peers: Sub-sector cohort filtered by market-cap band.",
    "",
    "Disclaimer",
    "----------",
    SEBI_DISCLAIMER,
    "",
  ].join("\r\n")
}

// ── public API ───────────────────────────────────────────────────
export async function buildCSVZip(bundle: CSVBundle): Promise<Blob> {
  const zip = new JSZip()
  zip.file("summary.csv", buildSummaryCSV(bundle.summary))
  zip.file("financials_annual.csv", buildFinancialsCSV(bundle.annualFinancials))
  zip.file("financials_quarterly.csv", buildFinancialsCSV(bundle.quarterlyFinancials))
  zip.file("ratios.csv", buildRatiosCSV(bundle.ratios))
  zip.file("peers.csv", buildPeersCSV(bundle.peers))
  zip.file("dividends.csv", buildDividendsCSV(bundle.dividends))
  zip.file("README.txt", buildReadme(bundle.ticker))
  return zip.generateAsync({ type: "blob", compression: "DEFLATE" })
}

export async function downloadCSVZip(bundle: CSVBundle): Promise<void> {
  const blob = await buildCSVZip(bundle)
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  const safe = bundle.ticker.replace(/\./g, "_")
  a.download = `YieldIQ_${safe}_data.zip`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// Exports for the test suite
export { buildSummaryCSV, buildFinancialsCSV, buildRatiosCSV, buildPeersCSV, buildDividendsCSV, buildReadme, toCSV, csvEscape }
