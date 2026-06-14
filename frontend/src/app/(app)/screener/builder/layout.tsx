import type { Metadata } from "next"

// `/screener/builder` (Smart Screener) is NESTED under `/screener`, so it
// inherits the parent `screener/layout.tsx` metadata — including its
// `alternates.canonical` pointing at `/discover/screener`. That parent
// canonical is WRONG for this page: the builder is a distinct surface
// (the composite multi-criteria Smart Screener), not a duplicate of
// `/discover/screener`. Left inherited, Google would treat `/screener/builder`
// as a duplicate of `/discover/screener` and drop it from the index.
//
// This SERVER layout overrides the inherited canonical so the builder
// self-canonicalises. `builder/page.tsx` is a `"use client"` component and
// can't export `metadata`, which is why this lives in a server layout.
//
// Absolute URL to match the codebase convention (no `metadataBase` is set;
// see app/page.tsx and app/legal/sla/page.tsx).
export const metadata: Metadata = {
  title: "Smart Screener — YieldIQ",
  alternates: {
    canonical: "https://yieldiq.in/screener/builder",
  },
}

export default function ScreenerBuilderLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>{children}</>
}
