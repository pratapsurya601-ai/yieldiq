"use client"
import { useEffect, useState, useCallback, useMemo } from "react"
import { useAuthStore } from "@/store/authStore"
import { useRouter } from "next/navigation"
import api from "@/lib/api"
import type {
  BenchmarkOutlier,
  BenchmarkOutliersResponse,
} from "@/types/admin"

// Same allow-list as /admin/realty and /admin/insurance. We deliberately
// duplicate rather than import to keep each admin page self-contained —
// the server's require_admin is the real gate; this is just UX.
const ADMIN_EMAILS = ["pratapsurya601@gmail.com", "suryasbss601@gmail.com"]

type DirectionFilter = "both" | "under" | "over"
type SortDir = "asc" | "desc"

const LIMIT_OPTIONS = [20, 50, 100] as const

/**
 * Severity bucket for a single delta_pct. delta_pct is a *fraction*
 * coming out of the backend (e.g. 0.33 = 33%), matching the OutlierRow
 * contract in backend/services/benchmark_reconciliation_service.py.
 */
function severityBucket(deltaPct: number): "high" | "med" | "low" {
  const abs = Math.abs(deltaPct)
  if (abs > 0.5) return "high"
  if (abs >= 0.3) return "med"
  return "low"
}

function rowClass(deltaPct: number): string {
  const b = severityBucket(deltaPct)
  if (b === "high") return "bg-red-50 hover:bg-red-100"
  if (b === "med") return "bg-amber-50 hover:bg-amber-100"
  return "hover:bg-gray-50"
}

function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—"
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function fmtPct(frac: number): string {
  if (!Number.isFinite(frac)) return "—"
  const pct = frac * 100
  const sign = pct > 0 ? "+" : ""
  return `${sign}${pct.toFixed(1)}%`
}

function fmtTs(iso: string): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toISOString().slice(0, 16).replace("T", " ") + "Z"
}

export default function BenchmarkOutliersAdminPage() {
  const { email } = useAuthStore()
  const router = useRouter()

  const [rows, setRows] = useState<BenchmarkOutlier[]>([])
  const [meta, setMeta] = useState<Omit<
    BenchmarkOutliersResponse,
    "rows"
  > | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  // Server-side filters
  const [limit, setLimit] = useState<number>(20)
  const [direction, setDirection] = useState<DirectionFilter>("both")

  // Client-side sort (only delta_pct is sortable per spec)
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const refresh = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const r = await api.get<BenchmarkOutliersResponse>(
        `/api/v1/admin/benchmark-outliers?limit=${limit}&direction=${direction}`,
      )
      const { rows: newRows, ...rest } = r.data
      setRows(newRows || [])
      setMeta(rest)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err?.response?.data?.detail || "Failed to load outliers")
    } finally {
      setLoading(false)
    }
  }, [limit, direction])

  // Wait for Zustand persist hydration before checking admin status.
  // See hotfix #360 / the same guard in /admin/realty: without this,
  // the first render sees email=null (pre-localStorage rehydrate) and
  // redirects valid admins to /home.
  const [hydrated, setHydrated] = useState(false)
  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setHydrated(true)
      return
    }
    const unsub = useAuthStore.persist.onFinishHydration(() =>
      setHydrated(true),
    )
    return unsub
  }, [])

  useEffect(() => {
    if (!hydrated) return
    if (!email || !ADMIN_EMAILS.includes(email)) {
      router.push("/home")
      return
    }
    refresh()
  }, [hydrated, email, router, refresh])

  // Sort by |delta_pct|. Backend already sorts desc; we still sort
  // client-side so the toggle works after server returns.
  const sortedRows = useMemo(() => {
    const copy = [...rows]
    copy.sort((a, b) => {
      const diff = Math.abs(a.delta_pct) - Math.abs(b.delta_pct)
      return sortDir === "desc" ? -diff : diff
    })
    return copy
  }, [rows, sortDir])

  if (!hydrated) return null
  if (!email || !ADMIN_EMAILS.includes(email)) return null

  return (
    <div
      className="max-w-6xl mx-auto px-4 py-8 space-y-6 pb-20"
      data-testid="admin-outliers-page"
    >
      <div>
        <h1 className="text-xl font-bold text-gray-900">
          Benchmark reconciliation outliers
        </h1>
        <p className="text-sm text-gray-500">
          Tickers whose model fair-value diverges from analyst consensus by
          more than the configured threshold. Layer A safety net —{" "}
          <code className="text-xs">
            docs/design/benchmark-reconciliation-framework.md §6.1
          </code>
          . Reconciliation runs daily at 10am IST.
        </p>
        {meta && (
          <p className="text-xs text-gray-400 mt-2">
            Generated {fmtTs(meta.generated_at)} · threshold{" "}
            {(meta.threshold_pct * 100).toFixed(0)}% · min analysts{" "}
            {meta.min_analysts} · {meta.count} row(s)
          </p>
        )}
      </div>

      {error && (
        <div
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          data-testid="admin-outliers-error"
        >
          {error}
        </div>
      )}

      {/* Controls */}
      <div className="bg-white rounded-2xl border border-gray-100 p-4 flex flex-wrap items-center gap-4">
        <div
          className="inline-flex rounded-lg border border-gray-200 overflow-hidden"
          role="group"
          aria-label="Direction filter"
          data-testid="direction-filter"
        >
          {(
            [
              { v: "both", label: "All" },
              { v: "under", label: "Under (we say low)" },
              { v: "over", label: "Over (we say high)" },
            ] as { v: DirectionFilter; label: string }[]
          ).map((opt) => (
            <button
              key={opt.v}
              type="button"
              onClick={() => setDirection(opt.v)}
              data-testid={`direction-chip-${opt.v}`}
              className={`px-3 py-1.5 text-xs font-medium ${
                direction === opt.v
                  ? "bg-blue-600 text-white"
                  : "bg-white text-gray-700 hover:bg-gray-50"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <label className="flex items-center gap-2 text-xs text-gray-700">
          <span>Limit</span>
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            data-testid="limit-select"
            className="rounded-lg border border-gray-200 px-2 py-1 text-xs"
          >
            {LIMIT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          data-testid="reload-button"
          className="ml-auto rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
        >
          {loading ? "Loading…" : "Reload"}
        </button>
      </div>

      {/* Table */}
      <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
        {loading ? (
          <div
            className="p-8 text-center text-sm text-gray-500"
            data-testid="admin-outliers-loading"
          >
            Loading…
          </div>
        ) : sortedRows.length === 0 ? (
          <div
            className="p-8 text-center text-sm text-gray-500"
            data-testid="admin-outliers-empty"
          >
            No outliers found — reconciliation may not have run yet
            (10am IST daily).
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table
              className="w-full text-sm"
              data-testid="admin-outliers-table"
            >
              <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-600">
                <tr>
                  <th className="px-4 py-2 text-left">Ticker</th>
                  <th className="px-4 py-2 text-right">Our FV</th>
                  <th className="px-4 py-2 text-right">Consensus</th>
                  <th className="px-4 py-2 text-right">
                    <button
                      type="button"
                      onClick={() =>
                        setSortDir(sortDir === "desc" ? "asc" : "desc")
                      }
                      data-testid="sort-delta"
                      className="inline-flex items-center gap-1 hover:text-gray-900"
                    >
                      Delta %{" "}
                      <span aria-hidden="true">
                        {sortDir === "desc" ? "▼" : "▲"}
                      </span>
                    </button>
                  </th>
                  <th className="px-4 py-2 text-left">Direction</th>
                  <th className="px-4 py-2 text-right">Analysts</th>
                  <th className="px-4 py-2 text-left">Source</th>
                  <th className="px-4 py-2 text-left">Last refreshed</th>
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((row) => {
                  const sev = severityBucket(row.delta_pct)
                  return (
                    <tr
                      key={row.ticker}
                      data-testid={`outlier-row-${row.ticker}`}
                      data-severity={sev}
                      className={`border-t border-gray-100 ${rowClass(
                        row.delta_pct,
                      )}`}
                    >
                      <td className="px-4 py-2 font-medium">{row.ticker}</td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {fmtNum(row.our_fv)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {fmtNum(row.consensus_fv)}
                      </td>
                      <td
                        className={`px-4 py-2 text-right tabular-nums font-medium ${
                          row.delta_pct < 0
                            ? "text-red-700"
                            : "text-emerald-700"
                        }`}
                      >
                        {fmtPct(row.delta_pct)}
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                            row.direction === "under"
                              ? "bg-red-100 text-red-800"
                              : "bg-amber-100 text-amber-800"
                          }`}
                        >
                          {row.direction}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {row.analyst_count}
                      </td>
                      <td className="px-4 py-2 text-xs text-gray-600">
                        {row.source}
                      </td>
                      <td className="px-4 py-2 text-xs text-gray-600">
                        {fmtTs(row.fetched_at)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
