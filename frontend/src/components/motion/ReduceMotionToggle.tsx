"use client"
/**
 * <ReduceMotionToggle> — switch widget for the in-app
 * "Reduce motion" override.
 *
 * Reads the current override state via `getMotionOverrideOff()` on
 * mount (so we never call localStorage during SSR / hydration). On
 * click flips the bit via `setMotionOverrideOff`, which:
 *   1. Writes the localStorage key (`yq:motion-off`),
 *   2. Sets the [data-yq-motion-off] attribute on <html> so CSS
 *      utilities flip in lockstep,
 *   3. Broadcasts a synthetic storage event so every mounted
 *      `useReducedMotion()` subscriber re-reads its snapshot.
 *
 * The visual treatment matches the Learn Mode / Pro Mode toggles
 * in the same Settings card so the user sees a consistent control.
 */
import { useEffect, useState } from "react"
import {
  getMotionOverrideOff,
  setMotionOverrideOff,
} from "@/lib/motion/useReducedMotion"

export default function ReduceMotionToggle() {
  // Server snapshot is "off" (= motion-on); we read the real value
  // after mount to avoid a hydration mismatch.
  const [off, setOff] = useState(false)
  useEffect(() => {
    setOff(getMotionOverrideOff())
  }, [])

  const handleToggle = () => {
    const next = !off
    setOff(next)
    setMotionOverrideOff(next)
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={off}
      aria-label="Reduce motion"
      onClick={handleToggle}
      className={`w-10 h-6 rounded-full transition shrink-0 ${
        off ? "bg-blue-600" : "bg-gray-200 dark:bg-gray-700"
      }`}
      data-motion="reduce-motion-toggle"
    >
      <div
        className={`w-4 h-4 bg-bg dark:bg-surface rounded-full shadow transition-transform ${
          off ? "translate-x-5" : "translate-x-1"
        }`}
      />
    </button>
  )
}

export { ReduceMotionToggle }
