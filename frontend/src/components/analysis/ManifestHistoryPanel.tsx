"use client"

// ManifestHistoryPanel — per-ticker "Why we changed this analysis"
// timeline. Surfaces the Day-94 cache-invalidation manifest from
// /api/v1/public/manifest-history/{ticker} so users can see, in
// plain English, every model change that has touched the ticker
// they're looking at.
//
// This is a trust signal — nobody else in Indian retail audits
// model changes in public. Latest 3 entries render expanded; older
// entries collapse behind a "Show all (N)" toggle.
//
// SEBI-safe: rationales are model-engineering descriptions, not
// investment advice. The header copy avoids advisory vocabulary.

import { useEffect, useMemo, useState } from "react"
import Cookies from "js-cookie"

// Task #123 (2026-05-23): the backend now returns one of two shapes
// from /api/v1/public/manifest-history/{ticker}:
//
//   * authed (cookie present) — { version_id, applied_at, rationale,
//     fields_affected } — the raw "engineering receipts" view.
//   * anon — { applied_at, description, fields_affected } — the
//     sanitized view (no version_id, rationale stripped of internal
//     cadence tokens like "Day-107a", "Audit#7", "PR #498").
//
// We render whichever fields are present and never assume the authed
// keys exist. Display copy normalises to `description` (anon) or
// `rationale` (authed), in that priority order.
interface ManifestEntry {
  version_id?: string
  applied_at: string | null
  rationale?: string
  description?: string
  fields_affected: string[]
}

interface ManifestHistoryResponse {
  ticker: string
  entries: ManifestEntry[]
}

const VISIBLE_DEFAULT = 3

// "26 May 2026, 5:30 AM IST" — single comma separator, uppercase AM/PM.
function fmtApplied(iso: string | null): string {
  if (!iso) return "—"
  try {
    const fmt = new Intl.DateTimeFormat("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
      timeZone: "Asia/Kolkata",
    })
    const formatted = fmt
      .format(new Date(iso))
      .replace(/\s*am\b/i, " AM")
      .replace(/\s*pm\b/i, " PM")
    return `${formatted} IST`
  } catch {
    return iso
  }
}

function FieldChip({ field }: { field: string }) {
  const label = field === "*" ? "all fields" : field
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full
                 text-[10px] font-medium tracking-wide
                 bg-surface text-caption border border-border
                 tabular-nums"
    >
      {label}
    </span>
  )
}

function TimelineCard({ entry }: { entry: ManifestEntry }) {
  // Task #123: prefer the sanitized `description` (anon shape) over
  // the raw `rationale` (authed shape). Either is rendered as the
  // headline copy; we never concatenate them.
  const copy = entry.description || entry.rationale || "Model updated."
  return (
    <li className="relative pl-6 py-3">
      {/* Dot on the rail. */}
      <span
        aria-hidden="true"
        className="absolute left-1 top-4 w-2 h-2 rounded-full bg-brand"
      />
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="text-sm text-ink leading-snug">{copy}</p>
        <span className="text-[11px] text-caption tabular-nums whitespace-nowrap">
          {fmtApplied(entry.applied_at)}
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {entry.version_id && (
          <code className="text-[10px] font-mono px-1.5 py-0.5 rounded
                           bg-surface text-caption border border-border">
            {entry.version_id}
          </code>
        )}
        {entry.fields_affected.map((f) => (
          <FieldChip key={f} field={f} />
        ))}
      </div>
    </li>
  )
}

export default function ManifestHistoryPanel({ ticker }: { ticker: string }) {
  const [data, setData] = useState<ManifestHistoryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    const symbol = (ticker || "").trim()
    if (!symbol) {
      setLoading(false)
      return
    }
    // Task #123: attach the Bearer token (same cookie the axios
    // api client uses) so authed users get the un-sanitized shape
    // with version_id + raw rationale. Anon users get the sanitized
    // shape (description without internal cadence tokens).
    const token = Cookies.get("yieldiq_token")
    const headers: Record<string, string> = token
      ? { Authorization: `Bearer ${token}` }
      : {}
    fetch(`${base}/api/v1/public/manifest-history/${symbol}`, { headers })
      .then((r) => (r.ok ? r.json() : null))
      .then((j: ManifestHistoryResponse | null) => {
        if (cancelled) return
        setData(j)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Could not load model update history")
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  const entries = data?.entries ?? []
  const visible = useMemo(
    () => (expanded ? entries : entries.slice(0, VISIBLE_DEFAULT)),
    [entries, expanded],
  )
  const hiddenCount = Math.max(0, entries.length - VISIBLE_DEFAULT)

  if (loading) {
    return (
      <section className="bg-bg dark:bg-surface rounded-2xl border border-border p-5">
        <h3 className="text-sm font-semibold text-ink mb-2">Why we changed this analysis</h3>
        <div className="text-xs text-caption">Loading model update history…</div>
      </section>
    )
  }

  if (entries.length === 0) {
    return (
      <section className="bg-bg dark:bg-surface rounded-2xl border border-border p-5">
        <h3 className="text-sm font-semibold text-ink mb-2">Why we changed this analysis</h3>
        <p className="text-xs text-caption">
          No model updates have applied to this ticker since YieldIQ launched
          {error ? ` (${error})` : "."}
        </p>
      </section>
    )
  }

  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border p-5"
      aria-label={`Model update history for ${ticker}`}
    >
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-ink">Why we changed this analysis</h3>
        <p className="text-xs text-caption mt-0.5">
          Every model change that has touched {ticker} since YieldIQ launched,
          newest first. Read-only audit log — no other Indian retail platform
          publishes this.
        </p>
      </div>

      <ol
        className="relative border-l border-border ml-1.5 divide-y divide-border"
        aria-label="Model update timeline, newest first"
      >
        {visible.map((entry) => (
          <TimelineCard key={entry.version_id} entry={entry} />
        ))}
      </ol>

      {hiddenCount > 0 && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            {expanded ? "Show fewer" : `Show all (${entries.length})`}
          </button>
        </div>
      )}
    </section>
  )
}
