"use client"
/**
 * FundsSearchInput — client search box for the /funds hub.
 *
 * Live-filters as you type: each keystroke is debounced ~300ms and the
 * result `router.replace(/funds?q=…)`-es back into the funds hub so the
 * server component re-renders with the filtered list — no Enter needed.
 * Enter still works (the wrapping <form> submits to the same URL, and
 * onSubmit fires the navigation immediately, cancelling any pending
 * debounce). The active `category` filter is preserved across searches.
 *
 * `category` is passed down from the server page rather than read via
 * useSearchParams() — this keeps the component free of the Suspense
 * prerender bailout that useSearchParams() triggers (see root CLAUDE.md
 * "/search Suspense bailout").
 *
 * Adds a focus-state glow ring so the input feels responsive on first
 * keystroke. Reduced-motion: skips the glow transition; the input still
 * gets the focus-ring (that's an accessibility cue, not decoration).
 */
import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"

import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { DURATION, cssEase } from "@/lib/motion/timing"

const DEBOUNCE_MS = 300

export default function FundsSearchInput({
  defaultQuery = "",
  category = "",
}: {
  defaultQuery?: string
  category?: string
}) {
  const router = useRouter()
  const reduced = useReducedMotion()
  const [focused, setFocused] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // The query we last navigated to — guards against re-pushing the same
  // URL when focus/blur or re-renders fire with an unchanged value.
  const lastPushedRef = useRef(defaultQuery)

  const buildUrl = useCallback(
    (value: string) => {
      const params = new URLSearchParams()
      const trimmed = value.trim()
      if (trimmed) params.set("q", trimmed)
      if (category) params.set("category", category)
      const qs = params.toString()
      return qs ? `/funds?${qs}` : "/funds"
    },
    [category],
  )

  const navigate = useCallback(
    (value: string) => {
      const trimmed = value.trim()
      if (trimmed === lastPushedRef.current) return
      lastPushedRef.current = trimmed
      router.replace(buildUrl(trimmed), { scroll: false })
    },
    [buildUrl, router],
  )

  const onChange = useCallback(
    (value: string) => {
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => navigate(value), DEBOUNCE_MS)
    },
    [navigate],
  )

  // Clear any pending debounce on unmount.
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const onSubmit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      // Enter: cancel the pending debounce and navigate immediately,
      // client-side (no full-page GET).
      e.preventDefault()
      if (timerRef.current) clearTimeout(timerRef.current)
      const value =
        (e.currentTarget.elements.namedItem("q") as HTMLInputElement | null)
          ?.value ?? ""
      navigate(value)
    },
    [navigate],
  )

  const wrapperStyle: React.CSSProperties = reduced
    ? {}
    : {
        transition: `box-shadow ${DURATION.fast}ms ${cssEase("out")}`,
        boxShadow: focused
          ? "0 0 0 4px rgba(37, 99, 235, 0.12)"
          : "0 0 0 0 rgba(37, 99, 235, 0)",
      }

  return (
    <form action="/funds" method="GET" onSubmit={onSubmit} className="mb-4">
      <label htmlFor="fund-search" className="sr-only">
        Search funds
      </label>
      <div className="rounded-lg" style={wrapperStyle} data-motion="funds-search-glow">
        <input
          id="fund-search"
          name="q"
          type="search"
          defaultValue={defaultQuery}
          placeholder="Search by scheme name or AMC..."
          autoComplete="off"
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          className="w-full rounded-lg border border-border bg-raised px-4 py-2.5 text-sm text-ink placeholder:text-caption focus:border-caption focus:outline-none focus:ring-1 focus:ring-caption"
        />
      </div>
    </form>
  )
}
