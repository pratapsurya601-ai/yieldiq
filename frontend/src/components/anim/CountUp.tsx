"use client"
import { useEffect, useState } from "react"
import { useInViewOnce } from "./useInViewOnce"
import { useReducedMotion } from "./useReducedMotion"

export interface CountUpProps {
  to: number
  from?: number
  /** Animation duration in seconds. Default 1.2. */
  duration?: number
  decimals?: number
  prefix?: string
  suffix?: string
  /** Custom formatter. Overrides decimals/prefix/suffix if provided. */
  format?: (n: number) => string
  className?: string
}

// Cubic ease-out: fast start, soft landing — feels like the number is
// "settling" rather than racing past.
function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3)
}

// Memoize formatters by decimal count — Intl.NumberFormat instantiation
// is non-trivial and CountUp can re-render 60x/sec during animation.
const FORMATTER_CACHE = new Map<number, Intl.NumberFormat>()
function getFormatter(decimals: number): Intl.NumberFormat {
  let f = FORMATTER_CACHE.get(decimals)
  if (!f) {
    f = new Intl.NumberFormat(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })
    FORMATTER_CACHE.set(decimals, f)
  }
  return f
}

function defaultFormat(
  n: number,
  decimals: number,
  prefix: string,
  suffix: string,
): string {
  return `${prefix}${getFormatter(decimals).format(n)}${suffix}`
}

/**
 * <CountUp /> — animates a number from `from` → `to` once, when the
 * element first enters the viewport. Per Design Manifesto rule 8:
 * "animations are storytelling, not decoration". This means:
 *  - never re-animate on re-render
 *  - never animate offscreen
 *  - respect prefers-reduced-motion (snap to final value)
 *  - SSR renders the final value so non-JS / pre-hydration users still
 *    see the right number.
 *
 * State model:
 *  - `animValue: number | null` — null means "not animating yet, show
 *    the SSR/final value". Set non-null once RAF starts. This lets us
 *    render the final value on the server and during the brief window
 *    between hydration and viewport entry, then take over once the
 *    animation actually begins.
 */
export function CountUp({
  to,
  from = 0,
  duration = 1.2,
  decimals = 0,
  prefix = "",
  suffix = "",
  format,
  className,
}: CountUpProps) {
  const reduced = useReducedMotion()
  const { ref, inView } = useInViewOnce<HTMLSpanElement>(0.2)
  const [animValue, setAnimValue] = useState<number | null>(null)

  useEffect(() => {
    // Reduced motion → never animate. Final value already shown.
    if (reduced) return
    // Wait for viewport entry.
    if (!inView) return

    let raf = 0
    let startTs: number | null = null
    const durationMs = Math.max(0, duration) * 1000
    const delta = to - from

    // All setState happens inside the RAF callback — the
    // `react-hooks/set-state-in-effect` rule allows setState in
    // subscriber/callback functions (RAF, IO, event handlers), just
    // not synchronously in the effect body.
    const tick = (now: number) => {
      if (startTs === null) startTs = now
      const elapsed = now - startTs
      const t = durationMs === 0 ? 1 : Math.min(1, elapsed / durationMs)
      setAnimValue(from + delta * easeOutCubic(t))
      if (t < 1) {
        raf = requestAnimationFrame(tick)
      } else {
        setAnimValue(to)
      }
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [reduced, inView, from, to, duration])

  // Until the animation effect fires (server, pre-hydration, pre-IO,
  // or reduced-motion), show the final value. Once animating, show the
  // tween. This keeps SSR == first client paint.
  const display = format
    ? format(animValue ?? to)
    : defaultFormat(animValue ?? to, decimals, prefix, suffix)

  return (
    <span ref={ref} className={className} data-anim="countup">
      {display}
    </span>
  )
}

export default CountUp
