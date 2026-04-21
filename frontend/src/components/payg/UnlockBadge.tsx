"use client"
// UnlockBadge — "Unlocked Xh left" chip rendered next to a ticker symbol
// on rails / watchlist / analysis pages when the user has an active PAYG
// unlock for it.
//
// The underlying store is updated on app mount (hydrate on first render)
// and after every successful verify. Hours remaining is derived from
// `unlocked_at + 24h` so the chip counts down correctly across a session
// without any extra backend polling.
import { useEffect, useState } from "react"
import { usePaygStore } from "@/store/paygStore"

interface Props {
  ticker: string
  /** Compact = short pill for dense lists. Default = verbose chip. */
  size?: "sm" | "default"
  className?: string
}

export default function UnlockBadge({ ticker, size = "default", className }: Props) {
  const isUnlocked = usePaygStore((s) => s.isUnlocked(ticker))
  const hours = usePaygStore((s) => s.hoursRemaining(ticker))

  // Re-render on an interval so the "Xh left" label stays fresh without
  // the user reloading. 10-min tick is plenty — we only show integer
  // hours. Also avoids spamming React with re-renders every second.
  const [, force] = useState(0)
  useEffect(() => {
    if (!isUnlocked) return
    const id = setInterval(() => force((x) => x + 1), 10 * 60 * 1000)
    return () => clearInterval(id)
  }, [isUnlocked])

  if (!isUnlocked || hours <= 0) return null

  if (size === "sm") {
    return (
      <span
        className={`inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded-full bg-brand-50 text-brand ${className ?? ""}`}
        title={`Unlocked \u00B7 ${hours}h remaining`}
      >
        <span aria-hidden>{"\uD83D\uDD13"}</span>
        {hours}h
      </span>
    )
  }

  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full bg-brand-50 text-brand ${className ?? ""}`}
      title={`PAYG unlock \u00B7 ${hours}h remaining`}
    >
      <span aria-hidden>{"\uD83D\uDD13"}</span>
      {`Unlocked \u00B7 ${hours}h left`}
    </span>
  )
}
