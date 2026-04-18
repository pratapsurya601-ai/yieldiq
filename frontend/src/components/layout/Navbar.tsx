"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/authStore"
import AnalysisCounter from "@/components/layout/AnalysisCounter"

interface NavTab {
  label: string
  href: string
  icon: (active: boolean) => React.ReactNode
  primary?: boolean
}

const TABS: NavTab[] = [
  {
    label: "Home",
    href: "/home",
    icon: (active) => (
      <svg className={cn("h-5 w-5", active ? "text-blue-600" : "text-gray-500")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12l8.954-8.955a1.126 1.126 0 011.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
      </svg>
    ),
  },
  {
    label: "Discover",
    href: "/discover",
    icon: (active) => (
      <svg className={cn("h-5 w-5", active ? "text-blue-600" : "text-gray-500")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5a17.92 17.92 0 01-8.716-2.247m0 0A8.966 8.966 0 013 12c0-1.777.514-3.434 1.401-4.83" />
      </svg>
    ),
  },
  {
    label: "Search",
    href: "/search",
    primary: true,
    icon: (active) => (
      <svg className={cn("h-5 w-5", active ? "text-white" : "text-white")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
      </svg>
    ),
  },
  {
    label: "Portfolio",
    href: "/portfolio",
    icon: (active) => (
      <svg className={cn("h-5 w-5", active ? "text-blue-600" : "text-gray-500")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 00.75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 00-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0112 15.75a23.978 23.978 0 01-7.577-1.22 2.016 2.016 0 01-.673-.38m0 0A2.18 2.18 0 013 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 013.413-.387m7.5 0V5.25A2.25 2.25 0 0013.5 3h-3a2.25 2.25 0 00-2.25 2.25v.894m7.5 0a48.667 48.667 0 00-7.5 0" />
      </svg>
    ),
  },
  {
    label: "Account",
    href: "/account",
    icon: (active) => (
      <svg className={cn("h-5 w-5", active ? "text-blue-600" : "text-gray-500")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75a17.933 17.933 0 01-7.499-1.632z" />
      </svg>
    ),
  },
]

export default function Navbar() {
  const pathname = usePathname()
  const tier = useAuthStore((s) => s.tier)

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-white/95 backdrop-blur-md border-t border-gray-200 pb-[env(safe-area-inset-bottom)]" aria-label="Main navigation">
      {tier === "free" && <AnalysisCounter />}
      {/* Thin separator between counter and nav items */}
      {tier === "free" && <div className="h-px bg-gray-100 mx-4" />}
      <div className="flex items-center justify-around px-2 h-14">
        {TABS.map((tab) => {
          const isActive = pathname.startsWith(tab.href)

          if (tab.primary) {
            return (
              <Link
                key={tab.href}
                href={tab.href}
                aria-label={tab.label}
                className={cn(
                  "flex flex-col items-center justify-center -mt-5",
                  "h-12 w-12 rounded-full bg-blue-600 shadow-md shadow-blue-300",
                  "active:scale-95 transition-transform"
                )}
              >
                {tab.icon(isActive)}
              </Link>
            )
          }

          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-label={tab.label}
              className={cn(
                "relative flex flex-col items-center justify-center gap-0.5 py-1 px-3 min-h-[44px] min-w-[44px]",
                "transition-colors active:scale-95"
              )}
            >
              {isActive && (
                <span className="absolute top-0 left-1/2 -translate-x-1/2 w-6 h-[2px] bg-blue-500 rounded-full" />
              )}
              {tab.icon(isActive)}
              <span
                className={cn(
                  "text-[10px] font-medium",
                  isActive ? "text-blue-600" : "text-gray-500"
                )}
              >
                {tab.label}
              </span>
            </Link>
          )
        })}
      </div>
    </nav>
  )
}
