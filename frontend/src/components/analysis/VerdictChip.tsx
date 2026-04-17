"use client"

import { cn } from "@/lib/utils"
import { VERDICT_COLORS } from "@/lib/constants"
import type { Verdict } from "@/types/api"

const VERDICT_LABELS: Record<Verdict, string> = {
  undervalued: "Undervalued",
  fairly_valued: "Fairly valued",
  overvalued: "Overvalued",
  avoid: "High Risk",
  data_limited: "Data Limited",
  unavailable: "Unavailable",
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
