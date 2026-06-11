"use client"
//
// DemoPreviewChip — dismissible pill linking /analysis/[ticker] to the
// redesign preview at /demo/analysis-redesign. Renders nothing until
// mounted (avoids SSR/hydration mismatch on window access). Dismiss
// persists in localStorage under a versioned key so a future design
// iteration can use a different key to resurface the chip.

import * as React from "react"
import Link from "next/link"

const STORAGE_KEY = "yiq_demo_preview_chip_dismissed_v1"

export default function DemoPreviewChip() {
  // `mounted` guards window access for SSR — render nothing until after
  // hydration so the server-rendered HTML always matches the first paint.
  const [mounted, setMounted] = React.useState(false)
  const [dismissed, setDismissed] = React.useState(false)

  React.useEffect(() => {
    try {
      setDismissed(window.localStorage.getItem(STORAGE_KEY) === "1")
    } catch {
      // localStorage unavailable (Safari private mode, quota) — show chip.
    }
    setMounted(true)
  }, [])

  const onDismiss = () => {
    try {
      window.localStorage.setItem(STORAGE_KEY, "1")
    } catch {
      // Ignore — dismiss is best-effort.
    }
    setDismissed(true)
  }

  if (!mounted || dismissed) return null

  return (
    <div
      role="note"
      className="relative flex flex-nowrap items-center justify-between gap-2 text-xs bg-brand-50 border border-border rounded-lg px-3 py-2 max-w-[72rem]"
    >
      {/* "New" accent dot */}
      <span
        aria-hidden
        className="shrink-0 w-2 h-2 rounded-full bg-brand"
      />
      <p className="min-w-0 text-ink flex-1">
        <Link
          href="/demo/analysis-redesign"
          className="text-brand font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded"
        >
          Preview our new analysis page →
        </Link>
      </p>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 text-caption hover:text-ink font-medium px-2 py-1 rounded transition"
        aria-label="Dismiss preview chip"
      >
        ×
      </button>
    </div>
  )
}
