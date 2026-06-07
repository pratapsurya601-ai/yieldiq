/**
 * TickerAvatar — sitewide logo chip for any per-ticker row.
 *
 * Renders a consistent square chip at 16/24/32/48px, used by the home
 * widgets (Recent Analyses, Watchlist), search dropdowns, peer tables,
 * portfolio rows, sector cohorts, and the comparison tool. The analysis
 * hero and the marquee carousel each have bespoke logo treatments and
 * are out of scope for this component.
 *
 * Fallback chain (each layer can be skipped if the URL is unknown; the
 * <img onError> handler advances to the next layer at runtime):
 *
 *   (a) Clearbit hot-link for the canonical 261-entry domain map
 *       (`getCompanyDomain` in `lib/logoUrl.ts`, reading
 *       `data/ticker_domains.json`). Highest fidelity for the curated
 *       NSE universe. Free-tier rate-limit ~100 req/day per IP; if
 *       rate-limited, layer (b) takes over via onError.
 *   (b) Brandfetch CDN keyed by clean ticker — works for US tickers
 *       (e.g. GOOGL/MSFT) where the symbol IS the brand.
 *   (c) Google favicon service for the same domain (or `<cleanTicker>.com`
 *       guess when no curated entry exists). Always-on, bulletproof,
 *       lower fidelity (~32-128px).
 *   (d) Sector-colored letter mark — final fallback. 1 letter for
 *       <=4-char tickers, 2 letters for longer (e.g. "HD" for HDFCBANK).
 *
 * A module-level URL cache (`logoStageCache`) prevents chips from
 * re-resolving the same ticker on every render across the page.
 */
"use client"

import { useState } from "react"

import { getCompanyDomain } from "@/lib/logoUrl"

import {
  NSE_TICKER_SECTORS,
  cleanTicker,
  type TickerSector,
} from "./tickerDomains"

export type TickerAvatarSize = "xs" | "sm" | "md" | "lg"

export interface TickerAvatarProps {
  /** NSE / BSE ticker symbol (with or without .NS / .BO suffix). */
  ticker: string
  /** xs (16) / sm (24) / md (32) / lg (48) px square. Defaults to "sm". */
  size?: TickerAvatarSize
  /**
   * Optional sector hint. When provided, drives the letter-mark color.
   * If absent, the component looks the ticker up in NSE_TICKER_SECTORS.
   */
  sector?: TickerSector | string | null
  /** Optional className appended to the wrapper for layout tweaks. */
  className?: string
}

const SIZE_PX: Record<TickerAvatarSize, 16 | 24 | 32 | 48> = {
  xs: 16,
  sm: 24,
  md: 32,
  lg: 48,
}

// Tailwind class shards keyed by size so consumers don't have to
// reach into the component to pick a font size for the letter mark.
const SIZE_CLASS: Record<TickerAvatarSize, string> = {
  xs: "h-4 w-4 text-[8px]",
  sm: "h-6 w-6 text-[10px]",
  md: "h-8 w-8 text-xs",
  lg: "h-12 w-12 text-sm",
}

// Sector → Tailwind bg color for letter-mark fallback. Defensively
// resolved at render time so an unknown sector string falls through to
// the neutral default rather than erroring.
const SECTOR_BG: Record<TickerSector, string> = {
  banking: "bg-indigo-600",
  tech: "bg-cyan-600",
  fmcg: "bg-amber-600",
  auto: "bg-orange-600",
  pharma: "bg-emerald-600",
  energy: "bg-red-600",
  industrials: "bg-slate-600",
  telecom: "bg-violet-600",
  default: "bg-zinc-600",
}

// Module-level cache of the LAST successful URL we resolved for a given
// clean ticker. Lets us skip dead Clearbit hops on re-renders within the
// same page lifecycle. Keyed by clean ticker, value is the resolved
// chip-stage index so re-renders pick up at the right layer.
const logoStageCache = new Map<string, number>()

/** 1-letter mark for short tickers, 2-letter for longer (HDFCBANK → "HD"). */
function letterMarkFor(cleaned: string): string {
  if (!cleaned) return "?"
  return cleaned.length <= 4 ? cleaned.slice(0, 1) : cleaned.slice(0, 2)
}

/**
 * Resolve the URL for a given fallback stage. Returns null when that
 * stage has no usable URL, signalling the caller to skip to the next.
 *
 *   stage 0 → Clearbit (needs curated NSE_TICKER_DOMAINS entry)
 *   stage 1 → Brandfetch CDN (works on bare ticker — e.g. GOOGL)
 *   stage 2 → Google favicon (domain OR `<ticker>.com` guess)
 *   stage 3+ → null (letter-mark fallback)
 */
function urlForStage(cleaned: string, stage: number): string | null {
  // Single source of truth for the curated ticker → domain map: the
  // 261-entry `data/ticker_domains.json` (via `getCompanyDomain`).
  // `cleaned` is already suffix-stripped + uppercase, so this is a
  // direct hashmap hit.
  const domain = getCompanyDomain(cleaned)
  switch (stage) {
    case 0:
      return domain ? `https://logo.clearbit.com/${domain}` : null
    case 1:
      // Brandfetch CDN — keyed by the brand/ticker itself. We pass the
      // clean ticker which works for US listings whose symbol IS the
      // brand (GOOGL → google logo). For Indian tickers this layer is
      // usually a 404 and onError advances to layer (c).
      return `https://cdn.brandfetch.io/${cleaned}`
    case 2: {
      const guess = domain || `${cleaned.toLowerCase()}.com`
      return `https://www.google.com/s2/favicons?domain=${guess}&sz=64`
    }
    default:
      return null
  }
}

/** Walk forward from `start` until we find a stage that has a URL or run
 *  out of layers. Lets the initial render skip Clearbit immediately when
 *  the ticker isn't in the curated map. Returns 3 (letter-mark sentinel)
 *  when no further URL is available. */
function firstUsableStage(cleaned: string, start: number): number {
  for (let s = start; s <= 2; s++) {
    if (urlForStage(cleaned, s) !== null) return s
  }
  return 3
}

export default function TickerAvatar({
  ticker,
  size = "sm",
  sector,
  className,
}: TickerAvatarProps) {
  const px = SIZE_PX[size]
  const dimClass = SIZE_CLASS[size]
  const cleaned = cleanTicker(ticker)

  // Start at the cached stage if one exists; otherwise walk forward
  // from stage 0 to find the first layer that has a URL for this ticker
  // (skips the Clearbit hop instantly when the ticker isn't curated).
  const cachedStage = logoStageCache.get(cleaned)
  const initialStage =
    cachedStage !== undefined ? cachedStage : firstUsableStage(cleaned, 0)
  const [stage, setStage] = useState<number>(initialStage)
  const src = urlForStage(cleaned, stage)

  // React Compiler memoizes this for us; no manual useCallback needed.
  const handleError = () => {
    // Advance to the next fallback layer that actually has a URL; the
    // next render picks it up (or null, which routes to the letter mark).
    setStage((s) => {
      const next = firstUsableStage(cleaned, s + 1)
      logoStageCache.set(cleaned, next)
      return next
    })
  }

  const baseClasses = [
    "inline-flex shrink-0 items-center justify-center overflow-hidden rounded",
    "bg-raised border border-border",
    dimClass,
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ")

  // Letter-mark fallback path. Hit when stage 3+ OR no URL available.
  if (!src) {
    const resolvedSector: TickerSector =
      ((typeof sector === "string" ? sector : null) as TickerSector) ||
      NSE_TICKER_SECTORS[cleaned] ||
      "default"
    const bg = SECTOR_BG[resolvedSector] ?? SECTOR_BG.default
    return (
      <span
        className={`${baseClasses} ${bg} text-white border-transparent`}
        aria-label={`${ticker} logo`}
        data-testid="ticker-avatar-monogram"
      >
        <span className="font-semibold tabular-nums">
          {letterMarkFor(cleaned)}
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
      {/*
       * Plain <img> rather than next/image: these chips appear inline
       * in dense lists where Next's optimizer would compete with LCP
       * candidates higher on the page AND proxy every Brandfetch/
       * Clearbit URL through /_next/image — net zero perf benefit at
       * 16-48px while ballooning origin bandwidth.
       *
       * `loading="lazy"` keeps the chip off the critical path.
       */}
      <img
        src={src}
        alt=""
        width={px}
        height={px}
        loading="lazy"
        decoding="async"
        onError={handleError}
        className="h-full w-full object-contain"
      />
    </span>
  )
}
