/**
 * @yieldiq/components/motion — reusable motion components.
 *
 * Built on the primitives in `@/lib/motion`. Every component in this
 * package:
 *   - honours `useReducedMotion()` (OS pref + in-app toggle),
 *   - is SSR-safe (no hydration mismatch on first paint),
 *   - tunes timing via `@/lib/motion/timing` constants.
 *
 * Existing call-sites should migrate to these gradually. The legacy
 * primitives in `@/components/anim` and `@/components/common/Reveal`
 * continue to work — they're not deprecated by this PR.
 */
export { default as Reveal, type RevealProps, type RevealDirection } from "./Reveal"
export {
  default as RevealStagger,
  type RevealStaggerProps,
  type StaggerDirection,
} from "./RevealStagger"
export { default as HoverCard, type HoverCardProps } from "./HoverCard"
export { default as PressScale, type PressScaleProps } from "./PressScale"
export { default as NumberFlip, type NumberFlipProps } from "./NumberFlip"
export {
  default as ShimmerSkeleton,
  type ShimmerSkeletonProps,
} from "./ShimmerSkeleton"
export {
  default as RouteTransition,
  type RouteTransitionProps,
} from "./RouteTransition"
export { default as MarqueeRow, type MarqueeRowProps } from "./MarqueeRow"
export { default as ReduceMotionToggle } from "./ReduceMotionToggle"
