"use client"

import { useState, useEffect } from "react"

/**
 * Fixed bottom-left "Beta" chip. Replaces the previous full-width
 * banner that stole ~40px of vertical space on every page. The chip
 * is dismissible; state is persisted in localStorage. Keep the key
 * `yiq_beta_banner_v2_dismissed` so users who already dismissed the
 * old banner don't see the new chip either.
 */
export default function BetaBanner() {
  const [show, setShow] = useState(false)

  useEffect(() => {
    const dismissed =
      typeof window !== "undefined" &&
      localStorage.getItem("yiq_beta_banner_v2_dismissed")
    if (!dismissed) setShow(true)
  }, [])

  const dismiss = () => {
    if (typeof window !== "undefined") {
      localStorage.setItem("yiq_beta_banner_v2_dismissed", "1")
    }
    setShow(false)
  }

  if (!show) return null

  return (
    <div
      className="fixed bottom-3 left-3 z-40 flex items-center gap-1 rounded-full border border-border bg-surface/95 backdrop-blur px-2.5 py-1 shadow-sm"
      role="status"
      aria-label="Beta notice"
    >
      <span className="text-[10px] font-bold uppercase tracking-wider text-brand">
        Beta
      </span>
      <span className="text-caption text-[10px] hidden sm:inline">
        · calibrating
      </span>
      <button
        onClick={dismiss}
        className="ml-1 text-caption hover:text-ink transition text-xs leading-none"
        aria-label="Dismiss beta notice"
      >
        &times;
      </button>
    </div>
  )
}
