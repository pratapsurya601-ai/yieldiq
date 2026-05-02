import type { Metadata } from "next"
import Link from "next/link"

/**
 * /methodology/accuracy — Backtested Fair-Value Accuracy Dashboard.
 *
 * Server-rendered. Hits /api/v1/public/accuracy and renders the
 * aggregate hit rate of the model's fair-value calls vs the actual
 * price 12 months later.
 *
 * Until ~Q3 2026 most numeric fields will be null because we only
 * began nightly snapshots in May 2026 — the dataset needs 12 months
 * of runway. The page is intentionally honest about that: an empty
 * state explains "Building backtest dataset, first meaningful
 * results: Q3 2026" instead of fabricating numbers.
 *
 * Visual conventions match /methodology and /methodology/performance:
 *   - hero max-w-3xl, content max-w-4xl
 *   - editorial serif for display
 *   - semantic color tokens (no hardcoded hex)
 *   - server component, no "use client"
 *
 * Sibling of /methodology/performance, which already covers the
 * *quarterly* return-vs-benchmark retrospective. This page covers a
 * different question: how close was our FAIR VALUE NUMBER itself to
 * the price 12 months later (a model-calibration question, not a
 * stock-picking question).
 */

export const dynamic = "force-static"
export const revalidate = 21600 // 6h, matches API s-maxage

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://api.yieldiq.in"

type VerdictBucket = {
  count: number
  median_return_12mo: number | null
}

type AccuracyPayload = {
  computed_at: string
  lookback_months: number
  tickers_evaluated: number
  median_fv_error_pct: number | null
  hit_rate_within_20pct: number | null
  hit_rate_within_50pct: number | null
  directional_accuracy: number | null
  by_verdict: {
    undervalued: VerdictBucket
    overvalued: VerdictBucket
    fairly_valued: VerdictBucket
  }
  data_caveat: string
}

export function generateMetadata(): Metadata {
  const title =
    "Fair-Value Accuracy — How close was our FV to the actual price?"
  const description =
    "Backtested accuracy of YieldIQ's fair-value estimates. We snapshot every " +
    "FV computation nightly and, 12 months later, compare it to the actual " +
    "price. Hit rate, error distribution, directional accuracy."
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

function formatPct(value: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—"
  }
  return `${value.toFixed(digits)}%`
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

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/30 p-8 text-center">
      <div className="font-serif text-xl text-foreground">
        Building backtest dataset
      </div>
      <p className="mx-auto mt-3 max-w-xl text-sm text-muted-foreground">
        We started snapshotting every fair-value computation nightly in
        May 2026. After 12 months of runway we&rsquo;ll be able to show
        a defensible hit rate. First meaningful results: Q3 2026.
      </p>
    </div>
  )
}

export default async function AccuracyPage() {
  const data = await fetchAccuracy()
  const meaningful = (data?.tickers_evaluated ?? 0) >= 100

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
          dedicated <code className="rounded bg-muted px-1 py-0.5 text-[0.85em]">fair_value_history</code>{" "}
          table. After 12 months we know, for each ticker, how close
          our number was to the actual price &mdash; and we publish
          the hit rate without spin.
        </p>
      </header>

      {/* Caveat */}
      {data?.data_caveat ? (
        <div className="mx-auto mt-8 max-w-3xl rounded-md border border-border bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          <strong className="font-semibold">Caveat: </strong>
          {data.data_caveat}
        </div>
      ) : null}

      {/* Headline metrics */}
      <section className="mt-10">
        <h2 className="font-serif text-xl text-foreground">
          Headline metrics
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Lookback window: {data?.lookback_months ?? 12} months.
          Tickers evaluated: <strong>{data?.tickers_evaluated ?? 0}</strong>.
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
            <EmptyState />
          </div>
        )}
      </section>

      {/* By verdict */}
      <section className="mt-12">
        <h2 className="font-serif text-xl text-foreground">
          Returns by verdict
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          For each verdict we issued ~12 months ago, what was the
          median 12-month price return?
        </p>
        <div className="mt-5 overflow-hidden rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">Verdict</th>
                <th className="px-4 py-3 font-medium">Tickers</th>
                <th className="px-4 py-3 font-medium">Median 12mo return</th>
              </tr>
            </thead>
            <tbody>
              {(["undervalued", "fairly_valued", "overvalued"] as const).map(
                (v) => {
                  const bucket =
                    data?.by_verdict?.[v] ?? {
                      count: 0,
                      median_return_12mo: null,
                    }
                  return (
                    <tr key={v} className="border-t border-border">
                      <td className="px-4 py-3 capitalize text-foreground">
                        {v.replace("_", " ")}
                      </td>
                      <td className="px-4 py-3 text-foreground">
                        {bucket.count}
                      </td>
                      <td className="px-4 py-3 text-foreground">
                        {formatPct(bucket.median_return_12mo, 1)}
                      </td>
                    </tr>
                  )
                },
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          A model that adds value should show:
          undervalued return &gt; fairly_valued return &gt; overvalued
          return. We will publish whether that ordering holds &mdash;
          either way &mdash; once the dataset is mature.
        </p>
      </section>

      {/* What "right" means */}
      <section className="mt-12 rounded-lg border border-border bg-card p-6">
        <h2 className="font-serif text-xl text-foreground">
          What &ldquo;right&rdquo; means here
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-muted-foreground">
          <li>
            <strong>FV error</strong> is{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-[0.85em]">
              |FV_then − Price_now| / Price_now
            </code>
            . Median, not mean &mdash; one mis-tagged stock cannot
            move the headline.
          </li>
          <li>
            <strong>Hit rate (±20%)</strong> is the share of tickers
            where the FV we computed 12 months ago landed within 20%
            of the actual current price. A passive null model
            (FV = price) would score 100% on this metric &mdash; so
            we also publish &hellip;
          </li>
          <li>
            <strong>Directional accuracy.</strong> A stock we called{" "}
            <em>undervalued</em> should outperform (return &gt; +5%);
            an <em>overvalued</em> call should under-perform (return
            &lt; &minus;5%); a <em>fairly valued</em> call should drift
            (|return| &le; 10%). The directional metric is the only
            one that genuinely tests stock-picking skill.
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
