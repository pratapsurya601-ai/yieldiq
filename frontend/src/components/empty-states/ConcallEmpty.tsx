"use client"

import Link from "next/link"
import { cn } from "@/lib/utils"

// Day-37 (2026-05-20): dark variants added — see
// docs/design/week2-ux-audit-2026-05-20.md
export default function ConcallEmpty() {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="h-16 w-16 rounded-full bg-tone-info-bg dark:bg-blue-950/40 flex items-center justify-center mb-4">
        <svg className="h-8 w-8 text-blue-500 dark:text-blue-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" />
        </svg>
      </div>

      <h2 className="text-lg font-semibold text-ink mb-1">
        No concall transcripts yet
      </h2>
      <p className="text-sm text-caption mb-6 max-w-xs">
        We&apos;re indexing earnings calls. Browse analyses while we populate.
      </p>

      <Link
        href="/discover"
        className={cn(
          "inline-flex items-center justify-center rounded-full px-6 py-2.5 min-h-[44px]",
          "bg-blue-600 text-white text-sm font-semibold",
          "hover:bg-blue-700 active:bg-blue-800 active:scale-[0.97] transition",
          "shadow-sm"
        )}
      >
        Go to Discover
      </Link>

      <a
        href="mailto:hello@yieldiq.in"
        className="mt-3 text-xs text-blue-600 dark:text-blue-400 hover:text-tone-info-fg dark:hover:text-blue-300 hover:underline font-medium"
      >
        Request a stock
      </a>
    </div>
  )
}
