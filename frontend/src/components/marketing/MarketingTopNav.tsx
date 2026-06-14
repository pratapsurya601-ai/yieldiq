"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { useAuthStore } from "@/store/authStore"
import { TIER_LIMITS } from "@/lib/constants"
import { cn } from "@/lib/utils"
import PressScale from "@/components/motion/PressScale"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { SLIDE_IN, SLIDE_IN_REDUCED, pickVariants } from "@/lib/motion/variants"

/**
 * Unified top navigation — used by every page surface (marketing root,
 * (marketing) layout, (stocks) layout, (app) layout on desktop).
 *
 * Same nav items are reachable everywhere. Auth state ONLY toggles the
 * right-side actions:
 *   - anon  → "Sign in" + "Start Free →"
 *   - auth  → usage badge ("0/5 today" for free tier) + avatar dropdown
 *            (Account, Portfolio, Compare, Sign out)
 *
 * Replaces three previous variants (Marketing/App/Stock) flagged in the
 * 2026-04-30 nav-consistency audit.
 */

type Variant = "light" | "dark"

const ANON_NAV_ITEMS: { label: string; href: string }[] = [
  { label: "Discover", href: "/discover" },
  { label: "Screener", href: "/discover/screener" },
  { label: "Earnings", href: "/earnings-calendar" },
  { label: "Blog", href: "/blog" },
  { label: "Methodology", href: "/methodology" },
  { label: "Pricing", href: "/pricing" },
]

// Authenticated users see their workspace destinations as the primary
// nav (Search / Watchlist / Portfolio are what they came back for) with
// Discover + Screener kept for cross-browsing. Marketing-only surfaces
// (Blog / Methodology / Pricing) remain reachable via the footer and the
// account dropdown's "Account" link, not as primary nav noise.
const AUTH_NAV_ITEMS: { label: string; href: string }[] = [
  { label: "Home", href: "/home" },
  { label: "Search", href: "/search" },
  { label: "Watchlist", href: "/watchlist" },
  { label: "Portfolio", href: "/portfolio" },
  { label: "Funds", href: "/funds" },
  { label: "Discover", href: "/discover" },
  { label: "Screener", href: "/discover/screener" },
]

interface Props {
  /** "dark" matches the gradient/marketing landing pages; "light" is the default workspace look. */
  variant?: Variant
}

export default function MarketingTopNav({ variant = "light" }: Props) {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const menuVariants = pickVariants(SLIDE_IN, SLIDE_IN_REDUCED, reduced)

  const token = useAuthStore((s) => s.token)
  const tier = useAuthStore((s) => s.tier)
  const analysesToday = useAuthStore((s) => s.analysesToday)
  const logout = useAuthStore((s) => s.logout)

  const rawLimit = TIER_LIMITS[tier]
  const dailyLimit = typeof rawLimit === "number" ? rawLimit : null

  // Swap the primary nav items based on auth state so logged-in users
  // see their workspace (Search/Watchlist/Portfolio) instead of the
  // marketing surfaces (Blog/Methodology/Pricing).
  const navItems = token ? AUTH_NAV_ITEMS : ANON_NAV_ITEMS

  useEffect(() => {
    setOpen(false)
    setMenuOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [menuOpen])

  const isDark = variant === "dark"

  const wrapperCls = isDark
    ? "sticky top-0 z-50 border-b border-white/5 bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B]"
    : "sticky top-0 z-50 bg-bg/95 backdrop-blur-md border-b border-border"

  const linkBase = isDark
    ? "text-gray-400 hover:text-white transition"
    : "text-body hover:text-ink transition"
  const linkActive = isDark ? "text-white font-semibold" : "text-tone-info-fg font-semibold"

  const ctaLink = isDark
    ? "bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-semibold px-4 py-2 rounded-lg hover:opacity-90 transition shadow-lg shadow-blue-500/20"
    : "bg-blue-600 dark:bg-blue-500 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-blue-700 dark:hover:bg-blue-400 transition"

  const signinLink = isDark
    ? "text-gray-400 hover:text-white text-sm transition"
    : "text-body hover:text-ink text-sm transition"

  return (
    <nav className={wrapperCls} aria-label="Primary navigation">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between gap-4">
        {/* Logo — `.hover-lift` gives the icon a subtle 2px lift on hover,
            announcing "this is interactive" without committing to a full
            scale. */}
        <Link
          href={token ? "/home" : "/"}
          className="hover-lift flex items-center gap-2 flex-shrink-0 rounded-lg px-1 -mx-1"
        >
          <img src="/logo-new.svg" alt="YieldIQ" className="w-7 h-7 rounded-lg" />
          <span className={cn("font-bold", isDark ? "text-white" : "text-ink")}>
            YieldIQ
          </span>
        </Link>

        {/* Desktop nav items — `data-yq-nav-link` enables the hover
            underline animation from globals.css. */}
        <div className="hidden md:flex items-center gap-6 text-sm">
          {navItems.map((item) => {
            const active = pathname === item.href || pathname.startsWith(item.href + "/")
            return (
              <Link
                key={item.href}
                href={item.href}
                data-yq-nav-link="true"
                data-yq-nav-active={active ? "true" : "false"}
                className={cn("relative", active ? linkActive : linkBase)}
              >
                {item.label}
              </Link>
            )
          })}
        </div>

        {/* Right-side actions — auth-aware. `min-h-8` reserves the
            32px height of the logged-in account button (h-8) from first
            paint: `token` is falsy on the first client render (auth
            resolves in an effect), so this cluster would otherwise grow
            ~24px → 32px when the account menu mounts, making the header
            taller and nudging the whole page down ~4px. A Chrome trace
            on /home pinned that nudge as the dominant CLS source
            (CLS 0.29). Reserving the height keeps the row stable. */}
        <div className="hidden md:flex items-center gap-3 flex-shrink-0 min-h-8">
          {token ? (
            <>
              {tier === "free" && dailyLimit !== null && (
                <Link
                  href="/pricing"
                  className={cn(
                    "inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg transition",
                    isDark
                      ? "bg-white/10 text-gray-200 hover:bg-white/15"
                      : "bg-surface text-body hover:bg-tone-neutral-bg"
                  )}
                  aria-label="Analyses used today"
                >
                  <span className="font-mono">{analysesToday}/{dailyLimit}</span>
                  <span>today</span>
                </Link>
              )}
              <div ref={menuRef} className="relative">
                <PressScale className="rounded-full" as="div">
                  <button
                    type="button"
                    onClick={() => setMenuOpen((v) => !v)}
                    aria-haspopup="menu"
                    aria-expanded={menuOpen}
                    aria-label="Account menu"
                    className={cn(
                      "h-8 w-8 rounded-full flex items-center justify-center transition",
                      isDark
                        ? "bg-white/10 text-white hover:bg-white/15"
                        : "bg-surface text-body hover:bg-tone-neutral-bg"
                    )}
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75a17.933 17.933 0 01-7.499-1.632z" />
                    </svg>
                  </button>
                </PressScale>
                {/* Account dropdown — SLIDE_IN variant animates the fade +
                    8px x-slide on open; AnimatePresence handles the exit
                    once `menuOpen` flips false. */}
                <AnimatePresence>
                  {menuOpen && (
                    <motion.div
                      key="account-menu"
                      role="menu"
                      variants={menuVariants}
                      initial="hidden"
                      animate="visible"
                      exit="hidden"
                      className="absolute right-0 mt-2 w-44 rounded-lg border border-border bg-bg dark:bg-surface shadow-lg overflow-hidden text-sm"
                    >
                      <Link href="/account" role="menuitem" className="block px-3 py-2 text-ink hover:bg-surface">Account</Link>
                      <Link href="/portfolio" role="menuitem" className="block px-3 py-2 text-ink hover:bg-surface">Portfolio</Link>
                      <Link href="/compare" role="menuitem" className="block px-3 py-2 text-ink hover:bg-surface">Compare</Link>
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => { logout(); setMenuOpen(false) }}
                        className="block w-full text-left px-3 py-2 text-ink hover:bg-surface border-t border-border"
                      >
                        Sign out
                      </button>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </>
          ) : (
            <>
              <Link href="/auth/login" className={signinLink}>Sign in</Link>
              <PressScale className="rounded-lg">
                <Link href="/auth/signup" className={ctaLink}>
                  Start Free &rarr;
                </Link>
              </PressScale>
            </>
          )}
        </div>

        {/* Mobile hamburger */}
        <button
          onClick={() => setOpen(!open)}
          className={cn(
            "md:hidden p-2 rounded-lg active:scale-95 transition-transform",
            isDark ? "text-white" : "text-ink"
          )}
          aria-label="Menu"
          aria-expanded={open}
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={open ? "M6 18L18 6M6 6l12 12" : "M4 6h16M4 12h16M4 18h16"} />
          </svg>
        </button>
      </div>

      {/* Mobile menu — same items as desktop */}
      {open && (
        <div className={cn(
          "md:hidden border-t px-4 py-3 space-y-1",
          isDark ? "border-white/5 bg-[#0F172A]" : "border-border bg-bg dark:bg-surface"
        )}>
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "block text-sm py-2",
                isDark ? "text-gray-300" : "text-body"
              )}
            >
              {item.label}
            </Link>
          ))}
          <div className={cn("pt-2 mt-2 border-t", isDark ? "border-white/5" : "border-border")}>
            {token ? (
              <>
                {tier === "free" && dailyLimit !== null && (
                  <div className={cn("text-xs mb-2", isDark ? "text-gray-400" : "text-caption")}>
                    <span className="font-mono">{analysesToday}/{dailyLimit}</span> analyses today
                  </div>
                )}
                <Link href="/account" className={cn("block text-sm py-2", isDark ? "text-gray-300" : "text-body")}>Account</Link>
                <Link href="/portfolio" className={cn("block text-sm py-2", isDark ? "text-gray-300" : "text-body")}>Portfolio</Link>
                <Link href="/compare" className={cn("block text-sm py-2", isDark ? "text-gray-300" : "text-body")}>Compare</Link>
                <button
                  type="button"
                  onClick={() => logout()}
                  className={cn("block text-sm py-2 w-full text-left", isDark ? "text-gray-300" : "text-body")}
                >
                  Sign out
                </button>
              </>
            ) : (
              <>
                <Link href="/auth/login" className={cn("block text-sm py-2", isDark ? "text-gray-300" : "text-body")}>Sign in</Link>
                <Link href="/auth/signup" className={cn("block text-center text-sm font-semibold px-4 py-2 rounded-lg mt-2", isDark
                  ? "bg-gradient-to-r from-blue-600 to-cyan-500 text-white"
                  : "bg-blue-600 dark:bg-blue-500 text-white")}>
                  Start Free &rarr;
                </Link>
              </>
            )}
          </div>
        </div>
      )}
    </nav>
  )
}
