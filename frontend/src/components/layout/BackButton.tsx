"use client"

/**
 * BackButton — small "← Back" affordance for deep-nested pages.
 *
 * Why: deep pages like /stocks/X/dupont, /portfolio/import, /report/X
 * leave the user stranded if their browser doesn't show a visible
 * back button (PWA standalone mode hides it entirely).
 *
 * Behaviour:
 *   - On the user's first visit (no history), clicking falls back
 *     to the configured `fallbackHref` instead of doing nothing.
 *   - Hidden on the top-level routes listed in HIDE_ON because
 *     those have no logical "back".
 */
import { useRouter, usePathname } from "next/navigation"
import { useEffect, useState } from "react"

interface Props {
  fallbackHref?: string
  label?: string
}

const HIDE_ON = new Set<string>([
  "/",
  "/home",
  "/discover",
  "/portfolio",
  "/screener",
  "/compare",
  "/landing",
  "/login",
  "/signup",
  "/onboarding",
])

export default function BackButton({
  fallbackHref = "/home",
  label = "Back",
}: Props) {
  const router = useRouter()
  const pathname = usePathname()
  const [canGoBack, setCanGoBack] = useState(false)

  useEffect(() => {
    // window.history.length is at least 1 for the current entry; >1 means
    // there's at least one prior in the stack we can pop to.
    if (typeof window !== "undefined") {
      setCanGoBack(window.history.length > 1)
    }
  }, [pathname])

  if (HIDE_ON.has(pathname || "")) return null

  const onClick = () => {
    if (canGoBack) {
      router.back()
    } else {
      router.push(fallbackHref)
    }
  }

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900 transition-colors px-2 py-1 -ml-2 rounded-lg hover:bg-gray-100"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-4 w-4"
        aria-hidden="true"
      >
        <path d="M19 12H5" />
        <path d="m12 19-7-7 7-7" />
      </svg>
      <span className="font-medium">{label}</span>
    </button>
  )
}
