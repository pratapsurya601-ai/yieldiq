"use client"

// VersionedSnapshotsPanel — T5.6 (2026-06-10) versioned model
// snapshots, per ticker, with filters and FV diffs.
//
// The Day-108a `ManifestHistoryPanel` already shows the raw timeline.
// This panel is a search/filter UI on top of the same data: filter
// by applied-date range, by fields-affected, and on demand pull the
// FV-history row pair around each entry's applied_at so the user can
// see what changed numerically as well as in plain English.
//
// SEBI-safe: all copy describes engine changes ("rebuilt the model
// for ABC industry") rather than investment advice. The FV-diff
// caption is a model output comparison, not a price recommendation.

import { useEffect, useMemo, useState } from "react"
import Cookies from "js-cookie"
import { getFVHistory, type FVHistoryPoint } from "@/lib/api"
import { formatCurrency } from "@/lib/utils"

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

interface VersionedSnapshotsPanelProps {
  ticker: string
  currency?: string | null
}

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

// "26 May 2026" — short date, no time, used in filter chips.
function fmtDateShort(iso: string | null): string {
  if (!iso) return "—"
  try {
    return new Intl.DateTimeFormat("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      timeZone: "Asia/Kolkata",
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

// Map a manifest entry's applied_at to the nearest FV-history row
// strictly BEFORE (`prev`) and on/after (`next`) the apply timestamp.
// Returns null if either side is missing — the diff button is hidden
// in that case rather than rendering a misleading half-pair.
interface FVDiff {
  before: FVHistoryPoint
  after: FVHistoryPoint
  pctChange: number | null
}

function pairFVRows(
  appliedISO: string | null,
  history: FVHistoryPoint[],
): FVDiff | null {
  if (!appliedISO || !history || history.length < 2) return null
  const applied = Date.parse(appliedISO)
  if (!Number.isFinite(applied)) return null
  // FV history rows are unsorted from the endpoint perspective — sort
  // ascending by date so the bracketing search is deterministic.
  const sorted = [...history].sort(
    (a, b) => Date.parse(a.date) - Date.parse(b.date),
  )
  let before: FVHistoryPoint | null = null
  let after: FVHistoryPoint | null = null
  for (const row of sorted) {
    const t = Date.parse(row.date)
    if (!Number.isFinite(t)) continue
    if (t < applied) {
      before = row
    } else if (t >= applied) {
      after = row
      break
    }
  }
  if (!before || !after) return null
  const beforeFV = before.fair_value
  const afterFV = after.fair_value
  if (!Number.isFinite(beforeFV) || !Number.isFinite(afterFV) || beforeFV <= 0) {
    return { before, after, pctChange: null }
  }
  return {
    before,
    after,
    pctChange: ((afterFV - beforeFV) / beforeFV) * 100,
  }
}

function FieldChip({
  field,
  active,
  onClick,
}: {
  field: string
  active?: boolean
  onClick?: () => void
}) {
  const label = field === "*" ? "all fields" : field
  const base =
    "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] " +
    "font-medium tracking-wide tabular-nums border transition-colors"
  const tone = active
    ? "bg-brand text-white border-brand"
    : "bg-surface text-caption border-border hover:border-brand/40"
  if (!onClick) {
    return <span className={`${base} ${tone}`}>{label}</span>
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className={`${base} ${tone}`}
      aria-pressed={active ? "true" : "false"}
    >
      {label}
    </button>
  )
}

function DiffBadge({ diff, currency }: { diff: FVDiff; currency?: string | null }) {
  const { before, after, pctChange } = diff
  const arrow = pctChange == null ? "" : pctChange >= 0 ? "↑" : "↓"
  const tone =
    pctChange == null
      ? "text-caption"
      : pctChange >= 0
        ? "text-emerald-600 dark:text-emerald-400"
        : "text-rose-600 dark:text-rose-400"
  return (
    <div className="mt-2 text-[11px] text-caption tabular-nums">
      <span>
        Fair value: {formatCurrency(before.fair_value, currency)}
        {" → "}
        {formatCurrency(after.fair_value, currency)}
      </span>
      {pctChange != null && (
        <span className={`ml-2 font-medium ${tone}`}>
          {arrow} {Math.abs(pctChange).toFixed(1)}%
        </span>
      )}
      <span className="ml-2 text-caption/70">
        ({fmtDateShort(before.date)} → {fmtDateShort(after.date)})
      </span>
    </div>
  )
}

function EntryCard({
  entry,
  fvHistory,
  currency,
}: {
  entry: ManifestEntry
  fvHistory: FVHistoryPoint[]
  currency?: string | null
}) {
  const [open, setOpen] = useState(false)
  const [showDiff, setShowDiff] = useState(false)
  const copy = entry.description || entry.rationale || "Model updated."
  // Heuristic: anything > 140 chars gets the "expand" affordance so
  // long engineering rationales don't dominate the panel height.
  const isLong = copy.length > 140
  const shortCopy = isLong && !open ? `${copy.slice(0, 140).trim()}…` : copy
  const diff = useMemo(
    () => pairFVRows(entry.applied_at, fvHistory),
    [entry.applied_at, fvHistory],
  )
  return (
    <li
      className="relative pl-6 py-3 group"
      data-testid="versioned-snapshot-entry"
    >
      <span
        aria-hidden="true"
        className="absolute left-1 top-4 w-2 h-2 rounded-full bg-brand"
      />
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p
          className="text-sm text-ink leading-snug"
          title={isLong ? copy : undefined}
        >
          {shortCopy}
          {isLong && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="ml-2 text-[11px] font-medium text-blue-600 hover:underline dark:text-blue-400"
            >
              {open ? "less" : "more"}
            </button>
          )}
        </p>
        <span className="text-[11px] text-caption tabular-nums whitespace-nowrap">
          {fmtApplied(entry.applied_at)}
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {entry.version_id && (
          <code className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface text-caption border border-border">
            {entry.version_id}
          </code>
        )}
        {entry.fields_affected.map((f) => (
          <FieldChip key={f} field={f} />
        ))}
        {diff && (
          <button
            type="button"
            onClick={() => setShowDiff((v) => !v)}
            className="text-[10px] font-medium px-1.5 py-0.5 rounded border border-border text-caption hover:border-brand/40 hover:text-ink"
            aria-pressed={showDiff ? "true" : "false"}
          >
            {showDiff ? "Hide diff" : "Diff"}
          </button>
        )}
      </div>
      {showDiff && diff && <DiffBadge diff={diff} currency={currency} />}
    </li>
  )
}

// Build the set of unique field labels present across entries so the
// filter UI doesn't need a hardcoded list — the manifest evolves.
function collectFieldOptions(entries: ManifestEntry[]): string[] {
  const seen = new Set<string>()
  for (const e of entries) {
    for (const f of e.fields_affected || []) seen.add(f)
  }
  return Array.from(seen).sort((a, b) => {
    if (a === "*") return -1
    if (b === "*") return 1
    return a.localeCompare(b)
  })
}

export default function VersionedSnapshotsPanel({
  ticker,
  currency,
}: VersionedSnapshotsPanelProps) {
  const [data, setData] = useState<ManifestHistoryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fvHistory, setFvHistory] = useState<FVHistoryPoint[]>([])
  // Filter state. Empty string means "no constraint".
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")
  const [fieldFilter, setFieldFilter] = useState<string | null>(null)

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

  // FV-history fetch is best-effort: a 403 (free-tier gate) or 404
  // simply leaves the diff buttons unrendered. The panel still works.
  useEffect(() => {
    let cancelled = false
    const symbol = (ticker || "").trim()
    if (!symbol) return
    getFVHistory(symbol, 3)
      .then((resp) => {
        if (cancelled) return
        if (resp && Array.isArray(resp.data)) setFvHistory(resp.data)
      })
      .catch(() => {
        // Swallow — the panel works without diffs.
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  const entries = data?.entries ?? []
  const fieldOptions = useMemo(() => collectFieldOptions(entries), [entries])

  const filtered = useMemo(() => {
    let out = entries
    if (dateFrom) {
      const t = Date.parse(dateFrom)
      if (Number.isFinite(t)) {
        out = out.filter((e) => {
          const x = e.applied_at ? Date.parse(e.applied_at) : NaN
          return Number.isFinite(x) && x >= t
        })
      }
    }
    if (dateTo) {
      // Inclusive end-of-day for the dateTo filter so a user picking
      // "10 June 2026" sees entries from that day.
      const t = Date.parse(dateTo) + 24 * 60 * 60 * 1000 - 1
      if (Number.isFinite(t)) {
        out = out.filter((e) => {
          const x = e.applied_at ? Date.parse(e.applied_at) : NaN
          return Number.isFinite(x) && x <= t
        })
      }
    }
    if (fieldFilter) {
      out = out.filter((e) =>
        (e.fields_affected || []).includes(fieldFilter),
      )
    }
    return out
  }, [entries, dateFrom, dateTo, fieldFilter])

  const clearFilters = () => {
    setDateFrom("")
    setDateTo("")
    setFieldFilter(null)
  }
  const hasFilters = Boolean(dateFrom || dateTo || fieldFilter)

  if (loading) {
    return (
      <section
        className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
        data-testid="versioned-snapshots-panel"
      >
        <h3 className="text-sm font-semibold text-ink mb-2">
          Versioned snapshots
        </h3>
        <div className="text-xs text-caption">Loading model update history…</div>
      </section>
    )
  }

  if (entries.length === 0) {
    return (
      <section
        className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
        data-testid="versioned-snapshots-panel"
      >
        <h3 className="text-sm font-semibold text-ink mb-2">
          Versioned snapshots
        </h3>
        <p className="text-xs text-caption">
          No model updates have applied to this ticker since YieldIQ launched
          {error ? ` (${error})` : "."}
        </p>
      </section>
    )
  }

  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
      aria-label={`Versioned snapshots for ${ticker}`}
      data-testid="versioned-snapshots-panel"
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-ink">Versioned snapshots</h3>
          <p className="text-xs text-caption mt-0.5">
            Search the model-change log for {ticker}. Filter by date or by the
            field a change touched.
          </p>
        </div>
        <span className="text-[11px] text-caption tabular-nums">
          {filtered.length} of {entries.length}
        </span>
      </div>

      {/* Filter row. Date inputs use native `<input type="date">` —
          mobile clients get the platform picker; desktop gets a
          calendar dropdown. Field filter is a single-select chip
          strip; multi-select adds UX complexity without payoff for
          a typical 5-20 entry panel. */}
      <div className="mb-4 flex flex-col gap-3" data-testid="versioned-snapshots-filters">
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-caption">
          <label className="flex items-center gap-1">
            <span>From</span>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="rounded border border-border bg-bg dark:bg-surface px-2 py-0.5 text-[11px] text-ink tabular-nums"
              aria-label="Filter from date"
            />
          </label>
          <label className="flex items-center gap-1">
            <span>To</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="rounded border border-border bg-bg dark:bg-surface px-2 py-0.5 text-[11px] text-ink tabular-nums"
              aria-label="Filter to date"
            />
          </label>
          {hasFilters && (
            <button
              type="button"
              onClick={clearFilters}
              className="ml-1 text-[11px] font-medium text-blue-600 hover:underline dark:text-blue-400"
            >
              Clear
            </button>
          )}
        </div>
        {fieldOptions.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-caption mr-1">Field:</span>
            {fieldOptions.map((f) => (
              <FieldChip
                key={f}
                field={f}
                active={fieldFilter === f}
                onClick={() =>
                  setFieldFilter((cur) => (cur === f ? null : f))
                }
              />
            ))}
          </div>
        )}
      </div>

      {filtered.length === 0 ? (
        <p className="text-xs text-caption py-4">
          No entries match the current filters.
        </p>
      ) : (
        <ol
          className="relative border-l border-border ml-1.5 divide-y divide-border"
          aria-label="Versioned snapshots timeline, newest first"
        >
          {filtered.map((entry, i) => (
            <EntryCard
              key={entry.version_id || `${entry.applied_at}-${i}`}
              entry={entry}
              fvHistory={fvHistory}
              currency={currency}
            />
          ))}
        </ol>
      )}
    </section>
  )
}
