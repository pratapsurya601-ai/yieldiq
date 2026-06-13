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
      <div className="mb-2 text-sm text-gray-500">{fund.amc}</div>
      <h1 className="text-2xl font-semibold tracking-tight text-gray-900 sm:text-3xl">
        {fund.scheme_name}
      </h1>
      <div className="mt-3 flex flex-wrap gap-2">
        {fund.category ? (
          <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700">
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
          <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700">
            {fund.plan} plan
          </span>
        ) : null}
        {fund.option ? (
          <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700">
            {fund.option}
          </span>
        ) : null}
        <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700">
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
  const schemeRow = [
    metrics?.ret_1y ?? null,
    metrics?.ret_3y ?? null,
    metrics?.ret_5y ?? null,
    metrics?.ret_10y ?? null,
    metrics?.ret_si ?? null,
  ]
  const benchRow = [
    benchmarkReturnPct(benchHist, 1),
    benchmarkReturnPct(benchHist, 3),
    benchmarkReturnPct(benchHist, 5),
    benchmarkReturnPct(benchHist, 10),
    benchmarkReturnPct(benchHist, Math.max(1, Math.floor(navHist.length / 12))),
  ]
  // SI excess uses scheme SI return when present, otherwise derive from
  // NAV series so the row is still meaningful pre-Phase-2.
  if (schemeRow[4] == null) schemeRow[4] = navReturnSI(navHist)

  const excessRow = schemeRow.map((s, i) => excess(s, benchRow[i]))
  const cols: { key: string; label: string }[] = [
    { key: "1y", label: "1Y" },
    { key: "3y", label: "3Y" },
    { key: "5y", label: "5Y" },
    { key: "10y", label: "10Y" },
    { key: "si", label: "SI" },
  ]

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="mb-3 text-base font-semibold text-gray-900">
        Trailing Returns
      </h2>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
              <th className="py-2 pr-4 font-medium">Series</th>
              {cols.map((c) => (
                <th key={c.key} className="py-2 pr-4 font-medium">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            <tr>
              <td className="py-2 pr-4 font-medium text-gray-900">Scheme</td>
              {schemeRow.map((v, i) => (
                <td key={i} className="py-2 pr-4 tabular-nums text-gray-900">
                  {fmtPct(v)}
                </td>
              ))}
            </tr>
            <tr>
              <td className="py-2 pr-4 font-medium text-gray-900">Benchmark</td>
              {benchRow.map((v, i) => (
                <td key={i} className="py-2 pr-4 tabular-nums text-gray-700">
                  {fmtPct(v)}
                </td>
              ))}
            </tr>
            <tr>
              <td className="py-2 pr-4 font-medium text-gray-900">Excess</td>
              {excessRow.map((v, i) => (
                <td
                  key={i}
                  className={
                    "py-2 pr-4 tabular-nums " +
                    (v == null
                      ? "text-gray-500"
                      : v >= 0
                        ? "text-emerald-700"
                        : "text-red-700")
                  }
                >
                  {fmtPct(v)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-gray-500">
        Trailing returns are CAGR for windows of 3 years or more, absolute for 1Y.
        Benchmark returns derived from the scheme&apos;s mandated TRI index.
        SI = since inception.
      </p>
    </section>
  )
}

function CostPanel({ metrics }: { metrics: FundDetailResponse["metrics"] }) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="mb-3 text-base font-semibold text-gray-900">
        Expense Ratio (TER)
      </h2>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-500">Direct</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">
            {fmtPct(metrics?.ter_direct)}
          </div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-500">Regular</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">
            {fmtPct(metrics?.ter_regular)}
          </div>
        </div>
      </div>
      <p className="mt-3 text-xs text-gray-500">
        Direct plans have a lower expense ratio because no distributor commission is
        paid. Regular plans are sold through intermediaries who provide advice.
      </p>
    </section>
  )
}

function ScoreChip({ metrics }: { metrics: FundDetailResponse["metrics"] }) {
  const grade = scoreGrade(metrics?.yieldiq_fund_score ?? null)
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="mb-3 text-base font-semibold text-gray-900">
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
            <div className="text-2xl font-semibold tabular-nums text-gray-900">
              {metrics?.yieldiq_fund_score}
              <span className="ml-1 text-sm font-normal text-gray-500">/ 100</span>
            </div>
            <div className="text-xs text-gray-500">
              Rule-based composite of returns, risk, cost, and tenure.
            </div>
          </div>
        </div>
      ) : (
        <div className="text-sm text-gray-500">
          {DASH} <span className="ml-1">Score not yet computed for this scheme.</span>
        </div>
      )}
    </section>
  )
}

function SebiFooter() {
  return (
    <footer className="mt-8 rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs leading-relaxed text-amber-900">
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
      <nav className="mb-4 text-sm text-gray-500">
        <Link href="/funds" className="hover:text-gray-900">
          Mutual Funds
        </Link>
        <span className="mx-2">/</span>
        <span className="text-gray-700">{data.fund.scheme_name}</span>
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
