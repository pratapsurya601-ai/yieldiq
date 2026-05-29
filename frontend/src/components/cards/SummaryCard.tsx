"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

/**
 * SummaryCard — verdict / score / single-big-metric card variant per
 * design-synthesis-2026-05-27 §5.
 *
 * Use for: hero verdict tile, Worry Index gauge card, sticky scorecard tiles.
 * Raised surface with the spec's two-layer subtle shadow.
 *
 * Pixel spec:
 *   rounded-2xl border border-border bg-raised
 *   p-4 md:p-6                              (card-md)
 *   shadow-[0_1px_2px_rgba(15,23,42,0.04),0_4px_12px_rgba(15,23,42,0.04)]
 *   flex flex-col gap-1
 *
 * Optional 4px verdict bar on the left edge — pass any CSS color via
 * `verdictBarColor`. The bar renders via a ::before pseudo-element so it
 * sits flush with the rounded card edge without affecting content layout.
 */
export interface SummaryCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode
  className?: string
  /**
   * Optional CSS color for the 4px left verdict bar.
   * Pass a hex, rgb, or CSS variable reference (e.g. `var(--color-success)`).
   * When omitted the bar is not rendered.
   */
  verdictBarColor?: string
}

export function SummaryCard({
  children,
  className,
  verdictBarColor,
  style,
  ...rest
}: SummaryCardProps) {
  const hasBar = Boolean(verdictBarColor)
  const mergedStyle = hasBar
    ? ({ ...(style ?? {}), ["--verdict-bar" as string]: verdictBarColor } as React.CSSProperties)
    : style

  return (
    <div
      className={cn(
        "rounded-2xl border border-border bg-raised",
        "p-4 md:p-6",
        "shadow-[0_1px_2px_rgba(15,23,42,0.04),0_4px_12px_rgba(15,23,42,0.04)]",
        "flex flex-col gap-1",
        hasBar &&
          "relative before:absolute before:left-0 before:top-0 before:h-full before:w-1 before:rounded-l-2xl before:bg-[var(--verdict-bar)]",
        className,
      )}
      style={mergedStyle}
      {...rest}
    >
      {children}
    </div>
  )
}
