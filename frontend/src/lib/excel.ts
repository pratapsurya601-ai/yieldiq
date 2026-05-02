/**
 * Excel export helper (Task C2)
 * --------------------------------------------------------------------------
 * Builds a .xlsx workbook from already-fetched fair-value page data and
 * triggers a browser download.
 *
 * Library choice: `xlsx` (SheetJS) — already a runtime dependency of
 * frontend (used by /portfolio/import for parsing Zerodha files), so
 * adding the export path here costs zero new dependencies and avoids
 * shipping a second spreadsheet library (`exceljs` would add ~700KB
 * gzipped on top of the existing xlsx bundle). No new npm dep added.
 */
import * as XLSX from "xlsx"
import type {
  StockSummary,
  HistoricalFinancialsResponse,
  RatioHistoryResponse,
  PublicPeersResponse,
} from "@/lib/api"

export interface ExcelBundle {
  ticker: string
  summary: StockSummary
  financials: HistoricalFinancialsResponse | null
  ratios: RatioHistoryResponse | null
  peers: PublicPeersResponse | null
}

function num(n: number | null | undefined): number | string {
  return n == null || !isFinite(n) ? "" : n
}

function buildSummarySheet(s: StockSummary): XLSX.WorkSheet {
  const rows: (string | number)[][] = [
    ["Field", "Value"],
    ["Ticker", s.ticker],
    ["Company", s.company_name],
    ["Sector", s.sector],
    ["Industry", s.industry],
    ["Exchange", s.exchange],
    ["Currency", s.currency],
    [],
    ["Fair Value (DCF)", num(s.fair_value)],
    ["Current Price", num(s.current_price)],
    ["Margin of Safety (%)", num(s.mos)],
    ["Verdict", s.verdict],
    ["YieldIQ Score (/100)", num(s.score)],
    ["Grade", s.grade],
    ["Economic Moat", s.moat],
    ["Piotroski (/9)", num(s.piotroski)],
    ["Confidence (%)", num(s.confidence)],
    ["WACC (%)", num(s.wacc != null ? s.wacc * 100 : null)],
    [],
    ["Bear case FV", num(s.bear_case)],
    ["Base case FV", num(s.base_case)],
    ["Bull case FV", num(s.bull_case)],
    [],
    ["ROE (%)", num(s.roe)],
    ["ROCE (%)", num(s.roce)],
    ["Debt / Equity", num(s.de_ratio)],
    ["Debt / EBITDA", num(s.debt_ebitda)],
    ["Interest Coverage", num(s.interest_coverage)],
    ["Current Ratio", num(s.current_ratio)],
    ["Asset Turnover", num(s.asset_turnover)],
    ["EV / EBITDA", num(s.ev_ebitda)],
    ["Revenue CAGR 3Y", num(s.revenue_cagr_3y != null ? s.revenue_cagr_3y * 100 : null)],
    ["Revenue CAGR 5Y", num(s.revenue_cagr_5y != null ? s.revenue_cagr_5y * 100 : null)],
    ["Market Cap", num(s.market_cap)],
    [],
    ["Last updated", s.last_updated ?? ""],
    ["Source", "yieldiq.in"],
  ]
  return XLSX.utils.aoa_to_sheet(rows)
}

function buildFinancialsSheet(f: HistoricalFinancialsResponse | null): XLSX.WorkSheet {
  if (!f || !f.periods?.length) return XLSX.utils.aoa_to_sheet([["No financials available"]])
  const header = [
    "Period End", "Type", "Revenue", "EBITDA", "EBIT", "PAT", "EPS Diluted",
    "CFO", "Capex", "Free Cash Flow",
    "Total Assets", "Total Equity", "Total Debt", "Cash", "Shares Out.",
    "ROE", "ROA", "D/E", "Gross Margin", "Op Margin", "Net Margin", "FCF Margin",
    "Revenue YoY", "PAT YoY",
  ]
  const rows: (string | number)[][] = [header]
  for (const p of f.periods) {
    rows.push([
      p.period_end, p.period_type,
      num(p.revenue), num(p.ebitda), num(p.ebit), num(p.pat), num(p.eps_diluted),
      num(p.cfo), num(p.capex), num(p.free_cash_flow),
      num(p.total_assets), num(p.total_equity), num(p.total_debt), num(p.cash_and_equivalents), num(p.shares_outstanding),
      num(p.roe), num(p.roa), num(p.debt_to_equity),
      num(p.gross_margin), num(p.operating_margin), num(p.net_margin), num(p.fcf_margin),
      num(p.revenue_growth_yoy), num(p.pat_growth_yoy),
    ])
  }
  return XLSX.utils.aoa_to_sheet(rows)
}

function buildRatiosSheet(r: RatioHistoryResponse | null): XLSX.WorkSheet {
  if (!r || !r.periods?.length) return XLSX.utils.aoa_to_sheet([["No ratio history available"]])
  const header = [
    "Period End", "Type",
    "ROE", "ROCE", "ROA", "D/E", "Debt/EBITDA", "Interest Cov.",
    "Gross Margin", "Op Margin", "Net Margin", "FCF Margin",
    "Revenue YoY", "EBITDA YoY", "PAT YoY", "FCF YoY",
    "P/E", "P/B", "EV/EBITDA", "Div Yield", "Market Cap (Cr)",
    "Current Ratio", "Asset Turnover",
  ]
  const rows: (string | number)[][] = [header]
  for (const p of r.periods) {
    rows.push([
      p.period_end, p.period_type,
      num(p.roe), num(p.roce), num(p.roa), num(p.de_ratio), num(p.debt_ebitda), num(p.interest_cov),
      num(p.gross_margin), num(p.operating_margin), num(p.net_margin), num(p.fcf_margin),
      num(p.revenue_yoy), num(p.ebitda_yoy), num(p.pat_yoy), num(p.fcf_yoy),
      num(p.pe_ratio), num(p.pb_ratio), num(p.ev_ebitda), num(p.dividend_yield), num(p.market_cap_cr),
      num(p.current_ratio), num(p.asset_turnover),
    ])
  }
  return XLSX.utils.aoa_to_sheet(rows)
}

function buildPeersSheet(p: PublicPeersResponse | null): XLSX.WorkSheet {
  if (!p || !p.peers?.length) return XLSX.utils.aoa_to_sheet([["No peer data available"]])
  const header = [
    "Rank", "Ticker", "Company", "Sector", "Sub-sector", "Mcap Ratio",
    "Fair Value", "Current Price", "MoS (%)", "Verdict", "Score", "Moat", "ROE", "P/E",
  ]
  const rows: (string | number)[][] = [header]
  for (const peer of p.peers) {
    rows.push([
      num(peer.rank), peer.ticker ?? peer.peer_ticker, peer.company_name ?? "",
      peer.sector ?? "", peer.sub_sector ?? "", num(peer.mcap_ratio),
      num(peer.fair_value), num(peer.current_price), num(peer.margin_of_safety),
      peer.verdict ?? "", num(peer.score), peer.moat ?? "", num(peer.roe), num(peer.pe_ratio),
    ])
  }
  return XLSX.utils.aoa_to_sheet(rows)
}

function buildScenariosSheet(s: StockSummary): XLSX.WorkSheet {
  const cmp = s.current_price
  // P0 MoS standardization (2026-05-02): denominator is CMP (industry
  // standard), not FV. Display clamped to [-100, +200] to match the
  // backend display contract.
  const mos = (fv: number) => {
    if (!(cmp > 0) || !(fv > 0)) return ""
    const raw = ((fv - cmp) / cmp) * 100
    return Math.max(-100, Math.min(200, raw))
  }
  const rows: (string | number)[][] = [
    ["Scenario", "Fair Value", "Current Price", "MoS (%)"],
    ["Bear", num(s.bear_case), num(cmp), mos(s.bear_case)],
    ["Base", num(s.base_case), num(cmp), mos(s.base_case)],
    ["Bull", num(s.bull_case), num(cmp), mos(s.bull_case)],
    [],
    ["WACC used (%)", num(s.wacc != null ? s.wacc * 100 : null)],
    ["Confidence (%)", num(s.confidence)],
  ]
  return XLSX.utils.aoa_to_sheet(rows)
}

export function buildWorkbook(bundle: ExcelBundle): XLSX.WorkBook {
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, buildSummarySheet(bundle.summary), "Summary")
  XLSX.utils.book_append_sheet(wb, buildFinancialsSheet(bundle.financials), "Historical Financials")
  XLSX.utils.book_append_sheet(wb, buildRatiosSheet(bundle.ratios), "Ratio History")
  XLSX.utils.book_append_sheet(wb, buildPeersSheet(bundle.peers), "Peers")
  XLSX.utils.book_append_sheet(wb, buildScenariosSheet(bundle.summary), "DCF Scenarios")
  return wb
}

export function downloadWorkbook(bundle: ExcelBundle): void {
  const wb = buildWorkbook(bundle)
  const filename = `${bundle.ticker.toUpperCase()}_yieldiq_analysis.xlsx`
  // writeFile triggers a download in browser builds of SheetJS.
  XLSX.writeFile(wb, filename)
}
