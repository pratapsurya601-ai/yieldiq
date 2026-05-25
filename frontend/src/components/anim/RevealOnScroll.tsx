"use client"
import type { ReactNode } from "react"
import { useInViewOnce } from "./useInViewOnce"
import { useReducedMotion } from "./useReducedMotion"

export interface RevealOnScrollProps {
  children: ReactNode
  /** Extra delay in ms before the reveal starts. Default 0. */
  delay?: number
  /** Fraction of the element that must be visible to trigger. Default 0.15. */
  threshold?: number
  /** Reveal duration in ms. Default 600. */
  durationMs?: number
  className?: string
}

/**
 * <RevealOnScroll> — the workhorse primitive. Wrap any section and it
 * fades + slides up 8px when it enters the viewport. Once revealed,
 * static (per manifesto rule 8: "no idle animations").
 *
 * SSR-safe: renders in final state on the server. After hydration we
 * still respect prefers-reduced-motion and skip the animation entirely.
 */
export function RevealOnScroll({
  children,
  delay = 0,
  threshold = 0.15,
  durationMs = 600,
  className,
}: RevealOnScrollProps) {
  const reduced = useReducedMotion()
  const { ref, inView } = useInViewOnce<HTMLDivElement>(threshold)
  const visible = reduced || inView

  const style: React.CSSProperties = {
    opacity: visible ? 1 : 0,
    transform: visible ? "translate3d(0,0,0)" : "translate3d(0,8px,0)",
    transition: reduced
      ? "none"
      : `opacity ${durationMs}ms ease-out ${delay}ms, transform ${durationMs}ms cubic-bezier(0.22,1,0.36,1) ${delay}ms`,
    willChange: visible ? "auto" : "opacity, transform",
  }

  return (
    <div ref={ref} className={className} style={style} data-anim="reveal">
      {children}
    </div>
  )
}

export default RevealOnScroll
