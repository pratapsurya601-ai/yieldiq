// Animation primitives — see Design Manifesto rule 8.
// Every primitive: SSR-safe, viewport-triggered once, reduced-motion-aware.
export { CountUp, type CountUpProps } from "./CountUp"
export { ChartDrawIn, type ChartDrawInProps } from "./ChartDrawIn"
export {
  FadeStagger,
  type FadeStaggerProps,
  type FadeDirection,
} from "./FadeStagger"
export { RevealOnScroll, type RevealOnScrollProps } from "./RevealOnScroll"
export { useReducedMotion } from "./useReducedMotion"
export { useInViewOnce } from "./useInViewOnce"
