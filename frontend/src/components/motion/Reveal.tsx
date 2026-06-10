"use client"
/**
 * <Reveal> — viewport-entrance primitive.
 *
 * Lives at `@/components/motion/Reveal` and is the canonical reveal
 * for new code. The legacy `@/components/common/Reveal` re-exports
 * this so existing call-sites keep working; the legacy props
 * (`direction`, `delay`, `threshold`, `as`) are all preserved.
 *
 * Differences from the legacy implementation:
 *   - Pulls easing + duration from `@/lib/motion/timing` so the curve
 *     tunes in one place.
 *   - Pulls reduced-motion from `@/lib/motion/useReducedMotion` so
 *     the in-app override toggle works alongside the OS-level pref.
 *   - Same SSR-render-final → hide-after-mount → reveal-on-IO
 *     two-step that the legacy file documented.
 *   - Same "tall element" shortcut: anything > 1.5 viewports skips
 *     IO and reveals immediately (otherwise IO never fires).
 */
import { useEffect, useRef, useState, type ReactNode } from "react"
import { cn } from "@/lib/utils"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { DURATION, cssEase } from "@/lib/motion/timing"

export type RevealDirection = "up" | "left" | "right" | "pop"

export interface RevealProps {
  children: ReactNode
  /** Direction the children translate from before revealing. */
  direction?: RevealDirection
  /** Extra delay in milliseconds before the reveal kicks off. */
  delay?: number
  /**
   * Legacy prop, intentionally ignored. The observer uses
   * `threshold: 0` so elements taller than the viewport reveal
   * correctly. Kept on the type for source compatibility.
   */
  threshold?: number
  className?: string
  as?: keyof React.JSX.IntrinsicElements
}

const HIDDEN: Record<RevealDirection, string> = {
  up: "opacity-0 translate-y-3",
  left: "opacity-0 translate-x-3",
  right: "opacity-0 -translate-x-3",
  pop: "opacity-0 scale-[0.96]",
}
const SHOWN: Record<RevealDirection, string> = {
  up: "opacity-100 translate-y-0",
  left: "opacity-100 translate-x-0",
  right: "opacity-100 translate-x-0",
  pop: "opacity-100 scale-100",
}

/** Built once at module-load so the CSS string is stable. */
const REVEAL_TRANSITION = `all ${DURATION.slow}ms ${cssEase("outExpo")}`

export default function Reveal({
  children,
  direction = "up",
  delay = 0,
  threshold: _threshold,
  className,
  as: Tag = "div",
}: RevealProps) {
  void _threshold // explicitly ignored — see prop docs
  const reduced = useReducedMotion()
  const ref = useRef<HTMLElement | null>(null)
  const [mounted, setMounted] = useState(false)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    queueMicrotask(() => setMounted(true))
  }, [])

  useEffect(() => {
    if (!mounted) return
    if (reduced) {
      queueMicrotask(() => setVisible(true))
      return
    }
    const node = ref.current
    if (!node) return
    if (typeof IntersectionObserver === "undefined") {
      queueMicrotask(() => setVisible(true))
      return
    }
    // Tall-element shortcut — see comment in legacy Reveal.tsx.
    if (typeof window !== "undefined") {
      const h = node.getBoundingClientRect().height
      if (h > window.innerHeight * 1.5) {
        queueMicrotask(() => setVisible(true))
        return
      }
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setVisible(true)
            observer.disconnect()
            break
          }
        }
      },
      { threshold: 0, rootMargin: "0px 0px -10% 0px" },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [mounted, reduced])

  const showFinal = !mounted || reduced || visible
  const stateClass = showFinal ? SHOWN[direction] : HIDDEN[direction]

  const TagAny = Tag as unknown as React.ElementType
  return (
    <TagAny
      ref={ref as React.RefObject<HTMLDivElement>}
      data-reveal={direction}
      data-reveal-visible={showFinal ? "true" : "false"}
      className={cn(
        "will-change-transform",
        stateClass,
        className,
      )}
      style={{
        transition: reduced ? "none" : REVEAL_TRANSITION,
        transitionDelay:
          showFinal && !reduced && mounted ? `${delay}ms` : undefined,
      }}
    >
      {children}
    </TagAny>
  )
}

export { Reveal }
