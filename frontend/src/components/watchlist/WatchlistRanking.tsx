"use client"
// ═══════════════════════════════════════════════════════════════
// T6.5 — Watchlist-Relative Ranking.
//
// Sorts the user's watchlist by Margin of Safety, fair-value gap,
// price change since added, or alphabetical order — surfacing
// the BIGGEST opportunity at the top. Renders as the default
// view on the watchlist tab; the prior list is still rendered
// underneath as the "All" fallback when no items have a cached
// valuation.
//
// Why this matters: prior to T6.5 the watchlist tab showed
// holdings in whatever order Supabase returned (effectively the
// alphabetic upsert order), so a brand-new addition with the
// largest model gap could sit at row 12 while a fairly-valued
// long-time pick sat at row 1. Ranking by MoS/FV-gap surfaces
// the opportunity-at-the-top behavior every competitor (Tickertape,
// Trendlyne, etc.) already ships.
//
// SEBI note: this component is descriptive ONLY. The labels stay
// in the allowed vocabulary ("Largest Margin of Safety", "Below
// fair value", etc.) — no advisory verbs, no subjective tone,
// no opinion words. See scripts/check_sebi_words.py for the
// enforcement.
// ═══════════════════════════════════════════════════════════════
import { useMemo, useState } from "react"
import Link from "next/link"
import type { WatchlistItemResponse } from "@/types/api"
import { formatCurrency } from "@/lib/utils"

// ── Sort keys ────────────────────────────────────────────────
//
// "mos" — Margin of Safety, the most direct expression of model
//   gap. Descending puts the largest discount-to-FV at the top.
// "fv_gap" — same dimension expressed in rupees, useful when
//   the user thinks in price not percent.
// "price_change" — % move from the price-at-added so the user
//   can see which holding has moved the most while they were
//   tracking it.
// "alphabetical" — escape hatch matching the prior order.
export type WatchlistSortKey = "mos" | "fv_gap" | "price_change" | "alphabetical"
export type SortDirection = "asc" | "desc"

export interface WatchlistRankingProps {
  holdings: WatchlistItemResponse[]
  /** Optional handler so the parent can keep its own delete plumbing. */
  onRemove?: (ticker: string) => void
  /** Disable remove button while a mutation is in flight. */
  removeDisabled?: boolean
}

// Stable default direction per key: MoS / FV gap default to
// descending (largest opportunity first); price change defaults
// to descending (biggest mover first); alphabetical defaults to
// ascending (A → Z, matches prior behavior).
const DEFAULT_DIRECTION: Record<WatchlistSortKey, SortDirection> = {
  mos: "desc",
  fv_gap: "desc",
  price_change: "desc",
  alphabetical: "asc",
}

const SORT_LABEL: Record<WatchlistSortKey, string> = {
  mos: "Margin of Safety",
  fv_gap: "Fair-value gap",
  price_change: "Price change since added",
  alphabetical: "Alphabetical",
}

const SORT_DESCRIPTION: Record<WatchlistSortKey, string> = {
  mos: "Largest model discount first",
  fv_gap: "Largest rupee gap to fair value first",
  price_change: "Biggest move since added first",
  alphabetical: "Ticker A to Z",
}

// ── compareBy ────────────────────────────────────────────────
//
// Returns the signed comparison value used by Array.sort. A
// positive return means `a` is "less interesting" than `b` so
// `b` comes first under the descending default. Missing data
// is always pushed to the bottom regardless of direction so a
// half-empty watchlist still produces a usable order.
export function compareBy(
  a: WatchlistItemResponse,
  b: WatchlistItemResponse,
  key: WatchlistSortKey,
): number {
  if (key === "alphabetical") {
    return a.ticker.localeCompare(b.ticker)
  }
  if (key === "mos") {
    return compareNullable(a.mos_pct, b.mos_pct)
  }
  if (key === "fv_gap") {
    return compareNullable(fvGapAbs(a), fvGapAbs(b))
  }
  // price_change
  return compareNullable(priceChangePct(a), priceChangePct(b))
}

function compareNullable(a: number | null | undefined, b: number | null | undefined): number {
  const aMissing = a === null || a === undefined || Number.isNaN(a)
  const bMissing = b === null || b === undefined || Number.isNaN(b)
  if (aMissing && bMissing) return 0
  // Missing always loses regardless of direction — the calling
  // layer flips the sign of present-vs-present pairs only.
  if (aMissing) return Number.POSITIVE_INFINITY
  if (bMissing) return Number.NEGATIVE_INFINITY
  return (a as number) - (b as number)
}

// Rupee distance between fair value and current price proxy.
// We use `added_price` as the price proxy because the watchlist
// item doesn't carry live price (live quote lookup is a separate
// query the home dashboard handles). When neither FV nor added
// price is known the holding sorts to the bottom via null.
export function fvGapAbs(h: WatchlistItemResponse): number | null {
  const fv = h.fair_value ?? null
  const ref = h.added_price && h.added_price > 0 ? h.added_price : null
  if (fv === null || ref === null) return null
  return fv - ref
}

// Percent change between added price and target price as a
// stand-in for "how much has it moved while I've been watching".
// When the user hasn't set a target we fall back to FV vs added.
export function priceChangePct(h: WatchlistItemResponse): number | null {
  const added = h.added_price && h.added_price > 0 ? h.added_price : null
  if (added === null) return null
  const ref = h.target_price && h.target_price > 0
    ? h.target_price
    : h.fair_value && h.fair_value > 0
      ? h.fair_value
      : null
  if (ref === null) return null
  return ((ref - added) / added) * 100
}

// ── Metric formatter ─────────────────────────────────────────
//
// Returns the per-row primary metric string rendered next to
// the rank. Kept SEBI-safe ("Margin of Safety", purely
// descriptive). Returns "—" when the underlying value is
// missing so the row still aligns visually.
export function formatMetric(h: WatchlistItemResponse, key: WatchlistSortKey): string {
  if (key === "alphabetical") return ""
  if (key === "mos") {
    const v = h.mos_pct
    if (v === null || v === undefined || Number.isNaN(v)) return "—"
    const sign = v > 0 ? "+" : ""
    return `MoS ${sign}${v.toFixed(1)}%`
  }
  if (key === "fv_gap") {
    const v = fvGapAbs(h)
    if (v === null || Number.isNaN(v)) return "—"
    const sign = v > 0 ? "+" : ""
    return `${sign}${formatCurrency(v, "INR")}`
  }
  // price_change
  const v = priceChangePct(h)
  if (v === null || Number.isNaN(v)) return "—"
  const sign = v > 0 ? "+" : ""
  return `${sign}${v.toFixed(1)}%`
}

// ── Component ────────────────────────────────────────────────

export function WatchlistRanking({ holdings, onRemove, removeDisabled }: WatchlistRankingProps) {
  const [sortKey, setSortKey] = useState<WatchlistSortKey>("mos")
  const [direction, setDirection] = useState<SortDirection>(DEFAULT_DIRECTION.mos)

  // Switching the sort key resets the direction to the default
  // for that key. Without this, switching from MoS (desc) to
  // Alphabetical leaves it descending — i.e. Z to A — which
  // surprises every user.
  const handleSortKey = (next: WatchlistSortKey) => {
    setSortKey(next)
    setDirection(DEFAULT_DIRECTION[next])
  }

  const toggleDirection = () => {
    setDirection((d) => (d === "asc" ? "desc" : "asc"))
  }

  const sorted = useMemo(() => {
    const copy = [...holdings]
    copy.sort((a, b) => {
      const cmp = compareBy(a, b, sortKey)
      // compareNullable returns ±Infinity for missing data so
      // the missing rows always end up at the bottom regardless
      // of the user-selected direction. Only flip when both
      // values were present (cmp is a finite number).
      if (!Number.isFinite(cmp)) return cmp
      return direction === "desc" ? -cmp : cmp
    })
    return copy
  }, [holdings, sortKey, direction])

  if (!holdings || holdings.length === 0) {
    return (
      <section
        data-testid="watchlist-ranking-empty"
        aria-label="Watchlist ranking (no items)"
        className="rounded-xl border border-dashed border-gray-200 dark:border-gray-700 p-6 text-center"
      >
        <p className="text-sm text-caption">Nothing to rank yet.</p>
        <p className="text-xs text-caption mt-1">
          Save a stock to your watchlist from any analysis page to see
          opportunities surface here.
        </p>
      </section>
    )
  }

  const top = sorted[0]
  const directionLabel = direction === "desc" ? "Largest first" : "Smallest first"

  return (
    <section
      data-testid="watchlist-ranking"
      aria-label="Watchlist ranked by selected metric"
      className="space-y-3"
    >
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-sm font-bold text-ink">
            Your watchlist, ranked
          </h2>
          <p className="text-xs text-caption">
            Sorted by <span className="font-semibold">{SORT_LABEL[sortKey]}</span>{" "}
            ({SORT_DESCRIPTION[sortKey]}).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor="watchlist-rank-key">
            Sort watchlist by
          </label>
          <select
            id="watchlist-rank-key"
            data-testid="watchlist-rank-key"
            value={sortKey}
            onChange={(e) => handleSortKey(e.target.value as WatchlistSortKey)}
            className="text-xs font-semibold bg-bg dark:bg-surface border border-border rounded-lg px-2 py-1.5 min-h-[36px]"
          >
            {(Object.keys(SORT_LABEL) as WatchlistSortKey[]).map((k) => (
              <option key={k} value={k}>
                {SORT_LABEL[k]}
              </option>
            ))}
          </select>
          <button
            type="button"
            data-testid="watchlist-rank-direction"
            onClick={toggleDirection}
            aria-label={`Toggle sort direction (currently ${directionLabel})`}
            className="text-xs font-semibold bg-bg dark:bg-surface border border-border rounded-lg px-2 py-1.5 min-h-[36px] hover:bg-surface"
          >
            {direction === "desc" ? "Largest first" : "Smallest first"}
          </button>
        </div>
      </header>

      {/* Top-opportunity highlight — shown only when the leading
          row carries a present metric (not just alphabetical or
          a missing-data fallback). Mirrors the discover-page
          "biggest gap today" tile so the watchlist feels alive. */}
      <TopOpportunityHighlight first={top} sortKey={sortKey} />

      <ol className="space-y-2" data-testid="watchlist-ranking-list">
        {sorted.map((h, idx) => {
          const metric = formatMetric(h, sortKey)
          const isLeader = idx === 0 && metric !== "" && metric !== "—"
          return (
            <li
              key={h.ticker}
              data-testid={`watchlist-ranking-row-${h.ticker}`}
              className={`flex items-center bg-bg dark:bg-surface rounded-xl border ${
                isLeader ? "border-blue-200" : "border-gray-100"
              } hover:border-blue-200 transition`}
            >
              <Link
                href={`/analysis/${h.ticker}`}
                className="flex-1 flex items-center gap-3 p-3 sm:p-4"
              >
                <span
                  aria-hidden="true"
                  className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold shrink-0 ${
                    isLeader
                      ? "bg-blue-600 text-white"
                      : "bg-surface text-caption"
                  }`}
                >
                  {idx + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-ink truncate">
                    {h.ticker.replace(".NS", "")}
                  </p>
                  <p className="text-xs text-caption truncate">
                    {h.company_name || "—"}
                  </p>
                </div>
                {metric && (
                  <span
                    data-testid={`watchlist-ranking-metric-${h.ticker}`}
                    className={`font-mono font-semibold text-xs sm:text-sm shrink-0 ${
                      metricToneClass(h, sortKey)
                    }`}
                  >
                    {metric}
                  </span>
                )}
              </Link>
              {onRemove && (
                <button
                  type="button"
                  onClick={() => onRemove(h.ticker)}
                  disabled={removeDisabled}
                  aria-label={`Remove ${h.ticker.replace(".NS", "")} from watchlist`}
                  className="flex items-center justify-center min-w-[44px] min-h-[44px] text-caption hover:text-red-500 active:scale-90 transition shrink-0"
                  title="Remove from watchlist"
                >
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M6 18L18 6M6 6l12 12"
                    />
                  </svg>
                </button>
              )}
            </li>
          )
        })}
      </ol>

      <p className="text-[10px] text-caption text-center pt-1">
        Ranking is descriptive model output, not investment advice.
        Rows missing a fair value sort to the bottom.
      </p>
    </section>
  )
}

// ── Top-opportunity highlight ────────────────────────────────
//
// Renders a one-line "{ticker} carries the largest {metric}"
// banner above the list. Suppressed when the leading row has no
// present metric (e.g. all rows are missing FV) so we never show
// a misleading "largest" claim against missing data.
export function TopOpportunityHighlight({
  first,
  sortKey,
}: {
  first: WatchlistItemResponse | undefined
  sortKey: WatchlistSortKey
}) {
  if (!first) return null
  const metric = formatMetric(first, sortKey)
  if (!metric || metric === "—" || sortKey === "alphabetical") return null
  const labelByKey: Record<Exclude<WatchlistSortKey, "alphabetical">, string> = {
    mos: "Margin of Safety",
    fv_gap: "gap to fair value",
    price_change: "move since added",
  }
  return (
    <div
      data-testid="watchlist-top-opportunity"
      className="rounded-xl bg-gradient-to-br from-blue-50 to-cyan-50 dark:from-blue-950/30 dark:to-cyan-950/30 border border-blue-100 dark:border-blue-900 px-3 py-2 flex items-center justify-between"
    >
      <div className="min-w-0">
        <p className="text-[10px] font-bold uppercase tracking-wider text-blue-700 dark:text-blue-300">
          Largest {labelByKey[sortKey as Exclude<WatchlistSortKey, "alphabetical">]} today
        </p>
        <p className="text-sm font-semibold text-ink truncate">
          {first.ticker.replace(".NS", "")}
          {first.company_name ? ` — ${first.company_name}` : ""}
        </p>
      </div>
      <span className="font-mono font-bold text-sm text-blue-700 dark:text-blue-300 shrink-0 ml-3">
        {metric}
      </span>
    </div>
  )
}

// Green for positive MoS / FV-gap / price-change, amber for
// negative, neutral otherwise. Alphabetical has no tone.
function metricToneClass(h: WatchlistItemResponse, key: WatchlistSortKey): string {
  if (key === "alphabetical") return "text-caption"
  let v: number | null = null
  if (key === "mos") v = h.mos_pct ?? null
  else if (key === "fv_gap") v = fvGapAbs(h)
  else v = priceChangePct(h)
  if (v === null || Number.isNaN(v)) return "text-caption"
  if (v > 0) return "text-green-600 dark:text-green-400"
  if (v < 0) return "text-amber-600 dark:text-amber-400"
  return "text-caption"
}

export default WatchlistRanking
