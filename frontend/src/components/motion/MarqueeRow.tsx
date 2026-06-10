"use client"
/**
 * <MarqueeRow> — infinite-scroll ticker tape primitive.
 *
 * Renders a horizontal row of children that loops continuously. Uses
 * the `ticker-scroll` keyframes already defined in globals.css —
 * we keep the keyframes there so the animation works for any
 * `.marquee-row` class users; this component handles the
 * duplicate-children + pause-on-hover concerns.
 *
 * Implementation note: an infinite marquee needs the children
 * duplicated so the loop reads as seamless. We render the children
 * twice (the original set + a clone) and translate -50% over the
 * duration — the clone slides in just as the original slides out.
 *
 * Reduced-motion users get a static row (no scroll, no clone) so
 * screen readers don't read duplicated content and the animation
 * stops as expected.
 */
import { Children, type ReactNode } from "react"
import { cn } from "@/lib/utils"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"

export interface MarqueeRowProps {
  children: ReactNode
  /** Seconds for one full loop. Lower = faster. Default 40. */
  durationS?: number
  /** Pause scrolling while the user is hovering the row. Default true. */
  pauseOnHover?: boolean
  /** Gap between children, in any CSS unit. Default "2rem". */
  gap?: string
  /** Reverse the scroll direction (right → left vs left → right). */
  reverse?: boolean
  className?: string
}

export default function MarqueeRow({
  children,
  durationS = 40,
  pauseOnHover = true,
  gap = "2rem",
  reverse = false,
  className,
}: MarqueeRowProps) {
  const reduced = useReducedMotion()
  const items = Children.toArray(children)

  // Reduced-motion path: render the items once, no clone, no
  // animation. Overflow stays hidden so layout is identical.
  if (reduced) {
    return (
      <div
        className={cn("overflow-hidden", className)}
        data-motion="marquee-reduced"
      >
        <div className="flex" style={{ gap }}>
          {items.map((child, i) => (
            <span key={i}>{child}</span>
          ))}
        </div>
      </div>
    )
  }

  // We render the children twice; the second copy is hidden from
  // screen readers via aria-hidden so the row reads as a single
  // list to assistive tech.
  const animation = `ticker-scroll ${durationS}s linear infinite`
  const direction = reverse ? "reverse" : "normal"

  return (
    <div
      className={cn(
        "overflow-hidden",
        pauseOnHover && "group",
        className,
      )}
      data-motion="marquee"
    >
      <div
        className={cn(
          "flex w-max",
          pauseOnHover && "group-hover:[animation-play-state:paused]",
        )}
        style={{
          gap,
          animation,
          animationDirection: direction,
        }}
      >
        {items.map((child, i) => (
          <span key={`a-${i}`}>{child}</span>
        ))}
        {/* Clone for seamless loop. Hidden from a11y tree. */}
        <div
          aria-hidden="true"
          className="flex shrink-0"
          style={{ gap, marginLeft: gap }}
        >
          {items.map((child, i) => (
            <span key={`b-${i}`}>{child}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

export { MarqueeRow }
