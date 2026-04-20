"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

/**
 * Portfolio CSV uploader (Task C3 — client half).
 * --------------------------------------------------------------------------
 * Accepts a CSV with columns: ticker, quantity, buy_price, buy_date.
 * Parses + validates client-side, then encodes the cleaned holdings into
 * the URL ("?h=TICKER:qty:price:date|...") so the server PortfolioSummary
 * component can pick them up via searchParams and run the per-ticker
 * fair-value fetches server-side.
 *
 * No backend persistence yet — this is the lightweight tracker variant.
 */

export interface ParsedHolding {
  ticker: string
  quantity: number
  buy_price: number
  buy_date: string
}

const REQUIRED_COLS = ["ticker", "quantity", "buy_price", "buy_date"] as const

function parseCSV(text: string): { rows: ParsedHolding[]; errors: string[] } {
  const errors: string[] = []
  const rows: ParsedHolding[] = []
  const lines = text
    .split(/\r?\n/)
    .map(l => l.trim())
    .filter(Boolean)
  if (lines.length < 2) {
    errors.push("CSV must contain a header row plus at least one holding.")
    return { rows, errors }
  }
  const header = lines[0].split(",").map(h => h.trim().toLowerCase())
  const idx: Record<string, number> = {}
  for (const col of REQUIRED_COLS) {
    const i = header.indexOf(col)
    if (i === -1) {
      errors.push(`Missing required column: "${col}". Found: ${header.join(", ")}`)
    }
    idx[col] = i
  }
  if (errors.length) return { rows, errors }

  for (let lineNo = 1; lineNo < lines.length; lineNo++) {
    const cells = lines[lineNo].split(",").map(c => c.trim())
    const ticker = (cells[idx.ticker] || "").toUpperCase()
    const qty = Number(cells[idx.quantity])
    const price = Number(cells[idx.buy_price])
    const date = cells[idx.buy_date] || ""
    if (!ticker) {
      errors.push(`Row ${lineNo + 1}: empty ticker`)
      continue
    }
    if (!isFinite(qty) || qty <= 0) {
      errors.push(`Row ${lineNo + 1} (${ticker}): invalid quantity "${cells[idx.quantity]}"`)
      continue
    }
    if (!isFinite(price) || price <= 0) {
      errors.push(`Row ${lineNo + 1} (${ticker}): invalid buy_price "${cells[idx.buy_price]}"`)
      continue
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      errors.push(`Row ${lineNo + 1} (${ticker}): buy_date must be YYYY-MM-DD (got "${date}")`)
      continue
    }
    rows.push({ ticker, quantity: qty, buy_price: price, buy_date: date })
  }
  return { rows, errors }
}

function encodeHoldings(rows: ParsedHolding[]): string {
  return rows
    .map(r => `${r.ticker}:${r.quantity}:${r.buy_price}:${r.buy_date}`)
    .join("|")
}

const SAMPLE = `ticker,quantity,buy_price,buy_date
RELIANCE,10,2800,2024-01-15
ITC,100,290,2023-08-20
HDFCBANK,15,1580,2024-03-10`

export default function PortfolioUploader() {
  const router = useRouter()
  const [text, setText] = useState("")
  const [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const onFile = async (file: File) => {
    if (!file) return
    if (file.size > 1_000_000) {
      setErrors(["File too large (>1MB). Trim it down or paste rows manually."])
      return
    }
    const t = await file.text()
    setText(t)
  }

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    const { rows, errors: errs } = parseCSV(text)
    if (errs.length) {
      setErrors(errs)
      setBusy(false)
      return
    }
    if (!rows.length) {
      setErrors(["No valid holdings parsed."])
      setBusy(false)
      return
    }
    setErrors([])
    const encoded = encodeHoldings(rows)
    router.push(`/portfolio/upload?h=${encodeURIComponent(encoded)}`)
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-2xl border bg-white p-5 sm:p-6"
      style={{ borderColor: "var(--color-border, #E2E8F0)" }}
    >
      <h2 className="text-lg font-bold mb-1" style={{ color: "var(--color-ink, #0F172A)" }}>
        Upload your holdings (CSV)
      </h2>
      <p className="text-xs text-gray-500 mb-4">
        Required columns:{" "}
        <code className="font-mono text-[11px]">ticker, quantity, buy_price, buy_date</code>{" "}
        (date format: <code className="font-mono text-[11px]">YYYY-MM-DD</code>).
      </p>

      <div className="flex flex-wrap items-center gap-3 mb-3">
        <label
          className="inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm cursor-pointer hover:bg-gray-50"
          style={{ borderColor: "var(--color-border, #E2E8F0)" }}
        >
          <input
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={e => {
              const f = e.target.files?.[0]
              if (f) void onFile(f)
            }}
          />
          Choose CSV file
        </label>
        <button
          type="button"
          onClick={() => setText(SAMPLE)}
          className="text-xs text-blue-600 hover:underline"
        >
          Load sample
        </button>
      </div>

      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        rows={8}
        spellCheck={false}
        placeholder="Paste CSV here…"
        className="w-full font-mono text-xs rounded-xl border p-3"
        style={{ borderColor: "var(--color-border, #E2E8F0)" }}
      />

      {errors.length > 0 && (
        <ul
          role="alert"
          className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700 list-disc list-inside space-y-0.5"
        >
          {errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex justify-end">
        <button
          type="submit"
          disabled={busy || !text.trim()}
          className="rounded-xl px-5 py-2 text-sm font-semibold text-white transition disabled:opacity-50"
          style={{ background: "var(--color-brand, #2563EB)" }}
        >
          {busy ? "Parsing…" : "Build summary →"}
        </button>
      </div>
    </form>
  )
}
