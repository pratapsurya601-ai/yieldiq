"use client"
/**
 * <RouteTransition> — page-level fade for app router transitions.
 *
 * Wrap a page (or a layout's `{children}`) and the content fades in
 * over ~200ms when the route changes. The pathname is used as the
 * AnimatePresence key, so each navigation triggers a fresh entrance.
 *
 * Why a separate primitive? Next.js App Router doesn't ship route
 * transitions out of the box (intentionally — it favours streaming
 * over animation). For pages where the transition is desirable
 * (marketing, onboarding), this primitive opts in.
 *
 * Reduced-motion: AnimatePresence is bypassed entirely; the children
 * render directly without any wrapper. This keeps the DOM identical
 * to a no-transition app for users who've opted out.
 */
import { usePathname } from "next/navigation"
import { AnimatePresence, motion } from "framer-motion"
import { type ReactNode } from "react"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { PAGE_TRANSITION, PAGE_TRANSITION_REDUCED, pickVariants } from "@/lib/motion/variants"

export interface RouteTransitionProps {
  children: ReactNode
  className?: string
}

export default function RouteTransition({
  children,
  className,
}: RouteTransitionProps) {
  const pathname = usePathname() || "/"
  const reduced = useReducedMotion()

  // Reduced-motion path: render directly so we don't introduce a
  // motion wrapper into the DOM for users who've opted out.
  if (reduced) {
    return <div className={className} data-motion="route-transition-reduced">{children}</div>
  }

  const variants = pickVariants(PAGE_TRANSITION, PAGE_TRANSITION_REDUCED, false)

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={pathname}
        variants={variants}
        initial="hidden"
        animate="visible"
        exit="exit"
        className={className}
        data-motion="route-transition"
      >
        {children}
      </motion.div>
    </AnimatePresence>
  )
}

export { RouteTransition }
