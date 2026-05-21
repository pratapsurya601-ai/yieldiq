"use client"

import { cn } from "@/lib/utils"
import { VERDICT_COLORS } from "@/lib/constants"
import type { Verdict } from "@/types/api"

const VERDICT_LABELS: Record<Verdict, string> = {
  undervalued: "Below Fair Value",
  fairly_valued: "Near Fair Value",
  overvalued: "Above Fair Value",
  avoid: "High Risk",
  data_limited: "Data Limited",
  unavailable: "Unavailable",
  // Day-61 (2026-05-21): rendered when model confidence < 50%. Honest
  // framing --- the model has a leaning but doesn't trust itself enough
  // to colour-code a confident verdict. The hero metrics still show
  // FV / MoS so the user can read the underlying number directly.
  low_confidence: "Low Confidence",
}

const SIZE_CLASSES = {
  sm: "px-2 py-0.5 text-xs",
  md: "px-3 py-1 text-sm",
  lg: "px-4 py-1.5 text-base",
} as const

interface VerdictChipProps {
  verdict: Verdict
  size?: "sm" | "md" | "lg"
}

export default function VerdictChip({ verdict, size = "md" }: VerdictChipProps) {
  const colors = VERDICT_COLORS[verdict]

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full font-medium border",
        colors.bg,
        colors.text,
        colors.border,
        SIZE_CLASSES[size]
      )}
    >
      {VERDICT_LABELS[verdict]}
    </span>
  )
}
