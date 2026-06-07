"use client"

/**
 * Detailed export dropdown — Pro-tier analyst-grade exports.
 *
 * Three formats, all generated entirely in-browser:
 *   - Excel: 10-sheet workbook with formula-driven DCF model (the user can
 *            edit assumption cells and Excel recomputes downstream).
 *   - PDF:   3-page polished report (hero / detail / context).
 *   - CSV:   zip of flat CSVs (one per slice) plus a README.
 *
 * Visibility / gating
 * -------------------
 *   - Free / unauthenticated users do not see this button at all (matches
 *     ProExcelExportButton's pattern). The legacy ExcelExportButton stays
 *     in place for them at lower fidelity.
 *   - Soft email-verify gate: same pattern as ExcelExportButton. We
 *     surface a clear instruction to verify before exporting rather
 *     than silently failing.
 *   - This is intentionally a NEW button — it does not replace the
 *     existing ProExcelExportButton (which streams a backend-built
 *     formula workbook). Two independent surfaces, two independent
 *     export paths.
 */
import { useEffect, useRef, useState } from "react"
import {
  getStockSummary,
  getHistoricalFinancials,
  getRatiosHistory,
  getPublicPeers,
  getDividendHistory,
} from "@/lib/api"
import { downloadDetailedWorkbook } from "@/lib/excel-detailed"
import { downloadPDFReport } from "@/lib/pdf-report"
import { downloadCSVZip } from "@/lib/csv-zip"
import { useAuthStore } from "@/store/authStore"

interface Props {
  ticker: string
  className?: string
}

type Format = "excel" | "pdf" | "csv"

export default function DetailedExportButton({ ticker, className }: Props) {
  const tier = useAuthStore((s) => s.tier)
  const token = useAuthStore((s) => s.token)
  const emailVerified = useAuthStore((s) => s.emailVerified)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<Format | null>(null)
  const [error, setError] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement | null>(null)

  // Click-outside to close the dropdown. Declared above the gating
  // early-return so hooks always run in the same order.
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  // Free / unauthenticated users — return null so the button is invisible.
  // Mirrors the gating used in ProExcelExportButton.
  if (tier !== "pro" && tier !== "starter" && tier !== "analyst") {
    return null
  }

  const handle = async (fmt: Format) => {
    // Soft email-verify gate — even though we generate in-browser from
    // public payloads, exports are a Pro value-add. Keep parity with
    // ProExcelExportButton so abusers can't sign up and scrape.
    if (token && !emailVerified) {
      setError(
        "Verify your email before exporting — use the banner at the top of the page to resend the verification link.",
      )
      setOpen(false)
      return
    }
    setBusy(fmt)
    setError(null)
    setOpen(false)
    try {
      const [summary, annual, quarterly, ratios, peers, dividends] = await Promise.all([
        getStockSummary(ticker),
        getHistoricalFinancials(ticker, 10, "annual"),
        getHistoricalFinancials(ticker, 8, "quarterly"),
        getRatiosHistory(ticker, 10, "annual"),
        getPublicPeers(ticker, 10),
        getDividendHistory(ticker, 10),
      ])
      if (!summary) {
        setError("Stock data is currently under review — try again shortly.")
        return
      }
      const ctx = {
        ticker,
        summary,
        annualFinancials: annual,
        quarterlyFinancials: quarterly,
        ratios,
        peers,
        dividends,
      }
      if (fmt === "excel") {
        downloadDetailedWorkbook(ctx)
      } else if (fmt === "pdf") {
        downloadPDFReport({
          ticker,
          summary,
          annualFinancials: annual,
          ratios,
          peers,
        })
      } else {
        await downloadCSVZip(ctx)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed")
    } finally {
      setBusy(null)
    }
  }

  return (
    <div ref={ref} className={`relative inline-block ${className ?? ""}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={busy != null}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-2 rounded-xl border bg-bg dark:bg-surface px-4 py-2 text-sm font-semibold transition hover:bg-surface dark:hover:bg-bg disabled:opacity-50"
        style={{
          borderColor: "var(--color-border, #E2E8F0)",
          color: "var(--color-ink, #0F172A)",
        }}
        title="Detailed Pro export — Excel, PDF, or CSV bundle"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        {busy === "excel" && "Building Excel…"}
        {busy === "pdf" && "Building PDF…"}
        {busy === "csv" && "Building CSV bundle…"}
        {busy == null && "Detailed export (Pro)"}
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-2 w-56 rounded-xl border bg-bg dark:bg-surface shadow-lg"
          style={{ borderColor: "var(--color-border, #E2E8F0)" }}
        >
          <button
            role="menuitem"
            type="button"
            onClick={() => handle("excel")}
            className="block w-full px-4 py-2 text-left text-sm hover:bg-surface dark:hover:bg-bg"
          >
            Download Excel (10 sheets)
          </button>
          <button
            role="menuitem"
            type="button"
            onClick={() => handle("pdf")}
            className="block w-full px-4 py-2 text-left text-sm hover:bg-surface dark:hover:bg-bg"
          >
            Download PDF (3 pages)
          </button>
          <button
            role="menuitem"
            type="button"
            onClick={() => handle("csv")}
            className="block w-full px-4 py-2 text-left text-sm hover:bg-surface dark:hover:bg-bg"
          >
            Download CSV bundle (zip)
          </button>
        </div>
      )}
      {error && (
        <p className="mt-2 text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
