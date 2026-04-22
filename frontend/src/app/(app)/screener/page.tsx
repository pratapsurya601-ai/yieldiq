"use client"

// Visual filter builder for the `/api/v1/public/screener` DSL endpoint.
// Everything shareable lives in the URL — the query string is the source
// of truth, and internal state mirrors it. That keeps bookmark/share URLs
// and "back" navigation cheap.

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import api from "@/lib/api"
import { cn } from "@/lib/utils"
import FilterBuilder from "@/components/screener/FilterBuilder"
import ResultsTable from "@/components/screener/ResultsTable"
import SavedQueries from "@/components/screener/SavedQueries"
import {
  SCREENER_PRESETS,
  buildShareUrl,
  loadSavedQueries,
  newClause,
  parseFilters,
  saveSavedQueries,
  serializeFilters,
  type FilterClause,
  type SavedQuery,
  type ScreenerFieldsResponse,
  type ScreenerQueryResponse,
} from "@/lib/screenerFilters"

const DEFAULT_LIMIT = 50

// Axios wraps FastAPI's `{detail: "..."}` body under error.response.data.detail.
// The default Error.message for axios is "Request failed with status code 4xx",
// which tells the user nothing. This helper walks the axios shape first and
// falls back to Error.message — critical for the P0-#1 fix: a screener 400/500
// must render a distinct actionable message, NOT the "No stocks match" empty
// state, so users don't falsely conclude the universe is empty.
function extractScreenerError(err: unknown): string {
  if (err && typeof err === "object") {
    const anyErr = err as {
      response?: { status?: number; data?: { detail?: unknown } }
      message?: string
    }
    const detail = anyErr.response?.data?.detail
    if (typeof detail === "string" && detail) return detail
    const status = anyErr.response?.status
    if (status && anyErr.message) return `${anyErr.message} (HTTP ${status})`
    if (anyErr.message) return anyErr.message
  }
  return "Check that every filter has a field and value."
}

function ScreenerInner() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  // Initial state from URL. We intentionally only read URL params once on
  // mount — subsequent URL updates are write-only (from our own actions).
  // Two-way sync is a trap here: every keystroke in the value input would
  // otherwise rewrite the URL.
  const [clauses, setClauses] = useState<FilterClause[]>(() =>
    parseFilters(searchParams.get("filters"))
  )
  const [sort, setSort] = useState<string>(() => searchParams.get("sort") || "")
  const [limit, setLimit] = useState<number>(() => {
    const n = Number(searchParams.get("limit"))
    return Number.isFinite(n) && n > 0 ? n : DEFAULT_LIMIT
  })
  const [hasRun, setHasRun] = useState<boolean>(() => !!searchParams.get("filters"))
  const [savedToken, setSavedToken] = useState(0)

  // Fields metadata. Safe to cache aggressively — the server publishes a
  // fixed schema that only changes on deploys.
  const { data: fieldsData } = useQuery<ScreenerFieldsResponse>({
    queryKey: ["screener-fields"],
    queryFn: async () => {
      const res = await api.get("/api/v1/public/screener/fields")
      return res.data
    },
    staleTime: 60 * 60 * 1000,
  })

  const fields = fieldsData?.fields ?? []
  const sortableFields = fieldsData?.sortable ?? fields.map((f) => f.key)

  // Serialized params drive the query key so refetches only happen when
  // the user hits "Run" (which calls triggerRun, which pushes to the URL).
  const filterString = serializeFilters(clauses)

  const queryKey = useMemo(
    () => ["screener-query", filterString, sort, limit, hasRun] as const,
    [filterString, sort, limit, hasRun]
  )

  const { data, isFetching, error } = useQuery<ScreenerQueryResponse>({
    queryKey,
    queryFn: async () => {
      const params = new URLSearchParams()
      if (filterString) params.set("filters", filterString)
      if (sort) params.set("sort", sort)
      if (limit) params.set("limit", String(limit))
      const res = await api.get(`/api/v1/public/screener/query?${params.toString()}`)
      return res.data
    },
    enabled: hasRun,
    staleTime: 30 * 1000,
  })

  // Push current state to the URL. Used both by Run and by preset/save-load.
  const pushUrl = useCallback(
    (nextClauses: FilterClause[], nextSort: string, nextLimit: number) => {
      const url = buildShareUrl(pathname, nextClauses, nextSort, nextLimit)
      router.replace(url, { scroll: false })
    },
    [pathname, router]
  )

  const triggerRun = useCallback(() => {
    setHasRun(true)
    pushUrl(clauses, sort, limit)
  }, [clauses, sort, limit, pushUrl])

  const applyPreset = useCallback(
    (presetKey: string) => {
      const preset = SCREENER_PRESETS.find((p) => p.key === presetKey)
      if (!preset) return
      const nextClauses = preset.filters.map((f) => newClause(f.field, f.op, f.value))
      const nextSort = preset.sort ?? ""
      setClauses(nextClauses)
      setSort(nextSort)
      setLimit(DEFAULT_LIMIT)
      setHasRun(true)
      pushUrl(nextClauses, nextSort, DEFAULT_LIMIT)
    },
    [pushUrl]
  )

  const handleSave = useCallback(() => {
    if (clauses.length === 0) return
    const name = window.prompt("Name this query", `Screener ${new Date().toLocaleDateString()}`)
    if (!name) return
    const entry: SavedQuery = {
      id: `sq-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      name,
      filters: clauses,
      sort,
      limit,
      createdAt: Date.now(),
    }
    const existing = loadSavedQueries()
    saveSavedQueries([entry, ...existing])
    setSavedToken((t) => t + 1)
  }, [clauses, sort, limit])

  const handleLoadSaved = useCallback(
    (q: SavedQuery) => {
      // Clone filters so future edits don't mutate the saved copy.
      const next = q.filters.map((f) => ({ ...f, id: `${f.id}-loaded-${Date.now()}` }))
      setClauses(next)
      setSort(q.sort)
      setLimit(q.limit || DEFAULT_LIMIT)
      setHasRun(true)
      pushUrl(next, q.sort, q.limit || DEFAULT_LIMIT)
    },
    [pushUrl]
  )

  // If the user lands with no filters and no saved run, show the empty
  // state. Once they've interacted (added a clause or run), we hide it.
  const showEmptyState = clauses.length === 0 && !hasRun

  // Surface API errors (rate limits, 4xx on malformed DSL, network) inline.
  useEffect(() => {
    if (error) {
      // no-op: rendered below; intentionally not toasting to keep deps narrow.
    }
  }, [error])

  return (
    <div className="max-w-2xl md:max-w-4xl lg:max-w-6xl mx-auto px-4 py-6 pb-20 space-y-5">
      <header>
        <h1 className="text-xl font-bold text-ink">Screener</h1>
        <p className="text-sm text-caption mt-1">
          Build a filter, run it against the full universe, save what works.
        </p>
        {/* SEBI-safe inline disclaimer. Global TrustFooter covers this
            too, but screened lists can easily be misread as stock
            picks, so we surface a direct reminder on this specific
            page. Don't remove without also updating the global footer. */}
        <p className="text-[11px] text-caption mt-2 leading-relaxed">
          Screener results are filter outputs from publicly available data &mdash;
          not stock picks or investment advice. YieldIQ is not registered with
          SEBI as an investment adviser. Form your own view.
        </p>
      </header>

      {showEmptyState ? (
        <div className="rounded-2xl border border-border bg-white p-6">
          <h2 className="text-sm font-semibold text-ink mb-3">Start with a preset</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {SCREENER_PRESETS.map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => applyPreset(p.key)}
                className={cn(
                  "text-left rounded-xl border border-border bg-bg p-4",
                  "hover:border-blue-300 hover:bg-blue-50/40 transition-colors"
                )}
              >
                <div className="text-sm font-semibold text-ink">{p.label}</div>
                <div className="text-xs text-caption mt-1">{p.description}</div>
              </button>
            ))}
          </div>
          <div className="mt-4 flex items-center gap-2">
            <span className="text-xs text-caption">or</span>
            <button
              type="button"
              onClick={() => setClauses([newClause()])}
              className="text-xs font-medium text-blue-600 hover:text-blue-700"
            >
              build from scratch
            </button>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_18rem] gap-5">
          <div className="space-y-4 min-w-0">
            <FilterBuilder
              clauses={clauses}
              fields={fields}
              sort={sort}
              limit={limit}
              sortableFields={sortableFields}
              onClausesChange={setClauses}
              onSortChange={setSort}
              onLimitChange={setLimit}
              onRun={triggerRun}
              onSave={handleSave}
              isRunning={isFetching}
              canSave={clauses.length > 0}
            />

            {error && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <p className="text-sm font-medium text-amber-800">
                  Screener failed &mdash; try different filters
                </p>
                <p className="text-xs text-amber-700 mt-1">
                  {extractScreenerError(error)}
                </p>
              </div>
            )}

            {hasRun && !error && (
              <ResultsTable
                rows={data?.results ?? []}
                total={data?.total ?? 0}
                isLoading={isFetching}
                pageSize={limit}
              />
            )}
          </div>

          <aside className="space-y-4">
            <SavedQueries reloadToken={savedToken} onLoad={handleLoadSaved} pathname={pathname} />
          </aside>
        </div>
      )}
    </div>
  )
}

export default function ScreenerPage() {
  // useSearchParams requires a Suspense boundary during static rendering;
  // see Next docs on the use-search-params bailout.
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-20">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      }
    >
      <ScreenerInner />
    </Suspense>
  )
}
