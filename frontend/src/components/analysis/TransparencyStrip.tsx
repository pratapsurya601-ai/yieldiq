"use client"

import { cn } from "@/lib/utils"
import type { Confidence } from "@/types/api"
import MetricTooltip from "@/components/common/MetricTooltip"

interface TransparencyStripProps {
  wacc: number
  waccMin: number
  waccMax: number
  fcfGrowth: number
  fcfGrowthHistAvg: number
  confidence: Confidence
  fcfDataSource?: string
}

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
  unusable: "Very Low",
}

export default function TransparencyStrip({
  wacc,
  waccMin,
  waccMax,
  fcfGrowth,
  fcfGrowthHistAvg,
  confidence,
  fcfDataSource,
}: TransparencyStripProps) {
  const fcfLabel = fcfDataSource === "ttm" ? "TTM" : "hist avg"
  const histExtras = fcfDataSource !== "ttm"
    ? ` ${fcfGrowthHistAvg >= 0 ? "+" : ""}${(fcfGrowthHistAvg * 100).toFixed(1)}%`
    : ""

  // Premium Feel R2 — wrap each model input with a hover-explainer so
  // a user can hover the figure and learn what it means without
  // leaving the page.
  return (
    <div className={cn("rounded-lg bg-surface px-3 py-2")}>
      <p className="text-xs text-caption leading-relaxed">
        Model:{" "}
        <MetricTooltip
          metric="wacc"
          label="WACC"
          showLabel={false}
          valueClassName="text-caption"
          value={
            <>
              WACC {(wacc * 100).toFixed(1)}% (industry {(waccMin * 100).toFixed(1)}&ndash;{(waccMax * 100).toFixed(1)}%)
            </>
          }
        />
        {" "}&middot;{" "}
        <MetricTooltip
          metric="fcf_revenue"
          label="FCF growth"
          showLabel={false}
          valueClassName="text-caption"
          title="FCF growth rate"
          description="Projected annual growth in free cash flow over the explicit DCF window. We seed it from history then taper toward the terminal rate."
          threshold="High-quality compounders: 8-15% sustained. Mature large-caps: 4-8%. Cyclicals: range-bound by where in the cycle we are."
          caveat="A single bumper year can flatter this number; check the historical average alongside the model forecast."
          value={
            <>
              FCF growth {fcfGrowth >= 0 ? "+" : ""}{(fcfGrowth * 100).toFixed(1)}%/yr ({fcfLabel}{histExtras})
            </>
          }
        />
        {" "}&middot;{" "}
        <MetricTooltip
          metric="confidence"
          label="Confidence"
          showLabel={false}
          valueClassName="text-caption"
          value={
            <>
              Confidence: {CONFIDENCE_LABEL[confidence]}
            </>
          }
        />
      </p>
    </div>
  )
}
