"use client"
import { Children, type ReactNode } from "react"
import { useInViewOnce } from "./useInViewOnce"
import { useReducedMotion } from "./useReducedMotion"

export type FadeDirection = "up" | "down" | "left" | "right"

export interface FadeStaggerProps {
  children: ReactNode
  /** Delay between successive children, ms. Default 100. */
  staggerMs?: number
  /** Direction the children slide IN from. Default "up". */
  direction?: FadeDirection
  /** Per-child transition duration, ms. Default 500. */
  durationMs?: number
  /** Viewport threshold to begin the stagger. Default 0.15. */
  threshold?: number
  className?: string
  /** Wrapper element for each child. Default "div". */
  as?: React.ElementType
}

function translateFor(direction: FadeDirection, visible: boolean): string {
  if (visible) return "translate3d(0,0,0)"
  switch (direction) {
    case "up":
      return "translate3d(0,8px,0)"
    case "down":
      return "translate3d(0,-8px,0)"
    case "left":
      return "translate3d(8px,0,0)"
    case "right":
      return "translate3d(-8px,0,0)"
  }
}

/**
 * <FadeStagger> — fades + slides each child into view, one after the
 * other. CSS-only (no framer-motion), per the bundle-size constraint.
 *
 * SSR renders children in their final position (opacity 1, no offset)
 * so non-JS users see the content. After mount we briefly snap them to
 * their pre-animation state before triggering the transition on
 * viewport entry.
 */
export function FadeStagger({
  children,
  staggerMs = 100,
  direction = "up",
  durationMs = 500,
  threshold = 0.15,
  className,
  as = "div",
}: FadeStaggerProps) {
  const reduced = useReducedMotion()
  const { ref, inView } = useInViewOnce<HTMLDivElement>(threshold)
  const visible = reduced || inView
  const items = Children.toArray(children)
  const Wrapper: React.ElementType = as

  return (
    <div ref={ref} className={className} data-anim="fade-stagger">
      {items.map((child, i) => {
        const delay = reduced ? 0 : i * staggerMs
        const style: React.CSSProperties = {
          opacity: visible ? 1 : 0,
          transform: translateFor(direction, visible),
          transition: reduced
            ? "none"
            : `opacity ${durationMs}ms ease-out ${delay}ms, transform ${durationMs}ms cubic-bezier(0.22,1,0.36,1) ${delay}ms`,
          willChange: visible ? "auto" : "opacity, transform",
        }
        return (
          <Wrapper
            key={i}
            style={style}
            data-stagger-index={i}
          >
            {child}
          </Wrapper>
        )
      })}
    </div>
  )
}

export default FadeStagger
