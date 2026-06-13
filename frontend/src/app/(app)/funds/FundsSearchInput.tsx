"use client"
/**
 * FundsSearchInput — client wrapper around the funds-landing search box.
 *
 * GET-submits to /funds (the funds hub itself), so the server component
 * re-renders with the filtered scheme list. Adds a focus-state glow ring
 * so the input feels responsive on first keystroke.
 *
 * Reduced-motion: skips the glow transition; the input still gets the
 * focus-ring (that's an accessibility cue, not decoration).
 */
import { useState } from "react"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { DURATION, cssEase } from "@/lib/motion/timing"

export default function FundsSearchInput({ defaultQuery = "" }: { defaultQuery?: string }) {
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
    <form action="/funds" method="GET" className="mb-6">
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
          defaultValue={defaultQuery}
          placeholder="Search by scheme name or AMC..."
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          className="w-full rounded-lg border border-border bg-raised px-4 py-2.5 text-sm text-ink placeholder:text-caption focus:border-caption focus:outline-none focus:ring-1 focus:ring-caption"
        />
      </div>
    </form>
  )
}
