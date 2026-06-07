import type { MetadataRoute } from "next"
import { BLOG_POSTS } from "@/lib/blog"
// Day-108c (2026-05-23) — sector landing-page slugs surfaced for SEO.
// Slug set MUST mirror backend/services/sector_pages.py SECTOR_PAGE_SLUGS.
import { SECTOR_PAGE_SLUGS } from "./(marketing)/sector/[slug]/sectorCohorts"
// 2026-06-04 — programmatic content experiment: 12 NIFTY-50 large-cap
// fair-value SEO pages at /fair-value/<TICKER>. Curated list, not
// derived from /all-tickers, so the sitemap entry stays scoped to the
// hand-authored content.
import { FAIR_VALUE_TICKERS } from "./(marketing)/fair-value/tickers"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // Static pages
  const staticPages: MetadataRoute.Sitemap = [
    { url: "https://yieldiq.in", lastModified: new Date(), priority: 1.0, changeFrequency: "daily" },
    { url: "https://yieldiq.in/features", priority: 0.7, changeFrequency: "weekly" },
    { url: "https://yieldiq.in/pricing", priority: 0.8, changeFrequency: "weekly" },
    { url: "https://yieldiq.in/stocks", priority: 0.9, changeFrequency: "daily" },
    { url: "https://yieldiq.in/nifty50", priority: 0.9, changeFrequency: "daily" },
    { url: "https://yieldiq.in/nifty-bank", priority: 0.8, changeFrequency: "daily" },
    { url: "https://yieldiq.in/nifty-it", priority: 0.8, changeFrequency: "daily" },
    { url: "https://yieldiq.in/earnings-calendar", priority: 0.8, changeFrequency: "daily" },
    { url: "https://yieldiq.in/news", priority: 0.7, changeFrequency: "hourly" },
    { url: "https://yieldiq.in/blog", priority: 0.9, changeFrequency: "weekly" },
    { url: "https://yieldiq.in/how-it-works", priority: 0.8, changeFrequency: "monthly" },
    { url: "https://yieldiq.in/methodology", priority: 0.6, changeFrequency: "monthly" },
    // Day-89: hypothetical YIQ-50 backtest marketing page.
    { url: "https://yieldiq.in/yiq50-backtest", priority: 0.7, changeFrequency: "weekly" },
    // Day-83: end-user help section. Each topic indexed as its own URL
    // so Google ranks them on the long-tail "how do I read X" queries.
    { url: "https://yieldiq.in/help", priority: 0.7, changeFrequency: "monthly" },
    { url: "https://yieldiq.in/help/reading-an-analysis", priority: 0.6, changeFrequency: "monthly" },
    { url: "https://yieldiq.in/help/fair-value-and-mos", priority: 0.6, changeFrequency: "monthly" },
    { url: "https://yieldiq.in/help/using-the-screener", priority: 0.6, changeFrequency: "monthly" },
    { url: "https://yieldiq.in/help/portfolio-prism", priority: 0.6, changeFrequency: "monthly" },
    { url: "https://yieldiq.in/help/confidence-and-limits", priority: 0.6, changeFrequency: "monthly" },
    { url: "https://yieldiq.in/help/sectors-and-cohorts", priority: 0.6, changeFrequency: "monthly" },
    { url: "https://yieldiq.in/help/pricing-and-tiers", priority: 0.6, changeFrequency: "monthly" },
    // J-copy-2b (audit item 17): static sector index page.
    { url: "https://yieldiq.in/sector", priority: 0.7, changeFrequency: "weekly" },
    // Sector rotation lens (2026-06-07): cross-sector valuation snapshot.
    { url: "https://yieldiq.in/sector-rotation", priority: 0.7, changeFrequency: "daily" },
    { url: "https://yieldiq.in/terms", priority: 0.3, changeFrequency: "monthly" },
    { url: "https://yieldiq.in/privacy", priority: 0.3, changeFrequency: "monthly" },
  ]

  // Dynamic stock pages from API
  let stockPages: MetadataRoute.Sitemap = []
  try {
    // Day-40 (2026-05-20): revalidate cut from 86400 (24h) -> 3600 (1h)
    // so newly-listed tickers surface in Google Search within an hour
    // of being added to the public/all-tickers endpoint. Previously
    // new IPOs took up to a day to enter the sitemap.
    const res = await fetch(`${API_BASE}/api/v1/public/all-tickers`, {
      next: { revalidate: 3600 },
    })
    if (res.ok) {
      const tickers: { ticker: string; last_updated: string | null }[] = await res.json()
      // URL-encode the ticker so symbols like "M&M" become "M%26M" — XML
      // sitemaps MUST contain only URL-safe characters; a bare "&" makes
      // Google Search Console emit "Parsing error" for the whole file.
      const fairValuePages: MetadataRoute.Sitemap = tickers.map(t => ({
        url: `https://yieldiq.in/stocks/${encodeURIComponent(t.ticker)}/fair-value`,
        lastModified: t.last_updated ? new Date(t.last_updated) : new Date(),
        changeFrequency: "daily" as const,
        priority: 0.7,
      }))
      // Day-40 (2026-05-20): /analysis/{ticker} added to sitemap. This is
      // the actual user-facing entry surface (the /stocks/.../fair-value
      // pages are SEO landing pages that link INTO /analysis). Previously
      // Google indexed only the SEO landing pages, missing the canonical
      // analysis URL entirely.
      const analysisPages: MetadataRoute.Sitemap = tickers.map(t => ({
        url: `https://yieldiq.in/analysis/${encodeURIComponent(t.ticker)}`,
        lastModified: t.last_updated ? new Date(t.last_updated) : new Date(),
        changeFrequency: "daily" as const,
        priority: 0.9,  // higher than /stocks since this is the canonical surface
      }))
      // Hex SEO pages — one per active ticker. Display ticker (no .NS suffix)
      // since the route accepts bare symbols. Kept alongside /prism so any
      // previously indexed bookmarks / external links still resolve (they now
      // 301 to /prism/* via next.config redirects, but we still list them for
      // sitemap completeness during the transition window).
      const hexPages: MetadataRoute.Sitemap = tickers.map(t => ({
        url: `https://yieldiq.in/hex/${encodeURIComponent(t.ticker.replace(/\.(NS|BO)$/i, ""))}`,
        lastModified: t.last_updated ? new Date(t.last_updated) : new Date(),
        changeFrequency: "daily" as const,
        priority: 0.7,
      }))
      // Prism SEO pages — the new canonical viral surface. One per ticker.
      const prismPages: MetadataRoute.Sitemap = tickers.map(t => ({
        url: `https://yieldiq.in/prism/${encodeURIComponent(t.ticker.replace(/\.(NS|BO)$/i, ""))}`,
        lastModified: t.last_updated ? new Date(t.last_updated) : new Date(),
        changeFrequency: "daily" as const,
        priority: 0.8,
      }))
      stockPages = [...fairValuePages, ...analysisPages, ...hexPages, ...prismPages]
    }
  } catch {
    // Sitemap generation should never fail — return static pages only
  }

  // Blog posts
  const blogPages: MetadataRoute.Sitemap = BLOG_POSTS.map(p => ({
    url: `https://yieldiq.in/blog/${p.slug}`,
    lastModified: new Date(p.date),
    changeFrequency: "monthly" as const,
    priority: 0.8,
  }))

  // Hand-picked head-to-head comparison pairs — high-intent SEO queries
  // for sector rivalries within Nifty 50 / Nifty Next 50.
  // Keep small and curated; do NOT explode O(n^2).
  const COMPARE_PAIRS: [string, string][] = [
    // Banks (private vs private, private vs PSU)
    ["HDFCBANK", "ICICIBANK"],
    ["HDFCBANK", "KOTAKBANK"],
    ["ICICIBANK", "AXISBANK"],
    ["SBIN", "HDFCBANK"],
    ["KOTAKBANK", "AXISBANK"],
    // IT services
    ["TCS", "INFY"],
    ["INFY", "WIPRO"],
    ["TCS", "HCLTECH"],
    ["WIPRO", "HCLTECH"],
    ["INFY", "TECHM"],
    // Energy / oil & gas
    ["RELIANCE", "ONGC"],
    ["BPCL", "IOC"],
    ["NTPC", "POWERGRID"],
    // Autos
    ["MARUTI", "M%26M"],
    ["BAJAJ-AUTO", "HEROMOTOCO"],
    ["TATAMOTORS", "M%26M"],
    // FMCG / consumer
    ["ITC", "HINDUNILVR"],
    ["ITC", "BRITANNIA"],
    ["NESTLEIND", "BRITANNIA"],
    ["DABUR", "MARICO"],
    // Paints
    ["ASIANPAINT", "BERGEPAINT"],
    // Pharma
    ["SUNPHARMA", "DRREDDY"],
    ["CIPLA", "DRREDDY"],
    ["DIVISLAB", "SUNPHARMA"],
    // Metals
    ["TATASTEEL", "JSWSTEEL"],
    ["HINDALCO", "VEDL"],
    // Cement
    ["ULTRACEMCO", "GRASIM"],
    // Telecom
    ["BHARTIARTL", "IDEA"],
  ]

  const comparePages: MetadataRoute.Sitemap = COMPARE_PAIRS.map(([a, b]) => ({
    url: `https://yieldiq.in/compare/${a}-vs-${b}`,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
    priority: 0.6,
  }))

  // Prism compare pages — same curated rivalries, new surface.
  const prismComparePages: MetadataRoute.Sitemap = COMPARE_PAIRS.map(([a, b]) => ({
    url: `https://yieldiq.in/prism/compare/${a}-vs-${b}`,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
    priority: 0.6,
  }))

  // Day-108c sector landing pages — one per cohort slug. Indexed
  // weekly because the aggregate medians shift slowly relative to
  // per-ticker pages.
  const sectorPages: MetadataRoute.Sitemap = SECTOR_PAGE_SLUGS.map(slug => ({
    url: `https://yieldiq.in/sector/${slug}`,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
    priority: 0.7,
  }))

  // Mutual fund pages (Phase 3-slim). One entry per active scheme.
  // Endpoint returns at most a few thousand active scheme variants
  // post-Phase-1 ingest; bounded enough for a single sitemap file.
  // Static "/funds" landing is always listed; detail URLs are listed
  // when the backend responds, fall through silently otherwise.
  const fundsLandingPage: MetadataRoute.Sitemap = [
    {
      url: "https://yieldiq.in/funds",
      lastModified: new Date(),
      changeFrequency: "daily" as const,
      priority: 0.7,
    },
  ]
  let fundDetailPages: MetadataRoute.Sitemap = []
  try {
    // Bounded LIMIT — sitemap.xml files >50k URLs split per Google's
    // spec, and we don't yet have detail coverage that would benefit
    // from indexing tens of thousands of schemes. Stay narrow until
    // the holdings + score work lands and the detail pages are
    // information-rich enough to rank.
    const res = await fetch(`${API_BASE}/api/v1/funds?limit=500`, {
      next: { revalidate: 3600 },
    })
    if (res.ok) {
      const body: { funds: { scheme_code: string }[] } = await res.json()
      fundDetailPages = body.funds.map((f) => ({
        url: `https://yieldiq.in/funds/${encodeURIComponent(f.scheme_code)}`,
        lastModified: new Date(),
        changeFrequency: "daily" as const,
        priority: 0.6,
      }))
    }
  } catch {
    // Sitemap must never throw — surface the landing-only fallback.
  }

  // Content-experiment fair-value SEO pages — one per curated ticker.
  // weekly cadence + 0.7 priority matches the brief and keeps these
  // pages from outranking the canonical /analysis/<TICKER> surface
  // (priority 0.9) on tied queries.
  const fairValueContentPages: MetadataRoute.Sitemap = FAIR_VALUE_TICKERS.map(
    (c) => ({
      url: `https://yieldiq.in/fair-value/${encodeURIComponent(c.ticker)}`,
      lastModified: new Date(),
      changeFrequency: "weekly" as const,
      priority: 0.7,
    }),
  )

  return [
    ...staticPages,
    ...blogPages,
    ...stockPages,
    ...comparePages,
    ...prismComparePages,
    ...sectorPages,
    ...fundsLandingPage,
    ...fundDetailPages,
    ...fairValueContentPages,
  ]
}
