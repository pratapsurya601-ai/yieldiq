"use client"

/**
 * RiskTab — the Risk section of the fund Asset Page.
 *
 * Consumes the optional `risk` block from the detail payload (added by a
 * parallel backend PR). Renders volatility / risk-adjusted-return /
 * drawdown / market-sensitivity metrics, each wrapped in a MetricTooltip
 * plain-English explainer. Defensive throughout:
 *   - any single metric that is null is HIDDEN (no em-dash noise);
 *   - if the whole block is absent (or every metric is null), the tab
 *     shows the "compute nightly" empty state instead.
 *
 * UNIT CONTRACT (see types/api.ts): stdev / max_drawdown / alpha /
 * benchmark_excess are DECIMAL FRACTIONS (×100 → %); sharpe / sortino /
 * beta / info_ratio / capture are dimensionless; category_percentile_3y
 * is 0-100.
 *
 * SEBI: purely descriptive statistics — no advisory vocabulary.
 */

import type { FundRiskBlock } from "@/types/api"
import MetricTooltip from "@/components/common/MetricTooltip"
import { RevealStagger } from "@/components/motion"

import TabEmptyState from "./TabEmptyState"
import { fracPct, present, ratio } from "./fund-format"

interface MetricSpec {
  label: string
  title: string
  description: string
  formula?: string
  /** Pre-formatted display string, or null to hide the metric. */
  value: string | null
}

function fmtPercentile(v: number | null | undefined): string | null {
  if (!present(v)) return null
  // 0-100 already; show the band position descriptively.
  return `${Math.round(v)}th`
}

export default function RiskTab({ risk }: { risk?: FundRiskBlock | null }) {
  if (!risk) {
    return (
      <TabEmptyState
        title="Risk metrics are being prepared"
        message="Risk metrics compute nightly — check back."
      />
    )
  }

  // Group the metrics into themed cards. Each entry carries its own
  // tooltip copy so the section is self-explanatory.
  const volatility: MetricSpec[] = [
    {
      label: "Std dev (3Y)",
      title: "Standard deviation (3Y)",
      description:
        "How much the fund's returns swing around their average, annualised over three years. Higher means a bumpier ride.",
      value: fracPct(risk.stdev_3y),
    },
    {
      label: "Std dev (5Y)",
      title: "Standard deviation (5Y)",
      description:
        "The same volatility measure over a five-year window — a longer-horizon view of how variable returns have been.",
      value: fracPct(risk.stdev_5y),
    },
    {
      label: "Max drawdown (3Y)",
      title: "Maximum drawdown (3Y)",
      description:
        "The largest peak-to-trough fall over the last three years. It frames the worst decline an investor would have sat through.",
      value: fracPct(risk.max_drawdown_3y),
    },
    {
      label: "Max drawdown (5Y)",
      title: "Maximum drawdown (5Y)",
      description:
        "The deepest peak-to-trough fall over the last five years.",
      value: fracPct(risk.max_drawdown_5y),
    },
  ]

  const riskAdjusted: MetricSpec[] = [
    {
      label: "Sharpe (3Y)",
      title: "Sharpe ratio (3Y)",
      description:
        "Return earned per unit of total volatility. A higher number means more reward for the same amount of bumpiness.",
      formula: "(Return − Risk-free) / Std dev",
      value: ratio(risk.sharpe_3y),
    },
    {
      label: "Sharpe (5Y)",
      title: "Sharpe ratio (5Y)",
      description:
        "The same reward-per-risk measure over five years.",
      formula: "(Return − Risk-free) / Std dev",
      value: ratio(risk.sharpe_5y),
    },
    {
      label: "Sortino (3Y)",
      title: "Sortino ratio (3Y)",
      description:
        "Like Sharpe, but only penalises downside volatility — it ignores upside swings, which most investors don't mind.",
      formula: "(Return − Risk-free) / Downside dev",
      value: ratio(risk.sortino_3y),
    },
    {
      label: "Sortino (5Y)",
      title: "Sortino ratio (5Y)",
      description:
        "The downside-only reward-per-risk measure over five years.",
      formula: "(Return − Risk-free) / Downside dev",
      value: ratio(risk.sortino_5y),
    },
  ]

  const marketSensitivity: MetricSpec[] = [
    {
      label: "Beta (3Y)",
      title: "Beta (3Y)",
      description:
        "How strongly the fund moves with its benchmark. 1.0 tracks the index; above 1 amplifies its moves, below 1 dampens them.",
      value: ratio(risk.beta_3y),
    },
    {
      label: "Alpha (3Y)",
      title: "Alpha (3Y)",
      description:
        "Return above (or below) what the fund's beta-implied market exposure would predict. Positive alpha is value added beyond market movement.",
      value: fracPct(risk.alpha_3y),
    },
    {
      label: "Info ratio (3Y)",
      title: "Information ratio (3Y)",
      description:
        "Excess return over the benchmark per unit of tracking error — consistency of out/under-performance.",
      formula: "Excess return / Tracking error",
      value: ratio(risk.info_ratio_3y),
    },
    {
      label: "Tracking error (3Y)",
      title: "Tracking error (3Y)",
      description:
        "How far the fund's returns stray from its benchmark. Lower means it hugs the index; higher means a more active stance.",
      value: ratio(risk.tracking_error_3y),
    },
    {
      label: "Up capture (3Y)",
      title: "Upside capture (3Y)",
      description:
        "Share of the benchmark's gains the fund captured in up months. Above 100 means it outpaced the index when markets rose.",
      value: present(risk.up_capture_3y) ? ratio(risk.up_capture_3y) : null,
    },
    {
      label: "Down capture (3Y)",
      title: "Downside capture (3Y)",
      description:
        "Share of the benchmark's losses the fund absorbed in down months. Below 100 means it fell less than the index.",
      value: present(risk.down_capture_3y) ? ratio(risk.down_capture_3y) : null,
    },
    {
      label: "Excess vs benchmark (3Y)",
      title: "Benchmark excess (3Y)",
      description:
        "Annualised return above (or below) the benchmark over three years.",
      value: fracPct(risk.benchmark_excess_3y),
    },
    {
      label: "Category position (3Y)",
      title: "Category percentile (3Y)",
      description:
        "Where this fund's three-year statistics sit within its SEBI sub-category, from 0 (lowest) to 100 (highest). Descriptive only.",
      value: fmtPercentile(risk.category_percentile_3y),
    },
  ]

  const groups: { heading: string; metrics: MetricSpec[] }[] = [
    { heading: "Volatility & drawdown", metrics: volatility },
    { heading: "Risk-adjusted return", metrics: riskAdjusted },
    { heading: "Market sensitivity", metrics: marketSensitivity },
  ].map((g) => ({ ...g, metrics: g.metrics.filter((m) => m.value !== null) }))

  const visibleGroups = groups.filter((g) => g.metrics.length > 0)

  if (visibleGroups.length === 0) {
    return (
      <TabEmptyState
        title="Risk metrics are being prepared"
        message="Risk metrics compute nightly — check back."
      />
    )
  }

  return (
    <div className="grid gap-6">
      {risk.as_of ? (
        <p className="text-xs text-caption">
          Risk statistics as of {risk.as_of}
          {risk.lookback ? ` · ${risk.lookback} lookback` : ""}.
        </p>
      ) : null}

      <RevealStagger threshold={0} className="grid gap-6" staggerMs={60}>
        {visibleGroups.map((group) => (
          <section
            key={group.heading}
            className="rounded-lg border border-border bg-raised p-4"
          >
            <h3 className="mb-3 text-base font-semibold text-ink">
              {group.heading}
            </h3>
            <div className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3 lg:grid-cols-4">
              {group.metrics.map((m) => (
                <div key={m.label} className="min-w-0">
                  <MetricTooltip
                    label={m.label}
                    value={
                      <span className="num text-lg font-semibold text-ink">
                        {m.value}
                      </span>
                    }
                    ariaValueText={m.value ?? undefined}
                    title={m.title}
                    description={m.description}
                    formula={m.formula}
                    className="flex-col items-start gap-0.5"
                  />
                </div>
              ))}
            </div>
          </section>
        ))}
      </RevealStagger>

      <p className="text-xs leading-relaxed text-caption">
        Risk statistics are descriptive measures derived from historical NAV
        and benchmark data. They describe past variability and do not predict
        future outcomes.
      </p>
    </div>
  )
}
