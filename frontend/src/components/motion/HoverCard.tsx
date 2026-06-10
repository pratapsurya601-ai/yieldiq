"use client"
/**
 * <HoverCard> — interactive-card hover primitive.
 *
 * Wrap a card-shaped element and it lifts 2px + adds a soft shadow +
 * scales to 1.02 on hover. Pure CSS via Tailwind + inline styles —
 * no Framer needed at runtime. Reduced-motion users get the lift
 * styling without the scale (lift is meaningful state feedback, the
 * scale is decorative).
 *
 * Design intent: hover feedback should read as "this is clickable"
 * in ~120ms (DURATION.instant). Anything slower starts to feel
 * laggy on a mouse-driven UI.
 */
import { type ReactNode } from "react"
import { cn } from "@/lib/utils"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { DURATION, cssEase } from "@/lib/motion/timing"

export interface HoverCardProps {
  children: ReactNode
  className?: string
  /** Disable the hover effect (e.g. card is in a disabled state). */
  disabled?: boolean
  as?: React.ElementType
  /** Forwarded onClick — HoverCard is meant to wrap clickables. */
  onClick?: () => void
}

export default function HoverCard({
  children,
  className,
  disabled = false,
  as: Tag = "div",
  onClick,
}: HoverCardProps) {
  const reduced = useReducedMotion()
  const TagAny: React.ElementType = Tag

  // Always transition the box-shadow + transform — reduced-motion
  // collapses the duration but we leave the transition wired up so
  // there's still subtle visual feedback on hover (otherwise the
  // card snaps without any "this is alive" cue).
  const transition = reduced
    ? "none"
    : `transform ${DURATION.instant}ms ${cssEase("out")}, box-shadow ${DURATION.instant}ms ${cssEase("out")}`

  const hoverClass = disabled
    ? ""
    : reduced
      ? // Reduced motion: keep the shadow change (state cue) but no transform.
        "hover:shadow-md focus-visible:shadow-md"
      : "hover:-translate-y-0.5 hover:shadow-md hover:scale-[1.02] focus-visible:-translate-y-0.5 focus-visible:shadow-md focus-visible:scale-[1.02]"

  return (
    <TagAny
      className={cn(hoverClass, className)}
      style={{ transition, willChange: disabled ? "auto" : "transform" }}
      onClick={disabled ? undefined : onClick}
      data-motion="hover-card"
      data-motion-reduced={reduced ? "true" : "false"}
    >
      {children}
    </TagAny>
  )
}

export { HoverCard }
