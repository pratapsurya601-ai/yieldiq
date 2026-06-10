"use client"
/**
 * <PressScale> — press-feedback primitive for buttons and clickables.
 *
 * Wraps the child and scales it to 0.97 on :active. This is the
 * standard "tap feedback" gesture on mobile; on desktop it doubles
 * as click confirmation. Reduced-motion users get a brief opacity
 * dip instead (visual feedback without the scale).
 *
 * Designed as a styling wrapper — does NOT inject a button element
 * or trap clicks. The caller still owns the semantic element
 * (button, a, div role=button) and click handler.
 */
import { type ReactNode } from "react"
import { cn } from "@/lib/utils"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { DURATION, cssEase } from "@/lib/motion/timing"

export interface PressScaleProps {
  children: ReactNode
  className?: string
  /** Element tag. Default "span" so it stays inline; pass "button" or "div" as needed. */
  as?: React.ElementType
  /** Disable the press effect (matches disabled button state). */
  disabled?: boolean
}

export default function PressScale({
  children,
  className,
  as: Tag = "span",
  disabled = false,
}: PressScaleProps) {
  const reduced = useReducedMotion()
  const TagAny: React.ElementType = Tag

  const transition = reduced
    ? "none"
    : `transform ${DURATION.instant}ms ${cssEase("out")}, opacity ${DURATION.instant}ms ${cssEase("out")}`

  // Active-state class: scale on motion-enabled, opacity dip on reduced.
  const activeClass = disabled
    ? ""
    : reduced
      ? "active:opacity-70"
      : "active:scale-[0.97]"

  return (
    <TagAny
      className={cn("inline-block", activeClass, className)}
      style={{
        transition,
        willChange: disabled ? "auto" : "transform",
      }}
      data-motion="press-scale"
      data-motion-reduced={reduced ? "true" : "false"}
    >
      {children}
    </TagAny>
  )
}

export { PressScale }
