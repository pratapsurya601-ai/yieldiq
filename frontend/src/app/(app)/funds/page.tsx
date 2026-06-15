/**
 * /funds — mutual-fund browse hub.
 *
 * Server component. Reads `q` (search scheme name / AMC) and `category`
 * from searchParams, fetches the filtered scheme list + the category
 * chips, and renders a rich card grid linking into the detail page.
 *
 * Redesign (2026-06-15): the hub now LEADS with what retail searches —
 * a curated equity-first chip row (Large Cap, Mid Cap, …, Debt) sits
 * above the raw AMFI-category chips, so users no longer land on
 * obscure debt schemes by default. Cards carry real numbers (YieldIQ
 * Fund Score, 1Y return, expense ratio, Riskometer) instead of being
 * click-to-learn stubs. Search filters live as you type (see
 * FundsSearchInput). No advisory copy — only AMC-published category
 * labels and the SEBI Riskometer chip; past-performance disclaimer at
 * the foot of the page.
 */
import type { Metadata } from "next"
import Link from "next/link"

import { fetchFundCategoriesSSR, fetchFundListSSR } from "@/lib/api"
import { RevealStagger } from "@/components/motion"
import FundsSearchInput from "./FundsSearchInput"
import FundCard, { type FundCardItem, compactCategory } from "./FundCard"

const MAX_CHIPS = 12

// ── Equity-first curated chips ──────────────────────────────────────
// Retail searches "large cap"/"index"/"ELSS", not "Equity Scheme -
// Large Cap Fund". Each friendly chip resolves to the REAL raw AMFI
// category string the API filters on (exact `category =` match) by
// keyword-matching the categories endpoint at request time — so we
// never hard-code a string that might drift from what's in the DB.
// `match` is tested against the lowercased raw category; the first
// matching raw category wins, and `exclude` guards against a broader
// keyword swallowing a narrower bucket (e.g. "cap" matching too much).
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
  count,
  active,
}: {
  href: string
  label: string
  count?: number
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
      {typeof count === "number" ? (
        <span className="ml-1 text-[11px] font-normal opacity-70">{count}</span>
      ) : null}
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

  const [{ funds, total }, { categories }] = await Promise.all([
    fetchFundListSSR(48, q || undefined, category || undefined),
    fetchFundCategoriesSSR(),
  ])

  // The list endpoint already returns the contract metrics per item
  // (ret_1y / yieldiq_fund_score / ter); widen to the card shape so the
  // cards can read them (see FundCard.FundCardItem).
  const cards = funds as FundCardItem[]

  const rawCategories = categories.map((c) => c.category)
  const friendly = FRIENDLY_CHIPS.map((chip) => ({
    label: chip.label,
    value: resolveFriendly(chip, rawCategories),
  })).filter((c): c is { label: string; value: string } => c.value !== null)

  // Raw AMFI chips, biggest buckets first, shown with compact labels.
  const rawChips = categories.slice(0, MAX_CHIPS)
  const filtered = Boolean(q || category)

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          Mutual Funds
        </h1>
        <p className="mt-1 text-sm text-caption">
          Browse Indian mutual-fund schemes with YieldIQ Fund Score, 1-year
          return, expense ratio and the SEBI Riskometer — facts, no fund picks.
        </p>
      </header>

      <FundsSearchInput defaultQuery={q} category={category} />

      {/* Equity-first curated chips — lead with what retail searches. */}
      {friendly.length > 0 ? (
        <div className="mb-3 flex flex-wrap gap-1.5">
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

      {/* Raw AMFI categories (compact labels), largest buckets first. */}
      {rawChips.length > 0 ? (
        <div className="mb-5 flex flex-wrap gap-1.5">
          {rawChips.map((c) => (
            <CategoryChip
              key={c.category}
              href={`/funds?category=${encodeURIComponent(c.category)}`}
              label={compactCategory(c.category)}
              count={c.count}
              active={category === c.category}
            />
          ))}
        </div>
      ) : null}

      {cards.length === 0 ? (
        <div className="rounded-lg border border-border bg-raised p-6 text-sm text-caption">
          {filtered
            ? "No schemes match this search. Try a different name, AMC, or category."
            : "Fund data is being ingested. Check back shortly."}
        </div>
      ) : (
        <>
          <div className="mb-3 text-xs text-caption">
            Showing {cards.length} of {total.toLocaleString("en-IN")}
            {filtered ? " matching" : ""} schemes.
          </div>
          {/*
            threshold={0} is load-bearing: this grid is ~16 rows tall, so
            RevealStagger's default 0.15 in-view threshold (15% of the
            wrapper) never fits in the viewport at the top — inView would
            never fire and every card would stay opacity-0 on load. With 0
            the stagger reveals as soon as the grid's top edge enters view
            (i.e. immediately). The cards are the page's primary content;
            they must not depend on a deep scroll to render.
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

      <footer className="mt-8 rounded-lg border border-tone-warn-bd bg-tone-warn-bg p-4 text-xs leading-relaxed text-tone-warn-fg">
        Past performance is not indicative of future returns. Mutual fund investments
        are subject to market risks; read all scheme-related documents carefully.
      </footer>
    </main>
  )
}
