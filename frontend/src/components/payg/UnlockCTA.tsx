"use client"
// UnlockCTA — the ₹99 / 24h pay-as-you-go alternative to a subscription.
// Presented alongside the upgrade-to-Analyst CTA on the tier-gate surface
// (analysis 429 screen). Calling state, toast, and Razorpay modal are
// handled inside `startPaygCheckout`.
import { useState } from "react"
import { startPaygCheckout } from "@/lib/payg"
import { useAuthStore } from "@/store/authStore"

interface Props {
  ticker: string
  /** Analytics tag — tells GA which surface the click came from. */
  source?: string
  /** Called on successful unlock. Typical use: refresh the current page /
   *  invalidate queries so the user sees the full analysis. */
  onUnlocked?: () => void
  /** Called with a message when the flow errored in a way worth toasting.
   *  Dismiss / cancelled is silent — no callback fires for it. */
  onError?: (message: string) => void
  /** Optional compact variant — smaller padding, fits in-line under a
   *  headline CTA. */
  variant?: "card" | "inline"
}

export default function UnlockCTA({
  ticker,
  source = "unknown",
  onUnlocked,
  onError,
  variant = "card",
}: Props) {
  const email = useAuthStore((s) => s.email)
  const [busy, setBusy] = useState(false)

  const handleClick = async () => {
    if (busy) return
    setBusy(true)
    try {
      const result = await startPaygCheckout({ ticker, email, source })
      if (result.ok) {
        onUnlocked?.()
      } else if (result.reason && result.reason !== "cancelled" && result.message) {
        onError?.(result.message)
      }
    } finally {
      setBusy(false)
    }
  }

  if (variant === "inline") {
    return (
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="inline-flex items-center justify-center px-4 py-2 min-h-[40px] bg-bg dark:bg-surface text-brand border border-brand/40 rounded-lg text-sm font-semibold hover:bg-brand-50 active:scale-[0.98] transition disabled:opacity-60"
      >
        {busy ? "Opening checkout…" : `Unlock ${"\u20B9"}99 \u00B7 24h`}
      </button>
    )
  }

  const display = ticker.replace(".NS", "").replace(".BO", "")
  return (
    <div className="mx-auto max-w-sm bg-bg border border-border rounded-2xl p-4 text-left shadow-sm">
      <p className="text-xs font-bold text-caption uppercase tracking-wider mb-1">
        Don&rsquo;t want a subscription?
      </p>
      <p className="text-sm text-body mb-3">
        Unlock <span className="font-semibold text-ink">{display}</span> for{" "}
        <span className="font-semibold text-ink">{"\u20B9"}99</span> &mdash;
        24-hour access to the full analysis.
      </p>
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="w-full py-2.5 min-h-[44px] bg-brand text-white rounded-lg text-sm font-semibold hover:opacity-90 active:scale-[0.98] transition disabled:opacity-60"
      >
        {busy ? "Opening checkout…" : `Unlock ${display} \u00B7 ${"\u20B9"}99`}
      </button>
      <p className="text-[10px] text-caption text-center mt-2">
        One-time payment. Access expires in 24 hours.
      </p>
    </div>
  )
}
