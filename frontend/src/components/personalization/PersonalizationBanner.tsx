"use client"
//
// PersonalizationBanner — one-time confirmation strip rendered on the
// next analysis page load after a style is picked. Dismissable; the
// dismissal persists so it never reappears for the same user.

import * as React from "react"
import Link from "next/link"
import {
  type InvestingStyle,
  STYLE_META,
  isBannerDismissed,
  dismissBanner,
} from "@/lib/personalization"

interface Props {
  style: InvestingStyle | null
}

export default function PersonalizationBanner({ style }: Props) {
  const [hidden, setHidden] = React.useState(true)

  React.useEffect(() => {
    if (!style) {
      setHidden(true)
      return
    }
    setHidden(isBannerDismissed())
  }, [style])

  if (!style || hidden) return null

  const meta = STYLE_META[style]

  const onDismiss = () => {
    dismissBanner()
    setHidden(true)
  }

  return (
    <div
      role="note"
      className="flex flex-wrap items-center justify-between gap-2 text-xs bg-brand-50 border border-border rounded-lg px-3 py-2 mb-3"
    >
      <p className="text-ink">
        <span aria-hidden className="mr-1.5">
          {meta.emoji}
        </span>
        Personalised for <span className="font-semibold">{meta.label}</span>{" "}
        investing.{" "}
        <Link
          href="/account/preferences"
          className="text-brand font-medium hover:underline"
        >
          Change in Preferences
        </Link>
      </p>
      <button
        type="button"
        onClick={onDismiss}
        className="text-caption hover:text-ink font-medium px-2 py-1 rounded transition"
        aria-label="Dismiss personalization banner"
      >
        Dismiss
      </button>
    </div>
  )
}
