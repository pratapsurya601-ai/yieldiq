"use client"

import { useState, useEffect, useRef } from "react"
import { cn } from "@/lib/utils"
import { trackExportUsed } from "@/lib/analytics"
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
    case "avoid":         return "Avoid"
    case "data_limited":  return "Data Limited"
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
    default:              return { bg: "#f5f5f5", text: "#525252" }
  }
}

function scoreEmoji(score: number): string {
  if (score >= 80) return "\ud83d\udfe2"
  if (score >= 60) return "\ud83d\udfe1"
  if (score >= 40) return "\ud83d\udfe0"
  return "\ud83d\udd34"
}

/* ── Export functions ─────────────────────────────────── */

function displayTicker(ticker: string): string {
  return ticker.replace(".NS", "").replace(".BO", "")
}

function buildWhatsAppText(p: ActionBarProps): string {
  const dt = displayTicker(p.ticker)
  const mosSign = p.mos >= 0 ? "+" : ""
  const verdictTag = verdictLabel(p.verdict).toUpperCase()

  return [
    `*${p.companyName}* (${dt})`,
    ``,
    `\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500`,
    `\u2502  Price      \u20b9${p.currentPrice.toLocaleString("en-IN")}`,
    `\u2502  Fair Value  \u20b9${p.fairValue.toLocaleString("en-IN")}`,
    `\u2502  MoS        ${mosSign}${p.mos.toFixed(1)}%`,
    `\u2502  Verdict     *${verdictTag}*`,
    `\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500`,
    ``,
    `Score *${p.score}*/100 (${p.grade}) \u2022 Moat: ${p.moat} \u2022 Piotroski: ${p.piotroski}/9`,
    `Bear \u20b9${p.bearCase.toLocaleString("en-IN")} \u2022 Base \u20b9${p.baseCase.toLocaleString("en-IN")} \u2022 Bull \u20b9${p.bullCase.toLocaleString("en-IN")}`,
    ``,
    `_Model estimate, not investment advice_`,
    `yieldiq.in/analysis/${dt}`,
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
  const { ticker, currentPrice } = props
  const [toast, setToast] = useState<string | null>(null)
  const [showExportMenu, setShowExportMenu] = useState(false)
  const [showCopied, setShowCopied] = useState(false)
  const exportRef = useRef<HTMLDivElement>(null)

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

  const handleWatchlist = () => {
    // TODO: add to watchlist
  }

  const handleAlert = () => {
    // TODO: set price alert
  }

  const handleCopyWhatsApp = async () => {
    setShowExportMenu(false)
    trackExportUsed("whatsapp", ticker)
    try {
      await navigator.clipboard.writeText(buildWhatsAppText(props))
      setToast("Copied! Paste on WhatsApp / Twitter")
      setTimeout(() => setToast(null), 2000)
    } catch {
      setToast("Could not copy to clipboard")
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
      <ActionButton
        label="Watchlist"
        onClick={handleWatchlist}
        icon={
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.562.562 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.562.562 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
          </svg>
        }
      />
      <ActionButton
        label="Alert"
        onClick={handleAlert}
        icon={
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
          </svg>
        }
      />

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
          <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 w-52 bg-white rounded-xl border border-gray-200 shadow-lg z-50 overflow-hidden animate-fade-in">
            <button
              onClick={handleCopyWhatsApp}
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
            >
              <span className="text-base leading-none">{"\ud83d\udcac"}</span>
              <span>Copy for WhatsApp</span>
            </button>
            <div className="h-px bg-gray-100" />
            <button
              onClick={handleDownloadPdf}
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
            >
              <span className="text-base leading-none">{"\ud83d\udcc4"}</span>
              <span>Download PDF</span>
            </button>
            <div className="h-px bg-gray-100" />
            <button
              onClick={handleDownloadCsv}
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
            >
              <span className="text-base leading-none">{"\ud83d\udcca"}</span>
              <span>Download CSV</span>
            </button>
          </div>
        )}
      </div>

      <ActionButton
        label="Share"
        onClick={handleShare}
        icon={
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z" />
          </svg>
        }
      />
    </div>
  )
}
