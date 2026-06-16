/**
 * /funds — research-grade mutual-fund SCREENER.
 *
 * Redesign (2026-06-16): the old "browse HUB" (animated category mosaic,
 * fund-house rail, Schemes A–Z sample grid, duplicate chip rows, animated
 * hero stat strip) is retired in favour of a single, restrained screener
 * modeled on global research leaders (Morningstar / Yahoo Finance) and
 * Groww: a thin header + result count, one horizontal FILTER BAR
 * (Category / Risk / Fund House dropdowns + quick pills + Clear all), and
 * ONE sortable table — Fund · Category · 1Y/3Y/5Y/10Y · YieldIQ Score ·
 * Expense · Risk. Multi-year returns are ANNUALIZED (per annum), the
 * global-research convention.
 *
 * This server component does only the FIRST-PAGE SSR fetch (fast first
 * paint) and parses the SSR `searchParams` for the initial filter/sort
 * state, then hands everything to the client <FundScreener>, which owns
 * all interaction (filter, sort, debounced search, pagination) and mirrors
 * state back to the URL via router.replace — no useSearchParams (avoids
 * the Vercel prerender Suspense bailout flagged in root CLAUDE.md).
 *
 * No advisory copy — only AMC-published category labels, the SEBI
 * Riskometer chip, and factual return/score/cost columns. Past-performance
 * disclaimer at the foot.
 */
import type { Metadata } from "next"

import {
  fetchFundAmcsSSR,
  fetchFundCategoriesSSR,
  fetchFundListSSR,
} from "@/lib/api"
import type { FundListItem, FundListSort, FundSortOrder } from "@/types/api"
import FundScreener from "./FundScreener"

export const revalidate = 300

const PAGE_SIZE = 25

// Sort keys the screener understands; anything else falls back to default.
const VALID_SORTS: ReadonlySet<FundListSort> = new Set<FundListSort>([
  "name",
  "score",
  "ret_1y",
  "ret_3y",
  "ret_5y",
  "ret_10y",
  "ter",
])

export const metadata: Metadata = {
  title: "Mutual Fund Screener — Returns, Score & Cost | YieldIQ",
  description:
    "Screen 14,000+ Indian mutual fund schemes in one sortable table: annualized 1Y/3Y/5Y/10Y returns, YieldIQ Fund Score, expense ratio and SEBI Riskometer — facts, no fund picks.",
  alternates: { canonical: "/funds" },
  openGraph: {
    title: "Mutual Fund Screener — Returns, Score & Cost | YieldIQ",
    description:
      "Filter and sort 14,000+ Indian mutual fund schemes by annualized returns, YieldIQ Fund Score, expense ratio and risk.",
    url: "https://yieldiq.in/funds",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Mutual Fund Screener — Returns, Score & Cost | YieldIQ",
    description:
      "Filter and sort 14,000+ Indian mutual fund schemes by annualized returns, YieldIQ Fund Score and cost.",
  },
}

interface Props {
  searchParams: Promise<{
    q?: string
    category?: string
    risk?: string
    amc?: string
    sort?: string
    order?: string
  }>
}

export default async function FundsScreenerPage({ searchParams }: Props) {
  const sp = await searchParams
  const q = typeof sp.q === "string" ? sp.q : ""
  const category = typeof sp.category === "string" ? sp.category : ""
  const risk = typeof sp.risk === "string" ? sp.risk : ""
  const amc = typeof sp.amc === "string" ? sp.amc : ""
  const sort: FundListSort =
    typeof sp.sort === "string" && VALID_SORTS.has(sp.sort as FundListSort)
      ? (sp.sort as FundListSort)
      : "score"
  const order: FundSortOrder = sp.order === "asc" ? "asc" : "desc"

  // First page only — the client screener fetches every subsequent page
  // and re-fetches on filter/sort changes. Categories + AMCs power the
  // filter-bar dropdowns. All three degrade to empty on backend miss.
  const [{ funds, total }, { categories }, { amcs }] = await Promise.all([
    fetchFundListSSR(PAGE_SIZE, q || undefined, category || undefined, {
      sort,
      order,
      risk: risk || undefined,
      amc: amc || undefined,
      offset: 0,
    }),
    fetchFundCategoriesSSR(),
    fetchFundAmcsSSR(),
  ])

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6 lg:px-8">
      <FundScreener
        initialFunds={funds as FundListItem[]}
        initialTotal={total}
        initialQuery={q}
        initialCategory={category}
        initialRisk={risk}
        initialAmc={amc}
        initialSort={sort}
        initialOrder={order}
        categories={categories}
        amcs={amcs}
      />

      <footer className="rounded-lg border border-tone-warn-bd bg-tone-warn-bg p-4 text-xs leading-relaxed text-tone-warn-fg">
        Past performance is not indicative of future returns. Returns shown
        for 3Y, 5Y and 10Y windows are annualized (per annum). Mutual fund
        investments are subject to market risks; read all scheme-related
        documents carefully.
      </footer>
    </main>
  )
}
