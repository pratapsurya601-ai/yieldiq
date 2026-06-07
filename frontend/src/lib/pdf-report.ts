/**
 * 3-page PDF report (Pro tier).
 * --------------------------------------------------------------------------
 * Generates a polished printable report in the browser using jsPDF — chosen
 * because @react-pdf/renderer pulls in ~1.5MB of dependencies (React tree
 * walker, font subsetting, layout engine) where jsPDF is ~400KB minified.
 *
 * Layout
 * ------
 *   Page 1 — Hero:    ticker, company, current price vs FV, discount,
 *                     verdict, YieldIQ score, grade, moat, Piotroski.
 *                     Two-line factual takeaways from numeric data.
 *
 *   Page 2 — Detail:  DCF scenario table, key ratios block, 10y
 *                     revenue + PAT mini-chart drawn with jsPDF lines.
 *
 *   Page 3 — Context: Peer table, methodology, sources, SEBI disclaimer.
 *
 * SEBI vocabulary
 * ---------------
 * Every string in this file is factual — no advisory verbs. The frontend
 * SEBI lint runs on this file. Verdict is sourced from the engine
 * (allow-listed token), not synthesised here.
 */
import { jsPDF } from "jspdf"
import type {
  StockSummary,
  HistoricalFinancialsResponse,
  RatioHistoryResponse,
  PublicPeersResponse,
} from "@/lib/api"
import { SEBI_DISCLAIMER } from "@/lib/excel-detailed"

export interface PDFBundle {
  ticker: string
  summary: StockSummary
  annualFinancials: HistoricalFinancialsResponse | null
  ratios: RatioHistoryResponse | null
  peers: PublicPeersResponse | null
}

const COLOR_INK = "#0F172A"
const COLOR_MUTED = "#475569"
const COLOR_BRAND = "#1E3A8A"
const COLOR_BORDER = "#E2E8F0"
const COLOR_BG_SOFT = "#F8FAFC"

// ── small helpers ────────────────────────────────────────────────
// PDF-internal formatters. We CANNOT use formatCurrency / formatNumber
// from @/lib/utils here because they emit the U+20B9 rupee glyph,
// which jsPDF's default Helvetica (WinAnsi-encoded) cannot render —
// the output mojibakes. We deliberately use the "INR " text prefix
// and ASCII-only digits with locale-grouped thousands separators.
// The same constraint does not apply to the Excel side (Excel
// renders the rupee glyph natively via its own font handling).
/* eslint-disable no-restricted-syntax */
function fmtINR(v: number | null | undefined, decimals = 2): string {
  if (v == null || !isFinite(v)) return "n/a"
  return `INR ${v.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`
}

function fmtPct(v: number | null | undefined, decimals = 1): string {
  if (v == null || !isFinite(v)) return "n/a"
  return `${v.toFixed(decimals)}%`
}

function fmtNum(v: number | null | undefined, decimals = 2): string {
  if (v == null || !isFinite(v)) return "n/a"
  return v.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}
/* eslint-enable no-restricted-syntax */

function drawHRule(doc: jsPDF, x1: number, y: number, x2: number): void {
  doc.setDrawColor(COLOR_BORDER)
  doc.setLineWidth(0.4)
  doc.line(x1, y, x2, y)
}

function drawPageFooter(doc: jsPDF, ticker: string, pageNumber: number, totalPages: number): void {
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  doc.setFontSize(8)
  doc.setTextColor(COLOR_MUTED)
  doc.text(`YieldIQ analyst report — ${ticker}`, 40, pageHeight - 20)
  doc.text(`Page ${pageNumber} of ${totalPages}`, pageWidth - 40, pageHeight - 20, { align: "right" })
  doc.text("yieldiq.in", pageWidth / 2, pageHeight - 20, { align: "center" })
}

// ── Page 1 — Hero ────────────────────────────────────────────────
function renderHero(doc: jsPDF, b: PDFBundle): void {
  const s = b.summary
  const pageWidth = doc.internal.pageSize.getWidth()
  let y = 60

  // Brand strip
  doc.setFillColor(COLOR_BRAND)
  doc.rect(0, 0, pageWidth, 6, "F")

  // Title
  doc.setTextColor(COLOR_INK)
  doc.setFont("helvetica", "bold")
  doc.setFontSize(26)
  doc.text(`${s.ticker}`, 40, y)
  y += 28
  doc.setFont("helvetica", "normal")
  doc.setFontSize(14)
  doc.setTextColor(COLOR_MUTED)
  doc.text(s.company_name || "", 40, y, { maxWidth: pageWidth - 80 })
  y += 18
  doc.setFontSize(10)
  doc.text(`${s.sector ?? ""} • ${s.industry ?? ""} • ${s.exchange ?? ""}`, 40, y)
  y += 22

  drawHRule(doc, 40, y, pageWidth - 40)
  y += 22

  // Valuation tile row
  doc.setTextColor(COLOR_INK)
  doc.setFontSize(11)
  doc.setFont("helvetica", "bold")
  doc.text("Valuation snapshot", 40, y)
  y += 16

  const tileW = (pageWidth - 80 - 30) / 4
  const tileH = 70
  const tiles: { label: string; value: string }[] = [
    { label: "Current price", value: fmtINR(s.current_price) },
    { label: "Fair value (base)", value: fmtINR(s.fair_value) },
    { label: "Discount to FV", value: fmtPct(s.mos) },
    { label: "YieldIQ score", value: `${s.score ?? "n/a"} / 100` },
  ]
  let tx = 40
  for (const t of tiles) {
    doc.setFillColor(COLOR_BG_SOFT)
    doc.setDrawColor(COLOR_BORDER)
    doc.roundedRect(tx, y, tileW, tileH, 6, 6, "FD")
    doc.setFontSize(9)
    doc.setTextColor(COLOR_MUTED)
    doc.setFont("helvetica", "normal")
    doc.text(t.label, tx + 10, y + 18)
    doc.setFontSize(14)
    doc.setTextColor(COLOR_INK)
    doc.setFont("helvetica", "bold")
    doc.text(t.value, tx + 10, y + 42)
    tx += tileW + 10
  }
  y += tileH + 24

  // Scenario table
  doc.setFontSize(11)
  doc.setFont("helvetica", "bold")
  doc.setTextColor(COLOR_INK)
  doc.text("Scenarios", 40, y)
  y += 12
  doc.setFontSize(10)
  const scenarioRows: [string, string, string][] = [
    ["Bear", fmtINR(s.bear_case), pctDelta(s.bear_case, s.current_price)],
    ["Base", fmtINR(s.base_case), pctDelta(s.base_case, s.current_price)],
    ["Bull", fmtINR(s.bull_case), pctDelta(s.bull_case, s.current_price)],
  ]
  drawTable(
    doc,
    40,
    y,
    [120, 160, 120],
    ["Scenario", "Fair value", "Vs price"],
    scenarioRows,
  )
  y += 18 + scenarioRows.length * 18 + 20

  // Quality block
  doc.setFontSize(11)
  doc.setFont("helvetica", "bold")
  doc.setTextColor(COLOR_INK)
  doc.text("Quality scorecard", 40, y)
  y += 12
  doc.setFontSize(10)
  const qualityRows: [string, string][] = [
    ["Grade", s.grade ?? "n/a"],
    ["Economic moat", s.moat ?? "n/a"],
    ["Piotroski (/9)", String(s.piotroski ?? "n/a")],
    ["Confidence", fmtPct(s.confidence)],
    ["WACC used", fmtPct(s.wacc != null ? s.wacc * 100 : null)],
  ]
  drawKVList(doc, 40, y, 200, qualityRows)
  y += qualityRows.length * 16 + 18

  // Factual takeaways (NO advisory verbs — descriptive only)
  doc.setFontSize(11)
  doc.setFont("helvetica", "bold")
  doc.text("Key metrics summary", 40, y)
  y += 14
  doc.setFontSize(10)
  doc.setFont("helvetica", "normal")
  doc.setTextColor(COLOR_MUTED)
  const bullets = [
    `Reported ROE of ${fmtPct(s.roe)} and ROCE of ${fmtPct(s.roce)} against a debt-to-equity ratio of ${fmtNum(s.de_ratio)}.`,
    `5-year revenue CAGR of ${fmtPct(s.revenue_cagr_5y != null ? s.revenue_cagr_5y * 100 : null)} with market capitalisation of INR ${fmtNum(s.market_cap, 0)} Cr.`,
    "Model-generated description of metrics. Not investment advice.",
  ]
  for (const line of bullets) {
    const wrapped = doc.splitTextToSize(`• ${line}`, doc.internal.pageSize.getWidth() - 80)
    doc.text(wrapped, 40, y)
    y += wrapped.length * 12 + 4
  }
}

function pctDelta(fv: number | null | undefined, cmp: number | null | undefined): string {
  if (fv == null || cmp == null || !(cmp > 0) || !(fv > 0)) return "n/a"
  return fmtPct(((fv - cmp) / cmp) * 100)
}

// ── tiny table helpers ───────────────────────────────────────────
function drawTable(
  doc: jsPDF,
  x: number,
  y: number,
  colWidths: number[],
  header: string[],
  rows: string[][],
): void {
  const rowH = 18
  // header
  doc.setFillColor(COLOR_BRAND)
  doc.setTextColor("#FFFFFF")
  doc.setFont("helvetica", "bold")
  doc.setFontSize(9)
  const totalW = colWidths.reduce((a, b) => a + b, 0)
  doc.rect(x, y, totalW, rowH, "F")
  let cx = x
  for (let i = 0; i < header.length; i++) {
    doc.text(header[i] ?? "", cx + 6, y + 12)
    cx += colWidths[i] ?? 0
  }
  // rows
  doc.setTextColor(COLOR_INK)
  doc.setFont("helvetica", "normal")
  doc.setDrawColor(COLOR_BORDER)
  for (let r = 0; r < rows.length; r++) {
    const ry = y + rowH + r * rowH
    const fillRow = r % 2 === 0
    if (fillRow) {
      doc.setFillColor(COLOR_BG_SOFT)
      doc.rect(x, ry, totalW, rowH, "F")
    }
    let cxr = x
    for (let i = 0; i < header.length; i++) {
      const cell = rows[r]?.[i] ?? ""
      doc.text(cell, cxr + 6, ry + 12)
      cxr += colWidths[i] ?? 0
    }
    doc.line(x, ry + rowH, x + totalW, ry + rowH)
  }
}

function drawKVList(
  doc: jsPDF,
  x: number,
  y: number,
  labelW: number,
  rows: [string, string][],
  opts?: { boldRowIndex?: number },
): void {
  doc.setFontSize(10)
  const boldIdx = opts?.boldRowIndex ?? -1
  for (let r = 0; r < rows.length; r++) {
    const ry = y + r * 16
    const isHighlight = r === boldIdx
    if (isHighlight) {
      doc.setFillColor(COLOR_BG_SOFT)
      doc.rect(x - 4, ry - 11, labelW + 120, 14, "F")
    }
    doc.setTextColor(COLOR_MUTED)
    doc.setFont("helvetica", isHighlight ? "bold" : "normal")
    doc.text(rows[r]?.[0] ?? "", x, ry)
    doc.setTextColor(COLOR_INK)
    doc.setFont("helvetica", "bold")
    doc.text(rows[r]?.[1] ?? "", x + labelW, ry)
  }
}

// ── Page 2 — DCF + WACC + Sensitivity ───────────────────────────
function renderDetail(doc: jsPDF, b: PDFBundle): void {
  const s = b.summary
  const pageWidth = doc.internal.pageSize.getWidth()
  let y = 60

  doc.setFillColor(COLOR_BRAND)
  doc.rect(0, 0, pageWidth, 6, "F")
  doc.setFontSize(18)
  doc.setFont("helvetica", "bold")
  doc.setTextColor(COLOR_INK)
  doc.text(`${s.ticker} — DCF & sensitivity`, 40, y)
  y += 28
  drawHRule(doc, 40, y, pageWidth - 40)
  y += 22

  // Side-by-side DCF scenarios (left) and WACC Build-Up (right).
  const colGap = 20
  const colW = (pageWidth - 80 - colGap) / 2
  const leftX = 40
  const rightX = leftX + colW + colGap

  // ── Left column: DCF scenarios ──────────────────────────────────
  doc.setFontSize(12)
  doc.setFont("helvetica", "bold")
  doc.setTextColor(COLOR_INK)
  doc.text("DCF scenarios", leftX, y)
  let leftY = y + 12
  const dcfRows: string[][] = [
    ["Bear", fmtINR(s.bear_case), pctDelta(s.bear_case, s.current_price)],
    ["Base", fmtINR(s.base_case), pctDelta(s.base_case, s.current_price)],
    ["Bull", fmtINR(s.bull_case), pctDelta(s.bull_case, s.current_price)],
  ]
  const dcfCols = [Math.round(colW * 0.28), Math.round(colW * 0.42), colW - Math.round(colW * 0.28) - Math.round(colW * 0.42)]
  drawTable(doc, leftX, leftY, dcfCols, ["Scenario", "Fair value", "Vs CMP"], dcfRows)
  leftY += 18 + dcfRows.length * 18 + 4

  // ── Right column: WACC Build-Up ─────────────────────────────────
  doc.setFontSize(12)
  doc.setFont("helvetica", "bold")
  doc.setTextColor(COLOR_INK)
  doc.text("WACC build-up", rightX, y)
  let rightY = y + 12
  const wacc = s.wacc != null ? s.wacc * 100 : null
  // Component assumptions — defaults match the engine's standard CAPM
  // build (see backend/services/dcf/wacc.py). Beta defaults to 1.0 when
  // sector beta isn't surfaced on the summary.
  const RF = 7.2
  const ERP = 6.0
  const BETA = 1.0
  const KD_PRETAX = 9.0
  const TAX_RATE = 25.0
  const W_E = 70.0
  const W_D = 30.0
  const TERMINAL_G = 4.0
  const COST_OF_EQUITY = RF + BETA * ERP
  const waccRows: [string, string][] = [
    ["Risk-free rate (Rf)", fmtPct(RF)],
    ["ERP x Beta", `${ERP.toFixed(1)}% x ${BETA.toFixed(2)}`],
    ["Cost of equity (CAPM)", fmtPct(COST_OF_EQUITY)],
    ["Pre-tax cost of debt", fmtPct(KD_PRETAX)],
    ["Tax rate", fmtPct(TAX_RATE)],
    ["Weight equity / debt", `${W_E.toFixed(0)}% / ${W_D.toFixed(0)}%`],
    ["WACC", fmtPct(wacc)],
    ["Terminal growth rate", fmtPct(TERMINAL_G)],
  ]
  drawKVList(doc, rightX, rightY, Math.round(colW * 0.62), waccRows, { boldRowIndex: 6 })
  rightY += waccRows.length * 16 + 4

  y = Math.max(leftY, rightY) + 18

  // ── Sensitivity matrix (full width) ─────────────────────────────
  doc.setFontSize(12)
  doc.setFont("helvetica", "bold")
  doc.setTextColor(COLOR_INK)
  doc.text("Sensitivity analysis - intrinsic value per share (INR)", 40, y)
  y += 14

  const matrixSpec = buildSensitivityMatrix(s, TERMINAL_G / 100)
  renderSensitivityMatrix(doc, 40, y, pageWidth - 80, matrixSpec)
  y += 18 + 5 * 22 + 6

  doc.setFontSize(8)
  doc.setFont("helvetica", "normal")
  doc.setTextColor(COLOR_MUTED)
  const footNote =
    "Centre cell is the base case. Rows: WACC plus or minus 2% in 1% steps. Columns: terminal growth plus or minus 2% in 1% steps."
  const wrappedFoot = doc.splitTextToSize(footNote, pageWidth - 80)
  doc.text(wrappedFoot, 40, y + 4)
}

// ── Page 3 — Key ratios + chart ─────────────────────────────────
function renderFinancials(doc: jsPDF, b: PDFBundle): void {
  const s = b.summary
  const pageWidth = doc.internal.pageSize.getWidth()
  let y = 60

  doc.setFillColor(COLOR_BRAND)
  doc.rect(0, 0, pageWidth, 6, "F")
  doc.setFontSize(18)
  doc.setFont("helvetica", "bold")
  doc.setTextColor(COLOR_INK)
  doc.text(`${s.ticker} - financials & ratios`, 40, y)
  y += 28
  drawHRule(doc, 40, y, pageWidth - 40)
  y += 22

  // Key ratios block
  doc.setFontSize(12)
  doc.setFont("helvetica", "bold")
  doc.setTextColor(COLOR_INK)
  doc.text("Key ratios", 40, y)
  y += 12
  const ratioRows: [string, string][] = [
    ["ROE", fmtPct(s.roe)],
    ["ROCE", fmtPct(s.roce)],
    ["Debt / Equity", fmtNum(s.de_ratio)],
    ["Debt / EBITDA", fmtNum(s.debt_ebitda)],
    ["Interest coverage", fmtNum(s.interest_coverage)],
    ["Current ratio", fmtNum(s.current_ratio)],
    ["EV / EBITDA", fmtNum(s.ev_ebitda)],
  ]
  drawKVList(doc, 40, y, 200, ratioRows)
  y += ratioRows.length * 16 + 22

  // 10y mini chart - Revenue + PAT lines on a single grid
  doc.setFontSize(12)
  doc.setFont("helvetica", "bold")
  doc.text("Revenue & net income (annual, INR Cr)", 40, y)
  y += 10
  renderMiniChart(doc, b.annualFinancials, 40, y, pageWidth - 80, 220)
}

// ── Sensitivity matrix helpers ──────────────────────────────────
interface SensitivityMatrix {
  waccOffsets: number[]            // row offsets in decimal (e.g. -0.02 .. +0.02)
  growthOffsets: number[]          // column offsets in decimal
  baseWacc: number                 // decimal
  baseGrowth: number               // decimal
  values: (number | null)[][]      // [row][col] IV per share, INR
}

// Build a 5x5 sensitivity matrix around the summary's base case.
//
// We use a closed-form 5-year DCF approximation so the off-diagonal cells
// move monotonically: higher WACC -> lower IV, higher g -> higher IV.
// We back out an implied FCF-per-share / shares-outstanding scalar from
// the base case so the centre cell exactly matches summary.fair_value.
// Inputs that would yield W <= g produce null (rendered as "n/a").
export function buildSensitivityMatrix(s: StockSummary, baseGrowth: number): SensitivityMatrix {
  const offsets = [-0.02, -0.01, 0.0, 0.01, 0.02]
  const baseWacc = s.wacc ?? 0.12

  // Per-share contribution of the 5-year explicit FCF stream, normalised
  // to base inputs. We treat FCF0 as an unknown scalar K (per share).
  // At base inputs, IV_base = K * (sum_5y + terminal_factor).
  // So K = fair_value / (sum_5y + terminal_factor).
  const fcfGrowth = baseGrowth // proxy for near-term FCF growth
  function ivCoefficient(W: number, g: number): number | null {
    if (!(W > g) || !isFinite(W) || !isFinite(g)) return null
    let pvSum = 0
    let fcf = 1
    for (let t = 1; t <= 5; t++) {
      fcf *= 1 + fcfGrowth
      pvSum += fcf / Math.pow(1 + W, t)
    }
    const terminalFcf = Math.pow(1 + fcfGrowth, 5) * (1 + g)
    const terminalPv = terminalFcf / ((W - g) * Math.pow(1 + W, 5))
    return pvSum + terminalPv
  }

  const baseCoef = ivCoefficient(baseWacc, baseGrowth)
  // K calibrates so centre cell == fair_value exactly.
  const K = baseCoef && baseCoef > 0 && s.fair_value > 0 ? s.fair_value / baseCoef : null

  const values: (number | null)[][] = offsets.map((wOff) =>
    offsets.map((gOff) => {
      if (K == null) return null
      const W = baseWacc + wOff
      const g = baseGrowth + gOff
      const coef = ivCoefficient(W, g)
      return coef == null ? null : coef * K
    }),
  )

  return {
    waccOffsets: offsets,
    growthOffsets: offsets,
    baseWacc,
    baseGrowth,
    values,
  }
}

function renderSensitivityMatrix(
  doc: jsPDF,
  x: number,
  y: number,
  width: number,
  m: SensitivityMatrix,
): void {
  const COLS = m.growthOffsets.length // 5
  const ROWS = m.waccOffsets.length   // 5
  const labelColW = 80
  const cellW = (width - labelColW) / COLS
  const headerH = 22
  const rowH = 22
  const centreRow = 2
  const centreCol = 2

  // Header row (terminal growth labels)
  doc.setFillColor(COLOR_BRAND)
  doc.rect(x, y, width, headerH, "F")
  doc.setTextColor("#FFFFFF")
  doc.setFont("helvetica", "bold")
  doc.setFontSize(9)
  doc.text("WACC \\ g", x + 6, y + 14)
  for (let c = 0; c < COLS; c++) {
    const cx = x + labelColW + c * cellW
    const gPct = (m.baseGrowth + m.growthOffsets[c]!) * 100
    const label = `${gPct.toFixed(1)}%`
    doc.text(label, cx + cellW / 2, y + 14, { align: "center" })
  }

  // Body
  doc.setDrawColor(COLOR_BORDER)
  doc.setLineWidth(0.4)
  doc.setFontSize(9)
  for (let r = 0; r < ROWS; r++) {
    const ry = y + headerH + r * rowH

    // Row label cell (WACC value)
    doc.setFillColor(COLOR_BG_SOFT)
    doc.rect(x, ry, labelColW, rowH, "F")
    doc.setTextColor(COLOR_INK)
    doc.setFont("helvetica", "bold")
    const wPct = (m.baseWacc + m.waccOffsets[r]!) * 100
    doc.text(`${wPct.toFixed(1)}%`, x + 6, ry + 14)

    for (let c = 0; c < COLS; c++) {
      const cx = x + labelColW + c * cellW
      const isCentre = r === centreRow && c === centreCol
      if (isCentre) {
        doc.setFillColor("#DBEAFE")
        doc.rect(cx, ry, cellW, rowH, "F")
      }
      doc.setDrawColor(COLOR_BORDER)
      doc.rect(cx, ry, cellW, rowH)

      const v = m.values[r]?.[c]
      const txt = v == null || !isFinite(v) ? "n/a" : fmtNum(v, 0)
      doc.setTextColor(COLOR_INK)
      doc.setFont("helvetica", isCentre ? "bold" : "normal")
      doc.text(txt, cx + cellW / 2, ry + 14, { align: "center" })
    }
    // Bottom rule for the row
    doc.setDrawColor(COLOR_BORDER)
    doc.line(x, ry + rowH, x + width, ry + rowH)
  }

  // Outer frame
  doc.setDrawColor(COLOR_BORDER)
  doc.rect(x, y, width, headerH + ROWS * rowH)
}

function renderMiniChart(
  doc: jsPDF,
  f: HistoricalFinancialsResponse | null,
  x: number,
  y: number,
  w: number,
  h: number,
): void {
  if (!f || !f.periods?.length) {
    doc.setFontSize(10)
    doc.setTextColor(COLOR_MUTED)
    doc.text("No historical financial series available.", x, y + 20)
    return
  }
  const sorted = [...f.periods].sort((a, b) =>
    (a.period_end ?? "").localeCompare(b.period_end ?? ""),
  )
  const revs = sorted.map((p) => p.revenue).filter((v): v is number => v != null && isFinite(v))
  const pats = sorted.map((p) => p.pat).filter((v): v is number => v != null && isFinite(v))
  if (revs.length === 0) {
    doc.setFontSize(10)
    doc.setTextColor(COLOR_MUTED)
    doc.text("No historical financial series available.", x, y + 20)
    return
  }
  const maxRev = Math.max(...revs)
  const maxPat = pats.length ? Math.max(...pats) : maxRev * 0.2
  const max = Math.max(maxRev, maxPat) * 1.1

  // Chart frame
  doc.setDrawColor(COLOR_BORDER)
  doc.setLineWidth(0.5)
  doc.rect(x, y, w, h)

  // Y-axis gridlines + labels (4 ticks)
  doc.setFontSize(8)
  doc.setTextColor(COLOR_MUTED)
  for (let i = 0; i <= 4; i++) {
    const gy = y + h - (i / 4) * h
    doc.setDrawColor("#F1F5F9")
    doc.line(x, gy, x + w, gy)
    const val = ((i / 4) * max).toFixed(0)
    doc.text(val, x - 4, gy + 3, { align: "right" })
  }

  // X-axis labels — year only (handle yyyy-mm-dd)
  const n = sorted.length
  const stepX = w / Math.max(1, n - 1)
  for (let i = 0; i < n; i++) {
    const px = x + i * stepX
    const label = (sorted[i]?.period_end ?? "").slice(0, 4)
    if (i === 0 || i === n - 1 || i % Math.max(1, Math.floor(n / 5)) === 0) {
      doc.setTextColor(COLOR_MUTED)
      doc.text(label, px, y + h + 12, { align: "center" })
    }
  }

  // Revenue line (blue)
  doc.setDrawColor(COLOR_BRAND)
  doc.setLineWidth(1.2)
  for (let i = 0; i < n - 1; i++) {
    const r0 = sorted[i]?.revenue
    const r1 = sorted[i + 1]?.revenue
    if (r0 == null || r1 == null) continue
    const x0 = x + i * stepX
    const x1 = x + (i + 1) * stepX
    const y0 = y + h - (r0 / max) * h
    const y1 = y + h - (r1 / max) * h
    doc.line(x0, y0, x1, y1)
  }
  // PAT line (slate)
  doc.setDrawColor("#64748B")
  for (let i = 0; i < n - 1; i++) {
    const p0 = sorted[i]?.pat
    const p1 = sorted[i + 1]?.pat
    if (p0 == null || p1 == null) continue
    const x0 = x + i * stepX
    const x1 = x + (i + 1) * stepX
    const y0 = y + h - (p0 / max) * h
    const y1 = y + h - (p1 / max) * h
    doc.line(x0, y0, x1, y1)
  }

  // Legend
  doc.setFontSize(8)
  doc.setDrawColor(COLOR_BRAND)
  doc.setFillColor(COLOR_BRAND)
  doc.rect(x + w - 130, y + 8, 8, 8, "F")
  doc.setTextColor(COLOR_INK)
  doc.text("Revenue", x + w - 118, y + 15)
  doc.setFillColor("#64748B")
  doc.rect(x + w - 70, y + 8, 8, 8, "F")
  doc.text("Net income", x + w - 58, y + 15)
}

// ── Page 3 — Peers + methodology + sources + SEBI ───────────────
function renderContext(doc: jsPDF, b: PDFBundle): void {
  const pageWidth = doc.internal.pageSize.getWidth()
  let y = 60
  doc.setFillColor(COLOR_BRAND)
  doc.rect(0, 0, pageWidth, 6, "F")
  doc.setFontSize(18)
  doc.setFont("helvetica", "bold")
  doc.setTextColor(COLOR_INK)
  doc.text(`${b.summary.ticker} — peers & methodology`, 40, y)
  y += 28
  drawHRule(doc, 40, y, pageWidth - 40)
  y += 22

  // Peers
  doc.setFontSize(12)
  doc.setFont("helvetica", "bold")
  doc.text("Peer cohort", 40, y)
  y += 12
  const peers = b.peers?.peers?.slice(0, 6) ?? []
  if (peers.length === 0) {
    doc.setFontSize(10)
    doc.setFont("helvetica", "normal")
    doc.setTextColor(COLOR_MUTED)
    doc.text("No peer data available.", 40, y + 14)
    y += 30
  } else {
    const peerRows = peers.map((p) => [
      p.ticker ?? p.peer_ticker ?? "",
      (p.company_name ?? "").slice(0, 30),
      fmtNum(p.pe_ratio),
      fmtPct(p.roe),
      String(p.score ?? "n/a"),
    ])
    drawTable(
      doc,
      40,
      y,
      [80, 200, 60, 70, 80],
      ["Ticker", "Company", "P/E", "ROE", "Score"],
      peerRows,
    )
    y += 18 + peerRows.length * 18 + 22
  }

  // Methodology
  doc.setFontSize(12)
  doc.setFont("helvetica", "bold")
  doc.setTextColor(COLOR_INK)
  doc.text("Methodology", 40, y)
  y += 14
  doc.setFontSize(10)
  doc.setFont("helvetica", "normal")
  doc.setTextColor(COLOR_MUTED)
  const methodology = [
    "Fair value is computed via a 5-year free-cash-flow projection discounted at WACC, with a Gordon-growth terminal value.",
    "WACC is built from the risk-free rate, equity risk premium, levered beta, after-tax cost of debt, and a debt weight derived from the capital structure.",
    "Bear / base / bull scenarios apply ± 25% flex to FCF growth and terminal growth inputs.",
    "Piotroski (/9) is the standard 9-component balance-sheet, profitability, and operating-efficiency score.",
  ]
  for (const line of methodology) {
    const wrapped = doc.splitTextToSize(`• ${line}`, pageWidth - 80)
    doc.text(wrapped, 40, y)
    y += wrapped.length * 12 + 4
  }
  y += 8

  // Sources
  doc.setFontSize(12)
  doc.setFont("helvetica", "bold")
  doc.setTextColor(COLOR_INK)
  doc.text("Sources", 40, y)
  y += 14
  doc.setFontSize(10)
  doc.setFont("helvetica", "normal")
  doc.setTextColor(COLOR_MUTED)
  const sources = [
    "Financials: BSE XBRL filings (primary), yfinance (fallback for missing periods).",
    "Prices: NSE / BSE close-of-day.",
    "Dividends: BSE corporate-action filings.",
    "Peers: Sub-sector cohort filtered by market-cap band.",
  ]
  for (const line of sources) {
    const wrapped = doc.splitTextToSize(`• ${line}`, pageWidth - 80)
    doc.text(wrapped, 40, y)
    y += wrapped.length * 12 + 4
  }
  y += 12

  // SEBI disclaimer block
  doc.setFillColor(COLOR_BG_SOFT)
  doc.setDrawColor(COLOR_BORDER)
  const wrapped = doc.splitTextToSize(SEBI_DISCLAIMER, pageWidth - 100)
  const boxH = wrapped.length * 12 + 20
  doc.roundedRect(40, y, pageWidth - 80, boxH, 6, 6, "FD")
  doc.setFontSize(9)
  doc.setTextColor(COLOR_INK)
  doc.text(wrapped, 50, y + 14)
}

// ── public API ───────────────────────────────────────────────────
export function buildPDFReport(bundle: PDFBundle): jsPDF {
  const doc = new jsPDF({ unit: "pt", format: "a4" })
  renderHero(doc, bundle)
  doc.addPage()
  renderDetail(doc, bundle)
  doc.addPage()
  renderFinancials(doc, bundle)
  doc.addPage()
  renderContext(doc, bundle)
  // Footer pass — fill in page numbers after all pages exist.
  const total = doc.getNumberOfPages()
  for (let i = 1; i <= total; i++) {
    doc.setPage(i)
    drawPageFooter(doc, bundle.ticker, i, total)
  }
  return doc
}

export function downloadPDFReport(bundle: PDFBundle): void {
  const doc = buildPDFReport(bundle)
  const safe = bundle.ticker.replace(/\./g, "_")
  doc.save(`YieldIQ_${safe}_report.pdf`)
}
