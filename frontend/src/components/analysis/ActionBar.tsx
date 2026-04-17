"use client"

import { useState, useEffect, useRef } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { cn } from "@/lib/utils"
import { trackExportUsed } from "@/lib/analytics"
import { checkInWatchlist, addToWatchlist, removeFromWatchlist, createAlert } from "@/lib/api"
import type { Verdict, MoatGrade } from "@/types/api"

interface ActionBarProps {
  ticker: string
  currentPrice: number
  companyName: string
  sector: string
  currency: string
  fairValue: number
  mos: number
  verdict: Verdict
  score: number
  grade: string
  piotroski: number
  moat: MoatGrade
  moatScore: number
  wacc: number
  fcfGrowth: number
  confidence: number
  bearCase: number
  baseCase: number
  bullCase: number
  bearMos: number
  bullMos: number
}

function ActionButton({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex flex-1 flex-col items-center gap-1 rounded-xl bg-gray-50 py-3 px-2",
        "text-gray-600 hover:bg-gray-100 active:bg-gray-200 transition-colors"
      )}
    >
      {icon}
      <span className="text-xs font-medium">{label}</span>
    </button>
  )
}

/* ── Verdict helpers ─────────────────────────────────── */

function verdictLabel(v: Verdict): string {
  switch (v) {
    case "undervalued":   return "Undervalued"
    case "fairly_valued": return "Fairly Valued"
    case "overvalued":    return "Overvalued"
    case "avoid":         return "High Risk"
    case "data_limited":  return "Data Limited"
    case "unavailable":   return "Unavailable"
    default:              return v
  }
}

function verdictEmoji(v: Verdict): string {
  switch (v) {
    case "undervalued":   return "\u2705"
    case "fairly_valued": return "\ud83d\udfe1"
    case "overvalued":    return "\ud83d\udfe0"
    case "avoid":         return "\ud83d\udd34"
    case "data_limited":  return "\u2753"
    case "unavailable":   return "\u26a0\ufe0f"
    default:              return ""
  }
}

function verdictColor(v: Verdict): { bg: string; text: string } {
  switch (v) {
    case "undervalued":   return { bg: "#dcfce7", text: "#166534" }
    case "fairly_valued": return { bg: "#dbeafe", text: "#1e40af" }
    case "overvalued":    return { bg: "#fee2e2", text: "#991b1b" }
    case "avoid":         return { bg: "#fef2f2", text: "#7f1d1d" }
    case "data_limited":  return { bg: "#f5f5f5", text: "#525252" }
    case "unavailable":   return { bg: "#f5f5f5", text: "#525252" }
    default:              return { bg: "#f5f5f5", text: "#525252" }
  }
}

function scoreEmoji(score: number): string {
  if (score >= 80) return "\ud83d\udfe2"
  if (score >= 60) return "\ud83d\udfe1"
  if (score >= 40) return "\ud83d\udfe0"
  return "\ud83d\udd34"
}

/* ── Share card helpers ──────────────────────────────── */

function getVerdictCardColors(v: Verdict): { bg: string; text: string; bgAlpha: string } {
  switch (v) {
    case "undervalued":   return { bg: "#10B981", text: "#10B981", bgAlpha: "rgba(16,185,129,0.15)" }
    case "fairly_valued": return { bg: "#3B82F6", text: "#3B82F6", bgAlpha: "rgba(59,130,246,0.15)" }
    case "overvalued":    return { bg: "#EF4444", text: "#EF4444", bgAlpha: "rgba(239,68,68,0.15)" }
    case "avoid":         return { bg: "#EF4444", text: "#EF4444", bgAlpha: "rgba(239,68,68,0.15)" }
    case "data_limited":  return { bg: "#6B7280", text: "#6B7280", bgAlpha: "rgba(107,114,128,0.15)" }
    case "unavailable":   return { bg: "#6B7280", text: "#6B7280", bgAlpha: "rgba(107,114,128,0.15)" }
    default:              return { bg: "#6B7280", text: "#6B7280", bgAlpha: "rgba(107,114,128,0.15)" }
  }
}

async function generateShareCard(p: ActionBarProps): Promise<Blob> {
  const W = 1080, H = 1080
  const canvas = document.createElement("canvas")
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext("2d")!

  // Background gradient
  const bgGrad = ctx.createLinearGradient(0, 0, 0, H)
  bgGrad.addColorStop(0, "#0F172A")
  bgGrad.addColorStop(1, "#1E293B")
  ctx.fillStyle = bgGrad
  ctx.fillRect(0, 0, W, H)

  // Helper: draw text
  const text = (
    str: string, x: number, y: number, size: number, color: string,
    weight = "600", align: CanvasTextAlign = "left"
  ) => {
    ctx.font = `${weight} ${size}px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`
    ctx.fillStyle = color
    ctx.textAlign = align
    ctx.fillText(str, x, y)
  }

  // Helper: rounded rect path
  const roundRect = (x: number, y: number, w: number, h: number, r: number) => {
    ctx.beginPath()
    ctx.moveTo(x + r, y)
    ctx.lineTo(x + w - r, y)
    ctx.quadraticCurveTo(x + w, y, x + w, y + r)
    ctx.lineTo(x + w, y + h - r)
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
    ctx.lineTo(x + r, y + h)
    ctx.quadraticCurveTo(x, y + h, x, y + h - r)
    ctx.lineTo(x, y + r)
    ctx.quadraticCurveTo(x, y, x + r, y)
    ctx.closePath()
  }

  // Helper: horizontal line
  const hLine = (y: number, marginX: number, color: string, width = 2) => {
    ctx.strokeStyle = color
    ctx.lineWidth = width
    ctx.beginPath()
    ctx.moveTo(marginX, y)
    ctx.lineTo(W - marginX, y)
    ctx.stroke()
  }

  const dt = displayTicker(p.ticker)
  const today = new Date().toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })
  const vc = getVerdictCardColors(p.verdict)

  // 1. Header — letter-spaced YIELDIQ
  ctx.save()
  ctx.font = "800 28px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
  ctx.fillStyle = "#3B82F6"
  ctx.textAlign = "left"
  let headerX = 60
  for (const ch of "YIELDIQ") {
    ctx.fillText(ch, headerX, 70)
    headerX += ctx.measureText(ch).width + 5
  }
  ctx.restore()
  text(today, W - 60, 70, 22, "#64748B", "500", "right")

  // 2. Divider
  hLine(100, 60, "#1E293B")

  // 3. Company name
  text(p.companyName, 60, 160, 48, "#FFFFFF", "700", "left")
  text(`${dt}  \u00B7  ${p.sector}`, 60, 195, 24, "#64748B", "400", "left")

  // 4. Verdict badge
  roundRect(60, 240, 960, 100, 16)
  ctx.fillStyle = vc.bgAlpha
  ctx.fill()
  text(verdictLabel(p.verdict), 100, 305, 36, vc.text, "700", "left")
  text(`Fair Value \u20B9${p.fairValue.toLocaleString("en-IN")}`, W - 100, 305, 36, "#FFFFFF", "700", "right")

  // 5. Price + MoS row
  text(`Current Price: \u20B9${p.currentPrice.toLocaleString("en-IN")}`, 60, 400, 28, "#94A3B8", "500", "left")
  const mosColor = p.mos >= 0 ? "#10B981" : "#EF4444"
  const mosSign = p.mos >= 0 ? "+" : ""
  text(`Margin of Safety: ${mosSign}${p.mos.toFixed(1)}%`, W - 60, 400, 28, mosColor, "600", "right")

  // 6. Score ring
  const cx = W / 2, cy = 560, ringR = 90
  ctx.lineWidth = 12
  ctx.lineCap = "round"
  // Background ring
  ctx.strokeStyle = "#1E293B"
  ctx.beginPath()
  ctx.arc(cx, cy, ringR, 0, Math.PI * 2)
  ctx.stroke()
  // Score arc
  const scoreAngle = (p.score / 100) * Math.PI * 2
  const scoreColor = p.score >= 75 ? "#10B981" : p.score >= 55 ? "#3B82F6" : p.score >= 35 ? "#F59E0B" : "#EF4444"
  ctx.strokeStyle = scoreColor
  ctx.beginPath()
  ctx.arc(cx, cy, ringR, -Math.PI / 2, -Math.PI / 2 + scoreAngle)
  ctx.stroke()
  ctx.lineCap = "butt"
  // Score number
  text(String(p.score), cx, cy + 18, 64, "#FFFFFF", "700", "center")
  // Grade below ring
  text(`Grade ${p.grade}`, cx, cy + ringR + 40, 28, "#94A3B8", "500", "center")

  // 7. Metrics strip
  const metricsY = 730
  const col1X = W / 6, col2X = W / 2, col3X = (W * 5) / 6
  // Labels
  text("MOAT", col1X, metricsY, 18, "#64748B", "600", "center")
  text("PIOTROSKI", col2X, metricsY, 18, "#64748B", "600", "center")
  text("QUALITY", col3X, metricsY, 18, "#64748B", "600", "center")
  // Values
  text(p.moat, col1X, metricsY + 38, 28, "#FFFFFF", "700", "center")
  text(`${p.piotroski}/9`, col2X, metricsY + 38, 28, "#FFFFFF", "700", "center")
  text(`${p.confidence.toFixed(0)}/100`, col3X, metricsY + 38, 28, "#FFFFFF", "700", "center")
  // Divider lines between columns
  const divX1 = W / 3, divX2 = (W * 2) / 3
  ctx.strokeStyle = "#1E293B"
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(divX1, metricsY - 15)
  ctx.lineTo(divX1, metricsY + 50)
  ctx.stroke()
  ctx.beginPath()
  ctx.moveTo(divX2, metricsY - 15)
  ctx.lineTo(divX2, metricsY + 50)
  ctx.stroke()

  // 8. Scenarios row
  const scenY = 845
  text(`Bear \u20B9${p.bearCase.toLocaleString("en-IN")}`, col1X, scenY, 24, "#EF4444", "600", "center")
  text(`Base \u20B9${p.baseCase.toLocaleString("en-IN")}`, col2X, scenY, 24, "#3B82F6", "600", "center")
  text(`Bull \u20B9${p.bullCase.toLocaleString("en-IN")}`, col3X, scenY, 24, "#10B981", "600", "center")

  // 9. Footer
  hLine(920, 60, "#1E293B")
  text("yieldiq.in", 60, 970, 24, "#3B82F6", "600", "left")
  text("Model estimate only. Not investment advice.", W - 60, 970, 18, "#475569", "400", "right")
  text("Scan any stock free \u2192", cx, 1020, 20, "#64748B", "500", "center")

  // Convert to blob
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob)
      else reject(new Error("Canvas toBlob failed"))
    }, "image/png")
  })
}

/* ── Export functions ─────────────────────────────────── */

function displayTicker(ticker: string): string {
  return ticker.replace(".NS", "").replace(".BO", "")
}

function buildWhatsAppText(p: ActionBarProps): string {
  const dt = displayTicker(p.ticker)
  const mosSign = p.mos >= 0 ? "+" : ""
  const verdictTag = verdictLabel(p.verdict)
  const ve = verdictEmoji(p.verdict)
  const se = scoreEmoji(p.score)
  const sym = p.currency === "INR" ? "\u20b9" : "$"
  const loc = p.currency === "INR" ? "en-IN" : "en-US"
  // Only append ".NS" in the share URL for Indian tickers
  const suffix = p.currency === "INR" ? ".NS" : ""

  // Attractive, clean format that makes people want to click the link
  return [
    `${ve} *${p.companyName}* is *${verdictTag}*`,
    ``,
    `${sym}${p.currentPrice.toLocaleString(loc)} \u2192 Fair Value *${sym}${p.fairValue.toLocaleString(loc)}* (${mosSign}${p.mos.toFixed(0)}% MoS)`,
    ``,
    `${se} *Score ${p.score}/100* | Grade ${p.grade}`,
    `\u{1f6e1}\ufe0f Moat: ${p.moat} | Piotroski: ${p.piotroski}/9`,
    ``,
    `\u{1f4c9} Bear ${sym}${p.bearCase.toLocaleString(loc)}`,
    `\u{1f4ca} Base ${sym}${p.baseCase.toLocaleString(loc)}`,
    `\u{1f4c8} Bull ${sym}${p.bullCase.toLocaleString(loc)}`,
    ``,
    `\u{1f50d} *See full DCF analysis:*`,
    `https://yieldiq.in/analysis/${dt}${suffix}`,
  ].join("\n")
}

function buildPdfHtml(p: ActionBarProps): string {
  const dt = displayTicker(p.ticker)
  const vc = verdictColor(p.verdict)
  const today = new Date().toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>YieldIQ Report - ${dt}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; color: #1a1a1a; background: #fff; }
  .page { max-width: 680px; margin: 0 auto; padding: 32px 28px; }
  .header { display: flex; align-items: center; justify-content: space-between; padding-bottom: 20px; border-bottom: 3px solid #2563eb; margin-bottom: 24px; }
  .logo { font-size: 22px; font-weight: 700; color: #2563eb; letter-spacing: -0.5px; }
  .logo span { color: #64748b; font-weight: 400; font-size: 13px; margin-left: 8px; }
  .date { font-size: 12px; color: #94a3b8; }
  .company-block { margin-bottom: 20px; }
  .company-name { font-size: 20px; font-weight: 700; }
  .company-meta { font-size: 13px; color: #64748b; margin-top: 2px; }
  .verdict-block { background: ${vc.bg}; color: ${vc.text}; padding: 16px 20px; border-radius: 12px; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between; }
  .verdict-label { font-size: 18px; font-weight: 700; }
  .verdict-right { text-align: right; }
  .verdict-right .fair { font-size: 15px; font-weight: 600; }
  .verdict-right .price { font-size: 12px; color: ${vc.text}; opacity: 0.8; margin-top: 2px; }
  .verdict-right .mos { font-size: 13px; font-weight: 600; margin-top: 4px; }
  .metrics-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 20px; }
  .metric-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; text-align: center; }
  .metric-card .label { font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
  .metric-card .value { font-size: 20px; font-weight: 700; color: #1e293b; }
  .metric-card .sub { font-size: 11px; color: #64748b; margin-top: 2px; }
  .scenarios { margin-bottom: 20px; }
  .scenarios h3 { font-size: 14px; font-weight: 600; color: #475569; margin-bottom: 10px; }
  .scenario-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
  .scenario { text-align: center; padding: 12px; border-radius: 10px; border: 1px solid #e2e8f0; }
  .scenario.bear { background: linear-gradient(to bottom, #fef2f2, #fff); }
  .scenario.base { background: linear-gradient(to bottom, #eff6ff, #fff); }
  .scenario.bull { background: linear-gradient(to bottom, #f0fdf4, #fff); }
  .scenario .s-label { font-size: 11px; color: #94a3b8; margin-bottom: 4px; }
  .scenario .s-value { font-size: 17px; font-weight: 700; }
  .scenario.bear .s-value { color: #dc2626; }
  .scenario.base .s-value { color: #2563eb; }
  .scenario.bull .s-value { color: #16a34a; }
  .scenario .s-mos { font-size: 11px; color: #94a3b8; margin-top: 2px; }
  .wacc-strip { background: #f1f5f9; border-radius: 8px; padding: 10px 16px; font-size: 12px; color: #475569; margin-bottom: 24px; display: flex; gap: 24px; }
  .wacc-strip strong { color: #1e293b; }
  .disclaimer { font-size: 10px; color: #94a3b8; text-align: center; line-height: 1.6; border-top: 1px solid #e2e8f0; padding-top: 16px; margin-top: 16px; }
  .disclaimer .brand { font-weight: 600; color: #64748b; }
  @media print {
    body { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
    .page { padding: 20px; }
  }
</style></head>
<body>
<div class="page">
  <div class="header">
    <div class="logo">YieldIQ<span>Report Card</span></div>
    <div class="date">${today}</div>
  </div>

  <div class="company-block">
    <div class="company-name">${p.companyName}</div>
    <div class="company-meta">${dt} &middot; ${p.sector}</div>
  </div>

  <div class="verdict-block">
    <div class="verdict-label">${verdictLabel(p.verdict)}</div>
    <div class="verdict-right">
      <div class="fair">Fair Value: &#8377;${p.fairValue.toFixed(0)}</div>
      <div class="price">CMP: &#8377;${p.currentPrice.toFixed(0)}</div>
      <div class="mos">MoS: ${p.mos >= 0 ? "+" : ""}${p.mos.toFixed(1)}%</div>
    </div>
  </div>

  <div class="metrics-grid">
    <div class="metric-card">
      <div class="label">YieldIQ Score</div>
      <div class="value">${p.score}</div>
      <div class="sub">Grade ${p.grade}</div>
    </div>
    <div class="metric-card">
      <div class="label">Piotroski</div>
      <div class="value">${p.piotroski}/9</div>
      <div class="sub">Financial health</div>
    </div>
    <div class="metric-card">
      <div class="label">Moat</div>
      <div class="value">${p.moat}</div>
      <div class="sub">Score: ${p.moatScore}/100</div>
    </div>
  </div>

  <div class="scenarios">
    <h3>Scenario Analysis</h3>
    <div class="scenario-grid">
      <div class="scenario bear">
        <div class="s-label">Bear Case</div>
        <div class="s-value">&#8377;${p.bearCase.toFixed(0)}</div>
        <div class="s-mos">MoS: ${p.bearMos >= 0 ? "+" : ""}${p.bearMos.toFixed(1)}%</div>
      </div>
      <div class="scenario base">
        <div class="s-label">Base Case</div>
        <div class="s-value">&#8377;${p.baseCase.toFixed(0)}</div>
        <div class="s-mos">MoS: ${p.mos >= 0 ? "+" : ""}${p.mos.toFixed(1)}%</div>
      </div>
      <div class="scenario bull">
        <div class="s-label">Bull Case</div>
        <div class="s-value">&#8377;${p.bullCase.toFixed(0)}</div>
        <div class="s-mos">MoS: ${p.bullMos >= 0 ? "+" : ""}${p.bullMos.toFixed(1)}%</div>
      </div>
    </div>
  </div>

  <div class="wacc-strip">
    <div><strong>WACC:</strong> ${(p.wacc * 100).toFixed(1)}%</div>
    <div><strong>FCF Growth:</strong> ${(p.fcfGrowth * 100).toFixed(1)}%</div>
    <div><strong>Confidence:</strong> ${p.confidence.toFixed(0)}%</div>
  </div>

  <div class="disclaimer">
    All outputs are model estimates using publicly available data. Not investment advice.<br>
    YieldIQ is not registered with SEBI as an investment adviser.<br><br>
    <span class="brand">Generated by YieldIQ &mdash; yieldiq.in</span>
  </div>
</div>
</body></html>`
}

function buildCsvContent(p: ActionBarProps): string {
  const dt = displayTicker(p.ticker)
  const today = new Date().toISOString().split("T")[0]
  const rows: [string, string][] = [
    ["Metric", "Value"],
    ["Company", p.companyName],
    ["Ticker", dt],
    ["Sector", p.sector],
    ["Currency", p.currency],
    ["Date", today],
    ["Current Price", p.currentPrice.toFixed(2)],
    ["Fair Value", p.fairValue.toFixed(2)],
    ["Margin of Safety (%)", p.mos.toFixed(1)],
    ["Verdict", verdictLabel(p.verdict)],
    ["YieldIQ Score", String(p.score)],
    ["Grade", p.grade],
    ["Piotroski Score", String(p.piotroski)],
    ["Moat", p.moat],
    ["Moat Score", String(p.moatScore)],
    ["WACC (%)", (p.wacc * 100).toFixed(2)],
    ["FCF Growth Rate (%)", (p.fcfGrowth * 100).toFixed(2)],
    ["Confidence Score", p.confidence.toFixed(0)],
    ["Bear Case", p.bearCase.toFixed(2)],
    ["Bear MoS (%)", p.bearMos.toFixed(1)],
    ["Base Case", p.baseCase.toFixed(2)],
    ["Bull Case", p.bullCase.toFixed(2)],
    ["Bull MoS (%)", p.bullMos.toFixed(1)],
  ]
  return rows.map(([k, v]) => `"${k}","${v}"`).join("\n")
}

function downloadCsv(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function printPdf(htmlContent: string) {
  const iframe = document.createElement("iframe")
  iframe.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:none"
  document.body.appendChild(iframe)
  const doc = iframe.contentDocument
  if (!doc) return
  doc.write(htmlContent)
  doc.close()
  setTimeout(() => {
    iframe.contentWindow?.focus()
    iframe.contentWindow?.print()
    setTimeout(() => document.body.removeChild(iframe), 1000)
  }, 500)
}

/* ── Component ────────────────────────────────────────── */

export default function ActionBar(props: ActionBarProps) {
  const { ticker, currentPrice, currency } = props
  const sym = currency === "INR" ? "\u20b9" : "$"
  const loc = currency === "INR" ? "en-IN" : "en-US"
  const [toast, setToast] = useState<string | null>(null)
  const [showExportMenu, setShowExportMenu] = useState(false)
  const [showCopied, setShowCopied] = useState(false)
  const [showAlertModal, setShowAlertModal] = useState(false)
  const [alertTargetPrice, setAlertTargetPrice] = useState("")
  const [alertDirection, setAlertDirection] = useState<"below" | "above">("below")
  const exportRef = useRef<HTMLDivElement>(null)
  const alertRef = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()

  // Watchlist state
  const { data: watchlistStatus } = useQuery({
    queryKey: ["watchlist-check", ticker],
    queryFn: () => checkInWatchlist(ticker),
    staleTime: 30_000,
  })
  const inWatchlist = watchlistStatus?.in_watchlist ?? false

  const watchlistAdd = useMutation({
    mutationFn: () => addToWatchlist({ ticker, company_name: props.companyName, added_price: currentPrice }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlist-check", ticker] })
      queryClient.invalidateQueries({ queryKey: ["watchlist"] })
      setToast("Added to watchlist")
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to add"
      setToast(msg)
    },
  })

  const watchlistRemove = useMutation({
    mutationFn: () => removeFromWatchlist(ticker),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlist-check", ticker] })
      queryClient.invalidateQueries({ queryKey: ["watchlist"] })
      setToast("Removed from watchlist")
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to remove"
      setToast(msg)
    },
  })

  const alertCreate = useMutation({
    mutationFn: (data: { ticker: string; alert_type: string; target_price: number }) => createAlert(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] })
      setShowAlertModal(false)
      setAlertTargetPrice("")
      setToast("Alert set! We'll email you when triggered.")
    },
    onError: (err: Error & { response?: { data?: { detail?: string } } }) => {
      const detail = err.response?.data?.detail || "Failed to create alert"
      setToast(detail)
    },
  })

  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 3000)
      return () => clearTimeout(t)
    }
  }, [toast])

  // Close export menu on outside click
  useEffect(() => {
    if (!showExportMenu) return
    const handler = (e: MouseEvent) => {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) {
        setShowExportMenu(false)
      }
    }
    document.addEventListener("click", handler)
    return () => document.removeEventListener("click", handler)
  }, [showExportMenu])

  // Close alert modal on outside click
  useEffect(() => {
    if (!showAlertModal) return
    const handler = (e: MouseEvent) => {
      if (alertRef.current && !alertRef.current.contains(e.target as Node)) {
        setShowAlertModal(false)
      }
    }
    document.addEventListener("click", handler)
    return () => document.removeEventListener("click", handler)
  }, [showAlertModal])

  const handleWatchlist = () => {
    if (inWatchlist) {
      watchlistRemove.mutate()
    } else {
      watchlistAdd.mutate()
    }
  }

  const handleAlert = (e: React.MouseEvent) => {
    e.stopPropagation()
    setShowAlertModal((v) => !v)
  }

  const handleAlertSubmit = () => {
    const price = parseFloat(alertTargetPrice)
    if (!price || price <= 0) {
      setToast("Enter a valid target price")
      return
    }
    alertCreate.mutate({ ticker, alert_type: alertDirection, target_price: price })
  }

  const handleShareWhatsApp = async () => {
    setShowExportMenu(false)
    trackExportUsed("whatsapp_card", ticker)

    try {
      const blob = await generateShareCard(props)
      const file = new File([blob], `YieldIQ_${displayTicker(ticker)}.png`, { type: "image/png" })

      if (navigator.share && navigator.canShare?.({ files: [file] })) {
        await navigator.share({
          files: [file],
          title: `${props.companyName} — ${verdictLabel(props.verdict)}`,
          text: `Check out this stock analysis on YieldIQ`,
        })
      } else {
        // Desktop fallback — download the card
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `YieldIQ_${displayTicker(ticker)}.png`
        a.click()
        URL.revokeObjectURL(url)
        setToast("Card downloaded! Share it on WhatsApp")
      }
    } catch {
      // Fallback to text share if canvas fails
      const waText = buildWhatsAppText(props)
      window.open(`https://wa.me/?text=${encodeURIComponent(waText)}`, "_blank")
    }
  }

  const handleShareTwitter = async () => {
    setShowExportMenu(false)
    trackExportUsed("twitter_card", ticker)
    const dt = displayTicker(ticker)

    try {
      const blob = await generateShareCard(props)
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `YieldIQ_${dt}.png`
      a.click()
      URL.revokeObjectURL(url)

      const tweetText = `${props.companyName} is ${verdictLabel(props.verdict)} — Score ${props.score}/100\n\nFull DCF analysis on @YieldIQ \ud83d\udc47`
      window.open(
        `https://twitter.com/intent/tweet?text=${encodeURIComponent(tweetText)}&url=${encodeURIComponent(`https://yieldiq.in/analysis/${dt}.NS`)}`,
        "_blank"
      )
      setToast("Card downloaded! Attach it to your tweet")
    } catch {
      window.open(
        `https://twitter.com/intent/tweet?text=${encodeURIComponent(`${props.companyName} analysis on YieldIQ`)}&url=${encodeURIComponent(`https://yieldiq.in/analysis/${dt}.NS`)}`,
        "_blank"
      )
    }
  }

  const handleCopyLink = async () => {
    setShowExportMenu(false)
    trackExportUsed("copy_link", ticker)
    try {
      await navigator.clipboard.writeText(buildWhatsAppText(props))
      setToast("Copied to clipboard!")
    } catch {
      setToast("Could not copy")
    }
  }

  const handleDownloadCard = async () => {
    setShowExportMenu(false)
    trackExportUsed("download_card", ticker)
    try {
      const blob = await generateShareCard(props)
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `YieldIQ_${displayTicker(ticker)}.png`
      a.click()
      URL.revokeObjectURL(url)
      setToast("Card downloaded!")
    } catch {
      setToast("Could not generate card")
    }
  }

  const handleDownloadPdf = () => {
    setShowExportMenu(false)
    trackExportUsed("pdf", ticker)
    printPdf(buildPdfHtml(props))
  }

  const handleDownloadCsv = () => {
    setShowExportMenu(false)
    trackExportUsed("csv", ticker)
    const dt = displayTicker(ticker)
    const today = new Date().toISOString().split("T")[0]
    downloadCsv(buildCsvContent(props), `YieldIQ_${dt}_${today}.csv`)
  }

  const handleShare = async () => {
    const shareUrl = `https://yieldiq.in/analysis/${ticker}`
    const dt = displayTicker(ticker)
    const shareData = {
      title: `${dt} \u2014 Stock Analysis`,
      text: `${dt} analysis on YieldIQ \u2014 check if it's undervalued or overvalued`,
      url: shareUrl,
    }

    if (navigator.share) {
      try {
        await navigator.share(shareData)
        return
      } catch {
        // User cancelled or share failed -- fall through to clipboard
      }
    }

    try {
      await navigator.clipboard.writeText(shareUrl)
      setShowCopied(true)
      setTimeout(() => setShowCopied(false), 2000)
    } catch {
      // Last resort: do nothing
    }
  }

  return (
    <div className="relative flex flex-row gap-2">
      {/* Copied toast */}
      {showCopied && (
        <div className="absolute -top-10 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-xs font-medium px-3 py-1.5 rounded-lg shadow-lg animate-fade-in whitespace-nowrap z-10">
          Link copied!
        </div>
      )}
      {/* General toast notification */}
      {toast && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-xs font-medium px-4 py-2 rounded-lg shadow-lg z-50 whitespace-nowrap">
          {toast}
        </div>
      )}

      {/* Watchlist — filled star if in watchlist, outline if not */}
      <button
        onClick={handleWatchlist}
        disabled={watchlistAdd.isPending || watchlistRemove.isPending}
        className={cn(
          "flex flex-1 flex-col items-center gap-1 rounded-xl py-3 px-2 transition-colors",
          inWatchlist
            ? "bg-amber-50 text-amber-600 hover:bg-amber-100"
            : "bg-gray-50 text-gray-600 hover:bg-gray-100 active:bg-gray-200"
        )}
      >
        {inWatchlist ? (
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.562.562 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.562.562 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
          </svg>
        ) : (
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.562.562 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.562.562 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
          </svg>
        )}
        <span className="text-xs font-medium">{inWatchlist ? "Saved" : "Watchlist"}</span>
      </button>

      {/* Alert — with popover modal */}
      <div ref={alertRef} className="relative flex-1">
        <button
          onClick={handleAlert}
          className={cn(
            "flex w-full flex-col items-center gap-1 rounded-xl bg-gray-50 py-3 px-2",
            "text-gray-600 hover:bg-gray-100 active:bg-gray-200 transition-colors"
          )}
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
          </svg>
          <span className="text-xs font-medium">Alert</span>
        </button>

        {/* Alert popover */}
        {showAlertModal && (
          <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 w-64 bg-white rounded-xl border border-gray-200 shadow-lg z-50 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-gray-900">Set Price Alert</p>
              <button onClick={() => setShowAlertModal(false)} className="text-gray-400 hover:text-gray-600">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <p className="text-xs text-gray-400">
              Current: <span className="font-mono text-gray-600">{sym}{currentPrice.toLocaleString(loc)}</span>
            </p>

            {/* Direction toggle */}
            <div className="flex bg-gray-100 rounded-lg p-0.5">
              <button
                onClick={() => setAlertDirection("below")}
                className={cn(
                  "flex-1 py-1.5 text-xs font-medium rounded-md transition-all",
                  alertDirection === "below" ? "bg-white text-blue-700 shadow-sm" : "text-gray-500"
                )}
              >
                Below
              </button>
              <button
                onClick={() => setAlertDirection("above")}
                className={cn(
                  "flex-1 py-1.5 text-xs font-medium rounded-md transition-all",
                  alertDirection === "above" ? "bg-white text-blue-700 shadow-sm" : "text-gray-500"
                )}
              >
                Above
              </button>
            </div>

            {/* Target price input */}
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">{sym}</span>
              <input
                type="number"
                value={alertTargetPrice}
                onChange={(e) => setAlertTargetPrice(e.target.value)}
                placeholder="Target price"
                className="w-full pl-7 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            <button
              onClick={handleAlertSubmit}
              disabled={alertCreate.isPending}
              className="w-full py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition disabled:opacity-50"
            >
              {alertCreate.isPending ? "Setting..." : "Set Alert"}
            </button>
          </div>
        )}
      </div>

      {/* Export with dropdown */}
      <div ref={exportRef} className="relative flex-1">
        <button
          onClick={(e) => { e.stopPropagation(); setShowExportMenu((v) => !v) }}
          className={cn(
            "flex w-full flex-col items-center gap-1 rounded-xl bg-gray-50 py-3 px-2",
            "text-gray-600 hover:bg-gray-100 active:bg-gray-200 transition-colors"
          )}
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
          </svg>
          <span className="text-xs font-medium">Export</span>
        </button>

        {showExportMenu && (
          <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 w-56 bg-white rounded-xl border border-gray-200 shadow-lg z-50 overflow-hidden">
            <div className="px-3 py-2 bg-gray-50 border-b border-gray-100">
              <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Share</span>
            </div>
            <button
              onClick={handleShareWhatsApp}
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-gray-700 hover:bg-green-50 hover:text-green-700 transition-colors"
            >
              <svg className="w-4 h-4 text-green-600" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/><path d="M12 0C5.373 0 0 5.373 0 12c0 2.625.846 5.059 2.284 7.034L.789 23.492a.5.5 0 00.611.611l4.458-1.495A11.952 11.952 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 22c-2.344 0-4.507-.795-6.23-2.131l-.355-.282-3.281 1.1 1.1-3.281-.282-.355A9.935 9.935 0 012 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10z"/></svg>
              <span>Share on WhatsApp</span>
            </button>
            <button
              onClick={handleShareTwitter}
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-gray-700 hover:bg-blue-50 hover:text-blue-700 transition-colors"
            >
              <svg className="w-4 h-4 text-gray-500" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
              <span>Share on X</span>
            </button>
            <button
              onClick={handleCopyLink}
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
            >
              <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
              <span>Copy to clipboard</span>
            </button>
            <div className="h-px bg-gray-100" />
            <div className="px-3 py-2 bg-gray-50 border-b border-gray-100">
              <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Download</span>
            </div>
            <button
              onClick={handleDownloadCard}
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
            >
              <svg className="w-4 h-4 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" /></svg>
              <span>Share card (PNG)</span>
            </button>
            <button
              onClick={handleDownloadPdf}
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
            >
              <svg className="w-4 h-4 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" /></svg>
              <span>PDF report</span>
            </button>
            <button
              onClick={handleDownloadCsv}
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
            >
              <svg className="w-4 h-4 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125" /></svg>
              <span>CSV data</span>
            </button>
          </div>
        )}
      </div>

      {/* Share — native share sheet on mobile, copy URL on desktop */}
      <ActionButton
        icon={
          showCopied ? (
            <svg className="h-5 w-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
          ) : (
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z" />
            </svg>
          )
        }
        label={showCopied ? "Copied!" : "Share"}
        onClick={handleShare}
      />
    </div>
  )
}
