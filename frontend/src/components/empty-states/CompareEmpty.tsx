"use client"

import Link from "next/link"
import { cn } from "@/lib/utils"

// Day-37 (2026-05-20): dark variants added — see
// docs/design/week2-ux-audit-2026-05-20.md
export default function CompareEmpty() {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="h-16 w-16 rounded-full bg-blue-50 dark:bg-blue-950/40 flex items-center justify-center mb-4">
        <svg className="h-8 w-8 text-blue-500 dark:text-blue-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 6l3-3 3 3M6 3v13.5M21 18l-3 3-3-3M18 20.5V7" />
        </svg>
      </div>

      <h2 className="text-lg font-semibold text-ink mb-1">
        Compare any two stocks
      </h2>
      <p className="text-sm text-caption mb-6 max-w-xs">
        Pick two companies to see side-by-side DCF, moat, and MoS.
      </p>

      <Link
        href="/nifty50"
        className={cn(
          "inline-flex items-center justify-center rounded-full px-6 py-2.5 min-h-[44px]",
          "bg-blue-600 text-white text-sm font-semibold",
          "hover:bg-blue-700 active:bg-blue-800 active:scale-[0.97] transition",
          "shadow-sm"
        )}
      >
        Browse Nifty 50
      </Link>

      <Link
        href="/compare/HDFCBANK-vs-ICICIBANK"
        className="mt-3 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 hover:underline font-medium"
      >
        Try HDFCBANK vs ICICIBANK
      </Link>
    </div>
  )
}
