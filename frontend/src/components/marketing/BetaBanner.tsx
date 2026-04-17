"use client"

import { useState, useEffect } from "react"

/**
 * Site-wide beta banner. Dismissible, state stored in localStorage.
 * Shown across all pages while data pipeline is being calibrated.
 */
export default function BetaBanner() {
  const [show, setShow] = useState(false)

  useEffect(() => {
    const dismissed = typeof window !== "undefined" && localStorage.getItem("yiq_beta_banner_v2_dismissed")
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
    <div className="bg-amber-50 border-b border-amber-200">
      <div className="max-w-6xl mx-auto px-4 py-2 flex items-center justify-between gap-3">
        <p className="text-xs text-amber-900 leading-snug">
          <span className="font-bold">Beta</span> &middot; Some valuation figures are being recalibrated.
          Fields with data quality issues are hidden automatically. Feedback welcome.
        </p>
        <button
          onClick={dismiss}
          className="text-amber-700 hover:text-amber-900 transition text-sm font-bold flex-shrink-0"
          aria-label="Dismiss"
        >
          &times;
        </button>
      </div>
    </div>
  )
}
