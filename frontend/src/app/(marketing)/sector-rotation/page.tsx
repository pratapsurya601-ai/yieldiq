// Sector rotation lens (2026-06-07) — `/sector-rotation`.
//
// Server component. Fetches /api/v1/public/sector-rotation at build /
// revalidate time and renders a heatmap-style grid of cohort sectors
// ranked by current median margin-of-safety, plus a "top 5 most
// discounted" callout.
//
// This page is read-only over the Day-108c cohort aggregator — no FV
// math, no advice vocabulary. The wording is
// strictly descriptive ("the model's median MoS estimate"), matching
// the backend disclosure surfaced in `notes`.
import type { Metadata } from "next"
import Link from "next/link"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

type SectorRow = {
  slug: string
  display_name: string
  ticker_count: number
  median_mos_pct: number | null
  median_fv_to_price_ratio: number | null
  median_score: number | null
  verdict_distribution: Record<string, number>
  pct_undervalued: number | null
  top_discounts: Array<{
    ticker: string
    name: string
    mos_pct: number
    verdict: string | null
  }>
}

type RotationPayload = {
  sectors: SectorRow[]
  ranked_slugs: string[]
  computed_at: string
  universe_ticker_count: number
  notes: string
}

export const metadata: Metadata = {
  title: "Sector rotation — Indian markets fundamentals lens | YieldIQ",
  description:
    "Cross-sector valuation snapshot. Median margin of safety, percentage of undervalued names, and most-discounted constituents for each YieldIQ cohort. Updated daily.",
  openGraph: {
    title: "Sector rotation — Indian markets fundamentals lens",
    description:
      "Daily snapshot of where the YieldIQ model is pricing fundamentals at a discount across sectors.",
    url: "https://yieldiq.in/sector-rotation",
    siteName: "YieldIQ",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Sector rotation — YieldIQ",
    description:
      "Daily snapshot of where the YieldIQ model is pricing fundamentals at a discount across sectors.",
  },
  alternates: { canonical: "https://yieldiq.in/sector-rotation" },
}

async function fetchRotation(): Promise<RotationPayload | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/sector-rotation`, {
      // 30-min revalidate — matches the backend edge cache window.
      next: { revalidate: 1800 },
    })
    if (!res.ok) return null
    return (await res.json()) as RotationPayload
  } catch {
    return null
  }
}

function pct(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  const sign = n > 0 ? "+" : ""
  return `${sign}${n.toFixed(digits)}%`
}

function num(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  return n.toFixed(digits)
}

// Heatmap colour for a sector card based on the median MoS.
// Tailwind classes only — no inline styles, no client JS. The bands
// are coarse (3 buckets each side) so the eye can scan the grid as a
// heatmap without parsing exact percentages. Null sectors get a
// neutral surface so they read as "no data" not "fair value".
function tileTone(mos: number | null): string {
  if (mos === null || mos === undefined || Number.isNaN(mos)) {
    return "border-border bg-bg dark:bg-surface"
  }
  if (mos >= 20) return "border-green-300 bg-green-50 dark:bg-green-900/20"
  if (mos >= 5) return "border-green-200 bg-green-50/60 dark:bg-green-900/10"
  if (mos > -5) return "border-blue-200 bg-blue-50/60 dark:bg-blue-900/10"
  if (mos > -20) return "border-rose-200 bg-rose-50/60 dark:bg-rose-900/10"
  return "border-rose-300 bg-rose-50 dark:bg-rose-900/20"
}

export default async function SectorRotationPage() {
  const data = await fetchRotation()

  // JSON-LD — descriptive Dataset, no claims about returns.
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Dataset",
    name: "YieldIQ sector rotation lens",
    description:
      "Cross-sector snapshot of median margin-of-safety and undervalued-name share for the YieldIQ cohort universe.",
    url: "https://yieldiq.in/sector-rotation",
    creator: {
      "@type": "Organization",
      name: "YieldIQ",
      url: "https://yieldiq.in",
    },
    variableMeasured: [
      "Median margin of safety",
      "Percentage of undervalued constituents",
      "Sector cohort size",
    ],
  }

  if (!data) {
    return (
      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-10 sm:py-14">
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        <h1 className="font-display text-3xl sm:text-4xl font-black text-ink tracking-tight mb-3">
          Sector rotation
        </h1>
        <p className="text-caption italic">
          The rotation snapshot is being computed. Check back shortly.
        </p>
      </main>
    )
  }

  // Build the rendered list in the rank order the backend returned —
  // never re-sort on the client. The backend's stable tie-break is
  // the source of truth so cached payloads and live payloads render
  // identically.
  const bySlug = new Map(data.sectors.map(s => [s.slug, s]))
  const ranked: SectorRow[] = data.ranked_slugs
    .map(slug => bySlug.get(slug))
    .filter((s): s is SectorRow => Boolean(s))

  // Top 5 most discounted sectors (those with positive median MoS,
  // in rank order). Used for the lead callout. We pick from the
  // already-ranked list rather than recomputing.
  const topSectors = ranked
    .filter(s => s.median_mos_pct !== null && s.median_mos_pct > 0)
    .slice(0, 5)

  return (
    <main className="max-w-5xl mx-auto px-4 sm:px-6 py-10 sm:py-14">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <header className="mb-8">
        <p className="text-[11px] font-bold text-caption uppercase tracking-widest mb-2">
          Indian markets — fundamentals lens
        </p>
        <h1 className="font-display text-3xl sm:text-4xl font-black text-ink tracking-tight mb-3">
          Sector rotation
        </h1>
        <p className="text-body text-base max-w-2xl leading-relaxed">
          Where is the YieldIQ model currently pricing fundamentals at a
          discount? Each cohort is summarised by the median margin of
          safety of its constituents. Updated daily.
        </p>
      </header>

      {/* Stat strip */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
        <Stat label="Sectors covered" value={String(ranked.length)} />
        <Stat
          label="Constituents in universe"
          value={String(data.universe_ticker_count)}
        />
        <Stat
          label="Most-discounted sector"
          value={
            topSectors[0]
              ? `${topSectors[0].display_name} ${pct(topSectors[0].median_mos_pct)}`
              : "—"
          }
        />
        <Stat
          label="Updated"
          value={formatComputedAt(data.computed_at)}
        />
      </section>

      {/* Top 5 most discounted callout. Renders descriptively — "median
          MoS shows X% upside vs price". */}
      {topSectors.length > 0 && (
        <section className="mb-10">
          <h2 className="text-lg font-semibold text-ink mb-3">
            Most discounted sectors right now
          </h2>
          <ol className="grid gap-2 md:grid-cols-5">
            {topSectors.map((s, idx) => (
              <li key={s.slug}>
                <Link
                  href={`/sector/${s.slug}`}
                  className="block bg-bg dark:bg-surface border border-border rounded-xl p-3 hover:border-brand hover:shadow-sm transition"
                >
                  <div className="text-[10px] uppercase tracking-wide text-caption mb-1">
                    #{idx + 1}
                  </div>
                  <div className="font-semibold text-ink mb-1">
                    {s.display_name}
                  </div>
                  <div className="text-sm text-green-700 dark:text-green-400 tabular-nums">
                    Median MoS {pct(s.median_mos_pct)}
                  </div>
                  <div className="text-xs text-caption tabular-nums">
                    {pct(s.pct_undervalued, 0)} of cohort undervalued
                  </div>
                </Link>
              </li>
            ))}
          </ol>
        </section>
      )}

      {/* Heatmap-style grid. Tone is driven by median_mos_pct so a
          green band reads as "model says discount", a red band as
          "model says premium". Click → existing sector landing page. */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold text-ink mb-3">
          All cohorts, ranked by median margin of safety
        </h2>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ranked.map(s => (
            <li key={s.slug}>
              <Link
                href={`/sector/${s.slug}`}
                className={`block border rounded-xl p-4 hover:shadow-sm transition ${tileTone(s.median_mos_pct)}`}
              >
                <div className="flex items-baseline justify-between mb-2">
                  <p className="font-semibold text-ink">{s.display_name}</p>
                  <span className="text-xs text-caption tabular-nums">
                    {s.ticker_count} {s.ticker_count === 1 ? "ticker" : "tickers"}
                  </span>
                </div>

                <div className="flex items-baseline gap-3 mb-2">
                  <span className="text-2xl font-bold text-ink tabular-nums">
                    {pct(s.median_mos_pct)}
                  </span>
                  <span className="text-xs text-caption">median MoS</span>
                </div>

                <div className="text-xs text-caption mb-3 tabular-nums">
                  {s.pct_undervalued === null
                    ? "Cohort data pending"
                    : `${pct(s.pct_undervalued, 0)} of cohort undervalued`}
                </div>

                {s.top_discounts.length > 0 && (
                  <div className="border-t border-border pt-2">
                    <div className="text-[10px] uppercase tracking-wide text-caption mb-1">
                      Largest cohort discounts
                    </div>
                    <ul className="text-xs space-y-0.5">
                      {s.top_discounts.map(t => (
                        <li
                          key={t.ticker}
                          className="flex justify-between gap-2"
                        >
                          <span className="text-ink truncate">{t.name}</span>
                          <span className="text-green-700 dark:text-green-400 tabular-nums shrink-0">
                            {pct(t.mos_pct)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <aside className="mt-12 rounded-lg border border-border bg-bg dark:bg-surface p-4">
        <h3 className="text-sm font-semibold text-ink mb-2">How to read this</h3>
        <ul className="text-sm space-y-1 text-body leading-relaxed">
          <li>
            Each tile shows the <span className="font-semibold">median margin of safety</span> of the
            cohort — the model&apos;s fair value minus current price, as a
            percentage of fair value.
          </li>
          <li>
            Greener tiles mean the cohort&apos;s median constituent is trading
            below the model&apos;s estimate of fair value; redder tiles mean
            the opposite.
          </li>
          <li>
            &quot;Cohort data pending&quot; means we don&apos;t yet have enough
            cached analyses for that cohort to compute a median — not that the
            sector is at fair value.
          </li>
        </ul>
        <p className="text-xs text-caption mt-3 leading-relaxed">
          {/* sebi-allow: recommendation */}
          {data.notes}
        </p>
      </aside>
    </main>
  )
}

// ── helpers ──────────────────────────────────────────────────────

function formatComputedAt(iso: string): string {
  // Compact "YYYY-MM-DD" — the rotation lens is daily, so a clock
  // time would imply false precision. Falls back to the raw string
  // when the input isn't parseable so we never throw at render time.
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toISOString().slice(0, 10)
  } catch {
    return iso
  }
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border bg-bg dark:bg-surface px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-caption">
        {label}
      </div>
      <div className="text-base font-semibold text-ink tabular-nums">
        {value}
      </div>
    </div>
  )
}
