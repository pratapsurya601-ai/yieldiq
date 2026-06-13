/**
 * /funds — mutual-fund browse hub.
 *
 * Server component. Reads `q` (search scheme name / AMC) and `category`
 * from searchParams, fetches the filtered scheme list + the category
 * chips, and renders a card grid linking into the detail page. Search
 * GET-submits back to this route (not the stock search). No advisory
 * copy — only AMC-published category labels and the SEBI Riskometer
 * chip. Past-performance disclaimer at the foot of the page.
 */
import Link from "next/link"

import { fetchFundCategoriesSSR, fetchFundListSSR } from "@/lib/api"
import type { FundListItem, FundRiskometerLevel } from "@/types/api"
import AmcAvatar from "@/components/common/AmcAvatar"
import { HoverCard, RevealStagger } from "@/components/motion"
import FundsSearchInput from "./FundsSearchInput"

const RISKOMETER_COLORS: Record<FundRiskometerLevel, { bg: string; text: string; label: string }> = {
  Low: { bg: "bg-emerald-100", text: "text-emerald-800", label: "Low" },
  LowToModerate: { bg: "bg-lime-100", text: "text-lime-800", label: "Low to Moderate" },
  Moderate: { bg: "bg-yellow-100", text: "text-yellow-800", label: "Moderate" },
  ModeratelyHigh: { bg: "bg-amber-100", text: "text-amber-900", label: "Moderately High" },
  High: { bg: "bg-orange-100", text: "text-orange-900", label: "High" },
  VeryHigh: { bg: "bg-red-100", text: "text-red-800", label: "Very High" },
}

const MAX_CHIPS = 14

function FundCard({ fund }: { fund: FundListItem }) {
  const risk = fund.riskometer_level ? RISKOMETER_COLORS[fund.riskometer_level] : null
  return (
    <HoverCard className="rounded-lg">
      <Link
        href={`/funds/${encodeURIComponent(fund.scheme_code)}`}
        className="block rounded-lg border border-border bg-raised p-4"
      >
        <div className="flex items-center gap-2">
          <AmcAvatar amc={fund.amc} size="sm" />
          <span className="truncate text-xs text-caption">{fund.amc}</span>
        </div>
        <div className="mt-1.5 line-clamp-2 text-sm font-semibold text-ink">
          {fund.scheme_name}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {fund.category ? (
            <span className="rounded-full bg-tone-info-bg px-2 py-0.5 text-[11px] font-medium text-tone-info-fg">
              {fund.category}
            </span>
          ) : null}
          {risk ? (
            <span
              className={`rounded-full ${risk.bg} ${risk.text} px-2 py-0.5 text-[11px] font-medium`}
            >
              {risk.label}
            </span>
          ) : null}
          {fund.plan ? (
            <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] font-medium text-body">
              {fund.plan}
            </span>
          ) : null}
        </div>
      </Link>
    </HoverCard>
  )
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

  const chips = categories.slice(0, MAX_CHIPS)
  const filtered = Boolean(q || category)

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          Mutual Funds
        </h1>
        <p className="mt-1 text-sm text-caption">
          Read-only NAV history, benchmark-relative returns, and risk metrics for
          Indian mutual-fund schemes.
        </p>
      </header>

      <FundsSearchInput defaultQuery={q} />

      {chips.length > 0 ? (
        <div className="mb-5 flex flex-wrap gap-1.5">
          <CategoryChip href="/funds" label="All" active={!category} />
          {chips.map((c) => (
            <CategoryChip
              key={c.category}
              href={`/funds?category=${encodeURIComponent(c.category)}`}
              label={c.category}
              count={c.count}
              active={category === c.category}
            />
          ))}
        </div>
      ) : null}

      {funds.length === 0 ? (
        <div className="rounded-lg border border-border bg-raised p-6 text-sm text-caption">
          {filtered
            ? "No schemes match this search. Try a different name, AMC, or category."
            : "Fund data is being ingested. Check back shortly."}
        </div>
      ) : (
        <>
          <div className="mb-3 text-xs text-caption">
            Showing {funds.length} of {total.toLocaleString("en-IN")}
            {filtered ? " matching" : ""} schemes.
          </div>
          <RevealStagger
            className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
            staggerMs={15}
          >
            {funds.map((f) => (
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
