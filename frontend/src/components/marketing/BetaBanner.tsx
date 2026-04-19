"use client"

import { useState, useEffect } from "react"

/**
 * Fixed bottom-left "Beta" chip.
 *
 * Default: HIDDEN. Per re-audit feedback ("erodes confidence when
 * visible during use") the pill no longer shows by default. Power
 * users / internal review can opt in by visiting any page with
 * `?beta=1` in the URL — that sets the localStorage flag to show
 * the pill on subsequent loads. The dismiss × clears the flag.
 *
 * Migration: previously-shown chip is silently hidden for everyone
 * on first load post this change. The legacy `yiq_beta_banner_v2_dismissed`
 * key is no longer consulted.
 */
const SHOW_KEY = "yiq_beta_pill_show"

export default function BetaBanner() {
  const [show, setShow] = useState(false)

  useEffect(() => {
    if (typeof window === "undefined") return
    // Opt-in via ?beta=1 URL param (sticky once set)
    const url = new URL(window.location.href)
    if (url.searchParams.get("beta") === "1") {
      localStorage.setItem(SHOW_KEY, "1")
    }
    setShow(localStorage.getItem(SHOW_KEY) === "1")
  }, [])

  const dismiss = () => {
    if (typeof window !== "undefined") {
      localStorage.removeItem(SHOW_KEY)
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
