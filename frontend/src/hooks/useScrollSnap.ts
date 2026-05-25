"use client"
import { useMemo, useRef } from "react"

export type ScrollSnapVariant = "mandatory" | "proximity" | "none"

export interface UseScrollSnapResult {
  /** Ref to attach to the scroll container. */
  ref: React.RefObject<HTMLDivElement | null>
  /** Class names to apply to the scroll container. */
  containerClassName: string
  /** Class names to apply to each direct child that should snap. */
  itemClassName: string
}

/**
 * useScrollSnap() — opt-in scroll-snap utilities for analysis pages.
 *
 * Per manifesto's "visual vocabulary": the analysis page wrapper uses
 * `scroll-snap-y mandatory` so sections snap into view as the user
 * scrolls. This hook just returns the right Tailwind class strings so
 * pages don't have to memorize them and we keep one source of truth.
 *
 * Variants:
 *  - "mandatory"  — snaps to nearest section, always
 *  - "proximity"  — only snaps if close to a section (gentler)
 *  - "none"       — no snapping; useful for conditionally disabling
 *                   (e.g., when a modal opens)
 */
export function useScrollSnap(
  variant: ScrollSnapVariant = "mandatory",
): UseScrollSnapResult {
  const ref = useRef<HTMLDivElement | null>(null)

  const containerClassName = useMemo(() => {
    switch (variant) {
      case "mandatory":
        return "snap-y snap-mandatory overflow-y-auto"
      case "proximity":
        return "snap-y snap-proximity overflow-y-auto"
      case "none":
        return ""
    }
  }, [variant])

  const itemClassName = variant === "none" ? "" : "snap-start"

  return { ref, containerClassName, itemClassName }
}

export default useScrollSnap
