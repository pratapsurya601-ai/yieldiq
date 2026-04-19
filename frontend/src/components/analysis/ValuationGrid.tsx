/**
 * ValuationGrid — shared Bear / Base / Bull scenario grid.
 *
 * Pure presentation, no client hooks → safe to render from RSC (the
 * public SEO page is SSR / ISR-revalidated). Both the public
 * stocks/[ticker]/fair-value page and (eventually) the authed
 * /analysis/[ticker] page consume this so the visual surface stays
 * in lock-step.
 *
 * Prop shape is intentionally minimal — `fair_value` + `mos_pct` are
 * the only required scenario fields. Callers with richer scenario
 * payloads (e.g. authed `ScenariosOutput` with `iv` / `growth` / `wacc`)
 * adapt at the call site:
 *
 *     <ValuationGrid
 *       bear={{ fair_value: scenarios.bear.iv, mos_pct: scenarios.bear.mos_pct }}
 *       base={{ fair_value: scenarios.base.iv, mos_pct: scenarios.base.mos_pct }}
 *       bull={{ fair_value: scenarios.bull.iv, mos_pct: scenarios.bull.mos_pct }}
 *       currentPrice={valuation.current_price}
 *       currency={company.currency}
 *     />
 *
 * The optional `verdict` field tints the band background — when omitted
 * the grid falls back to its default per-case palette
 * (bear=red, base=blue, bull=green) which mirrors the existing authed
 * `scenarioBlock` in AnalysisBody.
 */

import { formatCurrency } from "@/lib/utils"

export interface ScenarioCase {
  fair_value: number
  mos_pct: number
  verdict?: string
}

export interface ValuationGridProps {
  bear: ScenarioCase
  base: ScenarioCase
  bull: ScenarioCase
  currentPrice: number
  currency?: string
}

type CaseKey = "bear" | "base" | "bull"

const CASE_LABEL: Record<CaseKey, string> = {
  bear: "Bear case",
  base: "Base case",
  bull: "Bull case",
}

const CASE_PALETTE: Record<CaseKey, { border: string; bg: string; value: string }> = {
  bear: { border: "border-red-200", bg: "bg-red-50", value: "text-red-700" },
  base: { border: "border-blue-200", bg: "bg-blue-50", value: "text-blue-700" },
  bull: { border: "border-green-200", bg: "bg-green-50", value: "text-green-700" },
}

function fmtMos(mos: number | null | undefined): string {
  if (mos == null || Number.isNaN(mos)) return "\u2014"
  const sign = mos >= 0 ? "+" : ""
  return `${sign}${mos.toFixed(1)}%`
}

function mosTone(mos: number | null | undefined): string {
  if (mos == null || Number.isNaN(mos)) return "text-gray-400"
  return mos >= 0 ? "text-green-600" : "text-red-600"
}

export default function ValuationGrid({
  bear,
  base,
  bull,
  currentPrice,
  currency = "INR",
}: ValuationGridProps) {
  const cases: Array<{ key: CaseKey; data: ScenarioCase }> = [
    { key: "bear", data: bear },
    { key: "base", data: base },
    { key: "bull", data: bull },
  ]

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6">
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="text-lg font-bold text-gray-900">DCF Scenario Analysis</h2>
        <p className="text-xs text-gray-400">
          vs CMP {formatCurrency(currentPrice, currency)}
        </p>
      </div>
      <div className="grid grid-cols-3 gap-4">
        {cases.map(({ key, data }) => {
          const palette = CASE_PALETTE[key]
          return (
            <div
              key={key}
              className={`rounded-xl p-4 text-center border ${palette.border} ${palette.bg}`}
            >
              <p className="text-[11px] uppercase tracking-wider text-gray-500 mb-1">
                {CASE_LABEL[key]}
              </p>
              <p className={`text-xl font-bold font-mono tabular-nums ${palette.value}`}>
                {formatCurrency(data.fair_value, currency)}
              </p>
              <p className={`text-xs font-mono mt-1 ${mosTone(data.mos_pct)}`}>
                MoS {fmtMos(data.mos_pct)}
              </p>
              {data.verdict ? (
                <p className="text-[10px] text-gray-400 mt-1 capitalize">
                  {data.verdict.replace(/_/g, " ")}
                </p>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}
