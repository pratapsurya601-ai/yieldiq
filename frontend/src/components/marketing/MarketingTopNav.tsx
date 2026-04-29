"use client"

import Link from "next/link"
import { useState } from "react"
import { useAuthStore } from "@/store/authStore"

/**
 * Shared top navigation for marketing/blog/SEO pages.
 *
 * Logo → /landing (always lands on the marketing page, never auto-redirects)
 * Logged-in users see "Open App" instead of "Start Free"
 * Cross-links to other public pages so users can browse all SEO content
 */
export default function MarketingTopNav() {
  const [open, setOpen] = useState(false)
  const token = useAuthStore(s => s.token)

  return (
    <nav className="sticky top-0 z-50 bg-white/95 backdrop-blur-md border-b border-gray-100">
      <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
        <Link href="/landing" className="flex items-center gap-2 flex-shrink-0">
          <img src="/logo-new.svg" alt="YieldIQ" className="w-7 h-7 rounded-lg" />
          <span className="font-bold text-gray-900">YieldIQ</span>
        </Link>

        <div className="hidden md:flex items-center gap-6 text-sm">
          <Link href="/blog" className="text-gray-600 hover:text-gray-900 transition">Blog</Link>
          <Link href="/how-it-works" className="text-gray-600 hover:text-gray-900 transition">How it works</Link>
          <Link href="/nifty50" className="text-gray-600 hover:text-gray-900 transition">Nifty 50</Link>
          <Link href="/screens/high-roce" className="text-gray-600 hover:text-gray-900 transition">Screens</Link>
          <Link href="/earnings-calendar" className="text-gray-600 hover:text-gray-900 transition">Earnings</Link>
          <Link href="/news" className="text-gray-600 hover:text-gray-900 transition">News</Link>
          <Link href="/pricing" className="text-gray-600 hover:text-gray-900 transition">Pricing</Link>
          {token ? (
            <Link
              href="/home"
              className="bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-blue-700 transition"
            >
              Open App &rarr;
            </Link>
          ) : (
            <Link
              href="/auth/signup"
              className="bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-blue-700 transition"
            >
              Start Free &rarr;
            </Link>
          )}
        </div>

        {/* Mobile hamburger */}
        <button
          onClick={() => setOpen(!open)}
          className="md:hidden text-gray-700 p-2"
          aria-label="Menu"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={open ? "M6 18L18 6M6 6l12 12" : "M4 6h16M4 12h16M4 18h16"} />
          </svg>
        </button>
      </div>

      {/* Mobile menu */}
      {open && (
        <div className="md:hidden border-t border-gray-100 px-4 py-3 space-y-2 bg-white">
          <Link href="/blog" className="block text-sm py-2 text-gray-700">Blog</Link>
          <Link href="/how-it-works" className="block text-sm py-2 text-gray-700">How it works</Link>
          <Link href="/nifty50" className="block text-sm py-2 text-gray-700">Nifty 50</Link>
          <Link href="/nifty-bank" className="block text-sm py-2 text-gray-700">Nifty Bank</Link>
          <Link href="/nifty-it" className="block text-sm py-2 text-gray-700">Nifty IT</Link>
          <Link href="/screens/high-roce" className="block text-sm py-2 text-gray-700">High ROCE</Link>
          <Link href="/screens/wide-moat" className="block text-sm py-2 text-gray-700">Wide Moat</Link>
          <Link href="/earnings-calendar" className="block text-sm py-2 text-gray-700">Earnings Calendar</Link>
          <Link href="/news" className="block text-sm py-2 text-gray-700">News &amp; Filings</Link>
          <Link href="/pricing" className="block text-sm py-2 text-gray-700">Pricing</Link>
          {token ? (
            <Link href="/home" className="block bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-lg text-center mt-2">
              Open App &rarr;
            </Link>
          ) : (
            <Link href="/auth/signup" className="block bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-lg text-center mt-2">
              Start Free &rarr;
            </Link>
          )}
        </div>
      )}
    </nav>
  )
}
