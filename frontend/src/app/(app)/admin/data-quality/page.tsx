"use client"

// Phase A.2.2 (2026-05-23) — Data-quality validator admin dashboard.
//
// Reads GET /api/v1/admin/data-quality/runs (admin-gated; see
// backend/routers/admin_data_quality.py). One row per (table, populator)
// with the most recent overall_status. Click a row to expand its
// CheckResult list.
//
// The page is intentionally dense — operators triage from here, so the
// signal-to-noise must be high. Red rows float up via sort order; the
// "Recent failures" panel at the bottom catches anything that landed
// red in the bounded history but has since recovered.

import { useEffect, useMemo, useState } from "react"
import { useAuthStore } from "@/store/authStore"
import { useRouter } from "next/navigation"
import api from "@/lib/api"

const ADMIN_EMAILS = ["pratapsurya601@gmail.com", "suryasbss601@gmail.com"]

type OverallStatus = "green" | "yellow" | "red"
type CheckStatus = "pass" | "warn" | "fail"

interface CheckResult {
  name: string
  status: CheckStatus
  details: string
  threshold?: Record<string, unknown>
}

interface ChecksBundle {
  table?: string
  populator?: string
  last_run_at?: string | null
  checks?: CheckResult[]
  overall_status?: OverallStatus
}

interface LatestRow {
  table: string
  populator: string
  overall_status: OverallStatus
  run_at: string | null
  // The backend returns the full HealthCheckResult JSONB here.
  checks: ChecksBundle | CheckResult[]
}

interface HistoryRow {
  table: string
  populator: string
  overall_status: OverallStatus
  run_at: string | null
}

interface Summary {
  green: number
  yellow: number
  red: number
  total_tables: number
}

interface RunsResponse {
  latest_per_table: LatestRow[]
  history: HistoryRow[]
  summary: Summary
  cached: boolean
  cache_age_seconds: number
}

const STATUS_ORDER: Record<OverallStatus, number> = { red: 0, yellow: 1, green: 2 }

function StatusPill({ status }: { status: OverallStatus | CheckStatus }) {
  const palette: Record<string, string> = {
    green: "bg-green-100 text-green-800 border-green-200",
    pass: "bg-green-100 text-green-800 border-green-200",
    yellow: "bg-amber-100 text-amber-900 border-amber-200",
    warn: "bg-amber-100 text-amber-900 border-amber-200",
    red: "bg-red-100 text-red-800 border-red-200",
    fail: "bg-red-100 text-red-800 border-red-200",
  }
  const cls = palette[status] || "bg-gray-100 text-gray-700 border-gray-200"
  return (
    <span
      data-testid={`status-pill-${status}`}
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${cls}`}
    >
      {status.toUpperCase()}
    </span>
  )
}

function OverallBadge({ summary }: { summary: Summary }) {
  let status: OverallStatus = "green"
  if (summary.red > 0) status = "red"
  else if (summary.yellow > 0) status = "yellow"
  const label =
    status === "green"
      ? "All systems green"
      : status === "yellow"
      ? `${summary.yellow} table(s) yellow`
      : `${summary.red} table(s) red`
  return (
    <div
      data-testid="overall-badge"
      className="flex items-center gap-3 rounded-2xl border border-gray-100 bg-bg dark:bg-surface p-4"
    >
      <StatusPill status={status} />
      <div>
        <p className="text-sm font-semibold text-ink">{label}</p>
        <p className="text-xs text-caption">
          {summary.total_tables} table(s) tracked — green {summary.green} / yellow {summary.yellow} / red {summary.red}
        </p>
      </div>
    </div>
  )
}

function extractChecks(raw: LatestRow["checks"]): CheckResult[] {
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (raw.checks && Array.isArray(raw.checks)) return raw.checks
  return []
}

function TableRow({ row }: { row: LatestRow }) {
  const [open, setOpen] = useState(false)
  const checks = extractChecks(row.checks)
  const counts = checks.reduce(
    (acc, c) => {
      acc[c.status] = (acc[c.status] || 0) + 1
      return acc
    },
    { pass: 0, warn: 0, fail: 0 } as Record<CheckStatus, number>,
  )
  return (
    <div
      data-testid={`table-row-${row.table}`}
      className="rounded-xl border border-gray-100 bg-bg dark:bg-surface"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 p-4 text-left hover:bg-gray-50"
      >
        <div className="flex items-center gap-3 min-w-0">
          <StatusPill status={row.overall_status} />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink truncate">{row.table}</p>
            <p className="text-xs text-caption truncate">{row.populator}</p>
          </div>
        </div>
        <div className="flex items-center gap-4 shrink-0">
          <p className="text-xs text-caption">
            <span className="text-green-700">{counts.pass} pass</span>
            {" / "}
            <span className="text-amber-800">{counts.warn} warn</span>
            {" / "}
            <span className="text-red-700">{counts.fail} fail</span>
          </p>
          <p className="text-xs text-caption hidden md:block">
            {row.run_at ? new Date(row.run_at).toLocaleString() : "—"}
          </p>
          <span className="text-caption text-xs">{open ? "▾" : "▸"}</span>
        </div>
      </button>
      {open && (
        <div
          data-testid={`table-row-detail-${row.table}`}
          className="border-t border-gray-100 p-4 space-y-3"
        >
          {checks.length === 0 && (
            <p className="text-xs text-caption">No checks recorded.</p>
          )}
          {checks.map((c) => (
            <div key={c.name} className="flex items-start gap-3">
              <StatusPill status={c.status} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-ink break-words">{c.name}</p>
                <p className="text-xs text-caption break-words">{c.details}</p>
                {c.threshold && Object.keys(c.threshold).length > 0 && (
                  <details className="mt-1">
                    <summary className="text-[11px] text-caption cursor-pointer">
                      threshold
                    </summary>
                    <pre className="text-[11px] text-caption bg-gray-50 dark:bg-gray-900 p-2 rounded mt-1 overflow-x-auto">
                      {JSON.stringify(c.threshold, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            </div>
          ))}
          <p className="text-[11px] text-caption pt-2 border-t border-gray-100">
            See{" "}
            <a
              href="/docs/runbooks/data-quality-validation.md"
              className="underline text-blue-700"
            >
              data-quality-validation.md
            </a>{" "}
            for runbook guidance per check.
          </p>
        </div>
      )}
    </div>
  )
}

function RecentFailuresPanel({ rows }: { rows: LatestRow[] }) {
  const failed = useMemo(() => {
    const out: { row: LatestRow; check: CheckResult }[] = []
    for (const r of rows) {
      const checks = extractChecks(r.checks)
      for (const c of checks) {
        if (c.status === "fail") out.push({ row: r, check: c })
      }
    }
    return out.slice(0, 5)
  }, [rows])
  if (failed.length === 0) {
    return (
      <div
        data-testid="recent-failures"
        className="rounded-2xl border border-gray-100 p-4 bg-bg dark:bg-surface"
      >
        <h2 className="text-sm font-semibold text-ink mb-1">Recent failures</h2>
        <p className="text-xs text-caption">No failing checks in the current snapshot.</p>
      </div>
    )
  }
  return (
    <div
      data-testid="recent-failures"
      className="rounded-2xl border border-red-100 bg-red-50/40 p-4"
    >
      <h2 className="text-sm font-semibold text-ink mb-3">Recent failures (latest snapshot)</h2>
      <ul className="space-y-2">
        {failed.map(({ row, check }) => (
          <li
            key={`${row.table}-${check.name}`}
            className="rounded-xl bg-bg dark:bg-surface border border-red-100 p-3 text-xs"
          >
            <div className="flex items-center gap-2 mb-1">
              <StatusPill status="fail" />
              <span className="font-semibold text-ink">{row.table}</span>
              <span className="text-caption">/ {check.name}</span>
            </div>
            <p className="text-caption break-words">{check.details}</p>
            <a
              href={`/docs/runbooks/data-quality-validation.md#${check.name.replace(/\./g, "-")}`}
              className="text-[11px] underline text-blue-700"
            >
              Runbook section for {check.name}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function AdminDataQualityPage() {
  const { email } = useAuthStore()
  const router = useRouter()
  const [data, setData] = useState<RunsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const [hydrated, setHydrated] = useState(false)
  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setHydrated(true)
      return
    }
    const unsub = useAuthStore.persist.onFinishHydration(() => setHydrated(true))
    return unsub
  }, [])

  useEffect(() => {
    if (!hydrated) return
    if (!email || !ADMIN_EMAILS.includes(email)) {
      router.push("/home")
      return
    }
    api
      .get("/api/v1/admin/data-quality/runs")
      .then((r) => setData(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load data quality runs"))
      .finally(() => setLoading(false))
  }, [hydrated, email, router])

  if (!hydrated) return null
  if (!email || !ADMIN_EMAILS.includes(email)) return null

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center">
        <p className="text-lg font-medium text-red-600">{error}</p>
      </div>
    )
  }

  if (!data) return null

  const sortedRows = [...data.latest_per_table].sort((a, b) => {
    const s = STATUS_ORDER[a.overall_status] - STATUS_ORDER[b.overall_status]
    return s !== 0 ? s : a.table.localeCompare(b.table)
  })

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6 pb-20">
      <div>
        <h1 className="text-xl font-bold text-ink">Data quality</h1>
        <p className="text-sm text-caption">
          Validator runs per table — green / yellow / red at a glance.
          {data.cached && (
            <span className="ml-2 text-[11px]">
              (cached {data.cache_age_seconds}s)
            </span>
          )}
        </p>
      </div>

      <OverallBadge summary={data.summary} />

      <div data-testid="tables-grid" className="space-y-2">
        {sortedRows.length === 0 && (
          <p className="text-sm text-caption">
            No validator runs yet — the cron has not landed or the table is empty.
          </p>
        )}
        {sortedRows.map((row) => (
          <TableRow key={`${row.table}-${row.populator}`} row={row} />
        ))}
      </div>

      <RecentFailuresPanel rows={data.latest_per_table} />

      {data.history.length > 0 && (
        <div className="rounded-2xl border border-gray-100 bg-bg dark:bg-surface p-4">
          <h2 className="text-sm font-semibold text-ink mb-3">Last 7 days</h2>
          <div className="space-y-1 text-xs">
            {data.history.slice(0, 20).map((h, idx) => (
              <div
                key={`${h.table}-${h.run_at}-${idx}`}
                className="flex items-center justify-between gap-2"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <StatusPill status={h.overall_status} />
                  <span className="text-ink font-medium truncate">{h.table}</span>
                </div>
                <span className="text-caption shrink-0">
                  {h.run_at ? new Date(h.run_at).toLocaleString() : "—"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
