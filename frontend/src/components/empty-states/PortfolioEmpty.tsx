"use client"

import Link from "next/link"
import { cn } from "@/lib/utils"

export default function PortfolioEmpty() {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="h-16 w-16 rounded-full bg-blue-50 flex items-center justify-center mb-4">
        <svg className="h-8 w-8 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 00.75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 00-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0112 15.75a23.978 23.978 0 01-7.577-1.22 2.016 2.016 0 01-.673-.38m0 0A2.18 2.18 0 013 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 013.413-.387m7.5 0V5.25A2.25 2.25 0 0013.5 3h-3a2.25 2.25 0 00-2.25 2.25v.894m7.5 0a48.667 48.667 0 00-7.5 0" />
        </svg>
      </div>

      <h2 className="text-lg font-semibold text-gray-900 mb-1">
        Track your investments
      </h2>
      <p className="text-sm text-gray-500 mb-6 max-w-xs">
        Add stocks to your portfolio to monitor their health, track valuation changes, and get alerts.
      </p>

      <Link
        href="/search"
        className={cn(
          "inline-flex items-center rounded-full px-6 py-2.5",
          "bg-blue-600 text-white text-sm font-medium",
          "hover:bg-blue-700 active:bg-blue-800 transition-colors",
          "shadow-sm"
        )}
      >
        Analyse a stock first
      </Link>
    </div>
  )
}
