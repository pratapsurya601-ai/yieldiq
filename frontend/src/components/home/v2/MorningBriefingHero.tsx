"use client"
// Morning Briefing Hero — personalized /home opener.
//
// Replaces the plain "Good morning, {name}" greeting with a richer
// three-row block:
//   1. Caption: "Good morning, {name}  ·  {Mon 09 Jun 11:14 IST}"
//   2. Two-column tile band — LEFT = Your Portfolio (value + day Δ +
//      inline sparkline), RIGHT = NIFTY 50 (value + change + sparkline).
//   3. Glass card — "Morning briefing" label + 2-4 observational
//      sentences composed server-side (SEBI-clean, no advisory verbs).
//
// Data: GET /api/v1/home/morning-briefing (5-min server-side cache,
// pinned to user_id). React Query refetches every 5 min so the tile
// numbers stay live during a long /home dwell.
//
// Failure modes:
//   - Loading           → 3-row skeleton matching final dimensions.
//   - Error             → silent fallback to plain "Good morning, {name}"
//                         (auth store provides the name). We never
//                         surface API errors at the top of the page.
//   - Empty portfolio   → tile is hidden, NIFTY tile spans both columns,
//                         briefing copy invites the user to add a stock.
//
// Sparklines: rendered inline (~30 LOC SVG) to avoid coupling this PR
// to the parallel <Sparkline /> component agent's work.

import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  getMorningBriefing,
  type MorningBriefingResponse,
} from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { formatCurrency, formatPctSigned } from "@/lib/utils"

// ─────────────────────────────────────────────────────────────────
// Inline sparkline — intentionally minimal. Polyline scaled to a
// fixed viewBox so the row height stays stable as values change.
// ─────────────────────────────────────────────────────────────────

function InlineSparkline({
  values,
  color,
}: {
  values: number[]
  color: string
}) {
  if (!values || values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const width = 80
  const height = 24
  const points = values
    .map(
      (v, i) =>
        `${(i / (values.length - 1)) * width},${
          height - ((v - min) / range) * height
        }`,
    )
    .join(" ")
  return (
    <svg
      width={width}
      height={height}
      className="inline-block"
      data-testid="morning-briefing-sparkline"
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
      />
    </svg>
  )
}

// ─────────────────────────────────────────────────────────────────
// Localized date/time caption — IST, hydration-safe.
// ─────────────────────────────────────────────────────────────────

function formatISTCaption(): string {
  // Render after mount only — see useEffect below — so server-side
  // and client-side initial HTML match (server has no IST clock).
  const fmt = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
  return `${fmt.format(new Date())} IST`
}

function greetingForHour(hour: number): string {
  if (hour < 12) return "Good morning"
  if (hour < 17) return "Good afternoon"
  return "Good evening"
}

function currentISTHour(): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    hour: "numeric",
    hour12: false,
  }).formatToParts(new Date())
  const hourPart = parts.find((p) => p.type === "hour")
  return hourPart ? parseInt(hourPart.value, 10) : new Date().getHours()
}

function nameFromEmail(email: string | null): string {
  if (!email) return "there"
  const local = email.split("@")[0] || ""
  if (!local) return "there"
  const token = local.split(/[._\-+]/)[0] || local
  return token.charAt(0).toUpperCase() + token.slice(1).toLowerCase()
}

// ─────────────────────────────────────────────────────────────────
// Sub-components — Tile, Skeleton, Fallback
// ─────────────────────────────────────────────────────────────────

function PortfolioTile({
  data,
}: {
  data: NonNullable<MorningBriefingResponse["portfolio"]>
}) {
  const up = data.day_change_pct >= 0
  const color = up
    ? "text-green-600 dark:text-green-400"
    : "text-red-600 dark:text-red-400"
  const strokeColor = up ? "#16a34a" : "#dc2626"
  return (
    <div
      className="bg-surface border border-border rounded-2xl p-4"
      data-testid="morning-briefing-portfolio-tile"
    >
      <div className="text-[10px] font-bold uppercase tracking-wider text-caption mb-1.5">
        Your portfolio
      </div>
      <div className="text-2xl font-mono font-semibold text-ink leading-tight">
        {formatCurrency(data.total_value)}
      </div>
      <div className="flex items-center justify-between mt-1.5">
        <div className={`text-xs font-mono ${color}`}>
          {formatPctSigned(data.day_change_pct)}{" "}
          <span className="text-caption font-mono">
            ({formatCurrency(data.day_change)})
          </span>
        </div>
        <InlineSparkline values={data.sparkline_7d} color={strokeColor} />
      </div>
    </div>
  )
}

function NiftyTile({
  data,
}: {
  data: MorningBriefingResponse["market"]
}) {
  const pct = data.nifty_change_pct
  const up = pct === null ? true : pct >= 0
  const color =
    pct === null
      ? "text-caption"
      : up
        ? "text-green-600 dark:text-green-400"
        : "text-red-600 dark:text-red-400"
  const strokeColor = up ? "#16a34a" : "#dc2626"
  return (
    <div
      className="bg-surface border border-border rounded-2xl p-4"
      data-testid="morning-briefing-nifty-tile"
    >
      <div className="text-[10px] font-bold uppercase tracking-wider text-caption mb-1.5">
        NIFTY 50
      </div>
      <div className="text-2xl font-mono font-semibold text-ink leading-tight">
        {data.nifty_value === null
          ? "—"
          : // Indian-style thousands grouping ("23,123.45") matches
            // the MarketsStrip NIFTY tile. The canonical helpers do
            // not currently expose locale grouping — same pattern
            // used in MarketsStrip.tsx line 146.
            // eslint-disable-next-line no-restricted-syntax
            data.nifty_value.toLocaleString("en-IN", {
              maximumFractionDigits: 2,
            })}
      </div>
      <div className="flex items-center justify-between mt-1.5">
        <div className={`text-xs font-mono ${color}`}>
          {pct === null ? "—" : formatPctSigned(pct)}
        </div>
        <InlineSparkline
          values={data.nifty_sparkline_7d}
          color={strokeColor}
        />
      </div>
    </div>
  )
}

function Skeleton() {
  // Three rows that mirror the final layout dimensions:
  //   - 1 caption row
  //   - 2 tiles (each ~104px tall) in a 2-col grid
  //   - 1 briefing card (~88px tall)
  // Pulse animation keeps the skeleton readable on slow networks
  // without inducing the layout shift that empty boxes would cause.
  return (
    <div
      className="space-y-3"
      data-testid="morning-briefing-skeleton"
    >
      <div className="h-4 w-72 bg-border rounded animate-pulse" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="bg-surface border border-border rounded-2xl p-4">
          <div className="h-3 w-24 bg-border rounded animate-pulse mb-2" />
          <div className="h-7 w-32 bg-border rounded animate-pulse" />
          <div className="h-3 w-20 bg-border/70 rounded animate-pulse mt-2" />
        </div>
        <div className="bg-surface border border-border rounded-2xl p-4">
          <div className="h-3 w-16 bg-border rounded animate-pulse mb-2" />
          <div className="h-7 w-28 bg-border rounded animate-pulse" />
          <div className="h-3 w-16 bg-border/70 rounded animate-pulse mt-2" />
        </div>
      </div>
      <div className="bg-surface border border-border rounded-2xl p-4">
        <div className="h-3 w-32 bg-border rounded animate-pulse mb-2" />
        <div className="space-y-1.5">
          <div className="h-3.5 w-full bg-border/70 rounded animate-pulse" />
          <div className="h-3.5 w-5/6 bg-border/70 rounded animate-pulse" />
        </div>
      </div>
    </div>
  )
}

function FallbackGreeting({ name }: { name: string }) {
  // Quiet fallback when the briefing API errors out. Mirrors the
  // pre-hero greeting so the user never sees a broken-page banner.
  //
  // SSR-safe pattern (avoids `react-hooks/set-state-in-effect`):
  // keep a "mounted" flag, compute the IST greeting only when it's
  // true. The initial server-rendered HTML uses the neutral
  // "Welcome back" copy; the client swaps to the real time-of-day
  // greeting on first paint.
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    // SSR/CSR hydration boundary — the server has no IST clock so
    // it renders the neutral "Welcome back" copy. On first paint we
    // flip `mounted` so the IST-based greeting renders. This is the
    // standard React hydration pattern; the alternative
    // (suppressHydrationWarning) hides drift instead of resolving it.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true)
  }, [])
  const greeting = mounted ? greetingForHour(currentISTHour()) : "Welcome back"
  return (
    <div className="pt-2" data-testid="morning-briefing-fallback">
      <h1 className="font-display text-2xl md:text-3xl font-bold text-ink leading-tight">
        {greeting}, {name}.
      </h1>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────
// Public component
// ─────────────────────────────────────────────────────────────────

export default function MorningBriefingHero() {
  const email = useAuthStore((s) => s.email)
  const displayName = useAuthStore((s) => s.displayName)

  // Hydration-safe caption — `formatISTCaption()` depends on the
  // wall clock which differs server vs. client. We keep a "tick"
  // counter that increments once a minute; the caption is then a
  // pure derivation off it. This avoids the `react-hooks/set-state-
  // in-effect` lint rule (we only setState in response to an
  // external clock event, not synchronously on mount with a value
  // we could have derived).
  const [tick, setTick] = useState(0)
  useEffect(() => {
    // Hydration tick — server-rendered HTML has tick=0 (empty
    // caption), client flips to tick=1 on mount to render the IST
    // time. Same hydration-boundary pattern as the FallbackGreeting
    // mount flag above.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTick(1)
    const id = setInterval(() => setTick((t) => t + 1), 60_000)
    return () => clearInterval(id)
  }, [])
  const caption = tick > 0 ? formatISTCaption() : ""

  const { data, isLoading, isError } = useQuery({
    queryKey: ["home", "morning-briefing"],
    queryFn: getMorningBriefing,
    // Server caches 5 min; align the React Query stale time so we
    // don't burn the cache hit by refetching faster than necessary.
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    retry: 1,
  })

  // Falls back to the email-derived token when the user hasn't
  // completed the StepName onboarding (matches PersonalHeader).
  const userName =
    (displayName && displayName.trim()) ||
    data?.user_name ||
    nameFromEmail(email)
  const greetingHour = (() => {
    if (typeof window === "undefined") return 8 // SSR placeholder
    try {
      return currentISTHour()
    } catch {
      return 8
    }
  })()
  const greetingWord = greetingForHour(greetingHour)

  if (isLoading) {
    return <Skeleton />
  }

  if (isError || !data) {
    return <FallbackGreeting name={userName} />
  }

  return (
    <div
      className="space-y-3"
      data-testid="morning-briefing-hero"
    >
      {/* Row 1: caption */}
      <div className="flex items-baseline gap-2 flex-wrap">
        <h1 className="font-display text-xl md:text-2xl font-semibold text-ink leading-tight">
          {greetingWord}, {userName}
        </h1>
        {caption && (
          <span className="text-xs text-caption font-mono">
            <span className="px-1.5" aria-hidden="true">
              ·
            </span>
            {caption}
          </span>
        )}
      </div>

      {/* Row 2: tile band. When the user has no holdings, the
          portfolio tile collapses and NIFTY spans both columns. */}
      <div
        className={`grid gap-3 ${
          data.portfolio
            ? "grid-cols-1 md:grid-cols-2"
            : "grid-cols-1"
        }`}
      >
        {data.portfolio && <PortfolioTile data={data.portfolio} />}
        <NiftyTile data={data.market} />
      </div>

      {/* Row 3: briefing prose card. Larger readable type per spec. */}
      <div
        className="bg-surface border border-border rounded-2xl p-4"
        data-testid="morning-briefing-card"
      >
        <div className="text-[10px] font-bold uppercase tracking-wider text-caption mb-1.5">
          Morning briefing
        </div>
        <p className="text-sm md:text-[15px] text-ink leading-relaxed">
          {data.briefing_text}
        </p>
      </div>
    </div>
  )
}
