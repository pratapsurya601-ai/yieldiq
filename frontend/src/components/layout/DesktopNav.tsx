"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/authStore"
import { TIER_LIMITS } from "@/lib/constants"
import ThemeToggle from "@/components/layout/ThemeToggle"
import NotificationsBell from "@/components/notifications/NotificationsBell"
import PressScale from "@/components/motion/PressScale"

const LINKS = [
  { label: "Home", href: "/home" },
  { label: "Discover", href: "/discover" },
  { label: "Screener", href: "/discover/screener" },
  { label: "Portfolio", href: "/portfolio" },
  { label: "Compare", href: "/compare" },
]

export default function DesktopNav() {
  const pathname = usePathname()
  const tier = useAuthStore((s) => s.tier)
  const analysesToday = useAuthStore((s) => s.analysesToday)
  const rawLimit = TIER_LIMITS[tier]
  const dailyLimit = typeof rawLimit === "number" ? rawLimit : null
  const isNearLimit = tier === "free" && dailyLimit !== null && analysesToday >= dailyLimit - 1

  return (
    <header className="hidden md:block sticky top-0 z-40 bg-bg/95 dark:bg-bg/90 backdrop-blur-md border-b border-border">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-8">
        {/* Logo — `.hover-lift` adds a subtle 2px lift + shadow on hover.
            Reduced-motion users get a no-op (utility class self-disables). */}
        <Link
          href="/home"
          className="hover-lift flex items-center gap-2 flex-shrink-0 rounded-md px-1 -mx-1"
          aria-label="YieldIQ home"
        >
          <span className="text-lg font-black tracking-tight">
            <span className="text-ink">Yield</span>
            <span className="text-blue-600 dark:text-blue-400">IQ</span>
          </span>
          {tier === "free" && (
            <span className="text-[9px] font-bold text-caption uppercase tracking-wider bg-surface px-1.5 py-0.5 rounded">
              Free
            </span>
          )}
        </Link>

        {/* Nav links — `data-yq-nav-link` enables the CSS hover underline
            animation defined in globals.css. PressScale provides the
            tap-feedback gesture (scale on :active, opacity dip when
            reduced-motion is on). */}
        <nav className="flex items-center gap-1 flex-1" aria-label="Main navigation">
          {LINKS.map((l) => {
            const active =
              l.href === "/home"
                ? pathname === "/home"
                : pathname.startsWith(l.href)
            return (
              <PressScale key={l.href} className="rounded-lg">
                <Link
                  href={l.href}
                  data-yq-nav-link="true"
                  data-yq-nav-active={active ? "true" : "false"}
                  className={cn(
                    "relative px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                    active
                      ? "bg-tone-info-bg text-tone-info-fg"
                      : "text-body hover:text-ink hover:bg-surface"
                  )}
                >
                  {l.label}
                </Link>
              </PressScale>
            )
          })}
        </nav>

        <div className="flex items-center gap-3 flex-shrink-0">
          {tier === "free" && dailyLimit !== null && (
            <Link
              href="/pricing"
              className={cn(
                "hidden lg:inline-flex items-center gap-2 text-xs font-semibold px-3 py-1.5 rounded-lg transition",
                isNearLimit
                  ? "bg-tone-warn-bg text-tone-warn-fg hover:bg-amber-100 dark:hover:bg-amber-900/30 ring-1 ring-amber-200 dark:ring-amber-700/50"
                  : "bg-surface text-body hover:bg-tone-neutral-bg"
              )}
              aria-label="Analyses used today"
            >
              <span className="font-mono">{analysesToday}/{dailyLimit}</span>
              <span>today</span>
              {isNearLimit && <span className="text-[10px] font-bold">&uarr; Upgrade</span>}
            </Link>
          )}
          <PressScale className="rounded-lg">
            <Link
              href="/search"
              className="inline-flex items-center gap-2 bg-blue-600 dark:bg-blue-500 text-white text-sm font-semibold px-4 py-1.5 rounded-lg hover:bg-blue-700 dark:hover:bg-blue-400 transition"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
                />
              </svg>
              Search
            </Link>
          </PressScale>
          <NotificationsBell />
          <ThemeToggle />
          <PressScale className="rounded-full">
            <Link
              href="/account"
              aria-label="Account"
              className={cn(
                "h-8 w-8 rounded-full flex items-center justify-center transition",
                pathname.startsWith("/account")
                  ? "bg-tone-info-bg text-tone-info-fg ring-2 ring-blue-100 dark:ring-blue-900/40"
                  : "bg-surface text-body hover:bg-tone-neutral-bg"
              )}
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75a17.933 17.933 0 01-7.499-1.632z"
                />
              </svg>
            </Link>
          </PressScale>
        </div>
      </div>
    </header>
  )
}
