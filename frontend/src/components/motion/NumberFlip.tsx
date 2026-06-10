"use client"
/**
 * <NumberFlip> — animated number transition.
 *
 * Drop-in replacement for the legacy CountUpText / CountUp pattern.
 * The defining feature: when the `value` prop CHANGES (not just on
 * first reveal), the old digits flip out and the new digits flip in.
 * This makes live data feel "live" — a stock price tick or score
 * recompute is acknowledged rather than just being swapped.
 *
 * On first mount: same as CountUp — tween from `from` (default 0)
 * up to `value` once the element scrolls into view.
 *
 * Reduced-motion: skips both the entrance tween and the flip
 * transition. Just renders the formatted value as a plain span.
 *
 * SSR-safe: renders the final formatted value on the server so
 * crawlers and pre-hydration users see the right number.
 */
import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { useInViewOnce } from "@/components/anim/useInViewOnce"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { DURATION, cssEase } from "@/lib/motion/timing"

export interface NumberFlipProps {
  /** Target value. Changing this re-triggers the flip transition. */
  value: number
  /** Initial value for the first-mount tween. Default 0. */
  from?: number
  /** First-mount tween duration in seconds. Default 1.2. */
  duration?: number
  decimals?: number
  prefix?: string
  suffix?: string
  /** Custom formatter — overrides decimals/prefix/suffix. */
  format?: (n: number) => string
  className?: string
}

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3)
}

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

export default function NumberFlip({
  value,
  from = 0,
  duration = 1.2,
  decimals = 0,
  prefix = "",
  suffix = "",
  format,
  className,
}: NumberFlipProps) {
  const reduced = useReducedMotion()
  const { ref, inView } = useInViewOnce<HTMLSpanElement>(0.2)
  // `displayed` is the currently rendered numeric value. Starts at
  // `value` so the server snapshot and first client paint match.
  const [displayed, setDisplayed] = useState<number>(value)
  // `flipping` toggles a brief class to drive the flip transition.
  const [flipping, setFlipping] = useState(false)
  const prevValueRef = useRef<number>(value)
  const animatedFirstRef = useRef(false)

  // First-mount tween — runs once when the element scrolls into view.
  useEffect(() => {
    if (reduced) return
    if (!inView) return
    if (animatedFirstRef.current) return
    animatedFirstRef.current = true

    let raf = 0
    let startTs: number | null = null
    const ms = Math.max(0, duration) * 1000
    const delta = value - from
    setDisplayed(from)

    const tick = (now: number) => {
      if (startTs === null) startTs = now
      const t = ms === 0 ? 1 : Math.min(1, (now - startTs) / ms)
      setDisplayed(from + delta * easeOutCubic(t))
      if (t < 1) {
        raf = requestAnimationFrame(tick)
      } else {
        setDisplayed(value)
      }
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // We intentionally exclude `value` so a value change here doesn't
    // re-trigger the first-mount tween — value updates are handled
    // by the flip effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reduced, inView, from, duration])

  // Value-change flip — fires whenever `value` prop changes after first mount.
  useEffect(() => {
    if (prevValueRef.current === value) return
    prevValueRef.current = value
    if (reduced) {
      setDisplayed(value)
      return
    }
    // Trigger the flip class, then update the value mid-flip so the
    // old digits visually rotate out while the new ones rotate in.
    setFlipping(true)
    const flipDuration = DURATION.fast
    const halfway = window.setTimeout(() => {
      setDisplayed(value)
    }, flipDuration / 2)
    const done = window.setTimeout(() => {
      setFlipping(false)
    }, flipDuration)
    return () => {
      window.clearTimeout(halfway)
      window.clearTimeout(done)
    }
  }, [value, reduced])

  const display = format
    ? format(displayed)
    : defaultFormat(displayed, decimals, prefix, suffix)

  const style: React.CSSProperties = reduced
    ? {}
    : {
        display: "inline-block",
        transition: `transform ${DURATION.fast}ms ${cssEase("outExpo")}, opacity ${DURATION.fast}ms ${cssEase("out")}`,
        // Flip transform: rotateX(90deg) at the midpoint reads as
        // "card flipping over". The duration matches the timer above.
        transform: flipping ? "rotateX(-90deg)" : "rotateX(0)",
        opacity: flipping ? 0.4 : 1,
        transformOrigin: "center",
        // Avoid harsh anti-aliasing on the rotate transition.
        backfaceVisibility: "hidden",
      }

  return (
    <span
      ref={ref}
      className={cn("tabular-nums", className)}
      style={style}
      data-motion="number-flip"
      data-motion-flipping={flipping ? "true" : "false"}
    >
      {display}
    </span>
  )
}

export { NumberFlip }
