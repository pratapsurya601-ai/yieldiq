"use client"
/**
 * <RevealStagger> — list-entrance primitive.
 *
 * Wraps a list of children; each child fades + slides up in
 * sequence after the wrapper enters the viewport. CSS-only
 * implementation (no framer-motion) — keeps the bundle small for
 * call-sites that don't need the full motion engine.
 *
 * Uses `useInViewOnce` from the legacy anim package so the trigger
 * behavior is identical to FadeStagger; this is the renamed
 * successor that lives under the new namespace.
 */
import { Children, type ReactNode } from "react"
import { useInViewOnce } from "@/components/anim/useInViewOnce"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { DURATION, cssEase } from "@/lib/motion/timing"

export type StaggerDirection = "up" | "down" | "left" | "right"

export interface RevealStaggerProps {
  children: ReactNode
  /** Delay between successive children, ms. Default 80. */
  staggerMs?: number
  /** Direction children slide IN from. Default "up". */
  direction?: StaggerDirection
  /** Per-child transition duration, ms. Default 400 (DURATION.normal). */
  durationMs?: number
  /** Viewport threshold to begin the stagger. Default 0.15. */
  threshold?: number
  /** Optional extra wait before the first child reveals. */
  delayMs?: number
  className?: string
  /** Element tag for each child wrapper. Default "div". */
  as?: React.ElementType
}

function translateFor(d: StaggerDirection, visible: boolean): string {
  if (visible) return "translate3d(0,0,0)"
  switch (d) {
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

export default function RevealStagger({
  children,
  staggerMs = 80,
  direction = "up",
  durationMs = DURATION.normal,
  threshold = 0.15,
  delayMs = 0,
  className,
  as = "div",
}: RevealStaggerProps) {
  const reduced = useReducedMotion()
  const { ref, inView } = useInViewOnce<HTMLDivElement>(threshold)
  const visible = reduced || inView
  const items = Children.toArray(children)
  const Wrapper: React.ElementType = as

  // String built once per render — low cost; main allocation is the
  // template-literal per child, which is unavoidable because each
  // child has its own delay.
  const ease = cssEase("outExpo")

  return (
    <div ref={ref} className={className} data-anim="reveal-stagger">
      {items.map((child, i) => {
        const delay = reduced ? 0 : delayMs + i * staggerMs
        const style: React.CSSProperties = {
          opacity: visible ? 1 : 0,
          transform: translateFor(direction, visible),
          transition: reduced
            ? "none"
            : `opacity ${durationMs}ms ease-out ${delay}ms, transform ${durationMs}ms ${ease} ${delay}ms`,
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

export { RevealStagger }
