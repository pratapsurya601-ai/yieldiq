"use client"

import Link from "next/link"
import { cn } from "@/lib/utils"

export default function WatchlistEmpty() {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="h-16 w-16 rounded-full bg-blue-50 flex items-center justify-center mb-4">
        <svg className="h-8 w-8 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.562.562 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.562.562 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
        </svg>
      </div>

      <h2 className="text-lg font-semibold text-gray-900 mb-1">
        Add stocks you are watching
      </h2>
      <p className="text-sm text-gray-500 mb-6 max-w-xs">
        Tap the star icon on any analysis to add it to your watchlist and track valuation changes over time.
      </p>

      <Link
        href="/search"
        className={cn(
          "inline-flex items-center justify-center rounded-full px-6 py-2.5 min-h-[44px]",
          "bg-gray-100 text-gray-700 text-sm font-semibold",
          "hover:bg-gray-200 active:bg-gray-300 active:scale-[0.97] transition"
        )}
      >
        Search for stocks
      </Link>
    </div>
  )
}
