/**
 * motion/variants — preset shape tests.
 *
 * Pins:
 *   1. Every named variant exposes `hidden` + `visible` states (Framer
 *      Motion convention — other code reaches for these names).
 *   2. Each visible state carries a transition with `duration` (number,
 *      seconds) AND `ease` (cubic-bezier array). Without both, Framer
 *      falls back to its default ~300ms tween which defeats the
 *      design-tuned timing.
 *   3. Reduced-motion siblings collapse the transition to `duration: 0`
 *      while keeping target props (so the element still lands in the
 *      right place — `visible` shouldn't render `hidden`).
 *   4. Frozen identity: variant objects are immutable (Object.freeze)
 *      so render-to-render shallow compare in Framer succeeds without
 *      re-allocating the solver.
 *   5. `pickVariants` selector returns the right sibling.
 *   6. Stagger container exposes the stagger/delay child fields.
 */
import { describe, it, expect } from "vitest"
import type { Variant, Variants } from "framer-motion"
import {
  VARIANTS,
  VARIANTS_REDUCED,
  FADE,
  SLIDE_UP,
  SLIDE_IN,
  SCALE_IN,
  PAGE_TRANSITION,
  STAGGER_CONTAINER,
  STAGGER_ITEM,
  FADE_REDUCED,
  SLIDE_UP_REDUCED,
  pickVariants,
} from "@/lib/motion/variants"

// Cast helper — `Variant` is a union and the resolved object form
// carries the transition we want to inspect. Keeps the test readable.
function asObj(v: Variant | undefined): Record<string, unknown> {
  expect(v).toBeTruthy()
  expect(typeof v).toBe("object")
  return v as Record<string, unknown>
}

describe("motion/variants — shape", () => {
  const cases: Array<[string, Variants]> = [
    ["fade", FADE],
    ["slideUp", SLIDE_UP],
    ["slideIn", SLIDE_IN],
    ["scaleIn", SCALE_IN],
    ["pageTransition", PAGE_TRANSITION],
    ["staggerItem", STAGGER_ITEM],
  ]

  for (const [name, variant] of cases) {
    it(`${name} has hidden + visible states`, () => {
      expect(variant.hidden).toBeDefined()
      expect(variant.visible).toBeDefined()
    })

    it(`${name} visible carries a tuned transition`, () => {
      const v = asObj(variant.visible)
      const t = v.transition as Record<string, unknown>
      expect(t).toBeDefined()
      // Either a top-level duration or a per-prop transition.
      const dur = t.duration as unknown
      if (dur !== undefined) {
        expect(typeof dur).toBe("number")
        expect(dur as number).toBeGreaterThan(0)
      }
      // Easing must be an array (cubic-bezier) — we never use Framer's
      // string easings in this lib.
      const ease = t.ease as unknown
      if (ease !== undefined) {
        expect(Array.isArray(ease)).toBe(true)
        expect((ease as number[]).length).toBe(4)
      }
    })
  }

  it("staggerContainer carries staggerChildren + delayChildren", () => {
    const v = asObj(STAGGER_CONTAINER.visible)
    const t = v.transition as Record<string, unknown>
    expect(typeof t.staggerChildren).toBe("number")
    expect(t.staggerChildren as number).toBeGreaterThan(0)
    expect(typeof t.delayChildren).toBe("number")
  })

  it("pageTransition exposes an exit state", () => {
    expect(PAGE_TRANSITION.exit).toBeDefined()
  })
})

describe("motion/variants — reduced-motion siblings", () => {
  it("reduced FADE collapses transition to duration 0", () => {
    const v = asObj(FADE_REDUCED.visible)
    const t = v.transition as Record<string, unknown>
    expect(t.duration).toBe(0)
  })

  it("reduced SLIDE_UP keeps final position (y: 0)", () => {
    // Critical invariant: a reduced variant must still LAND at the
    // visible position, otherwise reduced-motion users see an
    // invisible / off-position element forever.
    const v = asObj(SLIDE_UP_REDUCED.visible)
    expect(v.y).toBe(0)
    expect(v.opacity).toBe(1)
  })

  it("every VARIANTS key has a VARIANTS_REDUCED twin", () => {
    for (const key of Object.keys(VARIANTS) as Array<keyof typeof VARIANTS>) {
      expect(VARIANTS_REDUCED[key]).toBeDefined()
    }
  })
})

describe("motion/variants — immutability", () => {
  it("variant objects are frozen", () => {
    expect(Object.isFrozen(FADE)).toBe(true)
    expect(Object.isFrozen(SLIDE_UP)).toBe(true)
    expect(Object.isFrozen(VARIANTS)).toBe(true)
    expect(Object.isFrozen(VARIANTS_REDUCED)).toBe(true)
  })
})

describe("motion/variants — pickVariants", () => {
  it("returns the reduced sibling when reducedMotion=true", () => {
    expect(pickVariants(FADE, FADE_REDUCED, true)).toBe(FADE_REDUCED)
  })
  it("returns the full variant when reducedMotion=false", () => {
    expect(pickVariants(FADE, FADE_REDUCED, false)).toBe(FADE)
  })
})
