"use client"

/**
 * Pro-tier "Download Excel" button — hits the backend
 * /api/v1/analysis/{ticker}/export.xlsx endpoint and streams the
 * resulting workbook to the user.
 *
 * Distinct from <ExcelExportButton/> (which builds a workbook in-browser
 * from the four public payloads). This one returns a formula-driven
 * institutional DCF model from the backend and is only visible for paid
 * tiers — free-tier users hit the upgrade CTA instead. The 402 path is
 * defensive only: we hide the button entirely when `tier === "free"`.
 */
import { useState } from "react"
import { useAuthStore } from "@/store/authStore"

interface Props {
  ticker: string
  className?: string
}

export default function ProExcelExportButton({ ticker, className }: Props) {
  const tier = useAuthStore((s) => s.tier)
  const token = useAuthStore((s) => s.token)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Free-tier (and unauthenticated) users do not see the button at all
  // per the spec. The upgrade CTA lives elsewhere on the page.
  if (tier !== "pro" && tier !== "starter" && tier !== "analyst") {
    return null
  }

  const handleClick = async () => {
    setBusy(true)
    setError(null)
    try {
      const base =
        process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
      const res = await fetch(
        `${base}/api/v1/analysis/${encodeURIComponent(ticker)}/export.xlsx`,
        {
          method: "GET",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        },
      )
      if (res.status === 402) {
        const body = await res.json().catch(() => null)
        setError(
          body?.detail?.message ||
            "Excel export requires a paid plan. Upgrade to Pro.",
        )
        return
      }
      if (!res.ok) {
        setError(`Excel export failed (${res.status}). Try again shortly.`)
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      const safe = ticker.replace(/\./g, "_")
      a.download = `YieldIQ_${safe}_DCF.xlsx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Excel export failed")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={className}>
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-xl border bg-bg dark:bg-surface px-4 py-2 text-sm font-semibold transition hover:bg-surface dark:hover:bg-bg disabled:opacity-50"
        style={{
          borderColor: "var(--color-border, #E2E8F0)",
          color: "var(--color-ink, #0F172A)",
        }}
        title="Download a formula-driven DCF workbook (Pro feature)"
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
        {busy ? "Building model…" : "Download Excel (Pro)"}
      </button>
      {error && (
        <p className="mt-2 text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
