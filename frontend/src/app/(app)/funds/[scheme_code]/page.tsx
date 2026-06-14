/**
 * /funds/[scheme_code] — read-only mutual fund analysis page.
 *
 * Server component. Pulls the composite payload from /api/v1/funds/{code}
 * via fetchFundSSR (5-min ISR), then renders:
 *
 *   1. Hero — scheme name, AMC, category badge, Riskometer chip,
 *      inception year, plan / option chips.
 *   2. NAV-vs-benchmark chart — client component (Recharts) with
 *      1Y/3Y/5Y/10Y toggle. Indexed to 100 on chart start.
 *   3. Trailing returns table — 1Y / 3Y / 5Y / 10Y / SI columns ×
 *      Scheme / Benchmark / Excess rows. Em-dash placeholders for
 *      every null field so the layout is stable while Phase 2's
 *      returns cache is empty.
 *   4. Cost panel — TER Direct + TER Regular, em-dash when null.
 *   5. YieldIQ Fund Score chip — null state when Phase 7 hasn't run.
 *   6. SEBI past-performance disclaimer footer (mandatory, verbatim).
 *
 * Intentionally NOT shipped (Phase 3-slim scope):
 *   - holdings / sector pie (Phase 4)
 *   - portfolio overlap (Phase 5)
 *   - compare / alerts (Phase 7)
 *   - AI narrative
 *   - "How to read this" modal (lesson from PR #674)
 */
import Link from "next/link"
import { notFound } from "next/navigation"

import { fetchFundSSR } from "@/lib/api"
import type {
  FundBenchmarkPoint,
  FundDetailResponse,
  FundNavPoint,
  FundRiskometerLevel,
} from "@/types/api"

import AmcAvatar from "@/components/common/AmcAvatar"

import FeeImpactCalculator from "./FeeImpactCalculator"
import FundJsonLd from "./JsonLd"
import NavBenchmarkChart from "./NavBenchmarkChart"

export const revalidate = 300

interface Props {
  params: Promise<{ scheme_code: string }>
}

// ── Riskometer palette ────────────────────────────────────────────────
// SEBI publishes six levels. Colour scale: green (low) → red (very
// high). Mirrors the same colour grammar used by the rest of the app
// (Tailwind's emerald/lime/amber/orange/red ramp).
const RISKOMETER_COLORS: Record<FundRiskometerLevel, { bg: string; text: string; label: string }> = {
  Low: { bg: "bg-emerald-100", text: "text-emerald-800", label: "Low" },
  LowToModerate: { bg: "bg-lime-100", text: "text-lime-800", label: "Low to Moderate" },
  Moderate: { bg: "bg-yellow-100", text: "text-yellow-800", label: "Moderate" },
  ModeratelyHigh: { bg: "bg-amber-100", text: "text-amber-900", label: "Moderately High" },
  High: { bg: "bg-orange-100", text: "text-orange-900", label: "High" },
  VeryHigh: { bg: "bg-red-100", text: "text-red-800", label: "Very High" },
}

const DASH = "—"

function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH
  return `${v.toFixed(2)}%`
}

function fmtPlain(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH
  return v.toFixed(2)
}

// Scheme trailing return for display, in PERCENT. The API stores returns
// as decimal fractions (ret_3y=0.77 ⇒ 77% cumulative), so we must ×100 —
// the previous code fed the raw fraction straight into fmtPct, rendering
// 0.0494 as "0.05%" (a 100× understatement) on every fund page. For
// windows ≥ 3y we annualize to CAGR using the same method as the
// benchmark row (`benchmarkReturnPct`), so the caption ("CAGR for 3y+")
// is honest and Scheme/Benchmark/Excess are apples-to-apples. 1Y is
// absolute; SI is handled separately (cumulative since first NAV).
function schemeReturnPct(
  retFraction: number | null | undefined,
  years: number,
): number | null {
  if (retFraction == null || !Number.isFinite(retFraction)) return null
  if (years <= 1) return retFraction * 100
  return (Math.pow(1 + retFraction, 1 / years) - 1) * 100
}

function inceptionYear(d: string | null | undefined): string {
  if (!d) return DASH
  const m = /^(\d{4})/.exec(d)
  return m ? m[1] : DASH
}

// ── Benchmark trailing returns ────────────────────────────────────────
//
// Phase 2's fund_returns_cache only stores scheme returns + costs.
// Benchmark trailing returns are derived live from the monthly TRI
// series we already shipped down — close enough for read-only display
// while Phase 2 ships the proper cached values. Returns in percent.

function benchmarkReturnPct(
  benchHist: FundBenchmarkPoint[],
  yearsBack: number,
): number | null {
  if (benchHist.length === 0) return null
  const last = benchHist[benchHist.length - 1]
  if (!last) return null
  const target = new Date(last.nav_date)
  target.setFullYear(target.getFullYear() - yearsBack)
  // Find the closest point >= target date.
  const targetIso = target.toISOString().slice(0, 10)
  const start = benchHist.find((p) => p.nav_date >= targetIso)
  if (!start || start.tri_value === 0) return null
  const totalRet = last.tri_value / start.tri_value
  if (yearsBack <= 1) return (totalRet - 1) * 100
  // Annualise for multi-year windows (CAGR).
  return (Math.pow(totalRet, 1 / yearsBack) - 1) * 100
}

function navReturnSI(navHist: FundNavPoint[]): number | null {
  if (navHist.length < 2) return null
  const first = navHist[0].nav
  const last = navHist[navHist.length - 1].nav
  if (!first) return null
  return ((last / first) - 1) * 100
}

// Benchmark SI as CUMULATIVE total return (not annualized) so it sits on
// the same basis as the scheme's ret_si, keeping the Excess SI cell
// meaningful. Returns null when the TRI series is absent (most schemes →
// em-dash, which is honest). Percent.
function benchmarkReturnSICum(benchHist: FundBenchmarkPoint[]): number | null {
  if (benchHist.length < 2) return null
  const first = benchHist[0]
  const last = benchHist[benchHist.length - 1]
  if (!first || !last || first.tri_value === 0) return null
  return (last.tri_value / first.tri_value - 1) * 100
}

function excess(scheme: number | null, bench: number | null): number | null {
  if (scheme == null || bench == null) return null
  return scheme - bench
}

function scoreGrade(score: number | null | undefined): { letter: string; band: string } | null {
  if (score == null || !Number.isFinite(score)) return null
  if (score >= 80) return { letter: "A", band: "bg-emerald-100 text-emerald-800" }
  if (score >= 65) return { letter: "B", band: "bg-lime-100 text-lime-800" }
  if (score >= 50) return { letter: "C", band: "bg-yellow-100 text-yellow-800" }
  if (score >= 35) return { letter: "D", band: "bg-orange-100 text-orange-900" }
  return { letter: "F", band: "bg-red-100 text-red-800" }
}

// ── Sub-components ────────────────────────────────────────────────────

function Hero({ fund }: { fund: FundDetailResponse["fund"] }) {
  const risk = fund.riskometer_level
    ? RISKOMETER_COLORS[fund.riskometer_level]
    : null
  return (
    <header className="mb-6">
      <div className="mb-2 flex items-center gap-2.5">
        <AmcAvatar amc={fund.amc} size="lg" />
        <span className="text-sm text-caption">{fund.amc}</span>
      </div>
      <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
        {fund.scheme_name}
      </h1>
      <div className="mt-3 flex flex-wrap gap-2">
        {fund.category ? (
          <span className="rounded-full bg-tone-info-bg px-2.5 py-0.5 text-xs font-medium text-tone-info-fg">
            {fund.category}
            {fund.sub_category ? ` · ${fund.sub_category}` : ""}
          </span>
        ) : null}
        {risk ? (
          <span
            className={`rounded-full ${risk.bg} ${risk.text} px-2.5 py-0.5 text-xs font-medium`}
            title="SEBI Riskometer"
          >
            Riskometer: {risk.label}
          </span>
        ) : null}
        {fund.plan ? (
          <span className="rounded-full bg-surface px-2.5 py-0.5 text-xs font-medium text-body">
            {fund.plan} plan
          </span>
        ) : null}
        {fund.option ? (
          <span className="rounded-full bg-surface px-2.5 py-0.5 text-xs font-medium text-body">
            {fund.option}
          </span>
        ) : null}
        <span className="rounded-full bg-surface px-2.5 py-0.5 text-xs font-medium text-body">
          Inception {inceptionYear(fund.inception_date)}
        </span>
      </div>
    </header>
  )
}

function ReturnsTable({
  metrics,
  benchHist,
  navHist,
}: {
  metrics: FundDetailResponse["metrics"]
  benchHist: FundBenchmarkPoint[]
  navHist: FundNavPoint[]
}) {
  // 1Y absolute; 3Y/5Y/10Y annualized to CAGR; SI cumulative since first
  // NAV. All converted from decimal fractions to percent.
  const schemeRow = [
    schemeReturnPct(metrics?.ret_1y, 1),
    schemeReturnPct(metrics?.ret_3y, 3),
    schemeReturnPct(metrics?.ret_5y, 5),
    schemeReturnPct(metrics?.ret_10y, 10),
    metrics?.ret_si != null && Number.isFinite(metrics.ret_si)
      ? metrics.ret_si * 100
      : null,
  ]
  const benchRow = [
    benchmarkReturnPct(benchHist, 1),
    benchmarkReturnPct(benchHist, 3),
    benchmarkReturnPct(benchHist, 5),
    benchmarkReturnPct(benchHist, 10),
    benchmarkReturnSICum(benchHist),
  ]
  // SI excess uses scheme SI return when present, otherwise derive from
  // NAV series so the row is still meaningful pre-Phase-2.
  if (schemeRow[4] == null) schemeRow[4] = navReturnSI(navHist)

  // Benchmark index mapping + TRI history aren't ingested yet (scheme →
  // benchmark mapping is null universe-wide), so the Benchmark/Excess rows
  // would be all em-dash. Hide them rather than render rows of dashes that
  // read as broken; surface them automatically once TRI data lands.
  const hasBenchmark = benchRow.some(
    (v) => v != null && Number.isFinite(v),
  )
  const excessRow = schemeRow.map((s, i) => excess(s, benchRow[i]))
  const cols: { key: string; label: string }[] = [
    { key: "1y", label: "1Y" },
    { key: "3y", label: "3Y" },
    { key: "5y", label: "5Y" },
    { key: "10y", label: "10Y" },
    { key: "si", label: "SI" },
  ]

  return (
    <section className="rounded-lg border border-border bg-raised p-4">
      <h2 className="mb-3 text-base font-semibold text-ink">
        Trailing Returns
      </h2>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-caption">
              <th className="py-2 pr-4 font-medium">Series</th>
              {cols.map((c) => (
                <th key={c.key} className="py-2 pr-4 font-medium">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            <tr>
              <td className="py-2 pr-4 font-medium text-ink">Scheme</td>
              {schemeRow.map((v, i) => (
                <td key={i} className="py-2 pr-4 tabular-nums text-ink">
                  {fmtPct(v)}
                </td>
              ))}
            </tr>
            {hasBenchmark ? (
              <>
                <tr>
                  <td className="py-2 pr-4 font-medium text-ink">Benchmark</td>
                  {benchRow.map((v, i) => (
                    <td key={i} className="py-2 pr-4 tabular-nums text-body">
                      {fmtPct(v)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="py-2 pr-4 font-medium text-ink">Excess</td>
                  {excessRow.map((v, i) => (
                    <td
                      key={i}
                      className={
                        "py-2 pr-4 tabular-nums " +
                        (v == null
                          ? "text-caption"
                          : v >= 0
                            ? "text-success"
                            : "text-warning")
                      }
                    >
                      {fmtPct(v)}
                    </td>
                  ))}
                </tr>
              </>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-caption">
        Trailing returns are annualized (CAGR) for 3Y / 5Y / 10Y and absolute
        for 1Y. SI is total return since the first available NAV.
        {hasBenchmark
          ? " Benchmark returns are derived from the scheme's mandated TRI index."
          : " Benchmark comparison is coming soon."}
      </p>
    </section>
  )
}

function CostPanel({ metrics }: { metrics: FundDetailResponse["metrics"] }) {
  return (
    <section className="rounded-lg border border-border bg-raised p-4">
      <h2 className="mb-3 text-base font-semibold text-ink">
        Expense Ratio (TER)
      </h2>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs uppercase tracking-wide text-caption">Direct</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">
            {fmtPct(metrics?.ter_direct)}
          </div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-caption">Regular</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">
            {fmtPct(metrics?.ter_regular)}
          </div>
        </div>
      </div>
      <p className="mt-3 text-xs text-caption">
        Direct plans have a lower expense ratio because no distributor commission is
        paid. Regular plans are sold through intermediaries who provide advice.
      </p>
    </section>
  )
}

function ScoreChip({ metrics }: { metrics: FundDetailResponse["metrics"] }) {
  const grade = scoreGrade(metrics?.yieldiq_fund_score ?? null)
  return (
    <section className="rounded-lg border border-border bg-raised p-4">
      <h2 className="mb-3 text-base font-semibold text-ink">
        YieldIQ Fund Score
      </h2>
      {grade ? (
        <div className="flex items-center gap-3">
          <span
            className={`inline-flex h-12 w-12 items-center justify-center rounded-full ${grade.band} text-xl font-bold`}
          >
            {grade.letter}
          </span>
          <div>
            <div className="text-2xl font-semibold tabular-nums text-ink">
              {metrics?.yieldiq_fund_score}
              <span className="ml-1 text-sm font-normal text-caption">/ 100</span>
            </div>
            <div className="text-xs text-caption">
              Rule-based composite of returns, risk, cost, and tenure.
            </div>
          </div>
        </div>
      ) : (
        <div className="text-sm text-caption">
          {DASH} <span className="ml-1">Score not yet computed for this scheme.</span>
        </div>
      )}
    </section>
  )
}

function SebiFooter() {
  return (
    <footer className="mt-8 rounded-lg border border-tone-warn-bd bg-tone-warn-bg p-4 text-xs leading-relaxed text-tone-warn-fg">
      Past performance is not indicative of future returns. Mutual fund investments
      are subject to market risks; read all scheme-related documents carefully.
    </footer>
  )
}

// ── Page ──────────────────────────────────────────────────────────────

export default async function FundPage({ params }: Props) {
  const { scheme_code } = await params
  const data = await fetchFundSSR(scheme_code)
  if (!data) {
    notFound()
  }

  // metrics for fmtPlain (cagr_3y / 5y, etc.) — surfaced inside cost panel only.
  void fmtPlain  // silence unused-import warnings; helper kept for future cards

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
      <nav className="mb-4 text-sm text-caption">
        <Link href="/funds" className="hover:text-ink">
          Mutual Funds
        </Link>
        <span className="mx-2">/</span>
        <span className="text-body">{data.fund.scheme_name}</span>
      </nav>

      <Hero fund={data.fund} />

      <div className="grid gap-6">
        <NavBenchmarkChart
          navHistory={data.nav_history}
          benchmarkHistory={data.benchmark_history}
        />

        <ReturnsTable
          metrics={data.metrics}
          benchHist={data.benchmark_history}
          navHist={data.nav_history}
        />

        <div className="grid gap-6 md:grid-cols-2">
          <CostPanel metrics={data.metrics} />
          <ScoreChip metrics={data.metrics} />
        </div>

        <FeeImpactCalculator
          terDirect={data.metrics?.ter_direct ?? null}
          terRegular={data.metrics?.ter_regular ?? null}
        />
      </div>

      <SebiFooter />

      <FundJsonLd fund={data.fund} metrics={data.metrics} />
    </main>
  )
}
