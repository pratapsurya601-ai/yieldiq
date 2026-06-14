import type { Metadata } from "next"

// SEO: `/screener` is an uncanonicalised duplicate of the nav-canonical
// surface `/discover/screener` (both are stock screeners over the same
// universe). Without a canonical tag Google sees two competing pages and
// splits ranking signal as duplicate content. `/screener` stays live and
// linked (it's referenced from several places), so we DON'T redirect —
// we point its canonical at `/discover/screener` so search engines
// consolidate on the one surface.
//
// This is a SERVER layout, so it can export `metadata` even though the
// child `page.tsx` is a `"use client"` component.
//
// NB: absolute URL to match the codebase convention (root layout sets no
// `metadataBase`; see app/page.tsx and app/legal/sla/page.tsx, which both
// use `https://yieldiq.in/...`). A bare relative path would emit an
// unresolved relative <link rel="canonical">.
export const metadata: Metadata = {
  title: "Screener — YieldIQ",
  alternates: {
    canonical: "https://yieldiq.in/discover/screener",
  },
}

export default function ScreenerLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
