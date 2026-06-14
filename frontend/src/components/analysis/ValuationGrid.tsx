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

import { formatCurrency, trueMosFromUpside } from "@/lib/utils"
import { SummaryCard } from "@/components/cards"
import MetricTooltip from "@/components/common/MetricTooltip"

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
  // Optional ticker — when present, formatCurrency forces INR for any
  // .NS / .BO / .IN suffix regardless of the currency tag (defense in
  // depth against bare-ticker USD-tag bugs, e.g. CAPLIPOINT).
  ticker?: string
}

type CaseKey = "bear" | "base" | "bull"

const CASE_LABEL: Record<CaseKey, string> = {
  bear: "Bear case",
  base: "Base case",
  bull: "Bull case",
}

const CASE_PALETTE: Record<CaseKey, { border: string; bg: string; value: string }> = {
  bear: {
    border: "border-tone-bad-bd dark:border-red-900",
    bg: "bg-tone-bad-bg dark:bg-red-950/30",
    value: "text-tone-bad-fg dark:text-red-300",
  },
  base: {
    border: "border-tone-info-bd dark:border-blue-900",
    bg: "bg-tone-info-bg dark:bg-blue-950/30",
    value: "text-tone-info-fg dark:text-blue-300",
  },
  bull: {
    border: "border-green-200 dark:border-green-900",
    bg: "bg-green-50 dark:bg-green-950/30",
    value: "text-green-700 dark:text-green-300",
  },
}

function fmtMos(mos: number | null | undefined): string {
  if (mos == null || Number.isNaN(mos)) return "\u2014"
  const sign = mos >= 0 ? "+" : ""
  return `${sign}${mos.toFixed(1)}%`
}

function mosTone(mos: number | null | undefined): string {
  if (mos == null || Number.isNaN(mos)) return "text-caption"
  return mos >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"
}

// Premium Feel R2 — metric keys mapping each scenario case to its
// explainer entry in lib/metric-explainers.ts. Base case shares the
// MoS explainer because it IS the centre of gravity of the DCF range.
const CASE_METRIC_KEY: Record<CaseKey, string> = {
  bear: "bear_case",
  base: "mos",
  bull: "bull_case",
}

export default function ValuationGrid({
  bear,
  base,
  bull,
  currentPrice,
  currency = "INR",
  ticker,
}: ValuationGridProps) {
  const cases: Array<{ key: CaseKey; data: ScenarioCase }> = [
    { key: "bear", data: bear },
    { key: "base", data: base },
    { key: "bull", data: bull },
  ]

  return (
    // PR-B (design-synthesis §5): scenario grid is a single-headline metric
    // container surface → SummaryCard. p-6 retained to match prior pixels.
    <SummaryCard className="p-6 gap-0">
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="text-lg font-bold text-ink">DCF Scenario Analysis</h2>
        <p className="text-xs text-caption">
          vs CMP {formatCurrency(currentPrice, currency, ticker)}
        </p>
      </div>
      {/* Mobile-PR-A (Issue 1, audit 2026-06-10): stack scenarios on
          sub-md to prevent ₹ currency strings from wrapping mid-number
          at 360px (≈107px / card was too narrow for `₹1,42,500`). */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {cases.map(({ key, data }) => {
          const palette = CASE_PALETTE[key]
          // Premium Feel R2 — wrap each scenario value with the
          // MetricTooltip primitive so users can hover the Bear / Base
          // / Bull figure to read what the case represents.
          return (
            <div
              key={key}
              className={`rounded-xl p-4 text-center border ${palette.border} ${palette.bg}`}
            >
              <p className="text-[11px] uppercase tracking-wider text-caption mb-1">
                {CASE_LABEL[key]}
              </p>
              <MetricTooltip
                metric={CASE_METRIC_KEY[key]}
                label={CASE_LABEL[key]}
                showLabel={false}
                value={
                  <span className={`text-xl font-bold font-mono tabular-nums ${palette.value}`}>
                    {formatCurrency(data.fair_value, currency, ticker)}
                  </span>
                }
              />
              <p className={`text-xs font-mono mt-1 ${mosTone(trueMosFromUpside(data.mos_pct))}`}>
                Margin of Safety {fmtMos(trueMosFromUpside(data.mos_pct))}
              </p>
              <p className="text-[10px] text-caption mt-0.5 tabular-nums">
                Implied upside {fmtMos(data.mos_pct)}
              </p>
              {data.verdict ? (
                <p className="text-[10px] text-caption mt-1 capitalize">
                  {data.verdict.replace(/_/g, " ")}
                </p>
              ) : null}
            </div>
          )
        })}
      </div>
    </SummaryCard>
  )
}
