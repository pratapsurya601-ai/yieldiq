import type { Metadata } from "next"
import Link from "next/link"

import {
  CalibrationScatter,
  ReturnAttributionBars,
  type CalibrationBucket,
  type ReturnAttributionDatum,
} from "./AccuracyCharts"

/**
 * /methodology/accuracy — Backtested Fair-Value Accuracy Dashboard.
 *
 * Server-rendered. Hits /api/v1/public/accuracy and renders four
 * datasets:
 *   1. Headline metrics (FV error, hit rate, directional accuracy).
 *   2. Directional accuracy by SEBI-vocabulary verdict band.
 *   3. Return attribution bars — mean 12mo return per band.
 *   4. Calibration scatter — MoS bucket → mean realized return.
 *
 * Honesty principles encoded in this page:
 *   - SEBI-safe vocabulary throughout (below_fair_value /
 *     near_fair_value / above_fair_value). Never "undervalued"/
 *     "overvalued" in user-visible copy.
 *   - "Insufficient history" gate: until 90+ snapshot days exist the
 *     numeric sections are replaced with a transparent empty state.
 *   - Hit rates are shown as-is. If a band performs worse than a coin
 *     flip we surface that — see the per-band table.
 *   - Sample size and data window are prominent above every chart so
 *     the reader never has to ask "across how many stocks?"
 *
 * Sibling of /methodology/performance, which covers the *quarterly*
 * return-vs-benchmark retrospective. This page asks a different
 * question: was our FV NUMBER calibrated to the price 12 months later?
 */

export const dynamic = "force-static"
export const revalidate = 21600 // 6h, matches API s-maxage

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://api.yieldiq.in"

// Minimum number of distinct snapshot days before we surface numeric
// metrics. Below this threshold the dashboard shows the empty state.
const MIN_DAYS_FOR_DASHBOARD = 90

type BandKey = "below_fair_value" | "near_fair_value" | "above_fair_value"

type DirectionalBand = {
  total: number
  correct: number
  hit_rate: number | null
}

type ReturnBand = {
  count: number
  mean_return_pct: number | null
  median_return_pct: number | null
}

type AccuracyPayload = {
  computed_at: string
  lookback_months: number
  tickers_evaluated: number
  snapshots_collected: number
  window_start: string | null
  window_end: string | null
  median_fv_error_pct: number | null
  hit_rate_within_20pct: number | null
  hit_rate_within_50pct: number | null
  directional_accuracy: number | null
  directional: {
    total: number
    directional_correct: number
    hit_rate: number | null
    by_band: Record<BandKey, DirectionalBand>
  }
  return_attribution: {
    by_band: Record<BandKey, ReturnBand>
    overall: ReturnBand
    monotonic: boolean | null
  }
  calibration: {
    buckets: CalibrationBucket[]
    monotonic: boolean | null
  }
  data_caveat: string
}

const BAND_LABEL: Record<BandKey, string> = {
  below_fair_value: "Below fair value",
  near_fair_value: "Near fair value",
  above_fair_value: "Above fair value",
}

const BAND_ORDER: BandKey[] = [
  "below_fair_value",
  "near_fair_value",
  "above_fair_value",
]

export function generateMetadata(): Metadata {
  const title =
    "Fair-Value Accuracy — How close was our FV to the actual price?"
  const description =
    "Backtested accuracy of YieldIQ's fair-value estimates. We snapshot every " +
    "FV computation nightly and, 12 months later, compare it to the actual " +
    "price. Directional hit rate by band, return attribution, calibration curve."
  return {
    title,
    description,
    alternates: {
      canonical: "https://yieldiq.in/methodology/accuracy",
    },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/methodology/accuracy",
      siteName: "YieldIQ",
      type: "article",
      locale: "en_IN",
      images: [
        {
          url: "https://yieldiq.in/icon-512.png",
          width: 512,
          height: 512,
          alt: "YieldIQ",
        },
      ],
    },
    twitter: {
      card: "summary",
      title,
      description,
      images: ["https://yieldiq.in/icon-512.png"],
    },
    robots: { index: true, follow: true },
  }
}

async function fetchAccuracy(): Promise<AccuracyPayload | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/accuracy`, {
      next: { revalidate: 21600 },
    })
    if (!res.ok) return null
    return (await res.json()) as AccuracyPayload
  } catch {
    return null
  }
}

function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—"
  }
  return `${value.toFixed(digits)}%`
}

function formatRate(rate: number | null, digits = 1): string {
  // hit_rate from /directional is 0..1; format as percent.
  if (rate === null || rate === undefined || Number.isNaN(rate)) return "—"
  return `${(rate * 100).toFixed(digits)}%`
}

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.valueOf())) return iso
  return d.toLocaleDateString("en-IN", {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

function daysBetween(a: string | null, b: string | null): number {
  if (!a || !b) return 0
  const da = new Date(a)
  const db = new Date(b)
  if (Number.isNaN(da.valueOf()) || Number.isNaN(db.valueOf())) return 0
  return Math.max(
    0,
    Math.round((db.valueOf() - da.valueOf()) / (1000 * 60 * 60 * 24)),
  )
}

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-2 font-serif text-3xl text-foreground">{value}</div>
      {hint ? (
        <div className="mt-2 text-xs text-muted-foreground">{hint}</div>
      ) : null}
    </div>
  )
}

function InsufficientHistory({
  daysCollected,
  windowStart,
  windowEnd,
}: {
  daysCollected: number
  windowStart: string | null
  windowEnd: string | null
}) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/30 p-8 text-center">
      <div className="font-serif text-xl text-foreground">
        Insufficient history
      </div>
      <p className="mx-auto mt-3 max-w-xl text-sm text-muted-foreground">
        We have <span className="font-semibold">{daysCollected}</span> day
        {daysCollected === 1 ? "" : "s"} of fair-value snapshots so far —
        we need at least <span className="font-semibold">{MIN_DAYS_FOR_DASHBOARD}</span> distinct
        snapshot days before publishing aggregate accuracy. The first
        meaningful 12-month evaluation lands once the snapshots that
        began in May 2026 mature in May 2027.
      </p>
      {windowStart && windowEnd ? (
        <p className="mx-auto mt-3 max-w-xl text-xs text-muted-foreground/80">
          Data window so far: {formatDate(windowStart)} —{" "}
          {formatDate(windowEnd)}
        </p>
      ) : null}
    </div>
  )
}

export default async function AccuracyPage() {
  const data = await fetchAccuracy()

  const windowDays = data
    ? Math.max(
        daysBetween(data.window_start, data.window_end) + 1,
        data.window_start && data.window_end ? 1 : 0,
      )
    : 0
  const meaningful =
    !!data && windowDays >= MIN_DAYS_FOR_DASHBOARD && data.tickers_evaluated >= 50

  const directional = data?.directional
  const attribution = data?.return_attribution
  const calibration = data?.calibration

  const attributionData: ReturnAttributionDatum[] = attribution
    ? BAND_ORDER.map((b) => ({
        band: b,
        count: attribution.by_band[b]?.count ?? 0,
        mean_return_pct: attribution.by_band[b]?.mean_return_pct ?? null,
        median_return_pct: attribution.by_band[b]?.median_return_pct ?? null,
      }))
    : []

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-12 md:py-16">
      {/* Hero */}
      <header className="mx-auto max-w-3xl">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          Methodology · Backtest
        </div>
        <h1 className="mt-3 font-serif text-3xl leading-tight text-foreground md:text-4xl">
          How accurate are our fair values?
        </h1>
        <p className="mt-4 text-base leading-relaxed text-muted-foreground">
          We snapshot every fair-value computation nightly to a
          dedicated{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-[0.85em]">
            fair_value_history
          </code>{" "}
          table. After 12 months we know, for each ticker, how the price
          actually moved — and we publish the hit rate without spin.
        </p>

        {/* Provenance strip — always visible, even when data is thin */}
        <dl className="mt-6 grid grid-cols-2 gap-4 rounded-md border border-border bg-card/50 p-4 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              Updated
            </dt>
            <dd className="mt-1 font-medium text-foreground">
              {data?.computed_at ? formatDate(data.computed_at) : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              Sample
            </dt>
            <dd className="mt-1 font-medium text-foreground">
              {data?.tickers_evaluated ?? 0} stock-months
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              Snapshots
            </dt>
            <dd className="mt-1 font-medium text-foreground">
              {data?.snapshots_collected?.toLocaleString("en-IN") ?? 0}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              Window
            </dt>
            <dd className="mt-1 text-xs font-medium text-foreground">
              {data?.window_start && data?.window_end
                ? `${formatDate(data.window_start)} → ${formatDate(data.window_end)}`
                : "—"}
            </dd>
          </div>
        </dl>
      </header>

      {/* Caveat */}
      {data?.data_caveat ? (
        <div className="mx-auto mt-8 max-w-3xl rounded-md border border-border bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          <span className="font-semibold">Caveat: </span>
          {data.data_caveat}
        </div>
      ) : null}

      {/* Headline metrics */}
      <section className="mt-10">
        <h2 className="font-serif text-xl text-foreground">
          Headline metrics
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Lookback window: {data?.lookback_months ?? 12} months. Tickers
          with both a T-12mo snapshot and a current price:{" "}
          <span className="font-semibold">{data?.tickers_evaluated ?? 0}</span>.
        </p>

        {meaningful ? (
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label="Median FV error"
              value={formatPct(data?.median_fv_error_pct ?? null)}
              hint="|FV − Price_now| / Price_now"
            />
            <MetricCard
              label="Hit rate (±20%)"
              value={formatPct(data?.hit_rate_within_20pct ?? null)}
              hint="FV within 20% of price 12mo later"
            />
            <MetricCard
              label="Hit rate (±50%)"
              value={formatPct(data?.hit_rate_within_50pct ?? null)}
              hint="FV within 50% of price 12mo later"
            />
            <MetricCard
              label="Directional accuracy"
              value={formatPct(data?.directional_accuracy ?? null)}
              hint="Verdict matched 12mo price direction"
            />
          </div>
        ) : (
          <div className="mt-6">
            <InsufficientHistory
              daysCollected={windowDays}
              windowStart={data?.window_start ?? null}
              windowEnd={data?.window_end ?? null}
            />
          </div>
        )}
      </section>

      {/* Directional accuracy by SEBI band */}
      <section className="mt-12">
        <h2 className="font-serif text-xl text-foreground">
          Directional accuracy by band
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          For each call we made ~12 months ago, did the price move the
          way our verdict implied?
        </p>
        <div className="mt-5 overflow-hidden rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">Verdict band</th>
                <th className="px-4 py-3 font-medium">Calls</th>
                <th className="px-4 py-3 font-medium">Correct</th>
                <th className="px-4 py-3 font-medium">Hit rate</th>
                <th className="px-4 py-3 font-medium">Vs coin flip</th>
              </tr>
            </thead>
            <tbody>
              {BAND_ORDER.map((b) => {
                const bucket = directional?.by_band[b] ?? {
                  total: 0,
                  correct: 0,
                  hit_rate: null,
                }
                const rate = bucket.hit_rate
                const vsCoin =
                  rate === null
                    ? "—"
                    : rate >= 0.5
                      ? `+${((rate - 0.5) * 100).toFixed(1)}pp`
                      : `${((rate - 0.5) * 100).toFixed(1)}pp`
                return (
                  <tr key={b} className="border-t border-border">
                    <td className="px-4 py-3 text-foreground">
                      {BAND_LABEL[b]}
                    </td>
                    <td className="px-4 py-3 text-foreground">
                      {bucket.total}
                    </td>
                    <td className="px-4 py-3 text-foreground">
                      {bucket.correct}
                    </td>
                    <td className="px-4 py-3 text-foreground">
                      {formatRate(rate)}
                    </td>
                    <td
                      className={`px-4 py-3 ${
                        rate === null
                          ? "text-muted-foreground"
                          : rate >= 0.5
                            ? "text-emerald-700 dark:text-emerald-400"
                            : "text-red-700 dark:text-red-400"
                      }`}
                    >
                      {vsCoin}
                    </td>
                  </tr>
                )
              })}
              <tr className="border-t border-border bg-muted/20 font-medium">
                <td className="px-4 py-3 text-foreground">Overall</td>
                <td className="px-4 py-3 text-foreground">
                  {directional?.total ?? 0}
                </td>
                <td className="px-4 py-3 text-foreground">
                  {directional?.directional_correct ?? 0}
                </td>
                <td className="px-4 py-3 text-foreground">
                  {formatRate(directional?.hit_rate ?? null)}
                </td>
                <td className="px-4 py-3 text-muted-foreground">—</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          A &ldquo;below fair value&rdquo; call counts as correct if the
          12mo return was &gt; +5%. &ldquo;Above fair value&rdquo;
          counts as correct if the return was &lt; &minus;5%.
          &ldquo;Near fair value&rdquo; counts as correct if |return| ≤
          10% (i.e. the stock did not deviate sharply in either
          direction). Bands that perform worse than 50% are shown in red
          — we do not hide them.
        </p>
      </section>

      {/* Return attribution bars */}
      <section className="mt-12">
        <h2 className="font-serif text-xl text-foreground">
          Return attribution
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Mean 12-month price return per verdict band. A model that adds
          value is expected to show below-FV &gt; near-FV &gt; above-FV.
        </p>
        <div className="mt-5 rounded-lg border border-border bg-card p-4">
          <ReturnAttributionBars data={attributionData} />
        </div>
        {attribution?.monotonic === false ? (
          <p className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
            <span className="font-semibold">Honesty note:</span> the expected ordering
            (below-FV &gt; near-FV &gt; above-FV) does <em>not</em> apply
            in the current sample. We publish that as-is.
          </p>
        ) : attribution?.monotonic === true ? (
          <p className="mt-3 text-xs text-muted-foreground">
            Expected ordering holds in the current sample (below-FV
            mean &gt; near-FV mean &gt; above-FV mean).
          </p>
        ) : null}
      </section>

      {/* Calibration scatter */}
      <section className="mt-12">
        <h2 className="font-serif text-xl text-foreground">
          Calibration curve
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Each point is one MoS bucket at T-12mo. The y-axis is the
          mean realized 12-month return for stocks in that bucket. A
          well-calibrated model produces a roughly monotonic upward
          pattern across the bucket midpoints.
        </p>
        <div className="mt-5 rounded-lg border border-border bg-card p-4">
          <CalibrationScatter data={calibration?.buckets ?? []} />
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          If higher MoS at T-12mo did <em>not</em> predict higher
          realized return, the model has no edge and we will say so
          here.
        </p>
      </section>

      {/* What "right" means */}
      <section className="mt-12 rounded-lg border border-border bg-card p-6">
        <h2 className="font-serif text-xl text-foreground">
          What &ldquo;right&rdquo; means here
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-muted-foreground">
          <li>
            <span className="font-semibold">FV error</span> is{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-[0.85em]">
              |FV_then − Price_now| / Price_now
            </code>
            . Median, not mean — one mis-tagged stock cannot move the
            headline.
          </li>
          <li>
            <span className="font-semibold">Hit rate (±20%)</span> is the share of tickers
            where the FV we computed 12 months ago landed within 20%
            of the actual current price. A passive null model (FV =
            price) would score 100% on this metric — so we also
            publish &hellip;
          </li>
          <li>
            <span className="font-semibold">Directional accuracy.</span> A stock we called
            below fair value tends to deliver positive 12-month
            return (return &gt; +5%); an above-fair-value call tends
            to deliver negative return (return &lt; &minus;5%); a
            near-fair-value call tends to drift (|return| ≤ 10%).
            This is the only metric that genuinely tests stock-picking
            skill.
          </li>
          <li>
            <span className="font-semibold">Calibration.</span> If our model says 30% MoS
            and the realized 12mo return averages 30% across that
            bucket, the model is well-calibrated. If 30% MoS averages
            5%, the model is over-confident. Either way, we plot it.
          </li>
          <li>
            We publish the numbers without spin. If the model is
            indistinguishable from random, you&rsquo;ll see that here.
          </li>
        </ul>
      </section>

      {/* Footer nav */}
      <footer className="mt-12 border-t border-border pt-6 text-sm text-muted-foreground">
        See also:{" "}
        <Link
          href="/methodology"
          className="text-foreground underline underline-offset-2"
        >
          full methodology
        </Link>
        {" · "}
        <Link
          href="/methodology/performance"
          className="text-foreground underline underline-offset-2"
        >
          quarterly performance retrospective
        </Link>
        {data?.computed_at ? (
          <span className="ml-2 block text-xs text-muted-foreground/70 md:ml-0 md:mt-2">
            Computed at {new Date(data.computed_at).toISOString()}
          </span>
        ) : null}
      </footer>
    </main>
  )
}
