"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

/**
 * DataCard — data-dense card variant per design-synthesis-2026-05-27 §5.
 *
 * Use for: peers tables, scorecard tiles, metric grids, F-Score breakdown,
 * financials tables, shareholding tables. Border-only (no shadow), tabular
 * body-sm typography by default, subtle hover when interactive.
 *
 * Pixel spec:
 *   rounded-lg border border-border bg-surface
 *   p-3 md:p-4               (card-sm → card-md)
 *   text-[13px] leading-[18px] num
 *   hover:bg-bg hover:border-ink/20 transition-colors (when hover=true)
 */
export interface DataCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode
  className?: string
  /** Enable subtle hover affordance. Defaults to true. Set false for non-interactive tiles. */
  hover?: boolean
}

export function DataCard({
  children,
  className,
  hover = true,
  ...rest
}: DataCardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-surface",
        "p-3 md:p-4",
        "text-[13px] leading-[18px] num",
        hover && "hover:bg-bg hover:border-ink/20 transition-colors",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  )
}
