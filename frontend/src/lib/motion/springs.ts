/**
 * motion/springs.ts — Framer-Motion spring preset constants.
 *
 * Springs are physics objects (stiffness, damping, mass) rather than
 * duration + easing. Four named presets cover ~95% of in-app uses;
 * a 5th preset lands here rather than getting inlined at a call site.
 *
 * Frozen at module-load so the same object identity is reused on
 * every render — Framer can shallow-compare and skip re-allocating
 * the underlying spring solver.
 */

export interface SpringConfig {
  readonly type: "spring"
  readonly stiffness: number
  readonly damping: number
  readonly mass: number
}

/**
 * `gentle` — default for layout shifts (sticky nav slide, drawer
 * expand). No overshoot, lands softly. Equivalent to ease-out
 * around ~400ms.
 */
export const SPRING_GENTLE: SpringConfig = Object.freeze({
  type: "spring" as const,
  stiffness: 170,
  damping: 26,
  mass: 1,
})

/**
 * `snappy` — quick acknowledgements: hover lift, press scale, chip
 * select. Higher stiffness + tighter damping means the motion is
 * over in ~180ms with no perceivable overshoot.
 */
export const SPRING_SNAPPY: SpringConfig = Object.freeze({
  type: "spring" as const,
  stiffness: 380,
  damping: 32,
  mass: 0.8,
})

/**
 * `bouncy` — set-piece moments only (achievement unlock, score
 * reveal). Light damping means a small overshoot before settling.
 * NEVER use on data-dense UI; the wobble reads as instability.
 */
export const SPRING_BOUNCY: SpringConfig = Object.freeze({
  type: "spring" as const,
  stiffness: 260,
  damping: 14,
  mass: 1,
})

/**
 * `smooth` — slow, deliberate transitions for number flips, big
 * card morphs. Higher mass slows the entire trajectory; no overshoot.
 */
export const SPRING_SMOOTH: SpringConfig = Object.freeze({
  type: "spring" as const,
  stiffness: 120,
  damping: 24,
  mass: 1.4,
})

/**
 * Map keyed by preset name. Convenient for components that take a
 * `spring="snappy"` prop and look up the config internally.
 */
export const SPRINGS = Object.freeze({
  gentle: SPRING_GENTLE,
  snappy: SPRING_SNAPPY,
  bouncy: SPRING_BOUNCY,
  smooth: SPRING_SMOOTH,
} as const)

export type SpringKey = keyof typeof SPRINGS
