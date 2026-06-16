/**
 * /funds — mutual-fund browse HUB.
 *
 * Server component. Reads `q` (search scheme name / AMC) and `category`
 * from searchParams. Two states:
 *
 *   • BARE (no q, no category) — the redesigned hub: an editorial hero
 *     with animated identity counters, the funds-scoped search, a
 *     curated equity-first chip row, the animated category mosaic
 *     (true census), a fund-house rail, a self-hiding riskometer
 *     spectrum, and a sample "Schemes A–Z" card grid. Rich on first
 *     paint — never an empty "search to browse" prompt.
 *
 *   • FILTERED (q and/or category) — the results view: the matched
 *     schemes as rich FundCards (YieldIQ Fund Score, 1Y return, expense
 *     ratio, Riskometer), with the active chips highlighted.
 *
 * Redesign (2026-06-16): the hub LEADS with real content built only
 * from identity fields that fill at scale (name / AMC / category /
 * riskometer / total), so the default landing is full of browsable
 * facts. No advisory copy — only AMC-published category labels and the
 * SEBI Riskometer chip; past-performance disclaimer at the foot.
 */
import type { Metadata } from "next"
import Link from "next/link"

import { fetchFundCategoriesSSR, fetchFundListSSR } from "@/lib/api"
import { RevealStagger } from "@/components/motion"
import FundsSearchInput from "./FundsSearchInput"
import FundsHero from "./FundsHero"
import FundsHubBrowse from "./FundsHubBrowse"
import FundCard, { type FundCardItem, compactCategory } from "./FundCard"

export const revalidate = 300

const MAX_CHIPS = 12

// ── Equity-first curated chips ──────────────────────────────────────
// Retail searches "large cap"/"index"/"ELSS", not "Equity Scheme -
// Large Cap Fund". Each friendly chip resolves to the REAL raw AMFI
// category string the API filters on (exact `category =` match) by
// keyword-matching the categories endpoint at request time — so we
// never hard-code a string that might drift from what's in the DB.
interface FriendlyChip {
  label: string
  match: (raw: string) => boolean
}

const FRIENDLY_CHIPS: FriendlyChip[] = [
  { label: "Large Cap", match: (r) => r.includes("large cap") && !r.includes("mid") },
  { label: "Mid Cap", match: (r) => r.includes("mid cap") && !r.includes("large") },
  { label: "Small Cap", match: (r) => r.includes("small cap") },
  { label: "Flexi Cap", match: (r) => r.includes("flexi cap") },
  { label: "ELSS (Tax)", match: (r) => r.includes("elss") },
  { label: "Index", match: (r) => r.includes("index") },
  { label: "Hybrid", match: (r) => r.includes("hybrid") },
  { label: "Debt", match: (r) => r.includes("debt") || r.includes("income") },
]

/** Pick the real AMFI category string for a friendly chip, or null. */
function resolveFriendly(
  chip: FriendlyChip,
  rawCategories: string[],
): string | null {
  for (const raw of rawCategories) {
    if (chip.match(raw.toLowerCase())) return raw
  }
  return null
}

function CategoryChip({
  href,
  label,
  active,
}: {
  href: string
  label: string
  active: boolean
}) {
  return (
    <Link
      href={href}
      className={`rounded-full border px-3 py-1 text-[12px] font-medium transition-colors ${
        active
          ? "border-tone-info-bd bg-tone-info-bg text-tone-info-fg"
          : "border-border bg-raised text-caption hover:bg-surface hover:text-ink"
      }`}
    >
      {label}
    </Link>
  )
}

// Route-specific metadata. Without this the /funds hub inherited the
// root layout's home-page title + OpenGraph tags (audit 2026-06-14),
// so every fund-section share/SEO surface read "DCF Stock Analysis".
export const metadata: Metadata = {
  title: "Mutual Funds — NAV, Returns & Costs | YieldIQ",
  description:
    "Browse 14,000+ Indian mutual fund schemes. Trailing returns, NAV-vs-benchmark, risk metrics and expense costs — facts, no fund picks.",
  alternates: { canonical: "/funds" },
  openGraph: {
    title: "Mutual Funds — NAV, Returns & Costs | YieldIQ",
    description:
      "Browse 14,000+ Indian mutual fund schemes with trailing returns, NAV-vs-benchmark and cost transparency.",
    url: "https://yieldiq.in/funds",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Mutual Funds — NAV, Returns & Costs | YieldIQ",
    description:
      "Browse 14,000+ Indian mutual fund schemes with trailing returns and cost transparency.",
  },
}

interface Props {
  searchParams: Promise<{ q?: string; category?: string }>
}

export default async function FundsLanding({ searchParams }: Props) {
  const sp = await searchParams
  const q = typeof sp.q === "string" ? sp.q : ""
  const category = typeof sp.category === "string" ? sp.category : ""
  const filtered = Boolean(q || category)

  // The categories census powers the curated chips, the raw-category chip
  // row, and the mosaic. The fund list is fetched in BOTH states: in the
  // filtered state it returns the matched cards; in the bare/hub state it
  // returns a sample (for the "A–Z" grid + AMC/risk facets) AND — the
  // reason it now runs in the bare state too — the true `total`, the
  // deduped COUNT(*) of the active universe (`_fetch_index_total`,
  // dedupe_plans=True). That is the honest "Schemes tracked" headline; the
  // old hero summed the category census (category-tagged subset, one row
  // per plan/option permutation), which was both partial AND inflated and
  // contradicted the "14,000+" meta. One list call now serves both the
  // hero number and the hub sample, so the bare state does not double-fetch.
  const [{ funds, total }, { categories }] = await Promise.all([
    fetchFundListSSR(48, q || undefined, category || undefined),
    fetchFundCategoriesSSR(),
  ])

  const cards = funds as FundCardItem[]

  const rawCategories = categories.map((c) => c.category)
  const friendly = FRIENDLY_CHIPS.map((chip) => ({
    label: chip.label,
    value: resolveFriendly(chip, rawCategories),
  })).filter((c): c is { label: string; value: string } => c.value !== null)

  const rawChips = categories.slice(0, MAX_CHIPS)

  // Identity aggregates for the hero.
  //
  // `totalSchemes` is the TRUE universe size — the deduped COUNT(*) the
  // list endpoint returns (`total`), the same number the live site
  // advertises ("browse ~14,000 schemes") and the meta promises. It is NOT
  // the category-census sum (that counts only category-tagged rows, one per
  // plan/option permutation — both partial and inflated).
  const totalSchemes = total
  const categoryCount = categories.length
  // Census is ordered biggest-bucket-first, so [0] names the largest
  // category. We surface its LABEL only — never a per-category scheme
  // count: the census count is non-deduped/partial and would contradict
  // the deduped "Showing N of M" the user lands on after clicking through
  // (honesty invariant — see CategoryMosaic). The relative ordering is
  // still a fair basis for "which category is largest".
  const largestCategory = categories[0] ?? null
  const largestCategoryLabel = largestCategory
    ? compactCategory(largestCategory.category)
    : ""

  // The curated + raw chip rows, reused in both states (above the search
  // in filtered state, below the hero in the hub state).
  const chipRows =
    friendly.length > 0 || rawChips.length > 0 ? (
      <div className="space-y-1.5">
        {friendly.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            <CategoryChip href="/funds" label="All Funds" active={!category} />
            {friendly.map((c) => (
              <CategoryChip
                key={c.label}
                href={`/funds?category=${encodeURIComponent(c.value)}`}
                label={c.label}
                active={category === c.value}
              />
            ))}
          </div>
        ) : null}
        {rawChips.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {rawChips.map((c) => (
              // No per-chip count: the census count is non-deduped/partial
              // and would contradict the deduped "Showing N of M" the chip
              // navigates to (honesty invariant — see CategoryMosaic).
              <CategoryChip
                key={c.category}
                href={`/funds?category=${encodeURIComponent(c.category)}`}
                label={compactCategory(c.category)}
                active={category === c.category}
              />
            ))}
          </div>
        ) : null}
      </div>
    ) : null

  return (
    <main className="mx-auto max-w-6xl space-y-12 px-4 py-8 sm:px-6 md:space-y-16 lg:px-8">
      {!filtered ? (
        // ── HUB (bare landing) ──────────────────────────────────────
        <>
          <FundsHero
            total={totalSchemes}
            categoryCount={categoryCount}
            largestCategoryLabel={largestCategoryLabel}
          >
            <div className="space-y-3">
              <FundsSearchInput defaultQuery={q} category={category} />
              {chipRows}
            </div>
          </FundsHero>

          <FundsHubBrowse
            categories={categories.map((c) => ({
              category: c.category,
              count: c.count,
            }))}
            sample={cards}
          />
        </>
      ) : (
        // ── FILTERED (results view) ─────────────────────────────────
        <div className="space-y-6">
          <header className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
              Mutual Funds
            </h1>
            <p className="text-sm text-caption">
              Browse Indian mutual-fund schemes with YieldIQ Fund Score, 1-year
              return, expense ratio and the SEBI Riskometer — facts, no fund
              picks.
            </p>
          </header>

          <div className="space-y-3">
            <FundsSearchInput defaultQuery={q} category={category} />
            {chipRows}
          </div>

          {cards.length === 0 ? (
            <div className="rounded-lg border border-border bg-raised p-6 text-sm text-caption">
              No schemes match this search. Try a different name, AMC, or
              category.
            </div>
          ) : (
            <>
              <div className="text-xs text-caption" aria-live="polite">
                Showing {cards.length} of {total.toLocaleString("en-IN")} matching
                schemes.
              </div>
              {/*
                threshold={0} is load-bearing: this grid is tall, so
                RevealStagger's default 0.15 in-view threshold never fits
                in the viewport at the top and every card would stay
                opacity-0 on load (memory #939). With 0 the stagger
                reveals as soon as the grid's top edge enters view.
              */}
              <RevealStagger
                className="grid items-stretch gap-3 sm:grid-cols-2 lg:grid-cols-3"
                staggerMs={15}
                threshold={0}
              >
                {cards.map((f) => (
                  <FundCard key={f.scheme_code} fund={f} />
                ))}
              </RevealStagger>
            </>
          )}
        </div>
      )}

      <footer className="rounded-lg border border-tone-warn-bd bg-tone-warn-bg p-4 text-xs leading-relaxed text-tone-warn-fg">
        Past performance is not indicative of future returns. Mutual fund
        investments are subject to market risks; read all scheme-related
        documents carefully.
      </footer>
    </main>
  )
}
