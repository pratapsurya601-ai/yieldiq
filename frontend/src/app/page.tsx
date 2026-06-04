/**
 * Root route `/` — server shell for the landing page.
 *
 * PR-2 (2026-06-04, acquisition fixes): until this PR the landing page
 * was a single `"use client"` file (now `LandingClient.tsx`). That meant
 * no `metadata` export was possible from this route, so the public
 * homepage shipped without a canonical link and without any JSON-LD
 * structured data. Phase 0 audit confirmed `/` had:
 *   - canonical: null
 *   - JSON-LD count: 0
 *
 * Fix: thin server wrapper that
 *   1. exports `metadata` to set the canonical to https://yieldiq.in/
 *      (this lands as <link rel="canonical"> in the SSR HTML).
 *   2. SSR-renders <LandingJsonLd /> so the WebSite + Organization
 *      schemas ship in the initial HTML stream Googlebot indexes.
 *   3. delegates everything interactive (auth redirect, landing copy,
 *      DemoCard rotation) to the unchanged `LandingClient`.
 *
 * The root layout already provides a sensible default <title>,
 * description, openGraph, twitter, and icons — we only override
 * `alternates.canonical` here. The other metadata.fields inherit.
 */

import type { Metadata } from "next"
import LandingClient from "./LandingClient"
import LandingJsonLd from "./LandingJsonLd"

export const metadata: Metadata = {
  alternates: {
    canonical: "https://yieldiq.in/",
  },
}

export default function RootPage() {
  return (
    <>
      <LandingJsonLd />
      <LandingClient />
    </>
  )
}
