import type { Metadata } from "next"
import { notFound } from "next/navigation"
import type { HexResponse } from "@/lib/hex"
import CompareClient from "./CompareClient"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function parseSlug(slug: string): { t1: string; t2: string } | null {
  if (!slug) return null
  const m = slug.match(/^(.+?)-vs-(.+)$/i)
  if (!m) return null
  const raw1 = m[1].trim().toUpperCase()
  const raw2 = m[2].trim().toUpperCase()
  if (!raw1 || !raw2) return null
  const withSuffix = (t: string) =>
    t.endsWith(".NS") || t.endsWith(".BO") ? t : `${t}.NS`
  return { t1: withSuffix(raw1), t2: withSuffix(raw2) }
}

function display(t: string): string {
  return t.replace(/\.(NS|BO)$/i, "")
}

async function getHex(ticker: string): Promise<HexResponse | null> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/hex/${encodeURIComponent(ticker)}`,
      { next: { revalidate: 3600 } }
    )
    if (!res.ok) return null
    return (await res.json()) as HexResponse
  } catch {
    return null
  }
}

export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> }
): Promise<Metadata> {
  const { slug } = await params
  const parsed = parseSlug(slug)
  if (!parsed) return { title: "Compare Hex | YieldIQ" }
  const t1 = display(parsed.t1)
  const t2 = display(parsed.t2)
  const title = `${t1} vs ${t2} \u2014 Hex Comparison | YieldIQ`
  const description = `Overlay the 6-axis hex of ${t1} and ${t2}: value, quality, growth, moat, safety, pulse. Model estimate.`
  const canonical = `https://yieldiq.in/hex/compare/${t1}-vs-${t2}`
  // Reuse the single-ticker OG for the first ticker — still branded.
  const ogUrl = `https://yieldiq.in/api/og/hex/${t1}`
  return {
    title,
    description,
    alternates: { canonical },
    openGraph: {
      title,
      description,
      url: canonical,
      siteName: "YieldIQ",
      type: "article",
      images: [{ url: ogUrl, width: 1200, height: 1200, alt: `${t1} Hex` }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [ogUrl],
    },
  }
}

export default async function HexComparePage(
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params
  const parsed = parseSlug(slug)
  if (!parsed) notFound()

  const [a, b] = await Promise.all([getHex(parsed.t1), getHex(parsed.t2)])
  if (!a || !b) notFound()

  const t1 = display(a.ticker || parsed.t1)
  const t2 = display(b.ticker || parsed.t2)
  const canonical = `https://yieldiq.in/hex/compare/${t1}-vs-${t2}`

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: `${t1} vs ${t2} \u2014 Hex Comparison`,
    description: `Side-by-side 6-axis hex comparison of ${t1} and ${t2}. Model estimate.`,
    url: canonical,
    author: { "@type": "Organization", name: "YieldIQ" },
    publisher: {
      "@type": "Organization",
      name: "YieldIQ",
      url: "https://yieldiq.in",
    },
  }

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <CompareClient a={a} b={b} canonical={canonical} />
    </>
  )
}
