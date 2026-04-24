"use client"

import { useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import * as XLSX from "xlsx"
import api from "@/lib/api"
import { useAuthStore } from "@/store/authStore"

type Broker = "zerodha" | "groww" | "upstox" | "icici" | "custom"

const BROKER_OPTIONS: { value: Broker; label: string; format: string }[] = [
  { value: "zerodha", label: "Zerodha Console", format: "Symbol, ISIN, Qty, Avg.cost, ..." },
  // sebi-allow: buy
  { value: "groww", label: "Groww", format: "Stock Name, ISIN, Quantity, Average buy price, ..." },
  { value: "upstox", label: "Upstox", format: "Company Name, Exchange, Quantity, Avg Price, ..." },
  { value: "icici", label: "ICICI Direct", format: "Stock, Qty, Avg Price, ..." },
  { value: "custom", label: "Custom / Manual", format: "ticker, quantity, avg_price" },
]

const ZERODHA_EXAMPLE = `Symbol,ISIN,Instrument,Qty,Avg.cost,LTP,Cur.val,P&L,Net chg.,Day chg.
RELIANCE,INE002A01018,EQ,10,2800,2943,29430,1430,5.10,1.20
ITC,INE154A01025,EQ,100,290,302,30240,1200,4.13,0.50
HDFCBANK,INE040A01034,EQ,15,1580,1642,24630,930,3.90,-0.20`

interface ImportResult {
  imported: number
  skipped: number
  total_parsed: number
  errors: string[]
  tier: string
}

export default function PortfolioImportPage() {
  const [broker, setBroker] = useState<Broker>("zerodha")
  const [csvText, setCsvText] = useState("")
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const router = useRouter()
  const tier = useAuthStore(s => s.tier)

  const [fileName, setFileName] = useState<string | null>(null)

  const handleLoadExample = () => {
    setCsvText(ZERODHA_EXAMPLE)
    setFileName(null)
  }

  /**
   * Convert xlsx/xls file to CSV using SheetJS (client-side).
   * Handles Zerodha's format where the data table starts at row 22
   * (rows 1-21 are metadata) by picking the largest sheet or the
   * "Equity" sheet if available.
   */
  const xlsxToCSV = async (file: File): Promise<string> => {
    const buffer = await file.arrayBuffer()
    const workbook = XLSX.read(buffer, { type: "array" })

    // Prefer "Equity" sheet (for Zerodha holdings), else "Combined", else first non-empty
    const preferred = ["Equity", "equity", "Combined", "combined", "Holdings", "holdings"]
    let sheetName: string | null = null
    for (const p of preferred) {
      if (workbook.SheetNames.includes(p)) {
        sheetName = p
        break
      }
    }
    if (!sheetName) sheetName = workbook.SheetNames[0]
    if (!sheetName) throw new Error("Excel file has no sheets")

    const worksheet = workbook.Sheets[sheetName]
    // Convert to CSV — empty cells become empty strings
    const csv = XLSX.utils.sheet_to_csv(worksheet, { blankrows: false })
    return csv
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)

    const isXlsx = /\.(xlsx|xls|xlsm)$/i.test(file.name)
    try {
      if (isXlsx) {
        // Parse xlsx → csv in the browser
        const csv = await xlsxToCSV(file)
        setCsvText(csv)
        setFileName(file.name)
      } else {
        // Plain CSV/text
        const text = await file.text()
        setCsvText(text)
        setFileName(file.name)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Could not read file"
      setError(`Failed to read ${file.name}: ${msg}`)
    }
  }

  const handleImport = async () => {
    if (!csvText.trim()) {
      setError("Paste your CSV or upload a file first")
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      // Always send as CSV text — xlsx is converted client-side
      const res = await api.post("/api/v1/portfolio/import", {
        csv_text: csvText,
        broker,
      })
      setResult(res.data)
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string }; status?: number }; message?: string }
      const status = err.response?.status
      const detail = err.response?.data?.detail || err.message || "Import failed"
      if (status === 402) {
        setError(`${detail} — Upgrade to Pro for unlimited imports.`)
      } else {
        setError(detail)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 pb-20">
      {/* Header */}
      <div className="mb-6">
        <Link href="/portfolio" className="text-xs text-gray-500 hover:text-gray-900 mb-3 inline-flex items-center gap-1">
          &larr; Back to portfolio
        </Link>
        <h1 className="text-2xl font-black text-gray-900 mb-1">Import Holdings</h1>
        <p className="text-sm text-gray-500">Upload or paste your broker CSV to bulk-add holdings.</p>
      </div>

      {/* Free tier notice */}
      {tier === "free" && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-6">
          <p className="text-xs font-bold text-amber-800 uppercase tracking-wider mb-1">Free Tier</p>
          <p className="text-sm text-amber-900">
            Free tier imports up to <b>5 holdings</b>. <Link href="/pricing" className="underline font-semibold">Upgrade to Pro</Link> for unlimited holdings.
          </p>
        </div>
      )}

      {/* Broker selection */}
      <div className="mb-5">
        <label className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2 block">1. Select Broker</label>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {BROKER_OPTIONS.map(b => (
            <button
              key={b.value}
              onClick={() => setBroker(b.value)}
              className={`text-left p-3 rounded-lg border-2 transition ${
                broker === b.value
                  ? "border-blue-500 bg-blue-50"
                  : "border-gray-200 bg-white hover:border-gray-300"
              }`}
            >
              <p className={`text-sm font-semibold ${broker === b.value ? "text-blue-700" : "text-gray-900"}`}>{b.label}</p>
            </button>
          ))}
        </div>
        <p className="text-[10px] text-gray-400 mt-2">Expected columns: {BROKER_OPTIONS.find(b => b.value === broker)?.format}</p>
      </div>

      {/* Input */}
      <div className="mb-5">
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs font-bold text-gray-500 uppercase tracking-wider">2. Upload File or Paste CSV</label>
          <div className="flex gap-3 text-xs">
            <button onClick={handleLoadExample} className="text-blue-600 hover:underline font-semibold">
              Load example
            </button>
            <label className="text-blue-600 hover:underline font-semibold cursor-pointer">
              Upload file
              <input type="file" accept=".csv,.txt,.xlsx,.xls,.xlsm" onChange={handleFileUpload} className="hidden" />
            </label>
          </div>
        </div>
        {fileName && (
          <div className="border-2 border-blue-200 bg-blue-50 rounded-lg p-3 mb-2 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p className="text-sm font-semibold text-blue-900 truncate">{fileName}</p>
              <span className="text-xs text-blue-700">&middot; Parsed to CSV ({csvText.split("\n").length} rows)</span>
            </div>
            <button
              onClick={() => { setFileName(null); setCsvText("") }}
              className="text-xs text-red-600 hover:underline font-semibold flex-shrink-0"
            >
              Remove
            </button>
          </div>
        )}
        <textarea
          value={csvText}
          onChange={e => { setCsvText(e.target.value); if (fileName) setFileName(null) }}
          placeholder="Paste CSV here, or click &ldquo;Upload file&rdquo; above (supports .csv, .xlsx)..."
          rows={10}
          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-xs font-mono bg-white resize-y"
        />
        <p className="text-[10px] text-gray-400 mt-1">Accepts: .csv, .xlsx, .xls (Excel files are auto-converted in the browser)</p>
      </div>

      {/* Import button */}
      <button
        onClick={handleImport}
        disabled={loading || !csvText.trim()}
        className="w-full py-3 bg-blue-600 text-white rounded-xl font-semibold hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed mb-4"
      >
        {loading ? "Importing..." : "Import Holdings"}
      </button>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-4">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      {/* Success */}
      {result && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-5 mb-4">
          <p className="text-sm font-bold text-green-800 mb-2">Import complete!</p>
          <ul className="text-sm text-green-900 space-y-1">
            <li>&bull; {result.imported} holdings imported</li>
            {result.skipped > 0 && <li>&bull; {result.skipped} skipped</li>}
            <li>&bull; {result.total_parsed} rows detected in CSV</li>
          </ul>
          {result.errors.length > 0 && (
            <details className="mt-3">
              <summary className="text-xs text-green-700 cursor-pointer">Show {result.errors.length} errors</summary>
              <ul className="mt-2 text-xs text-red-700 space-y-1">
                {result.errors.map((e, i) => <li key={i}>&bull; {e}</li>)}
              </ul>
            </details>
          )}
          <button
            onClick={() => router.push("/portfolio")}
            className="mt-4 w-full py-2 bg-green-600 text-white rounded-lg text-sm font-semibold hover:bg-green-700 transition"
          >
            View portfolio &rarr;
          </button>
        </div>
      )}

      {/* Help */}
      <div className="mt-8 bg-gray-50 border border-gray-200 rounded-xl p-5">
        <h3 className="text-sm font-bold text-gray-900 mb-2">How to export from Zerodha</h3>
        <ol className="text-xs text-gray-600 space-y-1 list-decimal list-inside">
          <li>Log in to <a href="https://console.zerodha.com" target="_blank" rel="noopener noreferrer" className="text-blue-600 underline">Zerodha Console</a></li>
          <li>Go to Portfolio &rarr; Holdings</li>
          <li>Click the download icon (top right) &rarr; Export CSV</li>
          <li>Open the file, copy-paste here, or upload directly</li>
        </ol>
      </div>

      <p className="text-[10px] text-gray-400 text-center mt-6">
        Your data is processed on YieldIQ servers. We never share your holdings.
      </p>
    </div>
  )
}
