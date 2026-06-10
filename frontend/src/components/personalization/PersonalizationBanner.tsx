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
    // Layout note (2026-06-11, P1 fix bug B): the analysis page mounts
    // <StickyTableOfContents/> as a `xl:block fixed right-6 w-52`
    // overlay. With `flex-wrap` on this banner, a content column wider
    // than ~1040px wraps the Dismiss button onto a new line that visually
    // collides with the TOC rail ("Dismiss" reading next to "Deep Dive
    // Tabs"). `relative` anchors the banner row so neither child can
    // escape; `max-w-[72rem]` (≈ matches the centered content column
    // intent) plus `flex-nowrap sm:flex-wrap` keeps the Dismiss button
    // inline with the prose at narrow widths instead of column-stacking.
    // `shrink-0` on the button + `min-w-0` on the prose are belt-and-
    // suspenders against the prose growing past its share and pushing
    // the button out of the flex container.
    <div
      role="note"
      className="relative flex flex-nowrap items-center justify-between gap-2 text-xs bg-brand-50 border border-border rounded-lg px-3 py-2 mb-3 max-w-[72rem]"
    >
      <p className="text-ink min-w-0">
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
        className="shrink-0 text-caption hover:text-ink font-medium px-2 py-1 rounded transition"
        aria-label="Dismiss personalization banner"
      >
        Dismiss
      </button>
    </div>
  )
}
