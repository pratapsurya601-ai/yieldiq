"use client"

import Link from "next/link"
import { cn } from "@/lib/utils"

export default function AlertsEmpty() {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="h-16 w-16 rounded-full bg-blue-50 flex items-center justify-center mb-4">
        <svg className="h-8 w-8 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
        </svg>
      </div>

      <h2 className="text-lg font-semibold text-gray-900 mb-1">
        No alerts set
      </h2>
      <p className="text-sm text-gray-500 mb-6 max-w-xs">
        Get notified when a stock&apos;s margin of safety crosses your threshold.
      </p>

      <Link
        href="/watchlist"
        className={cn(
          "inline-flex items-center justify-center rounded-full px-6 py-2.5 min-h-[44px]",
          "bg-blue-600 text-white text-sm font-semibold",
          "hover:bg-blue-700 active:bg-blue-800 active:scale-[0.97] transition",
          "shadow-sm"
        )}
      >
        Create alert
      </Link>

      <Link
        href="/portfolio?tab=alerts&example=1"
        className="mt-3 text-xs text-blue-600 hover:text-blue-700 hover:underline font-medium"
      >
        See example alert
      </Link>
    </div>
  )
}
