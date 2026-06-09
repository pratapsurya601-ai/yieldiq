"use client"
import { useEffect, useRef, useState, type ReactNode } from "react"
import { cn } from "@/lib/utils"
import { useReducedMotion } from "@/components/anim/useReducedMotion"

export type RevealDirection = "up" | "left" | "right" | "pop"

export interface RevealProps {
  children: ReactNode
  /**
   * Direction the children translate from before revealing.
   * - "up"    : starts 12px below, slides up (default)
   * - "left"  : starts 12px to the right, slides left
   * - "right" : starts 12px to the left, slides right
   * - "pop"   : starts at scale(0.96), pops to scale(1)
   */
  direction?: RevealDirection
  /** Extra delay in milliseconds before the reveal kicks off. Default 0. */
  delay?: number
  /**
   * Legacy prop. Kept for source-compat with PR #769 call-sites but
   * intentionally ignored: the observer now uses `threshold: 0` so
   * elements taller than the viewport (which can never satisfy a
   * non-zero threshold) reveal correctly. The viewport-height
   * short-circuit handles the multi-screen case directly. Safe to
   * remove from call-sites at any time.
   */
  threshold?: number
  /**
   * Optional className applied to the wrapper. Lets callers add margin
   * or layout classes without an extra wrapper div.
   */
  className?: string
  /** Render element tag. Default "div". */
  as?: keyof React.JSX.IntrinsicElements
}

/**
 * Premium-feel Round 1 — IntersectionObserver-driven fade + translate
 * primitive. Wraps any block and reveals it once when it scrolls into
 * view. After revealing it removes the observer so it never re-runs
 * (no idle animations on scroll back up).
 *
 * Design contract:
 *   - SSR-safe: server renders the final (revealed) markup; we hide
 *     and re-reveal on the client after first paint. Crawlers and
 *     no-JS users always see the content.
 *   - prefers-reduced-motion: reduce -> skip animation, render visible
 *     immediately.
 *   - Animation: opacity 0 -> 1 with a 12px directional translate or a
 *     scale(0.96) pop, transition-all duration-700 ease-out per the
 *     Premium Feel spec.
 */
export default function Reveal({
  children,
  direction = "up",
  delay = 0,
  threshold = 0.12,
  className,
  as: Tag = "div",
}: RevealProps) {
  const reduced = useReducedMotion()
  const ref = useRef<HTMLElement | null>(null)
  // Start mounted=false so the server markup and the first client paint
  // both render in the "hidden" position; once we know IO is available
  // we flip to true, attach the observer, and let the transition run.
  // Without this two-step the page would briefly flash final-state on
  // hydration before snapping back to start the animation.
  const [mounted, setMounted] = useState(false)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    // Flip mounted=true via a microtask so the cascading-render lint
    // rule (`react-hooks/set-state-in-effect`) stays happy — same
    // pattern AnalysisBody uses for first-paint personalization reads.
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
    // No IntersectionObserver (very old browser / SSR shim) -> reveal
    // immediately. Better to skip the animation than hide content.
    if (typeof IntersectionObserver === "undefined") {
      queueMicrotask(() => setVisible(true))
      return
    }
    // Short-circuit: blocks taller than 1.5x viewport never animate.
    // For very tall wrappers (e.g. the analysis tabs region — 5,426px
    // in a 533-900px viewport) only ~10-16% of the element is ever in
    // view at once, which sits below any non-zero IO threshold and the
    // intersect callback never fires. The animation is also pointless
    // on multi-screen elements (the user can see only a slice anyway),
    // so the failure mode (invisible content) is strictly worse than
    // skipping the reveal. Reveal immediately and skip the observer.
    if (typeof window !== "undefined") {
      const elHeight = node.getBoundingClientRect().height
      if (elHeight > window.innerHeight * 1.5) {
        queueMicrotask(() => setVisible(true))
        return
      }
    }
    // threshold: 0 — any pixel visible triggers, safest for blocks that
    // approach but never fully cross the viewport. rootMargin's negative
    // bottom inset gives a small extra safety margin so the trigger
    // zone reaches up into the lower 10% of the viewport.
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
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
  }, [mounted, reduced, threshold])

  // Hidden state classes per direction. Numbers are intentionally
  // small (12px translate, 96% scale) so the animation reads as
  // premium "settle in" rather than "fly in".
  const hiddenByDirection: Record<RevealDirection, string> = {
    up: "opacity-0 translate-y-3",
    left: "opacity-0 translate-x-3",
    right: "opacity-0 -translate-x-3",
    pop: "opacity-0 scale-[0.96]",
  }
  const shownByDirection: Record<RevealDirection, string> = {
    up: "opacity-100 translate-y-0",
    left: "opacity-100 translate-x-0",
    right: "opacity-100 translate-x-0",
    pop: "opacity-100 scale-100",
  }

  // SSR / pre-mount path: render in the final state so crawlers and the
  // first server-rendered HTML look complete. Reduced-motion path: also
  // final-state, no transition.
  const showFinal = !mounted || reduced || visible

  const stateClass = showFinal
    ? shownByDirection[direction]
    : hiddenByDirection[direction]

  const style: React.CSSProperties = {
    transitionDelay: showFinal && !reduced && mounted ? `${delay}ms` : undefined,
  }

  const TagAny = Tag as unknown as React.ElementType
  return (
    <TagAny
      ref={ref as React.RefObject<HTMLDivElement>}
      data-reveal={direction}
      data-reveal-visible={showFinal ? "true" : "false"}
      className={cn(
        "transition-all duration-700 ease-out will-change-transform",
        stateClass,
        className,
      )}
      style={style}
    >
      {children}
    </TagAny>
  )
}

export { Reveal }
