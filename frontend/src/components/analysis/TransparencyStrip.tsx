"use client"

import { cn } from "@/lib/utils"
import type { Confidence } from "@/types/api"

interface TransparencyStripProps {
  wacc: number
  waccMin: number
  waccMax: number
  fcfGrowth: number
  fcfGrowthHistAvg: number
  confidence: Confidence
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
}: TransparencyStripProps) {
  return (
    <div className={cn("rounded-lg bg-gray-50 px-3 py-2")}>
      <p className="text-xs text-gray-500 leading-relaxed">
        Model: WACC {wacc.toFixed(1)}% (industry {waccMin.toFixed(1)}&ndash;{waccMax.toFixed(1)}%)
        {" "}&middot;{" "}
        FCF growth +{fcfGrowth.toFixed(1)}%/yr (hist avg +{fcfGrowthHistAvg.toFixed(1)}%)
        {" "}&middot;{" "}
        Confidence: {CONFIDENCE_LABEL[confidence]}
      </p>
    </div>
  )
}
