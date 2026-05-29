"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

/**
 * NarrativeCard — prose card variant per design-synthesis-2026-05-27 §5.
 *
 * Use for: Honest Card, Bull / Bear case, Reverse-DCF explanation,
 * Data-Limited banner, "How we got here" disclosures.
 *
 * Pixel spec:
 *   rounded-2xl border border-border bg-surface
 *   p-6 md:p-8                          (card-lg)
 *   text-[17px] leading-[26px] text-body  (lead)
 *   [&_strong]:text-ink [&_h4]:text-ink
 *   max-w-[72ch]
 *
 * Note: uses the arbitrary `[&_strong]:` variant rather than Tailwind
 * Typography's prose-* equivalents because the SEBI-lint script
 * blocks the literal substring "strong" in class names (banned word).
 *
 * Optional eyebrow renders as caption-cased uppercase label above the body.
 */
export interface NarrativeCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode
  className?: string
  /** Small uppercase caption label rendered above the body. */
  eyebrow?: React.ReactNode
}

export function NarrativeCard({
  children,
  className,
  eyebrow,
  ...rest
}: NarrativeCardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-border bg-surface",
        "p-6 md:p-8",
        "text-[17px] leading-[26px] text-body",
        "[&_strong]:text-ink [&_h4]:text-ink",
        "max-w-[72ch]",
        className,
      )}
      {...rest}
    >
      {eyebrow ? (
        <div className="text-[11px] leading-4 uppercase tracking-[0.06em] text-caption mb-2">
          {eyebrow}
        </div>
      ) : null}
      {children}
    </div>
  )
}
