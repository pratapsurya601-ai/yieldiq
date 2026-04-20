// Screener filter DSL serialization.
//
// The backend accepts a comma-separated `filters` query param where each
// clause is `<field><op><value>`, e.g. "pe_ratio<20,roce>15". We keep the
// operator set narrow (six comparison ops) because that matches the backend
// parser; anything else is rejected server-side.
//
// Shape note: operator "=" and "!=" are allowed for string fields (sector)
// while numeric fields use the five numeric comparisons. We don't enforce
// that here — the UI constrains it when picking an operator.

export type FilterOperator = "<" | ">" | "<=" | ">=" | "=" | "!="

export const FILTER_OPERATORS: FilterOperator[] = ["<", ">", "<=", ">=", "=", "!="]

export interface FilterClause {
  id: string
  field: string
  op: FilterOperator
  value: string
}

export interface ScreenerField {
  key: string
  label: string
  // "numeric" renders a number input, "string" (sector) renders a select.
  type: "numeric" | "string"
  unit?: string
  options?: string[]
}

export interface ScreenerFieldsResponse {
  fields: ScreenerField[]
  sortable?: string[]
}

export interface ScreenerQueryRow {
  ticker: string
  [key: string]: string | number | null | undefined
}

export interface ScreenerQueryResponse {
  results: ScreenerQueryRow[]
  total: number
  page?: number
  page_size?: number
}

// Serialize clauses into the `filters` query param.
// Empty / incomplete clauses (missing field or value) are dropped silently
// so the UI can keep a blank row while the user edits.
export function serializeFilters(clauses: FilterClause[]): string {
  return clauses
    .filter((c) => c.field && c.value !== "" && c.value != null)
    .map((c) => `${c.field}${c.op}${c.value}`)
    .join(",")
}

// Parse a `filters` string back into clauses. Unknown operators are
// dropped rather than throwing; this is user-supplied URL input and we'd
// rather degrade than blow up the page.
const OP_REGEX = /^([a-zA-Z0-9_]+)(<=|>=|!=|<|>|=)(.+)$/

export function parseFilters(raw: string | null | undefined): FilterClause[] {
  if (!raw) return []
  return raw
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part, i) => {
      const m = part.match(OP_REGEX)
      if (!m) return null
      const [, field, op, value] = m
      return {
        id: `${Date.now()}-${i}-${field}`,
        field,
        op: op as FilterOperator,
        value,
      } satisfies FilterClause
    })
    .filter((c): c is FilterClause => c !== null)
}

export function newClause(field = "", op: FilterOperator = ">", value = ""): FilterClause {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    field,
    op,
    value,
  }
}

// Preset definitions — used by the empty-state buttons.
export interface ScreenerPreset {
  key: string
  label: string
  description: string
  filters: Omit<FilterClause, "id">[]
  sort?: string
}

export const SCREENER_PRESETS: ScreenerPreset[] = [
  {
    key: "cheap_quality",
    label: "Cheap + Quality",
    description: "Low P/E with high return on capital",
    filters: [
      { field: "pe_ratio", op: "<", value: "20" },
      { field: "roce", op: ">", value: "15" },
    ],
    sort: "mos",
  },
  {
    key: "high_quality",
    label: "High Quality",
    description: "Top return on equity with reasonable leverage",
    filters: [
      { field: "roe", op: ">", value: "18" },
      { field: "de_ratio", op: "<", value: "1" },
    ],
    sort: "roe",
  },
  {
    key: "deep_value",
    label: "Deep Value",
    description: "Market cap well above margin of safety threshold",
    filters: [
      { field: "mos", op: ">", value: "30" },
      { field: "pe_ratio", op: "<", value: "15" },
    ],
    sort: "mos",
  },
  {
    key: "smallcap_value",
    label: "Small-cap value",
    description: "Small market cap trading below fair value",
    filters: [
      { field: "market_cap_cr", op: "<", value: "5000" },
      { field: "mos", op: ">", value: "20" },
    ],
    sort: "mos",
  },
]

// Saved query storage (localStorage). We intentionally avoid putting this
// in the auth store — saved queries are a per-device convenience, not a
// synced user setting.

export interface SavedQuery {
  id: string
  name: string
  filters: FilterClause[]
  sort: string
  limit: number
  createdAt: number
}

const SAVED_QUERIES_KEY = "yieldiq_saved_screeners_v1"

export function loadSavedQueries(): SavedQuery[] {
  if (typeof window === "undefined") return []
  try {
    const raw = window.localStorage.getItem(SAVED_QUERIES_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as SavedQuery[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function saveSavedQueries(queries: SavedQuery[]): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(SAVED_QUERIES_KEY, JSON.stringify(queries))
  } catch {
    // Quota exceeded or storage disabled — non-fatal.
  }
}

export function buildShareUrl(pathname: string, filters: FilterClause[], sort: string, limit: number): string {
  const params = new URLSearchParams()
  const f = serializeFilters(filters)
  if (f) params.set("filters", f)
  if (sort) params.set("sort", sort)
  if (limit && limit !== 50) params.set("limit", String(limit))
  const qs = params.toString()
  return qs ? `${pathname}?${qs}` : pathname
}
