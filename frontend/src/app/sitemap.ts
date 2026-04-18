import type { MetadataRoute } from "next"
import { BLOG_POSTS } from "@/lib/blog"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // Static pages
  const staticPages: MetadataRoute.Sitemap = [
    { url: "https://yieldiq.in", lastModified: new Date(), priority: 1.0, changeFrequency: "daily" },
    { url: "https://yieldiq.in/features", priority: 0.7, changeFrequency: "weekly" },
    { url: "https://yieldiq.in/pricing", priority: 0.8, changeFrequency: "weekly" },
    { url: "https://yieldiq.in/nifty50", priority: 0.9, changeFrequency: "daily" },
    { url: "https://yieldiq.in/nifty-bank", priority: 0.8, changeFrequency: "daily" },
    { url: "https://yieldiq.in/nifty-it", priority: 0.8, changeFrequency: "daily" },
    { url: "https://yieldiq.in/earnings-calendar", priority: 0.8, changeFrequency: "daily" },
    { url: "https://yieldiq.in/news", priority: 0.7, changeFrequency: "hourly" },
    { url: "https://yieldiq.in/blog", priority: 0.9, changeFrequency: "weekly" },
    { url: "https://yieldiq.in/terms", priority: 0.3, changeFrequency: "monthly" },
    { url: "https://yieldiq.in/privacy", priority: 0.3, changeFrequency: "monthly" },
  ]

  // Dynamic stock pages from API
  let stockPages: MetadataRoute.Sitemap = []
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/all-tickers`, {
      next: { revalidate: 86400 },
    })
    if (res.ok) {
      const tickers: { ticker: string; last_updated: string | null }[] = await res.json()
      stockPages = tickers.map(t => ({
        url: `https://yieldiq.in/stocks/${t.ticker}/fair-value`,
        lastModified: t.last_updated ? new Date(t.last_updated) : new Date(),
        changeFrequency: "daily" as const,
        priority: 0.7,
      }))
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

  return [...staticPages, ...blogPages, ...stockPages, ...comparePages]
}
