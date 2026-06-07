/**
 * Detailed Excel export — 11-sheet analyst-grade workbook (Pro tier).
 * --------------------------------------------------------------------------
 * Builds a multi-sheet .xlsx workbook entirely in the browser. The basic
 * 5-sheet workbook lives in `lib/excel.ts` and is still used by the free
 * one-click ExcelExportButton; this module adds the Pro-tier 11-sheet
 * workbook driven by FORMULA cells (editing assumptions in the DCF sheet
 * recomputes downstream cells, including the 5x5 Sensitivity Matrix).
 *
 * Library choice
 * --------------
 * Reuses the existing `xlsx` (SheetJS) dependency — already bundled for
 * the basic export, no new dependency added on the Excel side.
 *
 * Conventions (per skills/xlsx)
 * ----------------------------
 *  - Blue text on EDITABLE assumption cells (so the user sees what they
 *    are allowed to change), black text on formula cells.
 *  - INR formatting in headers, e.g. "Revenue (₹Cr)".
 *  - Number format "₹#,##0.00" for currency, "0.00%" for percentages,
 *    plain integer for share counts and years.
 *  - All DCF derivations use Excel formulas referencing the assumption
 *    cells, so editing the assumptions recomputes the fair value live
 *    in Excel — no hardcoded propagation.
 */
import * as XLSX from "xlsx"
import type {
  StockSummary,
  HistoricalFinancialsResponse,
  RatioHistoryResponse,
  PublicPeersResponse,
  DividendHistoryResponse,
  HistoricalFinancialsPeriod,
} from "@/lib/api"

export interface DetailedExcelBundle {
  ticker: string
  summary: StockSummary
  annualFinancials: HistoricalFinancialsResponse | null
  quarterlyFinancials: HistoricalFinancialsResponse | null
  ratios: RatioHistoryResponse | null
  peers: PublicPeersResponse | null
  dividends: DividendHistoryResponse | null
}

// ── SEBI-clean disclaimer ────────────────────────────────────────
// This is the only piece of free text that ships in the workbook;
// every other cell is either a label, a number, or a formula. The
// copy is descriptive — no advisory verbs — so it passes the SEBI
// frontend lint.
export const SEBI_DISCLAIMER =
  "Model-generated description of metrics. Not investment advice. " +
  "YieldIQ is not a SEBI-registered Investment Advisor. This workbook " +
  "contains computed metrics for informational use only. Past performance " +
  "is not indicative of future returns. Consult a SEBI-registered advisor " +
  "for any investment decision."

const METHODOLOGY_NOTE =
  "Fair value is computed via a 5-year free-cash-flow projection " +
  "discounted at WACC, with a Gordon-growth terminal value. WACC is built " +
  "from the risk-free rate, equity-risk premium, levered beta, after-tax " +
  "cost of debt, and a debt-weight derived from the capital structure. " +
  "Bear / base / bull scenarios apply +/- 25% to the FCF growth and " +
  "terminal-growth inputs."

// ── helpers ──────────────────────────────────────────────────────
function n(v: number | null | undefined): number | "" {
  return v == null || !isFinite(v) ? "" : v
}

function applyHeader(ws: XLSX.WorkSheet, row: number, ncols: number): void {
  // Bold the first `ncols` cells of `row` (zero-indexed).
  for (let c = 0; c < ncols; c++) {
    const addr = XLSX.utils.encode_cell({ r: row, c })
    const cell = ws[addr]
    if (cell) {
      cell.s = {
        font: { bold: true, color: { rgb: "FFFFFF" } },
        fill: { fgColor: { rgb: "1E3A8A" } },
        alignment: { horizontal: "center" },
      }
    }
  }
}

function applyAssumptionStyle(ws: XLSX.WorkSheet, addr: string): void {
  const cell = ws[addr]
  if (cell) {
    cell.s = {
      font: { color: { rgb: "1D4ED8" }, bold: true },
      fill: { fgColor: { rgb: "EFF6FF" } },
    }
  }
}

function applyNumberFormat(ws: XLSX.WorkSheet, addr: string, fmt: string): void {
  const cell = ws[addr]
  if (cell && typeof cell.v === "number") {
    cell.z = fmt
  }
}

function setColWidths(ws: XLSX.WorkSheet, widths: number[]): void {
  ws["!cols"] = widths.map((wch) => ({ wch }))
}

// ── 1. Cover sheet ───────────────────────────────────────────────
function buildCoverSheet(s: StockSummary): XLSX.WorkSheet {
  const today = new Date().toISOString().slice(0, 10)
  const rows: (string | number)[][] = [
    ["YieldIQ Analyst Report"],
    [],
    ["Ticker", s.ticker],
    ["Company", s.company_name],
    ["Sector", s.sector],
    ["Industry", s.industry],
    ["Exchange", s.exchange],
    ["Currency", s.currency],
    ["Report date", today],
    ["Data last updated", s.last_updated ?? ""],
    [],
    ["Valuation summary"],
    ["Current price", n(s.current_price)],
    ["Fair value (base)", n(s.fair_value)],
    ["Bear case FV", n(s.bear_case)],
    ["Base case FV", n(s.base_case)],
    ["Bull case FV", n(s.bull_case)],
    ["Discount to FV (%)", n(s.mos)],
    ["Verdict (computed)", s.verdict],
    [],
    ["Quality scorecard"],
    ["YieldIQ score (/100)", n(s.score)],
    ["Grade", s.grade],
    ["Economic moat", s.moat],
    ["Piotroski (/9)", n(s.piotroski)],
    ["Confidence (%)", n(s.confidence)],
    [],
    ["Disclaimer"],
    [SEBI_DISCLAIMER],
  ]
  const ws = XLSX.utils.aoa_to_sheet(rows)
  setColWidths(ws, [28, 60])
  // Format currency cells
  for (const addr of ["B13", "B14", "B15", "B16", "B17"]) {
    applyNumberFormat(ws, addr, "₹#,##0.00")
  }
  applyNumberFormat(ws, "B18", "0.00")
  applyNumberFormat(ws, "B22", "0")
  applyNumberFormat(ws, "B25", "0")
  applyNumberFormat(ws, "B26", "0.0")
  // Merge the disclaimer cell across two columns
  ws["!merges"] = [
    { s: { r: 28, c: 0 }, e: { r: 28, c: 1 } },
  ]
  return ws
}

// ── 2. Valuation Summary sheet ────────────────────────────────────
function buildValuationSummarySheet(s: StockSummary): XLSX.WorkSheet {
  const rows: (string | number)[][] = [
    ["Scenario", "Fair value (₹)", "Current price (₹)", "Discount (%)", "Weight"],
    ["Bear",  n(s.bear_case), n(s.current_price), "", 0.25],
    ["Base",  n(s.base_case), n(s.current_price), "", 0.50],
    ["Bull",  n(s.bull_case), n(s.current_price), "", 0.25],
    [],
    ["Probability-weighted FV", "", "", "", ""],
    [],
    ["WACC summary"],
    ["WACC used (%)", n(s.wacc != null ? s.wacc * 100 : null)],
    ["Confidence (%)", n(s.confidence)],
    [],
    ["Note", METHODOLOGY_NOTE],
  ]
  const ws = XLSX.utils.aoa_to_sheet(rows)
  // Discount formula = (FV - CMP) / CMP * 100
  ws["D2"] = { t: "n", f: "(B2-C2)/C2*100" }
  ws["D3"] = { t: "n", f: "(B3-C3)/C3*100" }
  ws["D4"] = { t: "n", f: "(B4-C4)/C4*100" }
  // Probability-weighted FV
  ws["B6"] = { t: "n", f: "B2*E2 + B3*E3 + B4*E4" }
  // Number formats
  for (const r of [2, 3, 4]) {
    applyNumberFormat(ws, `B${r}`, "₹#,##0.00")
    applyNumberFormat(ws, `C${r}`, "₹#,##0.00")
    applyNumberFormat(ws, `D${r}`, "0.00")
    applyNumberFormat(ws, `E${r}`, "0%")
  }
  applyNumberFormat(ws, "B6", "₹#,##0.00")
  applyNumberFormat(ws, "B9", "0.00")
  applyNumberFormat(ws, "B10", "0.0")
  // Style header row
  applyHeader(ws, 0, 5)
  // Mark scenario weights as editable assumptions
  for (const addr of ["E2", "E3", "E4"]) applyAssumptionStyle(ws, addr)
  setColWidths(ws, [26, 16, 18, 14, 10])
  ws["!merges"] = [{ s: { r: 11, c: 1 }, e: { r: 11, c: 4 } }]
  return ws
}

// ── 3. DCF model sheet — editable assumptions + formulas ─────────
function buildDCFModelSheet(s: StockSummary, ann: HistoricalFinancialsResponse | null): XLSX.WorkSheet {
  // Anchor: latest FCF from the most recent annual period if available;
  // otherwise fall back to a synthesized number derived from EBITDA/EBIT
  // estimates. Editable so the user can override.
  let latestFCF = 0
  let sharesOutCr: number | null = null
  if (ann && ann.periods?.length) {
    // periods are sorted newest first in most callers; defensive sort
    const sorted = [...ann.periods].sort((a, b) =>
      (b.period_end ?? "").localeCompare(a.period_end ?? ""),
    )
    const latest = sorted[0]
    latestFCF = latest.free_cash_flow ?? latest.cfo ?? 0
    // Pull shares outstanding from the latest annual period. The XBRL
    // ingestor stores shares as an absolute count, so convert to Cr
    // (the unit used throughout this sheet) by dividing by 1e7.
    if (latest.shares_outstanding != null && isFinite(latest.shares_outstanding) && latest.shares_outstanding > 0) {
      const raw = latest.shares_outstanding
      // Heuristic: if the value is already small (< 1e5), treat it as
      // already-in-crores; otherwise treat it as an absolute count.
      sharesOutCr = raw < 1e5 ? raw : raw / 1e7
    }
  }
  // Fallback: derive shares from market_cap / current_price. market_cap
  // is in absolute rupees in StockSummary (see useHeroSignals.ts which
  // divides by 1e7 to display Cr), so the quotient is share count in
  // absolute units — divide by 1e7 for crores.
  if (sharesOutCr == null && s.market_cap > 0 && s.current_price > 0) {
    sharesOutCr = s.market_cap / s.current_price / 1e7
  }
  // Final fallback if nothing usable — leave as 100 Cr placeholder so
  // the formula chain still evaluates rather than #DIV/0!. Mark it via
  // the editable-assumption cell style so the user sees it is overridable.
  const sharesOutValue = sharesOutCr != null && isFinite(sharesOutCr) && sharesOutCr > 0 ? sharesOutCr : 100

  // The sheet layout — assumptions in rows 2-12, projection in 14+
  const rows: (string | number)[][] = [
    ["Assumption", "Value", "Unit", "Note"],
    ["Latest FCF (₹Cr)", latestFCF, "₹Cr", "Anchor — most recent annual FCF"],
    ["FCF growth, years 1-5 (%)", 8, "% p.a.", "Edit to flex growth"],
    ["Terminal growth (%)", 4, "%", "Long-run nominal GDP proxy"],
    ["Risk-free rate (%)", 7.0, "%", "10Y G-Sec"],
    ["Equity risk premium (%)", 6.0, "%", "India ERP"],
    ["Levered beta", 1.0, "x", "Sector beta"],
    ["Pre-tax cost of debt (%)", 9.0, "%", "Credit-adjusted"],
    ["Tax rate (%)", 25.0, "%", "Effective corporate"],
    ["Debt weight", 0.30, "ratio", "D / (D+E)"],
    ["Shares outstanding (Cr)", sharesOutValue, "Cr", "Diluted (from latest XBRL filing or mcap/price fallback)"],
    [],
    ["WACC build", "", "", ""],
    ["Cost of equity (%)", "", "%", "Rf + Beta * ERP"],
    ["After-tax cost of debt (%)", "", "%", "Kd * (1-T)"],
    ["WACC (%)", "", "%", "Wd * Kd_at + We * Ke"],
    [],
    ["Year", "FCF (₹Cr)", "Discount factor", "PV (₹Cr)"],
    [1, "", "", ""],
    [2, "", "", ""],
    [3, "", "", ""],
    [4, "", "", ""],
    [5, "", "", ""],
    [],
    ["Terminal value (₹Cr)", "", "", ""],
    ["PV of terminal (₹Cr)", "", "", ""],
    ["Sum of PVs (₹Cr)", "", "", ""],
    ["Equity value per share (₹)", "", "", ""],
  ]

  const ws = XLSX.utils.aoa_to_sheet(rows)

  // Cell addresses (1-indexed in Excel, 0-indexed in api):
  //   B2 = latest FCF, B3 = growth %, B4 = terminal growth %,
  //   B5 = rf, B6 = erp, B7 = beta, B8 = kd_pre, B9 = tax,
  //   B10 = debt weight, B11 = shares out.
  //   B14 = cost of equity, B15 = after-tax kd, B16 = WACC.
  //   Projection: B19..B23 = FCF Y1..Y5, C19..C23 = discount factor, D19..D23 = PV.
  //   B25 = terminal value, B26 = PV of terminal, B27 = sum of PVs,
  //   B28 = equity value per share.

  // Cost of equity = Rf + Beta * ERP
  ws["B14"] = { t: "n", f: "B5 + B7*B6" }
  // After-tax cost of debt = Kd_pre * (1 - tax)
  ws["B15"] = { t: "n", f: "B8 * (1 - B9/100)" }
  // WACC = Wd * Kd_at + We * Ke
  ws["B16"] = { t: "n", f: "B10*B15 + (1-B10)*B14" }

  // Projected FCF: B19 = B2*(1+B3/100), B20 = B19*(1+B3/100), etc.
  ws["B19"] = { t: "n", f: "B2*(1+B3/100)" }
  ws["B20"] = { t: "n", f: "B19*(1+B3/100)" }
  ws["B21"] = { t: "n", f: "B20*(1+B3/100)" }
  ws["B22"] = { t: "n", f: "B21*(1+B3/100)" }
  ws["B23"] = { t: "n", f: "B22*(1+B3/100)" }

  // Discount factor = 1 / (1 + WACC/100)^year
  ws["C19"] = { t: "n", f: "1/POWER(1+B$16/100, A19)" }
  ws["C20"] = { t: "n", f: "1/POWER(1+B$16/100, A20)" }
  ws["C21"] = { t: "n", f: "1/POWER(1+B$16/100, A21)" }
  ws["C22"] = { t: "n", f: "1/POWER(1+B$16/100, A22)" }
  ws["C23"] = { t: "n", f: "1/POWER(1+B$16/100, A23)" }

  // PV = FCF * DF
  ws["D19"] = { t: "n", f: "B19*C19" }
  ws["D20"] = { t: "n", f: "B20*C20" }
  ws["D21"] = { t: "n", f: "B21*C21" }
  ws["D22"] = { t: "n", f: "B22*C22" }
  ws["D23"] = { t: "n", f: "B23*C23" }

  // Terminal value = FCF_y5 * (1 + g) / (WACC - g)
  ws["B25"] = { t: "n", f: "B23*(1+B4/100)/((B16-B4)/100)" }
  // PV of terminal = TV * discount-factor at year 5
  ws["B26"] = { t: "n", f: "B25*C23" }
  // Sum of PVs = sum of PV column + PV of terminal
  ws["B27"] = { t: "n", f: "SUM(D19:D23)+B26" }
  // Equity per share = Sum of PVs / shares out
  ws["B28"] = { t: "n", f: "B27/B11" }

  // Style — mark editable assumption cells
  const assumptions = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "B11"]
  for (const addr of assumptions) applyAssumptionStyle(ws, addr)

  // Number formats
  applyNumberFormat(ws, "B2", "#,##0.00")
  applyNumberFormat(ws, "B11", "#,##0.00")
  for (const r of [3, 4, 5, 6, 8, 9]) applyNumberFormat(ws, `B${r}`, "0.00")
  applyNumberFormat(ws, "B7", "0.00")
  applyNumberFormat(ws, "B10", "0.00")
  applyNumberFormat(ws, "B14", "0.00")
  applyNumberFormat(ws, "B15", "0.00")
  applyNumberFormat(ws, "B16", "0.00")
  for (let r = 19; r <= 23; r++) {
    applyNumberFormat(ws, `B${r}`, "#,##0.00")
    applyNumberFormat(ws, `C${r}`, "0.0000")
    applyNumberFormat(ws, `D${r}`, "#,##0.00")
  }
  applyNumberFormat(ws, "B25", "#,##0.00")
  applyNumberFormat(ws, "B26", "#,##0.00")
  applyNumberFormat(ws, "B27", "#,##0.00")
  applyNumberFormat(ws, "B28", "₹#,##0.00")

  // Headers (row 1 and row 18)
  applyHeader(ws, 0, 4)
  applyHeader(ws, 17, 4)

  setColWidths(ws, [32, 16, 12, 36])
  // Anchor a note about which cells are editable
  void s
  return ws
}

// ── 4. Sensitivity Matrix sheet — 5x5 WACC x terminal-growth grid ──
function buildSensitivityMatrixSheet(): XLSX.WorkSheet {
  // Layout:
  //   A1: title
  //   A2: subtitle
  //   row 4 (Excel-1-indexed) = column headers (g offsets)
  //   rows 5..9 = WACC offset rows, columns B..F = grid cells
  //   A11: footnote
  //
  // Every grid cell is a LIVE FORMULA referencing 'DCF Model' assumption
  // cells: B2 (latest FCF), B3 (growth %), B4 (terminal g %), B11 (shares),
  // B16 (base WACC %). The flexed WACC = B16 + dw, flexed g = B4 + dg
  // (both already in percent — divide by 100 to convert to a fraction,
  // matching the convention used in the DCF Model sheet).
  //
  // Per-share fair value at offset (dw, dg):
  //   sum_{t=1..5} ( B2*(1+B3/100)^t / (1+(B16+dw)/100)^t )
  //   + ( B2*(1+B3/100)^5 * (1+(B4+dg)/100) / ((B16+dw-B4-dg)/100) )
  //     / (1+(B16+dw)/100)^5
  //   then divided by B11.
  //
  // Offsets are in percentage POINTS, so dw = -2, -1, 0, 1, 2 etc.
  const offsets = [-2, -1, 0, 1, 2]

  // Build a sensitivity cell formula for a given (dw, dg) offset pair.
  function cellFormula(dw: number, dg: number): string {
    // Helper to render an offset as a signed numeric literal: 0 → "",
    // positive → "+2", negative → "-2". Keeps the formula readable when
    // the offset is zero.
    const sw = dw === 0 ? "" : dw > 0 ? `+${dw}` : `${dw}`
    const sg = dg === 0 ? "" : dg > 0 ? `+${dg}` : `${dg}`
    // (B16 + dw) — flexed WACC (in %), and (B4 + dg) — flexed terminal g.
    const w = `('DCF Model'!B16${sw})`
    const g = `('DCF Model'!B4${sg})`
    // Per-year PV terms — inlined because Excel has no SUM-over-expression.
    const fcf = `'DCF Model'!B2`
    const gr = `'DCF Model'!B3`
    const shares = `'DCF Model'!B11`
    // (1 + B3/100)^t pre-folded numerically would defeat live recompute;
    // keep it symbolic.
    const pv = (t: number): string =>
      `${fcf}*POWER(1+${gr}/100,${t})/POWER(1+${w}/100,${t})`
    const sumPVs = [1, 2, 3, 4, 5].map(pv).join("+")
    const tv = `${fcf}*POWER(1+${gr}/100,5)*(1+${g}/100)/((${w}-${g})/100)`
    const pvTerminal = `(${tv})/POWER(1+${w}/100,5)`
    return `(${sumPVs}+${pvTerminal})/${shares}`
  }

  const colHeaderLabel = (dg: number): string => {
    if (dg === 0) return "g0%"
    return dg > 0 ? `g+${dg}%` : `g${dg}%`
  }
  const rowHeaderLabel = (dw: number): string => {
    if (dw === 0) return "WACC +0%"
    return dw > 0 ? `WACC +${dw}%` : `WACC ${dw}%`
  }

  // Seed the sheet with text labels — formula cells are written separately
  // because xlsx aoa_to_sheet can't carry { f: ... } payloads.
  const rows: (string | number)[][] = [
    ["Sensitivity Analysis — Intrinsic Value per Share (₹)"],
    ["Rows: WACC ±2% in 1% steps  |  Columns: Terminal growth ±2% in 1% steps"],
    [],
    ["", ...offsets.map(colHeaderLabel)],
    [rowHeaderLabel(offsets[0])],
    [rowHeaderLabel(offsets[1])],
    [rowHeaderLabel(offsets[2])],
    [rowHeaderLabel(offsets[3])],
    [rowHeaderLabel(offsets[4])],
    [],
    ["Centre cell is the base case from the DCF Model sheet. Move ±1% on WACC, ±2% on terminal growth — Excel recomputes live."],
  ]
  const ws = XLSX.utils.aoa_to_sheet(rows)

  // Write the 25 formula cells. Row index in Excel: 5..9 (1-indexed).
  // Col index in Excel: B..F.
  const colLetters = ["B", "C", "D", "E", "F"]
  for (let i = 0; i < offsets.length; i++) {
    const dw = offsets[i]
    const excelRow = 5 + i // rows 5..9
    for (let j = 0; j < offsets.length; j++) {
      const dg = offsets[j]
      const addr = `${colLetters[j]}${excelRow}`
      ws[addr] = { t: "n", f: cellFormula(dw, dg) }
      applyNumberFormat(ws, addr, "₹#,##0")
      // Standard right-aligned border style for non-centre cells.
      ws[addr].s = {
        alignment: { horizontal: "right" },
        border: {
          top: { style: "thin", color: { rgb: "D1D5DB" } },
          bottom: { style: "thin", color: { rgb: "D1D5DB" } },
          left: { style: "thin", color: { rgb: "D1D5DB" } },
          right: { style: "thin", color: { rgb: "D1D5DB" } },
        },
      }
    }
  }

  // Highlight the centre cell (D7 = base WACC × base g) with blue fill +
  // bold text so it stands out as the base case anchor.
  const centre = ws["D7"]
  if (centre) {
    centre.s = {
      font: { bold: true, color: { rgb: "1E3A8A" } },
      fill: { fgColor: { rgb: "DBEAFE" } },
      alignment: { horizontal: "right" },
      border: {
        top: { style: "medium", color: { rgb: "1E3A8A" } },
        bottom: { style: "medium", color: { rgb: "1E3A8A" } },
        left: { style: "medium", color: { rgb: "1E3A8A" } },
        right: { style: "medium", color: { rgb: "1E3A8A" } },
      },
    }
  }

  // Style the title row.
  const title = ws["A1"]
  if (title) {
    title.s = {
      font: { bold: true, sz: 14, color: { rgb: "1E3A8A" } },
    }
  }
  const subtitle = ws["A2"]
  if (subtitle) {
    subtitle.s = {
      font: { bold: true, italic: true, color: { rgb: "374151" } },
    }
  }

  // Header row (row 4) — column headers in B4..F4 and the row headers in
  // A5..A9 — bold, centered for columns, left for rows.
  for (let j = 0; j < colLetters.length; j++) {
    const addr = `${colLetters[j]}4`
    const cell = ws[addr]
    if (cell) {
      cell.s = {
        font: { bold: true, color: { rgb: "FFFFFF" } },
        fill: { fgColor: { rgb: "1E3A8A" } },
        alignment: { horizontal: "center" },
      }
    }
  }
  for (let i = 0; i < offsets.length; i++) {
    const addr = `A${5 + i}`
    const cell = ws[addr]
    if (cell) {
      cell.s = {
        font: { bold: true, color: { rgb: "FFFFFF" } },
        fill: { fgColor: { rgb: "1E3A8A" } },
        alignment: { horizontal: "left" },
      }
    }
  }

  // Merge the title, subtitle, and footnote across the matrix width.
  ws["!merges"] = [
    { s: { r: 0, c: 0 }, e: { r: 0, c: 5 } },
    { s: { r: 1, c: 0 }, e: { r: 1, c: 5 } },
    { s: { r: 10, c: 0 }, e: { r: 10, c: 5 } },
  ]

  setColWidths(ws, [14, 14, 14, 14, 14, 14])
  return ws
}

// ── 5. 10y Financials Annual sheet ───────────────────────────────
function buildAnnualFinancialsSheet(f: HistoricalFinancialsResponse | null): XLSX.WorkSheet {
  if (!f || !f.periods?.length) {
    return XLSX.utils.aoa_to_sheet([["No annual financials available"]])
  }
  const sorted = [...f.periods].sort((a, b) =>
    (a.period_end ?? "").localeCompare(b.period_end ?? ""),
  )
  const header = [
    "Year",
    "Revenue (₹Cr)",
    "EBITDA (₹Cr)",
    "EBIT (₹Cr)",
    "Net Income (₹Cr)",
    "EPS Diluted (₹)",
    "CFO (₹Cr)",
    "Capex (₹Cr)",
    "FCF (₹Cr)",
    "Gross Margin",
    "Op Margin",
    "Net Margin",
    "Revenue YoY",
    "PAT YoY",
  ]
  const rows: (string | number)[][] = [header]
  for (const p of sorted) {
    rows.push([
      (p.period_end ?? "").slice(0, 4),
      n(p.revenue),
      n(p.ebitda),
      n(p.ebit),
      n(p.pat),
      n(p.eps_diluted),
      n(p.cfo),
      n(p.capex),
      n(p.free_cash_flow),
      n(p.gross_margin),
      n(p.operating_margin),
      n(p.net_margin),
      n(p.revenue_growth_yoy),
      n(p.pat_growth_yoy),
    ])
  }
  const ws = XLSX.utils.aoa_to_sheet(rows)
  applyHeader(ws, 0, header.length)
  // Format columns
  for (let r = 1; r <= sorted.length; r++) {
    // Year as text (no comma separator) — coerce cell type to "s"
    const yearAddr = `A${r + 1}`
    if (ws[yearAddr]) {
      ws[yearAddr].t = "s"
      ws[yearAddr].z = "@"
    }
    for (const col of ["B", "C", "D", "E", "G", "H", "I"]) {
      applyNumberFormat(ws, `${col}${r + 1}`, "#,##0.00")
    }
    applyNumberFormat(ws, `F${r + 1}`, "#,##0.00")
    for (const col of ["J", "K", "L"]) {
      applyNumberFormat(ws, `${col}${r + 1}`, "0.00")
    }
    for (const col of ["M", "N"]) {
      applyNumberFormat(ws, `${col}${r + 1}`, "0.00")
    }
  }
  setColWidths(ws, [8, 14, 14, 14, 16, 14, 12, 12, 12, 12, 12, 12, 12, 12])
  return ws
}

// ── 5. 8q Quarterly Financials sheet ─────────────────────────────
function buildQuarterlyFinancialsSheet(f: HistoricalFinancialsResponse | null): XLSX.WorkSheet {
  if (!f || !f.periods?.length) {
    return XLSX.utils.aoa_to_sheet([["No quarterly financials available"]])
  }
  const sorted = [...f.periods].sort((a, b) =>
    (a.period_end ?? "").localeCompare(b.period_end ?? ""),
  )
  const header = [
    "Quarter end",
    "Revenue (₹Cr)",
    "EBITDA (₹Cr)",
    "PAT (₹Cr)",
    "EPS (₹)",
    "Op Margin",
    "Net Margin",
    "Revenue YoY",
    "PAT YoY",
  ]
  const rows: (string | number)[][] = [header]
  for (const p of sorted) {
    rows.push([
      p.period_end ?? "",
      n(p.revenue),
      n(p.ebitda),
      n(p.pat),
      n(p.eps_diluted),
      n(p.operating_margin),
      n(p.net_margin),
      n(p.revenue_growth_yoy),
      n(p.pat_growth_yoy),
    ])
  }
  const ws = XLSX.utils.aoa_to_sheet(rows)
  applyHeader(ws, 0, header.length)
  for (let r = 1; r <= sorted.length; r++) {
    for (const col of ["B", "C", "D"]) applyNumberFormat(ws, `${col}${r + 1}`, "#,##0.00")
    applyNumberFormat(ws, `E${r + 1}`, "#,##0.00")
    for (const col of ["F", "G", "H", "I"]) {
      applyNumberFormat(ws, `${col}${r + 1}`, "0.00")
    }
  }
  setColWidths(ws, [14, 14, 14, 14, 12, 12, 12, 12, 12])
  return ws
}

// ── 6. Ratios (10y) sheet ────────────────────────────────────────
function buildRatiosSheet(r: RatioHistoryResponse | null): XLSX.WorkSheet {
  if (!r || !r.periods?.length) {
    return XLSX.utils.aoa_to_sheet([["No ratio history available"]])
  }
  const sorted = [...r.periods].sort((a, b) =>
    (a.period_end ?? "").localeCompare(b.period_end ?? ""),
  )
  const header = [
    "Year",
    "ROE",
    "ROCE",
    "ROA",
    "D/E",
    "Debt/EBITDA",
    "Interest Cov",
    "Current Ratio",
    "Gross Margin",
    "Op Margin",
    "Net Margin",
    "P/E",
    "P/B",
    "EV/EBITDA",
    "Div Yield",
  ]
  const rows: (string | number)[][] = [header]
  for (const p of sorted) {
    rows.push([
      (p.period_end ?? "").slice(0, 4),
      n(p.roe),
      n(p.roce),
      n(p.roa),
      n(p.de_ratio),
      n(p.debt_ebitda),
      n(p.interest_cov),
      n(p.current_ratio),
      n(p.gross_margin),
      n(p.operating_margin),
      n(p.net_margin),
      n(p.pe_ratio),
      n(p.pb_ratio),
      n(p.ev_ebitda),
      n(p.dividend_yield),
    ])
  }
  const ws = XLSX.utils.aoa_to_sheet(rows)
  applyHeader(ws, 0, header.length)
  for (let i = 1; i <= sorted.length; i++) {
    const yearAddr = `A${i + 1}`
    if (ws[yearAddr]) {
      ws[yearAddr].t = "s"
      ws[yearAddr].z = "@"
    }
    for (let c = 1; c < header.length; c++) {
      const addr = `${XLSX.utils.encode_col(c)}${i + 1}`
      applyNumberFormat(ws, addr, "0.00")
    }
  }
  setColWidths(ws, [8, 8, 8, 8, 8, 12, 12, 12, 12, 12, 12, 8, 8, 12, 10])
  return ws
}

// ── 7. Peers Comparison sheet ────────────────────────────────────
function buildPeersSheet(p: PublicPeersResponse | null): XLSX.WorkSheet {
  if (!p || !p.peers?.length) {
    return XLSX.utils.aoa_to_sheet([["No peer data available"]])
  }
  const header = [
    "Rank",
    "Ticker",
    "Company",
    "Sector",
    "Sub-sector",
    "Current Price (₹)",
    "Fair Value (₹)",
    "Discount (%)",
    "P/E",
    "ROE",
    "Score (/100)",
    "Moat",
  ]
  const rows: (string | number)[][] = [header]
  for (const peer of p.peers) {
    rows.push([
      n(peer.rank),
      peer.ticker ?? peer.peer_ticker ?? "",
      peer.company_name ?? "",
      peer.sector ?? "",
      peer.sub_sector ?? "",
      n(peer.current_price),
      n(peer.fair_value),
      n(peer.margin_of_safety),
      n(peer.pe_ratio),
      n(peer.roe),
      n(peer.score),
      peer.moat ?? "",
    ])
  }
  const ws = XLSX.utils.aoa_to_sheet(rows)
  applyHeader(ws, 0, header.length)
  for (let i = 1; i <= p.peers.length; i++) {
    applyNumberFormat(ws, `F${i + 1}`, "₹#,##0.00")
    applyNumberFormat(ws, `G${i + 1}`, "₹#,##0.00")
    applyNumberFormat(ws, `H${i + 1}`, "0.00")
    applyNumberFormat(ws, `I${i + 1}`, "0.00")
    applyNumberFormat(ws, `J${i + 1}`, "0.00")
    applyNumberFormat(ws, `K${i + 1}`, "0")
  }
  setColWidths(ws, [6, 14, 26, 18, 18, 16, 16, 12, 8, 8, 12, 14])
  return ws
}

// ── 8. Dividend History sheet ────────────────────────────────────
function buildDividendsSheet(d: DividendHistoryResponse | null): XLSX.WorkSheet {
  if (!d || !d.dividends?.length) {
    return XLSX.utils.aoa_to_sheet([["No dividend history available"]])
  }
  const header = ["Ex-date", "DPS (₹)", "Source format"]
  const rows: (string | number)[][] = [header]
  // Group by year for the summary block — but keep the raw event list.
  for (const ev of d.dividends) {
    rows.push([ev.ex_date ?? "", n(ev.amount), ev.source_format ?? ""])
  }
  rows.push([])
  rows.push(["Total paid (5y, ₹)", n(d.total_paid_5y)])
  rows.push(["Events with %-of-face-value parsing", n(d.pct_fv_parsed_count ?? null)])
  rows.push(["Unparsed events", n(d.unparsed_count ?? null)])

  const ws = XLSX.utils.aoa_to_sheet(rows)
  applyHeader(ws, 0, header.length)
  for (let i = 1; i <= d.dividends.length; i++) {
    applyNumberFormat(ws, `B${i + 1}`, "₹#,##0.00")
  }
  setColWidths(ws, [16, 12, 20])
  return ws
}

// ── 9. Quality & Moat sheet ──────────────────────────────────────
function buildQualitySheet(s: StockSummary, ann: HistoricalFinancialsResponse | null): XLSX.WorkSheet {
  // We can't recompute the full 9-component Piotroski here without the
  // backend payload, so we surface the reported score plus the per-axis
  // numbers we have (ROE, ROCE, D/E, current ratio, asset turnover) so
  // the user can sanity-check the score against the inputs.
  const latest: HistoricalFinancialsPeriod | null = ann && ann.periods?.length
    ? [...ann.periods].sort((a, b) =>
        (b.period_end ?? "").localeCompare(a.period_end ?? ""),
      )[0]
    : null

  const rows: (string | number)[][] = [
    ["Metric", "Value", "Source"],
    ["Piotroski score (/9)", n(s.piotroski), "Engine"],
    ["YieldIQ score (/100)", n(s.score), "Engine"],
    ["Grade", s.grade, "Engine"],
    ["Economic moat", s.moat, "Engine"],
    [],
    ["Component", "Value", "Source"],
    ["ROE (%)", n(s.roe), "Summary"],
    ["ROCE (%)", n(s.roce), "Summary"],
    ["Debt / Equity", n(s.de_ratio), "Summary"],
    ["Debt / EBITDA", n(s.debt_ebitda), "Summary"],
    ["Interest coverage", n(s.interest_coverage), "Summary"],
    ["Current ratio", n(s.current_ratio), "Summary"],
    ["Asset turnover", n(s.asset_turnover), "Summary"],
    [],
    ["Most-recent annual snapshot"],
    ["Period end", latest?.period_end ?? "n/a", ""],
    ["Revenue (₹Cr)", n(latest?.revenue ?? null), ""],
    ["Net income (₹Cr)", n(latest?.pat ?? null), ""],
    ["FCF (₹Cr)", n(latest?.free_cash_flow ?? null), ""],
    ["Gross margin", n(latest?.gross_margin ?? null), ""],
    ["Operating margin", n(latest?.operating_margin ?? null), ""],
  ]
  const ws = XLSX.utils.aoa_to_sheet(rows)
  applyHeader(ws, 0, 3)
  applyHeader(ws, 6, 3)
  setColWidths(ws, [30, 16, 16])
  return ws
}

// ── 10. Methodology + Sources sheet ──────────────────────────────
function buildMethodologySheet(): XLSX.WorkSheet {
  const rows: (string | number)[][] = [
    ["YieldIQ methodology"],
    [],
    ["Engine"],
    ["Fair value", "5-year FCF projection discounted at WACC + Gordon-growth terminal value."],
    ["WACC build", "Rf + Beta * ERP for cost of equity; Kd_pre * (1 - tax) for after-tax cost of debt; weighted by D / (D+E)."],
    ["Scenarios", "Bear / Base / Bull apply ± 25% flex to FCF growth and terminal growth."],
    ["Piotroski", "9-component balance-sheet / profitability / operating-efficiency score."],
    ["Moat", "Computed from sustained ROE, gross margin, FCF stability, and competitive position."],
    [],
    ["Sources"],
    ["Financials", "BSE XBRL filings (primary), yfinance (fallback for missing periods)."],
    ["Prices", "NSE / BSE close-of-day."],
    ["Dividends", "BSE corporate-action filings."],
    ["Peers", "Sub-sector cohort filtered by market-cap band; criteria surfaced on /analysis/[ticker]."],
    [],
    ["Disclaimer"],
    [SEBI_DISCLAIMER],
    [],
    ["Report generated by", "yieldiq.in"],
  ]
  const ws = XLSX.utils.aoa_to_sheet(rows)
  setColWidths(ws, [22, 80])
  // Merge the long descriptive cells across columns so the text wraps
  ws["!merges"] = [
    { s: { r: 16, c: 0 }, e: { r: 16, c: 1 } },
  ]
  return ws
}

// ── Workbook assembly ────────────────────────────────────────────
export function buildDetailedWorkbook(bundle: DetailedExcelBundle): XLSX.WorkBook {
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, buildCoverSheet(bundle.summary), "Cover")
  XLSX.utils.book_append_sheet(wb, buildValuationSummarySheet(bundle.summary), "Valuation Summary")
  XLSX.utils.book_append_sheet(wb, buildDCFModelSheet(bundle.summary, bundle.annualFinancials), "DCF Model")
  XLSX.utils.book_append_sheet(wb, buildSensitivityMatrixSheet(), "Sensitivity Matrix")
  XLSX.utils.book_append_sheet(wb, buildAnnualFinancialsSheet(bundle.annualFinancials), "Financials Annual")
  XLSX.utils.book_append_sheet(wb, buildQuarterlyFinancialsSheet(bundle.quarterlyFinancials), "Financials Quarterly")
  XLSX.utils.book_append_sheet(wb, buildRatiosSheet(bundle.ratios), "Ratios 10y")
  XLSX.utils.book_append_sheet(wb, buildPeersSheet(bundle.peers), "Peers")
  XLSX.utils.book_append_sheet(wb, buildDividendsSheet(bundle.dividends), "Dividend History")
  XLSX.utils.book_append_sheet(wb, buildQualitySheet(bundle.summary, bundle.annualFinancials), "Quality & Moat")
  XLSX.utils.book_append_sheet(wb, buildMethodologySheet(), "Methodology")
  return wb
}

export function downloadDetailedWorkbook(bundle: DetailedExcelBundle): void {
  const wb = buildDetailedWorkbook(bundle)
  const safe = bundle.ticker.replace(/\./g, "_")
  XLSX.writeFile(wb, `YieldIQ_${safe}_detailed.xlsx`)
}
