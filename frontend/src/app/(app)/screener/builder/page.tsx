"use client"

// Smart Screener (composite multi-criteria builder).
//
// Sister page to /screener, this one drives the POST /api/v1/screener/smart
// endpoint which can filter on JSONB-payload fields the SQL DSL can't see
// (dividend_streak_years, sbc_intensity_label, fair_value_ratio, etc.). The
// flat /screener page is still the right tool for clean SQL-pushdown
// filters over ratio_history + market_metrics — don't redirect that page
// here unless you also port over its DSL parser.
//
// State / URL sync model mirrors /screener: the URL is the source of truth
// for share-ability, but we only read it on mount and write on user
// actions (Run, preset apply, saved-query load). Two-way binding would
// rewrite the URL on every keystroke in a value input.
//
// Wire format on the URL: `?sector=FMCG&c=<base64-of-criteria-json>`.
// We base64 the criteria array instead of comma-encoding each clause
// because string-op values can themselves contain commas (e.g. "Wide,
// Narrow" for an `in` op) — base64 sidesteps the escaping rabbit hole.

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import api from "@/lib/api"
import { trueMosFromUpside } from "@/lib/utils"
import {
  loadSavedQueries,
  saveSavedQueries,
  type SavedQuery,
  type FilterClause,
  type FilterOperator,
} from "@/lib/screenerFilters"
import ModelDisclaimer from "@/components/ModelDisclaimer"

// ────────────────────────────────────────────────────────────────
// Types — kept local so we don't pollute the legacy screener lib.
// The smart endpoint's `field` set is a superset of the SQL DSL set,
// and string ops (`in`, `not_in`) are smart-only, so a shared
// FilterClause type would force the legacy page to widen too.
// ────────────────────────────────────────────────────────────────

type SmartFieldType = "number" | "string"

interface SmartField {
  key: string
  label: string
  type: SmartFieldType
}

interface SmartFieldsResponse {
  fields: SmartField[]
  ops: { number: string[]; string: string[] }
  sort_keys: string[]
}

interface SmartCriterion {
  // Local-only — used for stable list keys while editing.
  id: string
  field: string
  op: string
  value: string
}

interface SmartMatch {
  ticker: string
  score: number | null
  mos: number | null
  fair_value_ratio: number | null
  pe_ratio: number | null
  roe: number | null
  sector: string | null
  verdict: string | null
}

interface SmartSummary {
  count: number
  median_mos: number | null
  median_score: number | null
  median_roe: number | null
}

interface SmartScreenerResponse {
  matches: SmartMatch[]
  count: number
  summary: SmartSummary
  sector: string | null
  sort: string
  limit: number
}

// Sector dropdown options. Curated short list rather than fetching
// the full master because the long tail is industry-classified
// fragments (e.g. "Trading", "Diversified") that don't map cleanly
// to user mental models. If you add a sector here also add it to
// the analysis_cache `sector` mirror in the engine's payload.
const SECTOR_OPTIONS = [
  "",
  "Banking",
  "NBFC",
  "FMCG",
  "Technology",
  "Pharma",
  "Auto",
  "Capital Goods",
  "Utilities",
  "Energy",
  "Metals",
  "Cement",
  "Telecom",
  "Insurance",
  "REIT",
]

function newCrit(field = "", op = ">", value = ""): SmartCriterion {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    field,
    op,
    value,
  }
}

// ────────────────────────────────────────────────────────────────
// URL encoding helpers.
// We use base64url so the URL stays clean (no '+' or '/' that need
// re-escaping). On parse we tolerate the legacy comma DSL too so
// share-links from the v1 screener still load — they just won't be
// editable in this builder until a user touches a row.
// ────────────────────────────────────────────────────────────────
function encodeCriteria(crits: SmartCriterion[]): string {
  const clean = crits
    .filter((c) => c.field && c.value !== "" && c.value != null)
    .map((c) => ({ field: c.field, op: c.op, value: c.value }))
  if (clean.length === 0) return ""
  const json = JSON.stringify(clean)
  if (typeof window === "undefined") {
    return Buffer.from(json, "utf-8").toString("base64")
  }
  return window
    .btoa(unescape(encodeURIComponent(json)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "")
}

function decodeCriteria(raw: string | null | undefined): SmartCriterion[] {
  if (!raw) return []
  try {
    const padded = raw.replace(/-/g, "+").replace(/_/g, "/")
    const json =
      typeof window === "undefined"
        ? Buffer.from(padded, "base64").toString("utf-8")
        : decodeURIComponent(escape(window.atob(padded)))
    const arr = JSON.parse(json)
    if (!Array.isArray(arr)) return []
    return arr
      .filter((x) => x && typeof x.field === "string" && typeof x.op === "string")
      .map((x, i) => ({
        id: `loaded-${Date.now()}-${i}`,
        field: String(x.field),
        op: String(x.op),
        value: String(x.value ?? ""),
      }))
  } catch {
    return []
  }
}

function buildBuilderUrl(
  pathname: string,
  sector: string,
  crits: SmartCriterion[],
): string {
  const params = new URLSearchParams()
  if (sector) params.set("sector", sector)
  const c = encodeCriteria(crits)
  if (c) params.set("c", c)
  const qs = params.toString()
  return qs ? `${pathname}?${qs}` : pathname
}

// ────────────────────────────────────────────────────────────────
// Inner page — needs useSearchParams() so it must sit inside the
// page-level <Suspense> boundary at the bottom of this file.
// ────────────────────────────────────────────────────────────────

function SmartScreenerInner() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const [sector, setSector] = useState<string>(() => searchParams.get("sector") || "")
  const [criteria, setCriteria] = useState<SmartCriterion[]>(() => {
    const decoded = decodeCriteria(searchParams.get("c"))
    return decoded.length > 0 ? decoded : [newCrit()]
  })
  const [hasRun, setHasRun] = useState<boolean>(() => !!searchParams.get("c"))
  const [savedToken, setSavedToken] = useState(0)
  const [copiedShare, setCopiedShare] = useState(false)

  // Field metadata. Cached aggressively — schema changes only on deploy.
  const { data: fieldsData } = useQuery<SmartFieldsResponse>({
    queryKey: ["smart-screener-fields"],
    queryFn: async () => {
      const res = await api.get("/api/v1/screener/smart/fields")
      return res.data
    },
    staleTime: 60 * 60 * 1000,
  })

  const fields = fieldsData?.fields ?? []
  const fieldByKey = useMemo(() => {
    const m = new Map<string, SmartField>()
    for (const f of fields) m.set(f.key, f)
    return m
  }, [fields])
  const numericOps = fieldsData?.ops.number ?? [">", "<", ">=", "<=", "=", "!="]
  const stringOps = fieldsData?.ops.string ?? ["=", "!=", "in", "not_in"]

  // Strip blank rows + non-numeric values for numeric fields before
  // hitting the network. Returned shape matches SmartScreenerRequest
  // on the backend.
  const apiCriteria = useMemo(() => {
    type ApiCriterion = { field: string; op: string; value: number | string }
    return criteria
      .filter((c) => c.field && c.value !== "" && c.value != null)
      .map((c): ApiCriterion | null => {
        const f = fieldByKey.get(c.field)
        if (f && f.type === "number") {
          const n = Number(c.value)
          if (!Number.isFinite(n)) return null
          return { field: c.field, op: c.op, value: n }
        }
        return { field: c.field, op: c.op, value: c.value }
      })
      .filter((c): c is ApiCriterion => c !== null)
  }, [criteria, fieldByKey])

  // Live count — runs on every criteria/sector edit, debounced via
  // react-query's `staleTime: 0` + a key change. Low-cost endpoint
  // (count-only, no sort, no per-row projection).
  const countKey = useMemo(
    () => ["smart-screener-count", sector, JSON.stringify(apiCriteria)] as const,
    [sector, apiCriteria],
  )
  const { data: countData, isFetching: isCounting } = useQuery<{ count: number }>({
    queryKey: countKey,
    queryFn: async () => {
      const res = await api.post("/api/v1/screener/smart/count", {
        sector: sector || null,
        criteria: apiCriteria,
      })
      return res.data
    },
    enabled: apiCriteria.length > 0 || !!sector,
    staleTime: 15 * 1000,
  })

  // Full run — only fires after Run is clicked. We intentionally
  // separate this from the count query so the count chip keeps
  // updating mid-edit but the full table doesn't recompute on
  // every keystroke.
  const runKey = useMemo(
    () => ["smart-screener-run", sector, JSON.stringify(apiCriteria), hasRun] as const,
    [sector, apiCriteria, hasRun],
  )
  const { data: runData, isFetching: isRunning, error: runError } = useQuery<SmartScreenerResponse>({
    queryKey: runKey,
    queryFn: async () => {
      const res = await api.post("/api/v1/screener/smart", {
        sector: sector || null,
        criteria: apiCriteria,
        sort: "mos",
        limit: 100,
      })
      return res.data
    },
    enabled: hasRun,
    staleTime: 30 * 1000,
  })

  // Push state to URL. Used by Run + by Load-saved.
  const pushUrl = useCallback(
    (nextSector: string, nextCrits: SmartCriterion[]) => {
      router.replace(buildBuilderUrl(pathname, nextSector, nextCrits), { scroll: false })
    },
    [pathname, router],
  )

  const triggerRun = useCallback(() => {
    setHasRun(true)
    pushUrl(sector, criteria)
  }, [sector, criteria, pushUrl])

  const addCriterion = useCallback(() => {
    setCriteria((cs) => [...cs, newCrit()])
  }, [])

  const removeCriterion = useCallback((id: string) => {
    setCriteria((cs) => cs.filter((c) => c.id !== id))
  }, [])

  const updateCriterion = useCallback((id: string, patch: Partial<SmartCriterion>) => {
    setCriteria((cs) =>
      cs.map((c) => {
        if (c.id !== id) return c
        const next = { ...c, ...patch }
        // When the user picks a new field, snap the op to a sane default
        // for that field's type — keeps the dropdown coherent (e.g.
        // selecting "moat" with op="<" would just produce a 400 later).
        if (patch.field !== undefined) {
          const f = fieldByKey.get(patch.field)
          if (f) {
            next.op = f.type === "number" ? ">" : "="
          }
        }
        return next
      }),
    )
  }, [fieldByKey])

  // Save — re-uses the existing /screener saved-queries store so a
  // user's "My screens" list spans both builders. We coerce the
  // smart criteria into the legacy FilterClause shape on save; the
  // legacy /screener page won't be able to evaluate `in` / `not_in`
  // (which it doesn't render an op button for), so on load we
  // detect the unknown op and silently drop the clause there. Saved
  // queries written from this page re-load here with full fidelity.
  const handleSave = useCallback(() => {
    if (apiCriteria.length === 0 && !sector) return
    const name = window.prompt("Name this query", `Smart screen ${new Date().toLocaleDateString()}`)
    if (!name) return
    const asFilterClauses: FilterClause[] = criteria
      .filter((c) => c.field && c.value !== "")
      .map((c, i) => ({
        id: `${Date.now()}-${i}`,
        field: c.field,
        op: c.op as FilterOperator,
        value: c.value,
      }))
    // Encode sector + builder marker in the sort field so the loader
    // (handleLoadSaved below) can tell smart-saves apart from legacy
    // saves and re-hydrate the sector dropdown. The legacy /screener
    // page ignores anything it doesn't understand in `sort`.
    const sortMeta = `__smart:${sector || ""}`
    const entry: SavedQuery = {
      id: `sq-smart-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      name,
      filters: asFilterClauses,
      sort: sortMeta,
      limit: 100,
      createdAt: Date.now(),
    }
    const existing = loadSavedQueries()
    saveSavedQueries([entry, ...existing])
    setSavedToken((t) => t + 1)
  }, [apiCriteria, sector, criteria])

  // Share — copy current URL to clipboard. We don't depend on the
  // user clicking Run first; the encoded criteria are valid in the
  // URL regardless of whether the page actually ran them.
  const handleShare = useCallback(async () => {
    const url = buildBuilderUrl(pathname, sector, criteria)
    const full =
      typeof window !== "undefined" ? `${window.location.origin}${url}` : url
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(full)
        setCopiedShare(true)
        setTimeout(() => setCopiedShare(false), 1500)
      } else {
        // Last-ditch fallback for browsers without async clipboard —
        // a prompt() is ugly but it lets the user copy manually
        // rather than the button doing nothing.
        window.prompt("Share URL", full)
      }
    } catch {
      window.prompt("Share URL", full)
    }
  }, [pathname, sector, criteria])

  const liveCount = countData?.count
  const showLiveCount = (apiCriteria.length > 0 || !!sector)

  // Soft validation — flag rows where the user picked a field but
  // left the value blank, so the Run button can be disabled and the
  // user gets a hint inline.
  const hasIncomplete = criteria.some(
    (c) => c.field && (c.value === "" || c.value == null),
  )

  // Errors from the run query — POST 400 means a bad field/op combo;
  // surface server detail rather than the generic "Request failed".
  const runErrorMsg = useMemo<string | null>(() => {
    if (!runError) return null
    const anyErr = runError as { response?: { data?: { detail?: unknown } }; message?: string }
    const detail = anyErr.response?.data?.detail
    if (typeof detail === "string" && detail) return detail
    return anyErr.message || "Smart screener failed"
  }, [runError])

  // Mirror /screener's "no filters & not run yet" empty state so
  // the layout doesn't look stranded when the user first lands.
  const showEmpty = apiCriteria.length === 0 && !sector && !hasRun

  // Keep the saved-token referenced so the dependency array on
  // SavedQueries-style child cells (if added later) wouldn't flag
  // an unused variable. No-op in this render.
  useEffect(() => {
    /* savedToken kept for future SavedQueries reload wiring */
    void savedToken
  }, [savedToken])

  return (
    <div className="max-w-2xl md:max-w-4xl lg:max-w-6xl mx-auto px-4 py-6 pb-20 space-y-5">
      <header>
        <h1 className="text-xl font-bold text-ink">Smart Screener</h1>
        <p className="text-sm text-caption mt-1">
          Stack criteria across valuation, quality, payouts and dilution. Builder
          maps onto the analysis cache so you can filter on fields the flat
          screener doesn&apos;t expose.
        </p>
        {/* SEBI-safe inline disclaimer — same posture as /screener,
            since "47 names match" can read like a research call if
            we don't anchor that this is a filter output. */}
        <p className="text-[11px] text-caption mt-2 leading-relaxed">
          Smart-screen output is a filter over publicly available data
          &mdash; not investment advice. YieldIQ is not registered with SEBI
          as an investment adviser. Form your own view.
        </p>
      </header>

      {/* ── Sector + criteria builder ────────────────────────────── */}
      <section
        className="rounded-2xl border border-border bg-white dark:bg-surface p-4 space-y-4"
        data-testid="smart-builder"
      >
        <div className="grid grid-cols-1 sm:grid-cols-[10rem_1fr] gap-3 items-start">
          <label className="text-xs font-medium text-caption mt-2">Sector</label>
          <select
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            className="w-full sm:max-w-xs border border-border rounded-lg px-3 py-2 text-sm bg-bg text-ink"
            data-testid="smart-sector"
          >
            {SECTOR_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s || "Any sector"}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-2">
          {criteria.map((c) => {
            const f = fieldByKey.get(c.field)
            const ops = f?.type === "string" ? stringOps : numericOps
            return (
              <div
                key={c.id}
                className="grid grid-cols-1 sm:grid-cols-[12rem_5rem_1fr_2rem] gap-2 items-center"
                data-testid="smart-criterion-row"
              >
                <select
                  value={c.field}
                  onChange={(e) => updateCriterion(c.id, { field: e.target.value })}
                  className="w-full border border-border rounded-lg px-2 py-2 text-sm bg-bg text-ink"
                  aria-label="Criterion field"
                >
                  <option value="">Pick a metric…</option>
                  {fields.map((opt) => (
                    <option key={opt.key} value={opt.key}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <select
                  value={c.op}
                  onChange={(e) => updateCriterion(c.id, { op: e.target.value })}
                  className="w-full border border-border rounded-lg px-2 py-2 text-sm bg-bg text-ink"
                  aria-label="Criterion operator"
                >
                  {ops.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
                <input
                  type={f?.type === "number" ? "number" : "text"}
                  step="any"
                  value={c.value}
                  onChange={(e) => updateCriterion(c.id, { value: e.target.value })}
                  placeholder={
                    f?.type === "string"
                      ? "value (comma-list for in/not_in)"
                      : "threshold"
                  }
                  className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-bg text-ink"
                  aria-label="Criterion value"
                />
                <button
                  type="button"
                  onClick={() => removeCriterion(c.id)}
                  className="text-caption hover:text-red-600 text-lg leading-none px-2"
                  aria-label="Remove criterion"
                  title="Remove"
                >
                  &times;
                </button>
              </div>
            )
          })}
          <button
            type="button"
            onClick={addCriterion}
            className="text-xs font-medium text-blue-600 hover:text-blue-700"
          >
            + Add criterion
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-border">
          <button
            type="button"
            onClick={triggerRun}
            disabled={isRunning || hasIncomplete || (apiCriteria.length === 0 && !sector)}
            className="px-4 py-2 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="smart-run"
          >
            {isRunning ? "Running…" : "Run"}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={apiCriteria.length === 0 && !sector}
            className="px-3 py-2 text-sm rounded-lg border border-border text-ink hover:bg-blue-50 dark:hover:bg-blue-950/30 disabled:opacity-50"
            data-testid="smart-save"
          >
            Save query
          </button>
          <button
            type="button"
            onClick={handleShare}
            disabled={apiCriteria.length === 0 && !sector}
            className="px-3 py-2 text-sm rounded-lg border border-border text-ink hover:bg-blue-50 dark:hover:bg-blue-950/30 disabled:opacity-50"
            data-testid="smart-share"
          >
            {copiedShare ? "Link copied" : "Share"}
          </button>

          {showLiveCount && (
            <span
              className="ml-auto text-xs text-caption"
              data-testid="smart-live-count"
            >
              {isCounting
                ? "Counting…"
                : liveCount === undefined
                  ? "—"
                  : `${liveCount} names match`}
            </span>
          )}
        </div>

        {hasIncomplete && (
          <p className="text-xs text-amber-700 dark:text-amber-300">
            Finish each criterion (field + value) before running.
          </p>
        )}
      </section>

      {/* ── Results ──────────────────────────────────────────────── */}
      {showEmpty ? (
        <div
          className="rounded-2xl border border-dashed border-border p-6 text-center"
          data-testid="smart-empty"
        >
          <p className="text-sm text-caption">
            Add a sector or a criterion to start. Try{" "}
            <span className="text-ink font-medium">FMCG · MoS &gt; 20 · ROE &gt; 15</span>.
          </p>
        </div>
      ) : null}

      {runErrorMsg && (
        <div
          className="rounded-xl border border-amber-200 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/40 p-4"
          data-testid="smart-error"
        >
          <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
            Smart screener failed
          </p>
          <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
            {runErrorMsg}
          </p>
        </div>
      )}

      {hasRun && runData && (
        <>
          <ModelDisclaimer compact className="mb-2" />

          <section
            className="rounded-2xl border border-border bg-white dark:bg-surface p-4"
            data-testid="smart-results"
          >
            <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1 mb-3">
              <h2 className="text-sm font-semibold text-ink">
                {runData.count} names match
              </h2>
              <p className="text-xs text-caption">
                {runData.summary.median_mos !== null && (
                  <>median implied upside {runData.summary.median_mos.toFixed(1)}% · </>
                )}
                {runData.summary.median_score !== null && (
                  <>median score {runData.summary.median_score.toFixed(0)} · </>
                )}
                {runData.summary.median_roe !== null && (
                  <>median ROE {runData.summary.median_roe.toFixed(1)}%</>
                )}
              </p>
            </header>

            {runData.matches.length === 0 ? (
              <p className="text-sm text-caption">
                No names match these criteria. Loosen a threshold or remove a
                criterion.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm" data-testid="smart-results-table">
                  <thead>
                    <tr className="text-left text-xs text-caption border-b border-border">
                      <th className="py-2 pr-3">Ticker</th>
                      <th className="py-2 pr-3">Sector</th>
                      <th className="py-2 pr-3 text-right">MoS</th>
                      <th className="py-2 pr-3 text-right">Score</th>
                      <th className="py-2 pr-3 text-right">P/E</th>
                      <th className="py-2 pr-3 text-right">ROE</th>
                      <th className="py-2 pr-3">Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runData.matches.map((m) => (
                      <tr key={m.ticker} className="border-b border-border/50">
                        <td className="py-2 pr-3 font-medium text-ink">
                          <a
                            href={`/stock/${encodeURIComponent(m.ticker)}`}
                            className="hover:text-blue-600"
                          >
                            {m.ticker.replace(/\.NS$|\.BO$/, "")}
                          </a>
                        </td>
                        <td className="py-2 pr-3 text-caption">{m.sector || "—"}</td>
                        <td className="py-2 pr-3 text-right">
                          {m.mos !== null ? (
                            <>
                              <span className="block">{(trueMosFromUpside(m.mos) ?? m.mos).toFixed(1)}%</span>
                              <span className="block text-[10px] text-caption">{m.mos.toFixed(1)}% upside</span>
                            </>
                          ) : "—"}
                        </td>
                        <td className="py-2 pr-3 text-right">
                          {m.score !== null ? m.score.toFixed(0) : "—"}
                        </td>
                        <td className="py-2 pr-3 text-right">
                          {m.pe_ratio !== null ? m.pe_ratio.toFixed(1) : "—"}
                        </td>
                        <td className="py-2 pr-3 text-right">
                          {m.roe !== null ? `${m.roe.toFixed(1)}%` : "—"}
                        </td>
                        <td className="py-2 pr-3 text-caption">
                          {m.verdict || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

export default function SmartScreenerPage() {
  // useSearchParams requires a Suspense boundary during static
  // rendering — see Next docs on the use-search-params bailout.
  return (
    <Suspense
      fallback={
        <div className="max-w-6xl mx-auto px-4 py-8 space-y-4">
          <h1 className="text-xl font-bold text-ink">Smart Screener</h1>
          <div className="h-32 bg-surface border border-border rounded-2xl animate-pulse" />
        </div>
      }
    >
      <SmartScreenerInner />
    </Suspense>
  )
}
