/**
 * @yieldiq/motion — shared animation primitives library.
 *
 * Single source of truth for durations, easings, springs, variants,
 * and reduced-motion handling across the app. Components in
 * `@/components/motion` build on top of this layer; pages generally
 * reach for the components, not these raw constants.
 *
 * See `frontend/src/lib/motion/README.md` (when added) for the full
 * map. Until then this index plus the per-file JSDoc IS the docs.
 */

// Timing — duration scale + easing curves.
export {
  DURATION,
  EASING,
  cssEase,
  durationS,
  type DurationKey,
  type EasingKey,
} from "./timing"

// Springs — physics presets for Framer's spring transitions.
export {
  SPRING_GENTLE,
  SPRING_SNAPPY,
  SPRING_BOUNCY,
  SPRING_SMOOTH,
  SPRINGS,
  type SpringConfig,
  type SpringKey,
} from "./springs"

// Variants — Framer Motion variant presets + reduced-motion siblings.
export {
  FADE,
  SLIDE_UP,
  SLIDE_IN,
  SCALE_IN,
  PAGE_TRANSITION,
  STAGGER_CONTAINER,
  STAGGER_ITEM,
  FADE_REDUCED,
  SLIDE_UP_REDUCED,
  SLIDE_IN_REDUCED,
  SCALE_IN_REDUCED,
  PAGE_TRANSITION_REDUCED,
  STAGGER_CONTAINER_REDUCED,
  STAGGER_ITEM_REDUCED,
  VARIANTS,
  VARIANTS_REDUCED,
  pickVariants,
  type VariantKey,
} from "./variants"

// Reduced-motion hook + override accessors.
export {
  useReducedMotion,
  getMotionOverrideOff,
  setMotionOverrideOff,
  MOTION_STORAGE_KEY,
  MOTION_MEDIA_QUERY,
} from "./useReducedMotion"
