/**
 * FundScreener — the client-owned filter + sort + pagination shell for the
 * research-grade /funds screener.
 *
 * The server page does the FIRST-PAGE SSR fetch (fast first paint) and
 * hands the rows + parsed initial state here. From mount on, THIS
 * component owns all screener state — search query, Category / Risk /
 * Fund House filters, sort column + order, and the loaded page set — and:
 *
 *   • fetches /api/v1/funds client-side (debounced search) on every
 *     change via listFundsScreener (axios client),
 *   • mirrors state to the URL querystring with router.replace so the
 *     view is shareable / back-button-friendly, WITHOUT useSearchParams
 *     (which triggers the Vercel prerender Suspense bailout — see root
 *     CLAUDE.md and the FundsSearchInput precedent). First paint reads the
 *     SSR `searchParams`; the client reads window.location only when it
 *     needs to (it doesn't here — state is seeded from props).
 *
 * GRACEFUL DEGRADATION while the backend sort/offset/risk/amc params and
 * ret_10y column roll out in a parallel PR:
 *   • The visible page is ALWAYS client-sorted by the active sort/order
 *     (NULLs last), so column ordering is correct even if the backend
 *     ignores `?sort=` and returns its default order.
 *   • "Load more" appends the next offset page; if the backend ignores
 *     `?offset=` and returns no new rows, the button hides itself
 *     (no-growth guard) so the user never sees a dead control.
 *   • The 10Y column only renders when some row carries ret_10y.
 *
 * No advisory copy. Sort/columns/score are factual, descriptive markers —
 * not best/top/recommended. Past-performance disclaimer is rendered by the
 * page footer.
 */
"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"

import type {
  FundAmcCount,
  FundCategoryCount,
  FundListItem,
  FundListSort,
  FundRiskLevelCount,
  FundRiskometerLevel,
  FundSortOrder,
} from "@/types/api"
import { listFundsScreener } from "@/lib/api"
import { RISKOMETER_ORDER } from "@/lib/fund-riskometer"
import { annualizeReturn, RETURN_WINDOW_YEARS } from "@/lib/fund-annualize"
import { compactCategory } from "./FundCard"
import FundScreenerTable from "./FundScreenerTable"

const PAGE_SIZE = 25
const DEBOUNCE_MS = 300
const DEFAULT_SORT: FundListSort = "score"
const DEFAULT_ORDER: FundSortOrder = "desc"

// Friendly quick-pills resolve to a real AMFI category string at render
// time by keyword-matching the categories census — never a hard-coded
// label that could drift from the DB (mirrors the old hub's chips).
interface FriendlyPill {
  label: string
  match: (raw: string) => boolean
}

const FRIENDLY_PILLS: FriendlyPill[] = [
  { label: "Large Cap", match: (r) => r.includes("large cap") && !r.includes("mid") },
  { label: "Mid Cap", match: (r) => r.includes("mid cap") && !r.includes("large") },
  { label: "Small Cap", match: (r) => r.includes("small cap") },
  { label: "Flexi Cap", match: (r) => r.includes("flexi cap") },
  { label: "ELSS (Tax)", match: (r) => r.includes("elss") },
  { label: "Index", match: (r) => r.includes("index") },
]

function resolvePill(pill: FriendlyPill, rawCategories: string[]): string | null {
  for (const raw of rawCategories) {
    if (pill.match(raw.toLowerCase())) return raw
  }
  return null
}

export interface FundScreenerProps {
  initialFunds: FundListItem[]
  initialTotal: number
  initialQuery: string
  initialCategory: string
  initialRisk: string
  initialAmc: string
  initialSort: FundListSort
  initialOrder: FundSortOrder
  categories: FundCategoryCount[]
  amcs: FundAmcCount[]
  /** Riskometer-level facets that actually carry schemes (data-driven).
   * Empty while `funds.riskometer_level` is unpopulated — the Risk
   * dropdown then self-hides so it can never zero out the grid. */
  riskLevels: FundRiskLevelCount[]
}

// ── Client-side sort safety net ──────────────────────────────────────
// Always sort the visible page by the active sort/order so ordering is
// correct even when the backend ignores `?sort=`. NULL metric values sort
// LAST in both directions (a fund with no 3Y must not jump to the top of
// a 3Y sort). Returns are compared ANNUALIZED so 3Y vs 5Y order by the
// same convention the table displays.
function metricFor(fund: FundListItem, sort: FundListSort): number | null {
  switch (sort) {
    case "score":
      return typeof fund.yieldiq_fund_score === "number" ? fund.yieldiq_fund_score : null
    case "ter":
      return typeof fund.ter_direct === "number" ? fund.ter_direct : null
    case "ret_1y":
      return annualizeReturn(fund.ret_1y, RETURN_WINDOW_YEARS.ret_1y)
    case "ret_3y":
      return annualizeReturn(fund.ret_3y, RETURN_WINDOW_YEARS.ret_3y)
    case "ret_5y":
      return annualizeReturn(fund.ret_5y, RETURN_WINDOW_YEARS.ret_5y)
    case "ret_10y":
      return annualizeReturn(fund.ret_10y, RETURN_WINDOW_YEARS.ret_10y)
    default:
      return null
  }
}

function clientSort(
  funds: FundListItem[],
  sort: FundListSort,
  order: FundSortOrder,
): FundListItem[] {
  const dir = order === "asc" ? 1 : -1
  const sorted = [...funds]
  sorted.sort((a, b) => {
    if (sort === "name") {
      return a.scheme_name.localeCompare(b.scheme_name) * dir
    }
    const av = metricFor(a, sort)
    const bv = metricFor(b, sort)
    // NULLs last, regardless of direction.
    if (av === null && bv === null) return 0
    if (av === null) return 1
    if (bv === null) return -1
    return (av - bv) * dir
  })
  return sorted
}

// A labeled <select> dropdown for the filter bar.
function FilterSelect({
  label,
  value,
  onChange,
  children,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  children: React.ReactNode
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px] font-medium text-caption">
      <span className="sr-only sm:not-sr-only">{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-0 rounded-lg border border-border bg-raised px-3 py-2 text-sm text-ink focus:border-caption focus:outline-none focus:ring-1 focus:ring-caption"
      >
        {children}
      </select>
    </label>
  )
}

const RISK_LABELS: Record<FundRiskometerLevel, string> = {
  Low: "Low",
  LowToModerate: "Low to Moderate",
  Moderate: "Moderate",
  ModeratelyHigh: "Moderately High",
  High: "High",
  VeryHigh: "Very High",
}

export default function FundScreener({
  initialFunds,
  initialTotal,
  initialQuery,
  initialCategory,
  initialRisk,
  initialAmc,
  initialSort,
  initialOrder,
  categories,
  amcs,
  riskLevels,
}: FundScreenerProps) {
  const router = useRouter()

  // The Risk filter is DATA-DRIVEN: it only exists when some scheme
  // actually carries a Riskometer level. `funds.riskometer_level` is
  // unpopulated for most of the universe, so this is usually false and
  // the Risk dropdown is hidden entirely (it would otherwise zero out the
  // grid for every selection — the bug this fixes). The set of selectable
  // levels is rendered in the natural Low→VeryHigh order, restricted to
  // those present, each with its scheme count.
  const presentRiskLevels = useMemo(() => {
    const present = new Map(riskLevels.map((r) => [r.risk, r.count]))
    return RISKOMETER_ORDER.filter((lvl) => present.has(lvl)).map((lvl) => ({
      level: lvl,
      count: present.get(lvl) ?? 0,
    }))
  }, [riskLevels])
  const riskFacetAvailable = presentRiskLevels.length > 0

  // ── Filter / sort / page state ─────────────────────────────────────
  const [query, setQuery] = useState(initialQuery)
  const [category, setCategory] = useState(initialCategory)
  // Ignore an incoming `?risk=` when no Riskometer data exists, so a stale
  // bookmarked link can't silently zero out the grid via a hidden control.
  const [risk, setRisk] = useState(riskFacetAvailable ? initialRisk : "")
  const [amc, setAmc] = useState(initialAmc)
  const [sort, setSort] = useState<FundListSort>(initialSort)
  const [order, setOrder] = useState<FundSortOrder>(initialOrder)

  // Loaded rows + total. The first page is seeded from SSR. `offset`
  // tracks how many rows we've already loaded for "Load more".
  const [funds, setFunds] = useState<FundListItem[]>(initialFunds)
  const [total, setTotal] = useState(initialTotal)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  // True once the backend returns no NEW rows for a Load-more (it ignored
  // `?offset=`); hides the button so the user never hits a dead control.
  const [paginationExhausted, setPaginationExhausted] = useState(false)

  // Skip the first fetch effect: SSR already provided the initial page for
  // the initial state, so re-fetching on mount would be a wasted round
  // trip and a flash.
  const firstRun = useRef(true)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Monotonic request id so a slow earlier response can't overwrite a
  // newer one (last-write-wins race guard).
  const reqIdRef = useRef(0)

  const rawCategories = useMemo(() => categories.map((c) => c.category), [categories])
  const pills = useMemo(
    () =>
      FRIENDLY_PILLS.map((p) => ({ label: p.label, value: resolvePill(p, rawCategories) })).filter(
        (p): p is { label: string; value: string } => p.value !== null,
      ),
    [rawCategories],
  )

  // Mirror current state to the URL (non-default params only).
  const mirrorUrl = useCallback(
    (next: {
      query: string
      category: string
      risk: string
      amc: string
      sort: FundListSort
      order: FundSortOrder
    }) => {
      const params = new URLSearchParams()
      if (next.query.trim()) params.set("q", next.query.trim())
      if (next.category) params.set("category", next.category)
      if (next.risk) params.set("risk", next.risk)
      if (next.amc) params.set("amc", next.amc)
      if (next.sort !== DEFAULT_SORT) params.set("sort", next.sort)
      if (next.order !== DEFAULT_ORDER) params.set("order", next.order)
      const qs = params.toString()
      router.replace(qs ? `/funds?${qs}` : "/funds", { scroll: false })
    },
    [router],
  )

  // Fetch the FIRST page for the current filter/sort state, replacing the
  // loaded set. Always called through the debounced effect below.
  const fetchFirstPage = useCallback(
    async (next: {
      query: string
      category: string
      risk: string
      amc: string
      sort: FundListSort
      order: FundSortOrder
    }) => {
      const id = ++reqIdRef.current
      setLoading(true)
      try {
        const res = await listFundsScreener({
          limit: PAGE_SIZE,
          q: next.query.trim() || undefined,
          category: next.category || undefined,
          risk: next.risk || undefined,
          amc: next.amc || undefined,
          sort: next.sort,
          order: next.order,
          offset: 0,
        })
        if (id !== reqIdRef.current) return // stale response
        setFunds(res.funds ?? [])
        setTotal(typeof res.total === "number" ? res.total : (res.funds?.length ?? 0))
        setPaginationExhausted(false)
      } catch {
        if (id !== reqIdRef.current) return
        setFunds([])
        setTotal(0)
      } finally {
        if (id === reqIdRef.current) setLoading(false)
      }
    },
    [],
  )

  // Re-fetch the first page whenever any facet / sort / search changes,
  // and mirror the URL. Debounced (300ms) so rapid typing or back-to-back
  // dropdown changes collapse into a single request; the URL mirror runs
  // immediately so a shared/bookmarked link always reflects the controls.
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false
      return
    }
    const next = { query, category, risk, amc, sort, order }
    mirrorUrl(next)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchFirstPage(next), DEBOUNCE_MS)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query, category, risk, amc, sort, order, mirrorUrl, fetchFirstPage])

  // ── Sort toggle ────────────────────────────────────────────────────
  // Same column flips order; a new column starts desc (asc for name, the
  // natural alphabetical default).
  const onSort = useCallback(
    (key: FundListSort) => {
      if (key === sort) {
        setOrder((o) => (o === "asc" ? "desc" : "asc"))
      } else {
        setSort(key)
        setOrder(key === "name" ? "asc" : "desc")
      }
    },
    [sort],
  )

  // ── Load more (pagination by offset) ───────────────────────────────
  const loadMore = useCallback(async () => {
    const id = reqIdRef.current // do not bump: this appends to the current query
    setLoadingMore(true)
    try {
      const res = await listFundsScreener({
        limit: PAGE_SIZE,
        q: query.trim() || undefined,
        category: category || undefined,
        risk: risk || undefined,
        amc: amc || undefined,
        sort,
        order,
        offset: funds.length,
      })
      if (id !== reqIdRef.current) return // a newer first-page fetch superseded us
      const incoming = res.funds ?? []
      // Dedupe by scheme_code so a backend that ignores `?offset=` (and
      // returns the same first page again) doesn't duplicate rows.
      const seen = new Set(funds.map((f) => f.scheme_code))
      const fresh = incoming.filter((f) => !seen.has(f.scheme_code))
      if (fresh.length === 0) {
        setPaginationExhausted(true)
      } else {
        setFunds((prev) => [...prev, ...fresh])
      }
    } catch {
      // leave the current set intact; the button stays for a retry
    } finally {
      setLoadingMore(false)
    }
  }, [query, category, risk, amc, sort, order, funds])

  const clearAll = useCallback(() => {
    setQuery("")
    setCategory("")
    setRisk("")
    setAmc("")
    setSort(DEFAULT_SORT)
    setOrder(DEFAULT_ORDER)
  }, [])

  const hasActiveFilters = Boolean(
    query.trim() ||
      category ||
      risk ||
      amc ||
      sort !== DEFAULT_SORT ||
      order !== DEFAULT_ORDER,
  )

  // Visible rows = client-sorted current set (degrade-graceful ordering).
  const visible = useMemo(() => clientSort(funds, sort, order), [funds, sort, order])

  // 10Y column only when some loaded row actually carries ret_10y.
  const showTenYear = useMemo(
    () => visible.some((f) => typeof f.ret_10y === "number" && f.ret_10y !== null),
    [visible],
  )

  // Risk column only when some loaded row actually carries a Riskometer
  // level — `funds.riskometer_level` is unpopulated for most of the
  // universe, so this is usually false and the column is omitted rather
  // than shown as a wall of em-dashes (matches the data-driven Risk
  // filter dropdown above).
  const showRisk = useMemo(
    () => visible.some((f) => typeof f.riskometer_level === "string" && !!f.riskometer_level),
    [visible],
  )

  const canLoadMore = !paginationExhausted && funds.length < total

  return (
    <div className="space-y-4">
      {/* ── Header ───────────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Mutual Funds</h1>
        <p className="num text-sm text-caption" aria-live="polite">
          {total.toLocaleString("en-IN")} funds
        </p>
      </header>

      {/* ── Filter bar ───────────────────────────────────────────────── */}
      <div className="space-y-3 rounded-lg border border-border bg-raised/40 p-3">
        {/* Search + facet dropdowns */}
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-[11px] font-medium text-caption">
            <span className="sr-only sm:not-sr-only">Search</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by scheme name or AMC..."
              autoComplete="off"
              aria-label="Search funds by scheme name or AMC"
              className="w-full rounded-lg border border-border bg-raised px-3 py-2 text-sm text-ink placeholder:text-caption focus:border-caption focus:outline-none focus:ring-1 focus:ring-caption"
            />
          </label>

          <FilterSelect label="Category" value={category} onChange={setCategory}>
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c.category} value={c.category}>
                {compactCategory(c.category)}
              </option>
            ))}
          </FilterSelect>

          {/* Data-driven: only rendered when some scheme carries a
              Riskometer level, so a selection can never empty the grid. */}
          {riskFacetAvailable ? (
            <FilterSelect label="Risk" value={risk} onChange={setRisk}>
              <option value="">All risk levels</option>
              {presentRiskLevels.map(({ level, count }) => (
                <option key={level} value={level}>
                  {RISK_LABELS[level]} ({count.toLocaleString("en-IN")})
                </option>
              ))}
            </FilterSelect>
          ) : null}

          {amcs.length > 0 ? (
            <FilterSelect label="Fund House" value={amc} onChange={setAmc}>
              <option value="">All fund houses</option>
              {amcs.map((a) => (
                <option key={a.amc} value={a.amc}>
                  {a.amc}
                </option>
              ))}
            </FilterSelect>
          ) : null}
        </div>

        {/* Quick category pills + Clear all */}
        <div className="flex flex-wrap items-center gap-1.5">
          {pills.map((p) => {
            const active = category === p.value
            return (
              <button
                key={p.label}
                type="button"
                aria-pressed={active}
                onClick={() => setCategory(active ? "" : p.value)}
                className={`rounded-full border px-3 py-1 text-[12px] font-medium transition-colors ${
                  active
                    ? "border-tone-info-bd bg-tone-info-bg text-tone-info-fg"
                    : "border-border bg-raised text-caption hover:bg-surface hover:text-ink"
                }`}
              >
                {p.label}
              </button>
            )
          })}
          {hasActiveFilters ? (
            <button
              type="button"
              onClick={clearAll}
              className="ml-auto rounded-full px-3 py-1 text-[12px] font-medium text-tone-info-fg underline-offset-2 hover:underline"
            >
              Clear all
            </button>
          ) : null}
        </div>
      </div>

      {/* Annualized caption (global-research convention). */}
      <p className="text-[11px] text-caption">
        3Y, 5Y and 10Y returns are annualized (per annum). Sorting and
        columns are factual data points, not recommendations.
      </p>

      {/* ── Results ──────────────────────────────────────────────────── */}
      {visible.length === 0 ? (
        <div className="rounded-lg border border-border bg-raised p-6 text-sm text-caption">
          {loading
            ? "Loading funds…"
            : "No funds match these filters. Try clearing a filter or a different search."}
        </div>
      ) : (
        <>
          <div
            className={loading ? "pointer-events-none opacity-60 transition-opacity" : "transition-opacity"}
          >
            <FundScreenerTable
              funds={visible}
              sort={sort}
              order={order}
              onSort={onSort}
              showTenYear={showTenYear}
              showRisk={showRisk}
            />
          </div>

          {/* Pagination footer */}
          <div className="flex flex-col items-center gap-2 pt-1">
            <p className="num text-xs text-caption" aria-live="polite">
              Showing {visible.length.toLocaleString("en-IN")} of{" "}
              {total.toLocaleString("en-IN")}
            </p>
            {canLoadMore ? (
              <button
                type="button"
                onClick={loadMore}
                disabled={loadingMore}
                className="rounded-lg border border-border bg-raised px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-surface disabled:opacity-50"
              >
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            ) : null}
          </div>
        </>
      )}
    </div>
  )
}
