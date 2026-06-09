import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"

/**
 * /calibration/[slug] — Per-sector deep-dive.
 *
 * Server component. Fetches the same calibration payload as the
 * parent /calibration page, finds the row whose slug matches the
 * URL parameter, and renders an extended single-sector view:
 *
 *   - Headline numbers (median |error|, p90 |error|, direction
 *     accuracy, signed median)
 *   - Observation context (ticker count + last observation date)
 *   - Per-ticker placeholder block describing the coming drill-down
 *     surface (the per-ticker API expansion is its own ticket)
 *
 * SEBI: same honest-numbers discipline as the parent page. No
 * advisory verbs, no quality claims.
 */

export const dynamic = "force-static"
export const revalidate = 86400 // 24h, matches API + parent page

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://api.yieldiq.in"

type SectorStat = {
  sector: string
  ticker_count: number
  observation_count: number
  median_abs_error_pct: number
  median_signed_error_pct: number
  p90_abs_error_pct: number
  direction_accuracy_pct: number
  last_observation_date: string
}

type CalibrationPayload = {
  sectors: SectorStat[]
  meta: {
    generated_at: string
    lookback_days: number
    min_observations: number
    quarantine_policy: string
    sector_count: number
  }
}

function sectorSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
}

function fmtPct(v: number | null | undefined, signed = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  if (signed) {
    const sign = v > 0 ? "+" : ""
    return `${sign}${v.toFixed(1)}%`
  }
  return `${v.toFixed(1)}%`
}

async function fetchCalibration(): Promise<CalibrationPayload | null> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/public/calibration/sectors`,
      { next: { revalidate: 86400 } },
    )
    if (!res.ok) return null
    return (await res.json()) as CalibrationPayload
  } catch {
    return null
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>
}): Promise<Metadata> {
  const { slug } = await params
  const data = await fetchCalibration()
  const stat = data?.sectors.find((s) => sectorSlug(s.sector) === slug)
  const sectorName = stat?.sector || slug
  return {
    title: `Calibration — ${sectorName} | YieldIQ`,
    description: `Per-sector calibration accuracy for ${sectorName}. Median fair-value error, 90th-percentile error, and direction-accuracy over the last 90 days.`,
    alternates: {
      canonical: `https://yieldiq.in/calibration/${slug}`,
    },
  }
}

export default async function SectorCalibrationPage({
  params,
}: {
  params: Promise<{ slug: string }>
}) {
  const { slug } = await params
  const data = await fetchCalibration()
  const stat = data?.sectors.find((s) => sectorSlug(s.sector) === slug)

  if (!stat) {
    notFound()
  }

  const meta = data?.meta

  return (
    <main className="min-h-screen bg-[color:var(--color-bg)] text-[color:var(--color-body)]">
      {/* Breadcrumb */}
      <section className="max-w-5xl mx-auto px-4 pt-8 pb-4">
        <nav className="text-xs text-[color:var(--color-caption)]">
          <Link
            href="/calibration"
            className="hover:text-[color:var(--color-ink)]"
          >
            Calibration
          </Link>
          <span className="mx-2">/</span>
          <span className="text-[color:var(--color-body)]">
            {stat.sector}
          </span>
        </nav>
      </section>

      {/* Hero */}
      <section className="max-w-5xl mx-auto px-4 pb-8">
        <p className="text-xs uppercase tracking-wider text-[color:var(--color-caption)] mb-3">
          Sector calibration
        </p>
        <h1
          className="font-[family-name:var(--font-editorial)] text-4xl text-[color:var(--color-ink)] mb-3"
          style={{ lineHeight: 1.1 }}
        >
          {stat.sector}
        </h1>
        <p className="text-sm text-[color:var(--color-caption)]">
          {stat.observation_count} observation
          {stat.observation_count === 1 ? "" : "s"} across{" "}
          {stat.ticker_count} ticker
          {stat.ticker_count === 1 ? "" : "s"} · most recent observation{" "}
          {stat.last_observation_date || "—"}
        </p>
      </section>

      {/* Headline stat grid */}
      <section className="max-w-5xl mx-auto px-4 pb-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6">
          <p className="text-xs uppercase tracking-wider text-[color:var(--color-caption)] mb-2">
            Median |Error|
          </p>
          <p className="font-[family-name:var(--font-display)] text-3xl text-[color:var(--color-ink)] tabular-nums">
            {fmtPct(stat.median_abs_error_pct)}
          </p>
          <p className="text-xs text-[color:var(--color-caption)] mt-1">
            typical FV-to-price gap
          </p>
        </div>
        <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6">
          <p className="text-xs uppercase tracking-wider text-[color:var(--color-caption)] mb-2">
            P90 |Error|
          </p>
          <p className="font-[family-name:var(--font-display)] text-3xl text-[color:var(--color-ink)] tabular-nums">
            {fmtPct(stat.p90_abs_error_pct)}
          </p>
          <p className="text-xs text-[color:var(--color-caption)] mt-1">
            9 in 10 observations within
          </p>
        </div>
        <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6">
          <p className="text-xs uppercase tracking-wider text-[color:var(--color-caption)] mb-2">
            Median Signed Error
          </p>
          <p className="font-[family-name:var(--font-display)] text-3xl text-[color:var(--color-ink)] tabular-nums">
            {fmtPct(stat.median_signed_error_pct, true)}
          </p>
          <p className="text-xs text-[color:var(--color-caption)] mt-1">
            positive = FV runs high
          </p>
        </div>
        <div className="rounded-xl border-2 border-[color:var(--color-brand)] bg-[color:var(--color-surface)] p-6">
          <p className="text-xs uppercase tracking-wider text-[color:var(--color-caption)] mb-2">
            Direction Accuracy
          </p>
          <p className="font-[family-name:var(--font-display)] text-3xl text-[color:var(--color-ink)] tabular-nums">
            {fmtPct(stat.direction_accuracy_pct)}
          </p>
          <p className="text-xs text-[color:var(--color-caption)] mt-1">
            90-day verdict vs actual
          </p>
        </div>
      </section>

      {/* Per-ticker placeholder block */}
      <section className="max-w-5xl mx-auto px-4 pb-10">
        <h2 className="font-[family-name:var(--font-display)] text-xl text-[color:var(--color-ink)] mb-4">
          Per-ticker breakdown
        </h2>
        <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6 text-sm">
          <p className="text-[color:var(--color-caption)] leading-relaxed">
            Per-ticker calibration tables roll out as the nightly
            fair-value history accumulates enough observations per name.
            For now the sector-level numbers above describe how the
            engine&rsquo;s {stat.sector} valuations have tracked actual
            prices over the last {meta?.lookback_days ?? 90} days.
          </p>
        </div>
      </section>

      {/* What this means */}
      <section className="max-w-5xl mx-auto px-4 pb-16">
        <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6 text-sm space-y-3">
          <p>
            <span className="font-medium text-[color:var(--color-ink)]">
              What does this mean?
            </span>{" "}
            Median |Error| is the typical FV-to-actual-price gap in this
            sector. Direction Accuracy is how often the engine&rsquo;s
            90-day-out verdict matched the actual price movement
            direction. Both metrics improve with more observations.
          </p>
          <p>
            <span className="font-medium text-[color:var(--color-ink)]">
              What&rsquo;s excluded.
            </span>{" "}
            {meta?.quarantine_policy ||
              "Pre-manifest-epoch rows and step-unverified rows are excluded by the at-rest quarantine gate."}
          </p>
          {meta ? (
            <p className="text-xs text-[color:var(--color-caption)]">
              Generated at{" "}
              {new Date(meta.generated_at).toISOString().slice(0, 16)}Z
            </p>
          ) : null}
        </div>
      </section>

      {/* Disclosure */}
      <section className="max-w-5xl mx-auto px-4 pb-16">
        <div className="rounded-lg border border-[color:var(--color-warning)] bg-[color:var(--color-surface)] p-4 text-xs text-[color:var(--color-body)] space-y-2">
          <p className="font-semibold text-[color:var(--color-ink)]">
            Disclosure
          </p>
          <p>
            Calibration metrics describe how the engine has tracked
            actual market prices over the past {meta?.lookback_days ?? 90}{" "}
            days. They are not a forecast and they are not investment
            advice. YieldIQ is not SEBI-registered as an investment
            adviser or research analyst.
          </p>
        </div>
      </section>
    </main>
  )
}
