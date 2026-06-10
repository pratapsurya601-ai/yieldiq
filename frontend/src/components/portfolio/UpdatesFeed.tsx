"use client"
/**
 * Portfolio Updates Feed (P0 #1, 2026-05-25).
 *
 * Per-holding categorised event stream. Backing endpoint:
 *   GET /api/v1/portfolio/me/updates?category=...&limit=...&offset=...
 *
 * The feed is intentionally read-only (the user does not author rows).
 * Categories are filtered client-side via the left sidebar; the
 * endpoint also accepts a category query param so each filter click
 * fires a focused query rather than client-side slicing.
 *
 * SEBI discipline: template-generated headlines only (no buy/sell/
 * hold/target). No LLM calls — all copy comes from the backend
 * template engine (backend/services/updates_feed/templates.py).
 */
import Link from "next/link"
import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  getPortfolioUpdates,
  type PortfolioUpdateCategory,
  type PortfolioUpdateItem,
} from "@/lib/api"
import { PressScale, RevealStagger } from "@/components/motion"

// Cap the visible stagger so very long update lists don't take a long
// time to finish their entrance. Per-page size is 25 today so this
// only matters if PAGE_SIZE is bumped above 50.
const MAX_STAGGER_ROWS = 50

type FilterValue = PortfolioUpdateCategory | "all"

interface CategoryOption {
  value: FilterValue
  label: string
  icon: string
}

// Icons are plain emoji to avoid pulling in another icon dep. Order
// mirrors the competitor spec (P0 #1 reference).
const CATEGORY_OPTIONS: CategoryOption[] = [
  { value: "all", label: "All updates", icon: "🗂️" },
  { value: "earnings", label: "Earnings", icon: "📈" },
  { value: "valuations", label: "Valuations", icon: "💰" },
  { value: "intrinsic_updates", label: "Intrinsic Updates", icon: "📊" },
  { value: "dividends", label: "Dividends", icon: "💸" },
  { value: "insider_trading", label: "Insider", icon: "👤" },
  { value: "risk_legal", label: "Risk & Legal", icon: "⚠️" },
  { value: "other", label: "Other", icon: "📋" },
]

const EMPTY_COPY: Record<FilterValue, string> = {
  all: "No updates yet for any of your holdings. Check back after the nightly refresh.",
  earnings: "No earnings updates yet.",
  valuations: "No model fair-value changes yet.",
  intrinsic_updates: "No intrinsic-value updates yet.",
  dividends: "No dividend updates yet.",
  insider_trading: "No insider activity yet.",
  risk_legal: "No risk or legal flags yet.",
  other: "No other updates yet.",
}

const PAGE_SIZE = 25

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  try {
    const d = new Date(iso)
    return d.toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })
  } catch {
    return iso
  }
}

function FeedRow({ item }: { item: PortfolioUpdateItem }) {
  const cat = CATEGORY_OPTIONS.find((c) => c.value === item.category)
  return (
    <article className="bg-bg dark:bg-surface rounded-xl border border-gray-100 dark:border-gray-800 p-4 space-y-2">
      <header className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span aria-hidden className="text-lg shrink-0">{cat?.icon ?? "📋"}</span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink truncate">
              {item.ticker === "*" ? "All holdings" : item.ticker}
            </p>
            <p className="text-[11px] uppercase tracking-wide text-caption">
              {cat?.label ?? item.category}
            </p>
          </div>
        </div>
        <time className="text-xs text-caption shrink-0" dateTime={item.event_at ?? undefined}>
          {formatDate(item.event_at)}
        </time>
      </header>
      <p className="text-sm font-medium text-ink leading-snug">{item.headline}</p>
      <p className="text-sm text-caption leading-relaxed">{item.detail}</p>
      {item.ticker !== "*" && (
        <div className="pt-1">
          <Link
            href={`/stocks/${encodeURIComponent(item.ticker)}`}
            className="text-xs font-semibold text-blue-600 hover:text-tone-info-fg"
          >
            View analysis →
          </Link>
        </div>
      )}
    </article>
  )
}

export interface UpdatesFeedProps {
  /** Initial selected filter — defaults to "all". */
  initialCategory?: FilterValue
}

export default function UpdatesFeed({ initialCategory = "all" }: UpdatesFeedProps) {
  const [filter, setFilter] = useState<FilterValue>(initialCategory)
  const [page, setPage] = useState(0)

  const queryKey = useMemo(
    () => ["portfolio-updates", filter, page] as const,
    [filter, page],
  )

  const { data, isLoading, isError } = useQuery({
    queryKey,
    queryFn: () =>
      getPortfolioUpdates({
        category: filter === "all" ? undefined : filter,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    staleTime: 60_000,
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const hasMore = (page + 1) * PAGE_SIZE < total

  return (
    <section className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4" aria-label="Portfolio updates">
      {/* Left filter sidebar */}
      <nav aria-label="Filter updates by category" className="md:sticky md:top-4 self-start">
        <ul className="flex md:flex-col gap-1 overflow-x-auto md:overflow-visible -mx-1 px-1 pb-1 md:pb-0">
          {CATEGORY_OPTIONS.map((opt) => {
            const active = filter === opt.value
            return (
              <li key={opt.value} className="shrink-0 md:shrink">
                <button
                  type="button"
                  onClick={() => { setFilter(opt.value); setPage(0) }}
                  aria-pressed={active}
                  className={
                    "w-full text-left text-sm font-medium px-3 py-2 rounded-lg transition flex items-center gap-2 " +
                    (active
                      ? "bg-tone-info-bg text-tone-info-fg ring-1 ring-blue-200 dark:bg-blue-950 dark:text-blue-300"
                      : "text-caption hover:bg-surface dark:hover:bg-gray-800")
                  }
                >
                  <span aria-hidden className="text-base">{opt.icon}</span>
                  <span className="truncate">{opt.label}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </nav>

      {/* Feed column */}
      <div className="space-y-3" data-testid="updates-feed">
        {isError && (
          <div className="rounded-xl border border-red-100 bg-tone-bad-bg dark:border-red-900 dark:bg-red-950 p-4 text-sm text-tone-bad-fg dark:text-red-300">
            Couldn&rsquo;t load updates. Please retry in a moment.
          </div>
        )}
        {isLoading && (
          <div className="space-y-3" aria-busy="true" aria-label="Loading updates">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton rounded-xl h-[120px]" />
            ))}
          </div>
        )}
        {!isLoading && !isError && items.length === 0 && (
          <div className="rounded-xl border border-dashed border-gray-200 dark:border-gray-700 p-8 text-center">
            <p className="text-sm text-caption">{EMPTY_COPY[filter]}</p>
          </div>
        )}
        {!isLoading && !isError && items.length > 0 && (
          <>
            {/* Motion: 30ms inter-row stagger on entrance. Wrapper key
                changes when the page advances so newly loaded rows get
                their own entrance treatment rather than re-running the
                full list animation. */}
            <RevealStagger
              key={page}
              staggerMs={items.length <= MAX_STAGGER_ROWS ? 30 : 0}
              className="space-y-3"
            >
              {items.map((it) => (
                <FeedRow key={it.id} item={it} />
              ))}
            </RevealStagger>
            {hasMore && (
              <div className="pt-2">
                <PressScale>
                  <button
                    type="button"
                    onClick={() => setPage((p) => p + 1)}
                    className="w-full text-sm font-semibold text-blue-600 hover:text-tone-info-fg py-2 rounded-lg border border-tone-info-bd dark:border-blue-800"
                  >
                    Load more
                  </button>
                </PressScale>
              </div>
            )}
            <p className="text-[11px] text-caption text-center pt-1">
              Showing {items.length} of {total.toLocaleString("en-IN")} updates
            </p>
          </>
        )}
      </div>
    </section>
  )
}
