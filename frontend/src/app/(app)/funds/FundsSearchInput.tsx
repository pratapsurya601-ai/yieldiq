"use client"
/**
 * FundsSearchInput — client wrapper around the funds-landing search box.
 *
 * Adds a focus-state glow ring on the wrapper so the input feels
 * responsive on first keystroke. Behaviour-equivalent to the previous
 * inline <form action="/search">: same name, same method, same target.
 *
 * Reduced-motion: skips the glow transition; the input still gets the
 * focus-ring (that's an accessibility cue, not decoration).
 */
import { useState } from "react"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { DURATION, cssEase } from "@/lib/motion/timing"

export default function FundsSearchInput() {
  const reduced = useReducedMotion()
  const [focused, setFocused] = useState(false)

  const wrapperStyle: React.CSSProperties = reduced
    ? {}
    : {
        transition: `box-shadow ${DURATION.fast}ms ${cssEase("out")}`,
        boxShadow: focused
          ? "0 0 0 4px rgba(37, 99, 235, 0.12)"
          : "0 0 0 0 rgba(37, 99, 235, 0)",
      }

  return (
    <form action="/search" method="GET" className="mb-6">
      <label htmlFor="fund-search" className="sr-only">
        Search funds
      </label>
      <div
        className="rounded-lg"
        style={wrapperStyle}
        data-motion="funds-search-glow"
      >
        <input
          id="fund-search"
          name="q"
          type="search"
          placeholder="Search by scheme name or AMC..."
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900"
        />
      </div>
    </form>
  )
}
