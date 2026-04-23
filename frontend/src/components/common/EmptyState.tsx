"use client"

// Shared empty-state component for first-visit / zero-holdings screens.
// Deliberately NOT used for "no results from a user query" — those are
// transient and warrant plain text with no illustration load cost.
//
// Usage:
//   <EmptyState
//     illustration="/illustrations/empty-portfolio.svg"
//     title="Track what you own"
//     description="Import your broker CSV or add a stock to see health scores."
//     actionLabel="Import CSV"
//     actionHref="/portfolio/import"
//     secondaryLabel="Explore stocks"
//     secondaryHref="/search"
//   />
//
// Illustrations live in frontend/public/illustrations/ (SVG). Keep
// max-height 160px so the card doesn't dominate the viewport on mobile.
//
// SEBI-safe language — use "discover" / "explore" / "try", never
// "buy" / "invest in" / "pick". Review every copy change against the
// ComplianceTest list in CI.

import Image from "next/image"
import Link from "next/link"
import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

interface EmptyStateProps {
  /** Path under /public, e.g. "/illustrations/empty-screener.svg". Omit for text-only. */
  illustration?: string
  /** Short descriptive alt text for the illustration. Default: "" (decorative). */
  illustrationAlt?: string
  title: string
  description?: string
  /** Primary action — internal Link href. */
  actionLabel?: string
  actionHref?: string
  /** Optional second action, lower-emphasis. */
  secondaryLabel?: string
  secondaryHref?: string
  /** Render custom action markup instead of the built-in buttons. */
  children?: ReactNode
  /** Extra classes for the outer container. */
  className?: string
}

export default function EmptyState({
  illustration,
  illustrationAlt = "",
  title,
  description,
  actionLabel,
  actionHref,
  secondaryLabel,
  secondaryHref,
  children,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center px-6 py-10 text-center rounded-2xl",
        "bg-white border border-gray-100",
        className,
      )}
    >
      {illustration && (
        <div className="relative w-full max-w-[240px] h-[160px] mb-5">
          <Image
            src={illustration}
            alt={illustrationAlt}
            fill
            priority={false}
            sizes="(max-width: 480px) 80vw, 240px"
            className="object-contain"
          />
        </div>
      )}

      <h2 className="text-lg font-semibold text-gray-900 mb-1">{title}</h2>

      {description && (
        <p className="text-sm text-gray-500 mb-5 max-w-sm">{description}</p>
      )}

      {children ? (
        <div className="flex flex-wrap justify-center gap-2">{children}</div>
      ) : (
        (actionLabel && actionHref) || (secondaryLabel && secondaryHref) ? (
          <div className="flex flex-wrap justify-center gap-2">
            {actionLabel && actionHref && (
              <Link
                href={actionHref}
                className={cn(
                  "inline-flex items-center justify-center rounded-full px-5 py-2.5 min-h-[44px]",
                  "bg-blue-600 text-white text-sm font-semibold",
                  "hover:bg-blue-700 active:bg-blue-800 active:scale-[0.97] transition",
                  "shadow-sm",
                )}
              >
                {actionLabel}
              </Link>
            )}
            {secondaryLabel && secondaryHref && (
              <Link
                href={secondaryHref}
                className={cn(
                  "inline-flex items-center justify-center rounded-full px-5 py-2.5 min-h-[44px]",
                  "bg-white border border-gray-200 text-gray-700 text-sm font-semibold",
                  "hover:border-blue-300 hover:text-blue-700 active:scale-[0.97] transition",
                )}
              >
                {secondaryLabel}
              </Link>
            )}
          </div>
        ) : null
      )}
    </div>
  )
}
