"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/authStore"
import { TIER_LIMITS } from "@/lib/constants"

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
    <header className="hidden md:block sticky top-0 z-40 bg-white/95 backdrop-blur-md border-b border-gray-200">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-8">
        <Link href="/home" className="flex items-center gap-2 flex-shrink-0" aria-label="YieldIQ home">
          <span className="text-lg font-black tracking-tight">
            <span className="text-gray-900">Yield</span>
            <span className="text-blue-600">IQ</span>
          </span>
          {tier === "free" && (
            <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wider bg-gray-100 px-1.5 py-0.5 rounded">
              Free
            </span>
          )}
        </Link>

        <nav className="flex items-center gap-1 flex-1" aria-label="Main navigation">
          {LINKS.map((l) => {
            const active =
              l.href === "/home"
                ? pathname === "/home"
                : pathname.startsWith(l.href)
            return (
              <Link
                key={l.href}
                href={l.href}
                className={cn(
                  "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                  active
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-600 hover:text-gray-900 hover:bg-gray-50"
                )}
              >
                {l.label}
              </Link>
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
                  ? "bg-amber-50 text-amber-700 hover:bg-amber-100 ring-1 ring-amber-200"
                  : "bg-gray-50 text-gray-600 hover:bg-gray-100"
              )}
              aria-label="Analyses used today"
            >
              <span className="font-mono">{analysesToday}/{dailyLimit}</span>
              <span>today</span>
              {isNearLimit && <span className="text-[10px] font-bold">&uarr; Upgrade</span>}
            </Link>
          )}
          <Link
            href="/search"
            className="inline-flex items-center gap-2 bg-blue-600 text-white text-sm font-semibold px-4 py-1.5 rounded-lg hover:bg-blue-700 transition"
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
          <Link
            href="/account"
            aria-label="Account"
            className={cn(
              "h-8 w-8 rounded-full flex items-center justify-center transition",
              pathname.startsWith("/account")
                ? "bg-blue-50 text-blue-700 ring-2 ring-blue-100"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
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
        </div>
      </div>
    </header>
  )
}
