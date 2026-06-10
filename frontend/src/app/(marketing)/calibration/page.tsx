import type { Metadata } from "next"
import Link from "next/link"
import { Reveal } from "@/components/motion"
import CalibrationSectorsTable from "./CalibrationSectorsTable"

/**
 * /calibration — Per-sector backtest accuracy public page (T1.2).
 *
 * Server component. Fetches /api/v1/public/calibration/sectors and
 * renders a per-sector calibration table:
 *
 *   Sector | Tickers | Observations | Median |Error| | P90 |Error|
 *          | Direction Accuracy
 *
 * Distinct from /yiq50-backtest (Day-89 basket-rotation backtest)
 * and /methodology/accuracy (admin-grade fair-value calibration
 * dashboard). This page is the public "how well does our FV match
 * the actual price, sector by sector?" trust surface.
 *
 * SEBI: every field is a factual calibration metric. No advisory
 * vocabulary. No quality claims of any kind — the copy is neutral
 * throughout and the empty state is honest about coverage gaps.
 */

export const dynamic = "force-static"
export const revalidate = 86400 // 24h, matches API s-maxage

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://api.yieldiq.in"

export const metadata: Metadata = {
  title: "Calibration — how accurate is the YieldIQ engine? | YieldIQ",
  description:
    "Per-sector calibration accuracy over the last 90 days, generated nightly. Median fair-value error, 90th-percentile error, and direction-accuracy by sector.",
  alternates: { canonical: "https://yieldiq.in/calibration" },
  openGraph: {
    title: "How accurate is the YieldIQ valuation engine?",
    description:
      "Per-sector calibration accuracy over the last 90 days — median FV-to-price gap and direction-accuracy, sector by sector.",
    url: "https://yieldiq.in/calibration",
    siteName: "YieldIQ",
    type: "website",
  },
}

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
    direction_bands: {
      below_mos_threshold_pct: number
      above_mos_threshold_pct: number
      forward_return_threshold_pct: number
      near_band_return_pct: number
    }
  }
}

// sectorSlug / fmtPct moved into CalibrationSectorsTable (2026-06-11)
// — the page no longer renders rows directly so the helpers are
// owned by the row component that uses them.

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

export default async function CalibrationPage() {
  const data = await fetchCalibration()
  const sectors = data?.sectors ?? []
  const meta = data?.meta

  return (
    <main className="min-h-screen bg-[color:var(--color-bg)] text-[color:var(--color-body)]">
      {/* Hero */}
      <section className="max-w-5xl mx-auto px-4 pt-12 pb-8">
        <p className="text-xs uppercase tracking-wider text-[color:var(--color-caption)] mb-3">
          Calibration
        </p>
        <h1
          className="font-[family-name:var(--font-editorial)] text-4xl sm:text-5xl text-[color:var(--color-ink)] mb-4"
          style={{ lineHeight: 1.1 }}
        >
          How accurate is our valuation engine?
        </h1>
        <p className="text-base sm:text-lg max-w-3xl">
          Below is per-sector calibration over the last{" "}
          {meta?.lookback_days ?? 90} days, generated nightly. Sectors with
          under {meta?.min_observations ?? 30} observations are excluded.
          Every number is computed from the same fair-value history the
          platform uses internally — the public view sees what the
          internal view sees, with quarantined rows removed.
        </p>
      </section>

      {/* Table or empty state.
          Motion (2026-06-11): table → CalibrationSectorsTable client
          component that owns the per-row stagger + per-row HoverCard
          treatment without breaking table semantics. Empty state
          wrapped in <Reveal> so the "still being built" callout
          fades in instead of snapping. */}
      <section className="max-w-5xl mx-auto px-4 pb-10">
        {sectors.length > 0 ? (
          <CalibrationSectorsTable sectors={sectors} />
        ) : (
          <Reveal>
            <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6 text-sm">
              <p className="font-semibold text-[color:var(--color-ink)] mb-2">
                Calibration coverage is still being built
              </p>
              <p className="text-[color:var(--color-caption)] leading-relaxed">
                We need at least {meta?.min_observations ?? 30} observations
                per sector before we publish a calibration number — anything
                less is noise. Coverage grows as the nightly fair-value
                history accumulates. Check back in a few weeks.
              </p>
            </div>
          </Reveal>
        )}
      </section>

      {/* What this means.
          Motion (2026-06-11): <Reveal> primitive — fades in on
          viewport entry. Same primitive as the empty-state callout,
          so both callouts share the same entrance curve. */}
      <section className="max-w-5xl mx-auto px-4 pb-16">
        <Reveal>
          <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6 text-sm space-y-3">
            <p>
              <span className="font-medium text-[color:var(--color-ink)]">
                What does this mean?
              </span>{" "}
              Median |Error| is the typical FV-to-actual-price gap.
              Direction Accuracy is how often our 90-day-out verdict matched
              the actual price movement direction. Both metrics improve
              with more observations.
            </p>
            <p>
              <span className="font-medium text-[color:var(--color-ink)]">
                How it&rsquo;s computed.
              </span>{" "}
              For each (ticker, day) row in the fair-value history table,
              we compare the engine&rsquo;s fair value to the actual market
              price on that day, and to the actual price ~90 days later.
              The median, 90th percentile, and direction-hit rate are
              aggregated per sector.
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
                {" · "}
                {meta.sector_count} sector
                {meta.sector_count === 1 ? "" : "s"} above the{" "}
                {meta.min_observations}-observation threshold
              </p>
            ) : null}
          </div>
        </Reveal>
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
          <p>
            For methodology details see{" "}
            <Link
              className="underline text-[color:var(--color-brand)]"
              href="/methodology"
            >
              /methodology
            </Link>
            .
          </p>
        </div>
      </section>
    </main>
  )
}
