"use client"

import { useEffect, useState } from "react"

import { useInViewOnce, useReducedMotion } from "@/components/anim"
import { formatCurrency } from "@/lib/utils"

/** easeOutCubic — the mockups' `eo()`. */
export const easeOut = (p: number): number => 1 - Math.pow(1 - p, 3)

/** easeOutBack — the mockups' `back()` (overshoot ~10%). */
export const backOut = (p: number): number => {
  const c1 = 1.70158
  const c3 = c1 + 1
  return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2)
}

export const linear = (p: number): number => p

/**
 * Stage clock for bespoke SVG choreography. The mockups animate on
 * load; in the route every sequence starts when its block first enters
 * the viewport (IntersectionObserver, once) and reduced motion snaps
 * straight to the final state. Components derive each sub-animation
 * from the single elapsed value via `seg()`.
 */
export function useStageClock<T extends Element = HTMLDivElement>(
  maxMs: number,
  threshold = 0.15,
): {
  ref: React.RefObject<T | null>
  inView: boolean
  reduced: boolean
  elapsed: number
  done: boolean
} {
  const reduced = useReducedMotion()
  const { ref, inView } = useInViewOnce<T>(threshold)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!inView) return
    if (reduced) {
      const id = window.setTimeout(() => setElapsed(maxMs), 0)
      return () => window.clearTimeout(id)
    }
    let raf = 0
    const t0 = performance.now()
    const step = (t: number) => {
      const e = Math.min(t - t0, maxMs)
      setElapsed(e)
      if (e < maxMs) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [inView, reduced, maxMs])

  return { ref, inView, reduced, elapsed, done: elapsed >= maxMs }
}

/** Eased progress (0..1) of one sub-animation on the stage clock. */
export function seg(
  elapsed: number,
  startMs: number,
  durMs: number,
  ease: (p: number) => number = easeOut,
): number {
  if (elapsed <= startMs) return 0
  return ease(Math.min((elapsed - startMs) / durMs, 1))
}

/** ₹-formatted integer, en-IN grouping — the mockups' `rupee()`. */
export function inr(n: number): string {
  return formatCurrency(Math.round(n))
}
