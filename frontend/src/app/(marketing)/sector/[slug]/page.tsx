// Day-108c (2026-05-23) — sector landing page (`/sector/<slug>`).
//
// Server component. Fetches /api/v1/public/sector/<slug> at build /
// revalidate time, renders SEO metadata + JSON-LD + a stat panel +
// the SectorTable client component. Returns 404 for unknown slugs.
import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import SectorTable from "./SectorTable"
import { NumberFlip, RevealStagger } from "@/components/motion"
import NumberContext from "@/components/common/NumberContext"
import {
  SECTOR_PAGE_SLUGS,
  SECTOR_DISPLAY,
  isSectorSlug,
} from "./sectorCohorts"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

type SectorPayload = {
  slug: string
  display_name: string
  cohort_tickers: string[]
  cohort_notes: string
  // Task #123: manifest_ref (e.g. "Day-107a") is no longer surfaced
  // on this public, anon-facing surface. The field may be omitted
  // entirely by the backend; keep the optional type for backwards
  // compatibility with any in-flight cached payload.
  manifest_ref?: string | null
  aggregates: {
    ticker_count: number
    median_fair_value_to_price_ratio: number | null
    median_score: number | null
    median_mos_pct: number | null
    median_pe: number | null
    median_roe: number | null
    verdict_distribution: Record<string, number>
  }
  tickers: Array<{
    ticker: string
    name: string
    score: number | null
    verdict: string | null
    fv: number | null
    price: number | null
    mos_pct: number | null
    pe_ratio: number | null
    roe: number | null
    fv_to_price: number | null
  }>
}

export async function generateStaticParams() {
  return SECTOR_PAGE_SLUGS.map(slug => ({ slug }))
}

export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> }
): Promise<Metadata> {
  const { slug } = await params
  if (!isSectorSlug(slug)) return { title: "Sector not found | YieldIQ" }
  const display = SECTOR_DISPLAY[slug]
  const title = `${display} valuations — DCF cohort dashboard | YieldIQ`
  const description = `${display} sector valuation snapshot. Cohort DCF assumptions, fair value vs price ratios, percentile distribution, and per-ticker drilldown. Updated daily.`
  const url = `https://yieldiq.in/sector/${slug}`
  return {
    title,
    description,
    openGraph: { title, description, url, siteName: "YieldIQ", type: "website" },
    twitter: { card: "summary_large_image", title, description },
    alternates: { canonical: url },
  }
}

async function fetchSector(slug: string): Promise<SectorPayload | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/sector/${slug}`, {
      // 30-min revalidate — matches backend edge cache window.
      next: { revalidate: 1800 },
    })
    if (!res.ok) return null
    return (await res.json()) as SectorPayload
  } catch {
    return null
  }
}

// pct/num helpers removed 2026-06-11 — Stat now uses <NumberFlip>
// directly, which formats and animates in one component. Pages that
// need a non-animated string still have lib/utils formatters.

export default async function SectorPage(
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params
  if (!isSectorSlug(slug)) notFound()
  const data = await fetchSector(slug)
  const display = SECTOR_DISPLAY[slug]

  const verdictDist = data?.aggregates?.verdict_distribution ?? {
    undervalued: 0, fairly_valued: 0, overvalued: 0,
  }

  // JSON-LD structured data — Article + Dataset so Google recognises
  // this as a sector summary page.
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Dataset",
    name: `${display} sector valuation cohort`,
    description: data?.cohort_notes ?? `Valuation snapshot of the ${display} cohort.`,
    url: `https://yieldiq.in/sector/${slug}`,
    creator: { "@type": "Organization", name: "YieldIQ", url: "https://yieldiq.in" },
    variableMeasured: [
      "Fair value", "Margin of safety", "YieldIQ score", "Verdict",
    ],
  }

  if (!data) {
    return (
      <main className="max-w-5xl mx-auto px-4 py-10">
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
        <h1 className="text-3xl font-semibold text-ink mb-3">{display} valuations</h1>
        <p className="text-caption italic">
          Sector data is being computed. Check back shortly.
        </p>
      </main>
    )
  }

  return (
    <main className="max-w-5xl mx-auto px-4 py-10">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <header className="mb-6">
        <p className="text-xs uppercase tracking-wide text-caption mb-1">Sector landing page</p>
        <h1 className="text-3xl md:text-4xl font-semibold text-ink">
          {display} valuations
        </h1>
      </header>

      <section className="prose prose-sm max-w-none mb-8">
        <p className="text-ink leading-relaxed">{data.cohort_notes}</p>
      </section>

      {/* Hide tiles whose aggregate is null rather than rendering a bare
          em-dash next to populated tiles (audit 2026-05-26 P1). Tickers
          is always populated for any cohort that loads at all; the
          financial medians can legitimately be null when the underlying
          provider lags.

          Motion (2026-06-11): RevealStagger entrance + NumberFlip on
          each tile's numeric value. The flip honors reduced-motion via
          the primitive's internal hook. */}
      <RevealStagger
        as="section"
        className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-8"
        staggerMs={60}
      >
        <Stat
          label="Tickers"
          numericValue={data.aggregates.ticker_count}
          decimals={0}
        />
        {data.aggregates.median_mos_pct !== null && data.aggregates.median_mos_pct !== undefined && (
          <Stat
            label="Median MoS"
            numericValue={data.aggregates.median_mos_pct}
            decimals={1}
            suffix="%"
            context={cohortContext(data.aggregates.ticker_count)}
          />
        )}
        {data.aggregates.median_score !== null && data.aggregates.median_score !== undefined && (
          <Stat
            label="Median score"
            numericValue={data.aggregates.median_score}
            decimals={0}
            context={cohortContext(data.aggregates.ticker_count)}
          />
        )}
        {data.aggregates.median_pe !== null && data.aggregates.median_pe !== undefined && (
          <Stat
            label="Median P/E"
            numericValue={data.aggregates.median_pe}
            decimals={1}
            context={cohortContext(data.aggregates.ticker_count)}
          />
        )}
        {data.aggregates.median_roe !== null && data.aggregates.median_roe !== undefined && (
          <Stat
            label="Median ROE"
            numericValue={data.aggregates.median_roe}
            decimals={1}
            suffix="%"
            context={cohortContext(data.aggregates.ticker_count)}
          />
        )}
      </RevealStagger>

      <section className="mb-8">
        <h2 className="text-lg font-semibold text-ink mb-3">Verdict distribution</h2>
        {/* Motion: stagger the three verdict pills in. staggerMs is
            tight (40ms) — three chips feel sluggish on a longer stagger. */}
        <RevealStagger
          className="flex flex-wrap gap-3 text-sm"
          staggerMs={40}
          direction="up"
        >
          <Pill kind="undervalued" count={verdictDist.undervalued ?? 0} />
          <Pill kind="fairly_valued" count={verdictDist.fairly_valued ?? 0} />
          <Pill kind="overvalued" count={verdictDist.overvalued ?? 0} />
        </RevealStagger>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-semibold text-ink mb-3">Cohort constituents</h2>
        <SectorTable rows={data.tickers} />
      </section>

      <aside className="mt-12 rounded-lg border border-gray-200 bg-gray-50 p-4">
        <h3 className="text-sm font-semibold text-ink mb-2">Related</h3>
        <ul className="text-sm space-y-1">
          {/* Task #123 (2026-05-23): manifest_ref intentionally not
              rendered on this public surface — see
              backend/services/cache_invalidation_manifest.py
              `_public_description` for the sanitization contract. */}
          <li>
            <Link href="/help/sectors-and-cohorts" className="text-blue-700 hover:underline">
              How sector cohorts work
            </Link>
          </li>
          <li>
            <Link href="/methodology" className="text-blue-700 hover:underline">
              YieldIQ methodology
            </Link>
          </li>
        </ul>
        <p className="text-xs text-caption mt-3">{/* sebi-allow: recommendation */}
          Sector medians describe the cohort math, not a recommendation.
          Each per-ticker page links to the full DCF with assumptions.
        </p>
      </aside>
    </main>
  )
}

/**
 * Number-comprehension context (2026-06-11): each median tile says
 * how wide the cohort behind it is. Uses ticker_count, which is
 * already in the aggregates payload — no invented data.
 */
function cohortContext(tickerCount: number | null | undefined): string | null {
  if (typeof tickerCount !== "number" || !Number.isFinite(tickerCount) || tickerCount <= 0) {
    return null
  }
  return `${tickerCount} ${tickerCount === 1 ? "stock" : "stocks"}`
}

function Stat({
  label,
  numericValue,
  decimals,
  suffix,
  context,
}: {
  label: string
  numericValue: number
  decimals: number
  suffix?: string
  /** e.g. "12 stocks" — rendered as a muted "across N stocks" caption. */
  context?: string | null
}) {
  // Motion (2026-06-11): NumberFlip tweens the value on first view.
  // Reduced-motion users see the static number — the primitive
  // skips the tween internally.
  return (
    <div className="rounded border border-gray-200 bg-white px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-caption">{label}</div>
      <div className="text-lg font-semibold text-ink tabular-nums">
        <NumberFlip
          value={numericValue}
          decimals={decimals}
          suffix={suffix ?? ""}
        />
      </div>
      <NumberContext label="across" value={context} className="block mt-0.5 text-[10px]" />
    </div>
  )
}

function Pill({ kind, count }: { kind: "undervalued" | "fairly_valued" | "overvalued"; count: number }) {
  const map = {
    undervalued: { label: "Undervalued", cls: "bg-green-50 text-green-700 border-green-200" },
    fairly_valued: { label: "Fairly valued", cls: "bg-blue-50 text-blue-700 border-blue-200" },
    overvalued: { label: "Overvalued", cls: "bg-red-50 text-red-700 border-red-200" },
  }
  const { label, cls } = map[kind]
  return (
    <span className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border ${cls}`}>
      <span className="font-medium">{label}</span>
      {/* NumberFlip animates the count tween on first reveal. */}
      <NumberFlip value={count} decimals={0} className="tabular-nums" />
    </span>
  )
}
