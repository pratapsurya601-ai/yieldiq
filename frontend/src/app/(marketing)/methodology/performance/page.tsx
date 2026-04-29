import type { Metadata } from "next"
import Link from "next/link"

/**
 * /methodology/performance — Public Performance Retrospective.
 *
 * Server-rendered page that hits the public retrospective endpoint
 * and renders the summary plus winners/losers + caveat header.
 *
 * SCAFFOLDING: in this PR the page renders against the SAMPLE
 * payload that the backend endpoint returns (is_sample=true). The
 * layout is the deliverable; numbers will be real once Phase 2
 * backfills model_predictions_history.
 *
 * Voice: analyst appendix, plain. Same visual conventions as
 * /methodology — hero max-w-3xl, prose max-w-4xl, semantic tokens
 * only. No marketing language. The caveat at top is a SEBI-driven
 * non-negotiable.
 */

export const dynamic = "force-static"
export const revalidate = 3600  // 1h, matches the API's s-maxage

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://api.yieldiq.in"

type Outcome = { ticker: string; return_pct: number }

type SectorRow = {
  sector: string
  benchmark_ticker: string
  n: number
  mean_return: number
  benchmark_return: number
  outperform_rate: number
}

type Summary = {
  period: { start: string; end: string; label: string }
  window_days: number
  mos_threshold: number
  n_predictions: number
  mean_return: number | null
  median_return: number | null
  hit_rate: number | null
  outperform_rate: number | null
  benchmark: { ticker: string; return_pct: number; mode?: string }
  winners: Outcome[]
  losers: Outcome[]
  sector_breakdown?: SectorRow[] | null
  is_sample?: boolean
  last_updated?: string | null
  disclaimer?: string
}

export function generateMetadata(): Metadata {
  const title = "Performance Retrospective — How YieldIQ's calls have done"
  const description =
    "Quarterly retrospective of YieldIQ model predictions vs realised returns. " +
    "Methodology, hit rates, winners and losers, and the Nifty benchmark."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/methodology/performance" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/methodology/performance",
      siteName: "YieldIQ",
      type: "article",
      locale: "en_IN",
    },
    robots: { index: true, follow: true },
  }
}

async function fetchSummary(
  period: string,
  windowDays: number,
  benchmark: string = "auto",
): Promise<Summary> {
  const url = `${API_BASE}/api/v1/public/retrospective?period=${encodeURIComponent(period)}&window=${windowDays}&benchmark=${encodeURIComponent(benchmark)}`
  try {
    const res = await fetch(url, { next: { revalidate: 3600 } })
    if (!res.ok) throw new Error(`status ${res.status}`)
    const json = (await res.json()) as Summary
    // Defensive: ensure required arrays exist so downstream renders
    // never crash on partial DB responses.
    return {
      ...json,
      winners: Array.isArray(json.winners) ? json.winners : [],
      losers: Array.isArray(json.losers) ? json.losers : [],
    }
  } catch {
    // Hard fallback — keeps the static build green even if the API
    // is down. Mirrors the SAMPLE the API itself currently returns.
    return SAMPLE_FALLBACK
  }
}

function fmtLastUpdated(iso: string | null | undefined): string | null {
  if (!iso) return null
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return null
    return d.toLocaleDateString("en-IN", {
      year: "numeric", month: "short", day: "numeric",
    })
  } catch {
    return null
  }
}

const SAMPLE_FALLBACK: Summary = {
  period: { start: "2025-04-01", end: "2025-06-30", label: "Q1FY26" },
  window_days: 90,
  mos_threshold: 30.0,
  n_predictions: 47,
  mean_return: 12.4,
  median_return: 9.8,
  hit_rate: 0.638,
  outperform_rate: 0.553,
  benchmark: { ticker: "NIFTY500.NS", return_pct: 6.2 },
  winners: [
    { ticker: "POWERGRID.NS",  return_pct: 38.2 },
    { ticker: "BHARTIARTL.NS", return_pct: 31.7 },
    { ticker: "SUNPHARMA.NS",  return_pct: 27.4 },
    { ticker: "ITC.NS",        return_pct: 24.1 },
    { ticker: "HDFCBANK.NS",   return_pct: 21.8 },
  ],
  losers: [
    { ticker: "ZOMATO.NS",    return_pct: -18.3 },
    { ticker: "PAYTM.NS",     return_pct: -14.2 },
    { ticker: "VEDL.NS",      return_pct:  -9.5 },
    { ticker: "ADANIENT.NS",  return_pct:  -6.8 },
    { ticker: "TATASTEEL.NS", return_pct:  -3.1 },
  ],
  is_sample: true,
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return "—"
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`
}

function fmtRate(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—"
  return `${(v * 100).toFixed(1)}%`
}

export default async function PerformancePage() {
  const summary = await fetchSummary("Q1FY26", 90)
  const isSample = !!summary.is_sample
  const benchReturn = summary.benchmark?.return_pct ?? 0

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      {/* SEBI caveat — at the very top, non-collapsible. */}
      <aside
        className="mb-10 rounded-md border border-amber-300/60 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/30 dark:text-amber-200"
        role="note"
      >
        <p className="font-medium">Past results are not indicative of future returns.</p>
        <p className="mt-1">
          This page is a descriptive retrospective of model output vs realised
          prices. It is not investment advice. Sample size, selection-bias and
          survivorship-bias caveats apply (see methodology below). YieldIQ does
          not provide securities advisory services under SEBI (Investment
          Advisers) Regulations, 2013.
        </p>
      </aside>

      {isSample ? (
        <aside className="mb-8 rounded-md border border-dashed border-neutral-400/60 bg-neutral-50 p-3 text-xs text-neutral-700 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300">
          <strong>Preview:</strong> the numbers below are sample data showing
          the page layout. The first real retrospective publishes once the
          backfill in <code>scripts/backfill_predictions.py</code> completes.
        </aside>
      ) : (
        fmtLastUpdated(summary.last_updated) ? (
          <p className="mb-8 text-xs text-neutral-500">
            Last updated: {fmtLastUpdated(summary.last_updated)}
          </p>
        ) : null
      )}

      {/* Hero */}
      <header className="mb-10 max-w-3xl">
        <p className="mb-2 text-xs uppercase tracking-wider text-neutral-500">
          Performance Retrospective · {summary.period.label}
        </p>
        <h1 className="font-serif text-4xl leading-tight tracking-tight">
          Of {summary.n_predictions} stocks called undervalued in {summary.period.label},{" "}
          {Math.round(((summary.outperform_rate ?? 0) * summary.n_predictions))}{" "}
          ({fmtRate(summary.outperform_rate)}) outperformed the Nifty 500 over
          the next {summary.window_days} days.
        </h1>
        <p className="mt-3 text-neutral-600 dark:text-neutral-400">
          Period: {summary.period.start} → {summary.period.end}. Margin-of-safety
          threshold: {summary.mos_threshold.toFixed(0)}%. Benchmark:{" "}
          {summary.benchmark.ticker} ({fmtPct(benchReturn)} over the same window).
        </p>
      </header>

      {/* Headline grid */}
      <section className="mb-12 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Predictions" value={String(summary.n_predictions)} />
        <Stat label="Mean return" value={fmtPct(summary.mean_return)} />
        <Stat label="Median return" value={fmtPct(summary.median_return)} />
        <Stat label="Hit rate (return > 0)" value={fmtRate(summary.hit_rate)} />
      </section>

      {/* Histogram placeholder — Phase 2 will render real bins */}
      <section className="mb-12">
        <h2 className="mb-3 font-serif text-2xl">Distribution of returns</h2>
        <div className="flex h-40 items-end gap-1 rounded-md border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-800 dark:bg-neutral-900">
          {[3, 6, 11, 14, 9, 4, 2].map((h, i) => (
            <div
              key={i}
              className="flex-1 rounded-sm bg-neutral-400/70 dark:bg-neutral-600"
              style={{ height: `${(h / 14) * 100}%` }}
              aria-hidden="true"
            />
          ))}
        </div>
        <p className="mt-2 text-xs text-neutral-500">
          {/* TODO(task12-phase2): real binned histogram from outcome rows. */}
          Bins: &lt;-20 / -20→-10 / -10→0 / 0→10 / 10→20 / 20→30 / &gt;30%.
        </p>
      </section>

      {/* Winners / losers */}
      <section className="mb-12 grid gap-6 md:grid-cols-2">
        <OutcomeCard title="Top 5 winners" rows={summary.winners} kind="winner" />
        <OutcomeCard title="Top 5 losers" rows={summary.losers} kind="loser" />
      </section>

      {/* Per-sector breakdown */}
      <section className="mb-12">
        <h2 className="mb-3 font-serif text-2xl">Per-sector breakdown</h2>
        <p className="mb-3 text-sm text-neutral-600 dark:text-neutral-400">
          Sector-relative is the honest comparison: an IT pick should beat
          Nifty IT, not the broad market. Aggregate outperform-rate above is
          n-weighted across these sectors.
        </p>
        <SectorBreakdown rows={summary.sector_breakdown ?? null} />
      </section>

      {/* Methodology link */}
      <section className="prose prose-neutral max-w-none dark:prose-invert">
        <h2>Methodology, in one paragraph</h2>
        <p>
          We snapshot every covered ticker's model verdict each trading day
          into <code>model_predictions_history</code>. After {summary.window_days}{" "}
          days we read the realised price and compute return vs the price the
          model saw. We summarise across only the high-conviction subset
          (margin-of-safety ≥ {summary.mos_threshold.toFixed(0)}%). The
          benchmark is {summary.benchmark.ticker} over the same window. Full
          design notes — including survivorship-bias and look-ahead caveats —
          are in <Link href="/methodology">/methodology</Link> and the design
          doc shipped alongside this page.
        </p>
      </section>
    </main>
  )
}

function SectorBreakdown({ rows }: { rows: SectorRow[] | null }) {
  if (!rows || rows.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-neutral-300 bg-neutral-50 p-4 text-sm text-neutral-600 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-400">
        Aggregate Nifty 500 only — sector breakdown will appear in the next
        quarterly publication, once enough per-sector predictions accumulate.
      </div>
    )
  }
  return (
    <div className="overflow-x-auto rounded-md border border-neutral-200 dark:border-neutral-800">
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wider text-neutral-500 dark:bg-neutral-900">
          <tr>
            <th className="px-4 py-2">Sector</th>
            <th className="px-4 py-2 text-right">n</th>
            <th className="px-4 py-2 text-right">Mean return</th>
            <th className="px-4 py-2 text-right">Benchmark</th>
            <th className="px-4 py-2 text-right">Outperform</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
          {rows.map((r) => (
            <tr key={`${r.sector}-${r.benchmark_ticker}`}>
              <td className="px-4 py-2">
                <span className="font-medium">{r.sector}</span>{" "}
                <span className="text-xs text-neutral-500">
                  ({r.benchmark_ticker})
                </span>
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{r.n}</td>
              <td className="px-4 py-2 text-right tabular-nums">
                {fmtPct(r.mean_return)}
              </td>
              <td className="px-4 py-2 text-right tabular-nums text-neutral-600 dark:text-neutral-400">
                {fmtPct(r.benchmark_return)}
              </td>
              <td className="px-4 py-2 text-right tabular-nums">
                {fmtRate(r.outperform_rate)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-neutral-200 bg-neutral-50 p-4 dark:border-neutral-800 dark:bg-neutral-900">
      <p className="text-xs uppercase tracking-wider text-neutral-500">{label}</p>
      <p className="mt-1 font-serif text-2xl">{value}</p>
    </div>
  )
}

function OutcomeCard({
  title, rows, kind,
}: { title: string; rows: Outcome[]; kind: "winner" | "loser" }) {
  return (
    <div className="rounded-md border border-neutral-200 dark:border-neutral-800">
      <div className="border-b border-neutral-200 px-4 py-2 text-sm font-medium dark:border-neutral-800">
        {title}
      </div>
      <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
        {rows.map((r) => (
          <li
            key={r.ticker}
            className="flex items-center justify-between px-4 py-2 text-sm"
          >
            <span className="font-mono">{r.ticker.replace(".NS", "")}</span>
            <span
              className={
                kind === "winner"
                  ? "text-emerald-700 dark:text-emerald-400"
                  : "text-rose-700 dark:text-rose-400"
              }
            >
              {fmtPct(r.return_pct)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
