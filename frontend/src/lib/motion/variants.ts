/**
 * motion/variants.ts — Framer-Motion variant presets.
 *
 * Variants are static descriptions of "hidden" + "visible" states;
 * Framer interpolates between them when the `animate` prop changes.
 * Exported as `Variants` objects (Framer's type) and frozen so the
 * same identity is reused render-to-render (Framer can skip the
 * variant-changed shallow compare).
 *
 * Reduced-motion fallback: each variant ships a sibling
 * `*_REDUCED` that snap-cuts (duration 0). Components are expected
 * to pick between the two based on `useReducedMotion()`. Why two
 * objects rather than a runtime branch inside the variant? Framer
 * memoizes variant identity; mutating a variant per-render would
 * defeat that memoization.
 *
 * Naming: each variant always exposes `hidden` and `visible` as the
 * two states (consistent with Framer convention). Stagger
 * containers add a third state `exit` that mirrors `hidden`.
 */
import type { Variants } from "framer-motion"
import { DURATION, EASING } from "./timing"

// ── Single-element entrance variants ─────────────────────────────────
//
// Each one is "hidden → visible" so callers do
//   <motion.div variants={FADE} initial="hidden" animate="visible" />.

/** Pure opacity 0 → 1. No translate. The mildest entrance. */
export const FADE: Variants = Object.freeze({
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      duration: DURATION.normal / 1000,
      ease: EASING.out,
    },
  },
})

/** Fade + 8px slide up. Default for content cards and Reveal. */
export const SLIDE_UP: Variants = Object.freeze({
  hidden: { opacity: 0, y: 8 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: DURATION.normal / 1000,
      ease: EASING.outExpo,
    },
  },
})

/** Fade + 8px slide in from the right. Used by drawers/sheets. */
export const SLIDE_IN: Variants = Object.freeze({
  hidden: { opacity: 0, x: 8 },
  visible: {
    opacity: 1,
    x: 0,
    transition: {
      duration: DURATION.normal / 1000,
      ease: EASING.outExpo,
    },
  },
})

/** Scale 0.96 → 1 with fade. Used for pop-in modals and tooltips. */
export const SCALE_IN: Variants = Object.freeze({
  hidden: { opacity: 0, scale: 0.96 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: {
      duration: DURATION.fast / 1000,
      ease: EASING.outExpo,
    },
  },
})

/**
 * Page-level fade for route transitions. Symmetric (same shape for
 * `exit` as `hidden`) so Next layout transitions don't appear lopsided.
 */
export const PAGE_TRANSITION: Variants = Object.freeze({
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      duration: DURATION.fast / 1000,
      ease: EASING.out,
    },
  },
  exit: {
    opacity: 0,
    transition: {
      duration: DURATION.instant / 1000,
      ease: EASING.out,
    },
  },
})

// ── Stagger container + item ─────────────────────────────────────────
//
// Pair these: wrap a list with STAGGER_CONTAINER and give each child
// STAGGER_ITEM. The container handles delayChildren/staggerChildren;
// the item just describes its own entrance.

/**
 * Wrapper for a list. `staggerChildren: 0.08s` ≈ 80ms between siblings,
 * which reads as "they're appearing in sequence" without feeling slow.
 * `delayChildren: 0.05` adds a tiny pause before the first child so the
 * stagger reads as intentional rather than a side-effect of mount lag.
 */
export const STAGGER_CONTAINER: Variants = Object.freeze({
  hidden: { opacity: 1 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.08,
      delayChildren: 0.05,
    },
  },
})

/** Default per-child entrance under a stagger container. */
export const STAGGER_ITEM: Variants = Object.freeze({
  hidden: { opacity: 0, y: 8 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: DURATION.normal / 1000,
      ease: EASING.outExpo,
    },
  },
})

// ── Reduced-motion siblings ──────────────────────────────────────────
//
// State still transitions hidden → visible (so AnimatePresence keeps
// working) but the transition takes 0s so the user perceives a snap
// cut. Critically we KEEP the layout final state — we don't render
// `hidden` permanently, because that would hide content.

function reducedFrom(v: Variants): Variants {
  // `visible` keeps its target props (so the element lands in the
  // right place) but the transition collapses to `duration: 0`.
  const out: Variants = {}
  for (const key of Object.keys(v) as Array<keyof Variants>) {
    const state = v[key]
    if (typeof state === "object" && state !== null) {
      out[key] = { ...state, transition: { duration: 0 } }
    } else {
      out[key] = state
    }
  }
  return Object.freeze(out)
}

export const FADE_REDUCED: Variants = reducedFrom(FADE)
export const SLIDE_UP_REDUCED: Variants = reducedFrom(SLIDE_UP)
export const SLIDE_IN_REDUCED: Variants = reducedFrom(SLIDE_IN)
export const SCALE_IN_REDUCED: Variants = reducedFrom(SCALE_IN)
export const PAGE_TRANSITION_REDUCED: Variants = reducedFrom(PAGE_TRANSITION)
export const STAGGER_CONTAINER_REDUCED: Variants = Object.freeze({
  hidden: { opacity: 1 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0, delayChildren: 0 },
  },
})
export const STAGGER_ITEM_REDUCED: Variants = reducedFrom(STAGGER_ITEM)

/**
 * Convenience picker. Components do:
 *   const v = pickVariants(SLIDE_UP, SLIDE_UP_REDUCED, reduced)
 * and pass `v` to `<motion.div variants={v} />`.
 */
export function pickVariants(
  full: Variants,
  reduced: Variants,
  reducedMotion: boolean,
): Variants {
  return reducedMotion ? reduced : full
}

/** Bundle of every named variant — useful in tests + storybook. */
export const VARIANTS = Object.freeze({
  fade: FADE,
  slideUp: SLIDE_UP,
  slideIn: SLIDE_IN,
  scaleIn: SCALE_IN,
  pageTransition: PAGE_TRANSITION,
  staggerContainer: STAGGER_CONTAINER,
  staggerItem: STAGGER_ITEM,
} as const)

export const VARIANTS_REDUCED = Object.freeze({
  fade: FADE_REDUCED,
  slideUp: SLIDE_UP_REDUCED,
  slideIn: SLIDE_IN_REDUCED,
  scaleIn: SCALE_IN_REDUCED,
  pageTransition: PAGE_TRANSITION_REDUCED,
  staggerContainer: STAGGER_CONTAINER_REDUCED,
  staggerItem: STAGGER_ITEM_REDUCED,
} as const)

export type VariantKey = keyof typeof VARIANTS
