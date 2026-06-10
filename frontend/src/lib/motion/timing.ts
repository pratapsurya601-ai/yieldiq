/**
 * motion/timing.ts — single source of truth for durations + easings.
 *
 * Every component in the motion library reaches into this file rather
 * than defining its own ms values. That way the "premium feel" curve
 * tunes in one place, not 38.
 *
 * Numbers are intentionally on the small side — per the Design
 * Manifesto: animations are storytelling, not decoration. Anything
 * over ~700ms reads as sluggish on an analysis page where the user
 * is here to read.
 *
 * All values frozen at module-load so callers can't mutate them.
 */

export const DURATION = Object.freeze({
  /** Hover lift, press scale, tooltip in/out — must feel instant. */
  instant: 120,
  /** Tab fade, dropdown reveal, icon transitions. */
  fast: 200,
  /** Default reveal/fade — Reveal, FadeStagger child. */
  normal: 400,
  /** Hero / signature reveals, set-piece moments. */
  slow: 600,
  /** Number flips, long CountUp tweens. */
  deliberate: 1200,
} as const)

export type DurationKey = keyof typeof DURATION

/**
 * Framer-Motion easings. Strings map to Framer's named curves; arrays
 * are cubic-bezier control points. Names match the CSS curve they
 * approximate so the design team can reason about one curve, not two.
 *
 * `outExpo` is the "settle in" curve used across the analysis page:
 * heavy decel, soft landing. `outBack` overshoots slightly — only use
 * for set-piece moments (Prism signature, level-up celebration).
 */
export const EASING = Object.freeze({
  /** Linear — only for shimmer-style infinite loops. */
  linear: [0, 0, 1, 1] as [number, number, number, number],
  /** Smooth in-out — default for two-way transitions (open/close). */
  inOut: [0.4, 0, 0.2, 1] as [number, number, number, number],
  /** Material-style ease-out — gentle decel, no overshoot. */
  out: [0, 0, 0.2, 1] as [number, number, number, number],
  /** Premium "settle" — heavier decel than `out`, used by Reveal. */
  outExpo: [0.22, 1, 0.36, 1] as [number, number, number, number],
  /** Overshoot — set-piece only. Adds a tiny bounce on landing. */
  outBack: [0.34, 1.56, 0.64, 1] as [number, number, number, number],
} as const)

export type EasingKey = keyof typeof EASING

/**
 * CSS-string helpers for non-Framer call-sites (Tailwind transitions,
 * inline styles). Returns the bezier as `cubic-bezier(a,b,c,d)`.
 */
export function cssEase(key: EasingKey): string {
  const [a, b, c, d] = EASING[key]
  return `cubic-bezier(${a},${b},${c},${d})`
}

/** Convert a DURATION key to seconds (Framer expects seconds). */
export function durationS(key: DurationKey): number {
  return DURATION[key] / 1000
}
