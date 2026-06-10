"use client"
/**
 * <ShimmerSkeleton> — animated loading placeholder.
 *
 * Renders a div with the `.skeleton` shimmer animation already
 * defined in globals.css (skeleton-shimmer keyframes, 1.8s loop).
 * This wrapper exists so call-sites don't have to remember the
 * class name + the rounding + the size pattern every time.
 *
 * Reduced-motion users get a flat block in `--color-border`
 * (handled by the existing globals.css media query — see
 * `@media (prefers-reduced-motion: reduce) .skeleton`).
 *
 * Variants:
 *   variant="text" — single line, rounded-sm. Default.
 *   variant="block" — rectangle (uses the size you give).
 *   variant="circle" — perfect circle (uses the smaller of w/h).
 */
import { cn } from "@/lib/utils"

export interface ShimmerSkeletonProps {
  className?: string
  variant?: "text" | "block" | "circle"
  /** ARIA label for screen readers. Default "Loading". */
  label?: string
  /** Width in CSS units (number → px). */
  width?: number | string
  /** Height in CSS units (number → px). */
  height?: number | string
}

function toCss(v: number | string | undefined): string | undefined {
  if (v === undefined) return undefined
  return typeof v === "number" ? `${v}px` : v
}

export default function ShimmerSkeleton({
  className,
  variant = "text",
  label = "Loading",
  width,
  height,
}: ShimmerSkeletonProps) {
  const radiusClass =
    variant === "circle"
      ? "rounded-full"
      : variant === "block"
        ? "rounded-md"
        : "rounded-sm"

  // Sensible defaults: text is a 1em-tall line; block fills the
  // parent; circle is square so width/height should match.
  const sizeStyle: React.CSSProperties = {
    width: toCss(width),
    height: toCss(height) ?? (variant === "text" ? "1em" : undefined),
  }

  return (
    <span
      role="status"
      aria-label={label}
      aria-busy="true"
      className={cn("skeleton block", radiusClass, className)}
      style={sizeStyle}
      data-motion="shimmer-skeleton"
    />
  )
}

export { ShimmerSkeleton }
