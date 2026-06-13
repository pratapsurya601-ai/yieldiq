/**
 * AmcAvatar — fund-house (AMC) logo chip for the /funds pages.
 *
 * The mutual-fund analogue of TickerAvatar. Resolves a favicon-based
 * logo for the AMC's domain (curated in `data/amc_domains.json` via
 * `getAmcDomain`) and falls back through DuckDuckGo to a deterministic
 * branded letter-mark when no logo is available.
 *
 * Fallback chain (the <img onError> handler advances at runtime):
 *
 *   (0) Google s2/favicons for the curated AMC domain. Always-on, free,
 *       returns a real PNG (~32-128px) — the fund house's own brand mark.
 *   (1) DuckDuckGo icon service for the same domain — independent
 *       crawler, saves the day when Google's favicon index is stale.
 *   (2) Letter-mark — AMC initials on a deterministic on-brand tint.
 *       Reached immediately for any AMC not in the curated domain map.
 *
 * No self-hosted PNG stage (unlike TickerAvatar): there are only ~50
 * fund houses and the favicon IS the brand mark, so a build-time fetch +
 * binary commit isn't worth it.
 */
"use client"

import { useState } from "react"

import { getAmcDomain, normalizeAmcName } from "@/lib/logoUrl"

export type AmcAvatarSize = "sm" | "md" | "lg"

export interface AmcAvatarProps {
  /** AMC banner string straight from the funds API (e.g. "HDFC Mutual Fund"). */
  amc: string
  /** sm (24) / md (32) / lg (44) px square. Defaults to "sm". */
  size?: AmcAvatarSize
  /** Optional className appended to the wrapper for layout tweaks. */
  className?: string
}

const SIZE_PX: Record<AmcAvatarSize, number> = { sm: 24, md: 32, lg: 44 }

const SIZE_CLASS: Record<AmcAvatarSize, string> = {
  sm: "h-6 w-6 text-[10px]",
  md: "h-8 w-8 text-xs",
  lg: "h-11 w-11 text-sm",
}

// Letter-mark tints. No sector taxonomy for AMCs, so we pick a stable
// colour per house by hashing its name — gives visual variety across a
// grid without implying meaning.
const MARK_BG = [
  "bg-indigo-600",
  "bg-cyan-700",
  "bg-emerald-700",
  "bg-violet-600",
  "bg-amber-600",
  "bg-rose-600",
  "bg-teal-700",
  "bg-slate-600",
]

function hashIndex(s: string, n: number): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) | 0
  }
  return Math.abs(h) % n
}

/** AMC initials: first letter of up to two significant words ("Aditya
 *  Birla Sun Life" → "AB"), or the first two characters of a single-word
 *  house ("HDFC" → "HD"). */
function initialsFor(amc: string): string {
  const norm = normalizeAmcName(amc)
  if (!norm) return "?"
  const words = norm.split(" ").filter(Boolean)
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase()
  }
  return norm.slice(0, 2).toUpperCase()
}

function urlForStage(domain: string | null, stage: number): string | null {
  if (!domain) return null
  switch (stage) {
    case 0:
      return `https://www.google.com/s2/favicons?domain=${domain}&sz=128`
    case 1:
      return `https://icons.duckduckgo.com/ip3/${domain}.ico`
    default:
      return null
  }
}

export default function AmcAvatar({ amc, size = "sm", className }: AmcAvatarProps) {
  const px = SIZE_PX[size]
  const dimClass = SIZE_CLASS[size]
  const domain = getAmcDomain(amc)

  const [stage, setStage] = useState(0)
  const src = urlForStage(domain, stage)

  const baseClasses = [
    "inline-flex shrink-0 items-center justify-center overflow-hidden rounded",
    "bg-raised border border-border",
    dimClass,
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ")

  // Letter-mark fallback — no domain, or every favicon stage errored.
  if (!src) {
    const bg = MARK_BG[hashIndex(normalizeAmcName(amc) || amc, MARK_BG.length)]
    return (
      <span
        className={`${baseClasses} ${bg} border-transparent text-white`}
        aria-label={`${amc} logo`}
        data-testid="amc-avatar-monogram"
      >
        <span className="font-semibold tracking-tight">{initialsFor(amc)}</span>
      </span>
    )
  }

  return (
    <span
      className={baseClasses}
      aria-label={`${amc} logo`}
      data-testid="amc-avatar-image"
    >
      {/* Plain <img>, not next/image: tiny inline chips where Next's
          optimizer would proxy every favicon through /_next/image for no
          benefit at 24-44px. */}
      <img
        src={src}
        alt=""
        width={px}
        height={px}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setStage((s) => s + 1)}
        className="h-full w-full object-contain"
      />
    </span>
  )
}
