import type { Metadata } from "next"
import Link from "next/link"
import BacktestChart from "./BacktestChart"

/**
 * Day-89 — /backtest marketing page.
 *
 * Server component. Fetches the YieldIQ-50 annual-rotation hypothetical
 * backtest from the public API and renders:
 *   1. Hero with disclaimer
 *   2. Cumulative delta vs Nifty (the headline number)
 *   3. Indexed-equity-curve chart (Recharts island)
 *   4. Per-year breakdown table
 *   5. Methodology + SEBI disclosure
 *
 * Vocabulary (SEBI): no buy/sell/hold/strong/accumulate/recommend/
 * outperform/underperform/should. The headline number is framed as
 * "delta vs Nifty proxy" or "produced/yielded".
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

interface PerYear {
  year_start: string
  year_end: string
  picks: string[]
  method: string
  yiq50_return_pct: number | null
  nifty_return_pct: number | null
  delta_pct: number | null
  tickers_priced: number
}

interface BacktestData {
  lookback_years: number
  universe_size: number
  universe_coverage_pct: number
  yiq50_total_return_pct: number
  nifty_total_return_pct: number
  delta_pct: number
  per_year_breakdown: PerYear[]
  benchmark: string
  _meta: {
    method: string
    caveat: string
    survivorship_note: string
    disclaimer: string
  }
}

export const metadata: Metadata = {
  title: "Backtest — YieldIQ-50 hypothetical 3-year return vs Nifty | YieldIQ",
  description:
    "Hypothetical annual-rotation backtest: the top 5 stocks within the YieldIQ-50 universe by margin of safety, held 12 months, vs a Nifty-top-5 proxy. Methodology disclosed.",
  alternates: { canonical: "https://yieldiq.in/backtest" },
  openGraph: {
    title: "YieldIQ-50 Backtest — what the framework would have produced",
    description:
      "Hypothetical results based on backtesting methodology. Past returns are not indicative of future results.",
    url: "https://yieldiq.in/backtest",
    siteName: "YieldIQ",
    type: "website",
  },
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  const sign = v > 0 ? "+" : ""
  return `${sign}${v.toFixed(2)}%`
}

function deltaColorClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return ""
  if (v > 0) return "text-[color:var(--color-success)]"
  if (v < 0) return "text-[color:var(--color-danger)]"
  return ""
}

function buildCurve(data: BacktestData): { label: string; yiq50: number; nifty: number }[] {
  // Cumulative indexed series starting at 100 at year-0.
  const out: { label: string; yiq50: number; nifty: number }[] = [
    { label: "Start", yiq50: 100, nifty: 100 },
  ]
  let y = 100
  let n = 100
  for (const row of data.per_year_breakdown) {
    if (row.yiq50_return_pct !== null) y *= 1 + row.yiq50_return_pct / 100
    if (row.nifty_return_pct !== null) n *= 1 + row.nifty_return_pct / 100
    out.push({
      label: row.year_end.slice(0, 7),
      yiq50: Math.round(y * 100) / 100,
      nifty: Math.round(n * 100) / 100,
    })
  }
  return out
}

export default async function BacktestPage({
  searchParams,
}: {
  searchParams: Promise<{ lookback?: string }>
}) {
  const sp = await searchParams
  const lookbackRaw = (sp.lookback || "3y").toLowerCase()
  const lookback = ["1y", "3y", "5y"].includes(lookbackRaw) ? lookbackRaw : "3y"

  let data: BacktestData | null = null
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/public/backtest/yiq50?lookback=${lookback}`,
      { next: { revalidate: 43200 } },
    )
    if (res.ok) data = (await res.json()) as BacktestData
  } catch {
    // Page renders an empty-state below if the fetch failed
  }

  return (
    <main className="bg-[color:var(--color-bg)] text-[color:var(--color-body)] min-h-screen">
      {/* Top disclaimer — always visible above the fold */}
      <div className="bg-[color:var(--color-brand-50)] border-b border-[color:var(--color-border)] text-xs text-[color:var(--color-body)]">
        <div className="max-w-5xl mx-auto px-4 py-2">
          Past returns are not indicative of future results. Hypothetical
          results based on backtesting methodology.
        </div>
      </div>

      {/* Hero */}
      <section className="max-w-5xl mx-auto px-4 pt-12 pb-8">
        <p className="text-xs uppercase tracking-wider text-[color:var(--color-caption)] mb-3">
          Backtest · {lookback.toUpperCase()} lookback
        </p>
        <h1
          className="font-[family-name:var(--font-editorial)] text-4xl sm:text-5xl text-[color:var(--color-ink)] mb-4"
          style={{ lineHeight: 1.1 }}
        >
          What if you&rsquo;d followed YieldIQ&rsquo;s framework{" "}
          {data ? data.lookback_years : 3} years ago?
        </h1>
        <p className="text-base sm:text-lg max-w-2xl">
          A hypothetical illustration. Each year, an equal-weighted basket of
          the top 5 names in the YieldIQ-50 universe by margin of safety at
          year-start, held for 12 months, settled at year-end.
        </p>
      </section>

      {/* Headline numbers */}
      {data ? (
        <section className="max-w-5xl mx-auto px-4 pb-10 grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6">
            <p className="text-xs uppercase tracking-wider text-[color:var(--color-caption)] mb-2">
              YieldIQ-50 top 5
            </p>
            <p className="font-[family-name:var(--font-display)] text-4xl text-[color:var(--color-ink)]">
              {fmtPct(data.yiq50_total_return_pct)}
            </p>
            <p className="text-xs text-[color:var(--color-caption)] mt-1">
              cumulative, {data.lookback_years}y
            </p>
          </div>
          <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6">
            <p className="text-xs uppercase tracking-wider text-[color:var(--color-caption)] mb-2">
              Nifty proxy basket
            </p>
            <p className="font-[family-name:var(--font-display)] text-4xl text-[color:var(--color-ink)]">
              {fmtPct(data.nifty_total_return_pct)}
            </p>
            <p className="text-xs text-[color:var(--color-caption)] mt-1">
              cumulative, {data.lookback_years}y
            </p>
          </div>
          <div className="rounded-xl border-2 border-[color:var(--color-brand)] bg-[color:var(--color-surface)] p-6">
            <p className="text-xs uppercase tracking-wider text-[color:var(--color-caption)] mb-2">
              Delta vs Nifty proxy
            </p>
            <p
              className={
                "font-[family-name:var(--font-display)] text-4xl " +
                (deltaColorClass(data.delta_pct) ||
                  "text-[color:var(--color-ink)]")
              }
            >
              {fmtPct(data.delta_pct)}
            </p>
            <p className="text-xs text-[color:var(--color-caption)] mt-1">
              hypothetical, cumulative
            </p>
          </div>
        </section>
      ) : (
        <section className="max-w-5xl mx-auto px-4 pb-10">
          <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6 text-sm">
            Backtest data is warming up. Refresh in a few minutes.
          </div>
        </section>
      )}

      {/* Chart */}
      {data && data.per_year_breakdown.length > 0 ? (
        <section className="max-w-5xl mx-auto px-4 pb-12">
          <h2 className="font-[family-name:var(--font-display)] text-xl text-[color:var(--color-ink)] mb-4">
            Indexed equity curve (start = 100)
          </h2>
          <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-4">
            <BacktestChart data={buildCurve(data)} />
          </div>
        </section>
      ) : null}

      {/* Per-year table */}
      {data && data.per_year_breakdown.length > 0 ? (
        <section className="max-w-5xl mx-auto px-4 pb-12">
          <h2 className="font-[family-name:var(--font-display)] text-xl text-[color:var(--color-ink)] mb-4">
            Per-year breakdown
          </h2>
          <div className="overflow-x-auto rounded-xl border border-[color:var(--color-border)]">
            <table className="w-full text-sm">
              <thead className="bg-[color:var(--color-surface)] text-[color:var(--color-caption)] text-xs uppercase tracking-wider">
                <tr>
                  <th className="text-left px-4 py-3">Window</th>
                  <th className="text-left px-4 py-3">Picks</th>
                  <th className="text-right px-4 py-3">YIQ-50 top 5</th>
                  <th className="text-right px-4 py-3">Nifty proxy</th>
                  <th className="text-right px-4 py-3">Delta</th>
                  <th className="text-left px-4 py-3">Method</th>
                </tr>
              </thead>
              <tbody className="bg-[color:var(--color-bg)]">
                {data.per_year_breakdown.map((row) => (
                  <tr
                    key={row.year_start}
                    className="border-t border-[color:var(--color-border)]"
                  >
                    <td className="px-4 py-3 whitespace-nowrap text-[color:var(--color-body)]">
                      {row.year_start} → {row.year_end}
                    </td>
                    <td className="px-4 py-3 text-[color:var(--color-body)]">
                      {row.picks.join(", ")}
                    </td>
                    <td className="px-4 py-3 text-right text-[color:var(--color-ink)] tabular-nums">
                      {fmtPct(row.yiq50_return_pct)}
                    </td>
                    <td className="px-4 py-3 text-right text-[color:var(--color-ink)] tabular-nums">
                      {fmtPct(row.nifty_return_pct)}
                    </td>
                    <td
                      className={
                        "px-4 py-3 text-right tabular-nums " +
                        deltaColorClass(row.delta_pct)
                      }
                    >
                      {fmtPct(row.delta_pct)}
                    </td>
                    <td className="px-4 py-3 text-xs text-[color:var(--color-caption)]">
                      {row.method === "fv_history"
                        ? "historical MoS"
                        : "large-cap slice"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {/* Methodology + disclaimers */}
      <section className="max-w-5xl mx-auto px-4 pb-16">
        <h2 className="font-[family-name:var(--font-display)] text-xl text-[color:var(--color-ink)] mb-4">
          Methodology &amp; limitations
        </h2>
        <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6 text-sm space-y-3">
          <p>
            <span className="font-medium text-[color:var(--color-ink)]">
              Universe.
            </span>{" "}
            The 50 stocks currently featured by YieldIQ as the curated
            YieldIQ-50 (canary set). The universe is the CURRENT basket, not
            the basket as it existed historically — survivorship bias is
            present.
          </p>
          <p>
            <span className="font-medium text-[color:var(--color-ink)]">
              Rotation.
            </span>{" "}
            Each year we pick the top 5 by margin-of-safety at year-start,
            equal-weight them, and settle at year-end. The cycle repeats
            annually.
          </p>
          <p>
            <span className="font-medium text-[color:var(--color-ink)]">
              Benchmark.
            </span>{" "}
            {data ? data.benchmark : "Nifty 50 proxy basket"}. Index ETF data
            is not directly cached; the proxy is an equal-weighted basket of
            the Nifty 50&rsquo;s top 5 by index weight.
          </p>
          <p>
            <span className="font-medium text-[color:var(--color-ink)]">
              Data source for picks.
            </span>{" "}
            {data?._meta?.caveat ||
              "Fair-value history rows used where available; deterministic large-cap slice as fallback."}
          </p>
          <p>
            <span className="font-medium text-[color:var(--color-ink)]">
              Costs.
            </span>{" "}
            Trading costs, taxes (STT, STCG/LTCG), and slippage are NOT
            modelled. Real-world net returns would be lower.
          </p>
          <p>
            <span className="font-medium text-[color:var(--color-ink)]">
              Survivorship.
            </span>{" "}
            {data?._meta?.survivorship_note ||
              "Universe membership is current; no de-listings reconstructed."}
          </p>
          {data ? (
            <p className="text-xs text-[color:var(--color-caption)]">
              Universe coverage: {data.universe_coverage_pct}% of{" "}
              {data.universe_size} tickers had usable price history.
            </p>
          ) : null}
        </div>
      </section>

      {/* SEBI disclosure */}
      <section className="max-w-5xl mx-auto px-4 pb-16">
        <div className="rounded-lg border border-[color:var(--color-warning)] bg-[color:var(--color-surface)] p-5 text-xs text-[color:var(--color-body)] space-y-2">
          <p className="font-semibold text-[color:var(--color-ink)]">
            Disclosure
          </p>
          <p>
            Hypothetical results based on backtesting methodology. Past
            returns are not indicative of future results.
          </p>
          <p>
            This page is for educational illustration only. This is not
            investment advice. YieldIQ is not SEBI-registered as an investment
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
