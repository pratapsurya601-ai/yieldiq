"use client"
import {
  Children,
  cloneElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from "react"
import { useInViewOnce } from "./useInViewOnce"
import { useReducedMotion } from "./useReducedMotion"

export interface ChartDrawInProps {
  children: ReactNode
  /** Delay before draw-in starts, ms. Default 0. */
  animationBegin?: number
  /** Duration of the draw-in, ms. Default 900. */
  animationDuration?: number
  /** Viewport-entry threshold. Default 0.2. */
  threshold?: number
  className?: string
  /**
   * If true, also wrap with a CSS clip-path reveal in addition to the
   * Recharts prop injection. Useful for non-Recharts children
   * (SVG paths, D3 charts) — they get a left-to-right reveal even if
   * they ignore the injected props.
   */
  cssReveal?: boolean
}

interface InjectableProps {
  isAnimationActive?: boolean
  animationBegin?: number
  animationDuration?: number
}

/**
 * <ChartDrawIn> — wraps a Recharts chart (or any SVG children) so the
 * draw-in animation only fires when the chart enters the viewport.
 *
 * Strategy (per manifesto rule 8: charts draw in left-to-right on first
 * viewport entry):
 *  1. Mount the children with `isAnimationActive={false}` so Recharts
 *     does NOT animate on initial render (which would happen offscreen).
 *  2. On viewport entry, re-render with `isAnimationActive={true}` plus
 *     the configured begin/duration props. Recharts re-runs its
 *     animation.
 *  3. If `cssReveal` is set (or the child isn't a Recharts component),
 *     also apply a `clip-path` left→right reveal so non-Recharts SVG
 *     gets the same effect.
 *  4. Reduced motion → render immediately, static.
 */
export function ChartDrawIn({
  children,
  animationBegin = 0,
  animationDuration = 900,
  threshold = 0.2,
  className,
  cssReveal = false,
}: ChartDrawInProps) {
  const reduced = useReducedMotion()
  const { ref, inView } = useInViewOnce<HTMLDivElement>(threshold)
  const active = reduced ? true : inView

  // Inject Recharts-style animation props into direct children.
  const injected = Children.map(children, (child) => {
    if (!isValidElement(child)) return child
    const el = child as ReactElement<InjectableProps>
    return cloneElement(el, {
      isAnimationActive: !reduced && active,
      animationBegin,
      animationDuration,
    })
  })

  // CSS reveal: clip-path inset from the right collapses to 0 on entry.
  const useCss = cssReveal && !reduced
  const style = useCss
    ? {
        clipPath: active ? "inset(0 0 0 0)" : "inset(0 100% 0 0)",
        transition: `clip-path ${animationDuration}ms cubic-bezier(0.22,1,0.36,1) ${animationBegin}ms`,
      }
    : undefined

  return (
    <div
      ref={ref}
      className={className}
      data-anim="chart-drawin"
      data-in-view={active ? "true" : "false"}
      style={style}
    >
      {injected}
    </div>
  )
}

export default ChartDrawIn
