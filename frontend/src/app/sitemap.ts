import type { MetadataRoute } from "next"

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

  return [...staticPages, ...stockPages]
}
