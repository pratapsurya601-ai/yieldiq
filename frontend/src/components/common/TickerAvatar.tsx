/**
 * TickerAvatar — small-chip logo wrapper for per-ticker rows.
 *
 * Wraps the existing logo-resolution chain in `lib/logoUrl.ts` to
 * render a consistent square chip at 16/24/32px, suitable for
 * watchlist pills, market-news cards, and any compact ticker row.
 *
 * Fallback chain (driven entirely by `getLogoUrl`):
 *   1. Brandfetch CDN (if `NEXT_PUBLIC_BRANDFETCH_CLIENT_ID` set)
 *   2. Google favicon CDN
 *   3. Monogram: clean two-letter initials on `bg-raised`
 *
 * Non-goals:
 *   - Hover state / animation: out of scope here; consumers wrap in
 *     their own interactive container if needed.
 *   - Inline styles or new tokens: relies on existing `bg-raised`,
 *     `text-body`, `text-caption`, `border-border` utility classes.
 */
"use client"

import { useState } from "react"

import { getLogoUrl } from "@/lib/logoUrl"

export type TickerAvatarSize = "sm" | "md" | "lg"

export interface TickerAvatarProps {
  /** NSE / BSE ticker symbol (with or without .NS / .BO suffix). */
  ticker: string
  /** 16 / 24 / 32 px square. Defaults to "md" (24px). */
  size?: TickerAvatarSize
  /** Optional className appended to the wrapper for layout tweaks. */
  className?: string
}

const SIZE_PX: Record<TickerAvatarSize, 16 | 24 | 32> = {
  sm: 16,
  md: 24,
  lg: 32,
}

// Tailwind class shards keyed by size so consumers don't have to
// reach into the component to pick a font size for the monogram.
const SIZE_CLASS: Record<TickerAvatarSize, string> = {
  sm: "h-4 w-4 text-[8px]",
  md: "h-6 w-6 text-[10px]",
  lg: "h-8 w-8 text-xs",
}

/**
 * Derive a two-letter monogram from the ticker. Strips exchange
 * suffix first so HDFCBANK.NS → "HD" not ".N".
 */
function monogramFor(ticker: string): string {
  const cleaned = (ticker || "").toUpperCase().replace(/\.(NS|BO)$/i, "")
  if (!cleaned) return "?"
  return cleaned.slice(0, 2)
}

export default function TickerAvatar({
  ticker,
  size = "md",
  className,
}: TickerAvatarProps) {
  const px = SIZE_PX[size]
  const dimClass = SIZE_CLASS[size]
  const initialSrc = getLogoUrl(ticker, 64)

  // Track image-load failure so we can fall through to the monogram
  // when Brandfetch/favicon URLs 404 at runtime. `imgFailed=true` and
  // `initialSrc=null` both route to the monogram path.
  const [imgFailed, setImgFailed] = useState(false)
  const showMonogram = !initialSrc || imgFailed

  const baseClasses = [
    "inline-flex shrink-0 items-center justify-center overflow-hidden rounded",
    "bg-raised border border-border",
    dimClass,
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ")

  if (showMonogram) {
    return (
      <span
        className={baseClasses}
        aria-label={`${ticker} logo`}
        data-testid="ticker-avatar-monogram"
      >
        <span className="font-medium text-body tabular-nums">
          {monogramFor(ticker)}
        </span>
      </span>
    )
  }

  return (
    <span
      className={baseClasses}
      aria-label={`${ticker} logo`}
      data-testid="ticker-avatar-image"
    >
      {/* Plain <img> rather than next/image: these chips appear inline
          in lists/news cards where Next's optimizer is overkill and
          would compete with LCP candidates higher on the page. */}
      <img
        src={initialSrc as string}
        alt=""
        width={px}
        height={px}
        loading="lazy"
        decoding="async"
        onError={() => setImgFailed(true)}
        className="h-full w-full object-contain"
      />
    </span>
  )
}
