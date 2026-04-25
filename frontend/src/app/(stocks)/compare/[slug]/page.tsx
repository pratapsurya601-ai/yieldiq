import type { Metadata } from "next"
import { notFound } from "next/navigation"
import CompareClient, { type CompareData } from "./CompareClient"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// Parse a slug like "ITC-vs-BRITANNIA", "itc-vs-britannia", or
// "ITC.BO-vs-BRITANNIA". Defaults to .NS suffix when none specified.
// Splits case-insensitively on "-vs-" so frontend can be slug-agnostic.
function parseSlug(slug: string): { ticker1: string; ticker2: string } | null {
  if (!slug) return null
  // Case-insensitive split on "-vs-"
  const m = slug.match(/^(.+?)-vs-(.+)$/i)
  if (!m) return null
  const raw1 = m[1].trim().toUpperCase()
  const raw2 = m[2].trim().toUpperCase()
  if (!raw1 || !raw2) return null
  const withSuffix = (t: string): string => {
    if (t.endsWith(".NS") || t.endsWith(".BO")) return t
    return `${t}.NS`
  }
  return { ticker1: withSuffix(raw1), ticker2: withSuffix(raw2) }
}

function display(t: string): string {
  return t.replace(/\.(NS|BO)$/i, "")
}

async function getCompareData(ticker1: string, ticker2: string): Promise<CompareData | null> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/public/compare?ticker1=${encodeURIComponent(ticker1)}&ticker2=${encodeURIComponent(ticker2)}`,
      { next: { revalidate: 3600 } }
    )
    if (!res.ok) return null
    return (await res.json()) as CompareData
  } catch {
    return null
  }
}

export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> }
): Promise<Metadata> {
  const { slug } = await params
  const parsed = parseSlug(slug)
  if (!parsed) return { title: "Compare Stocks | YieldIQ" }
  const t1 = display(parsed.ticker1)
  const t2 = display(parsed.ticker2)
  const canonical = `https://yieldiq.in/compare/${t1}-vs-${t2}`
  const title = `${t1} vs ${t2} \u2014 Which Sits Further Below Fair Value? | YieldIQ`
  const description = `Side-by-side DCF fair value, margin of safety, moat, and quality comparison between ${t1} and ${t2}. Updated daily.`
  return {
    title,
    description,
    robots: { index: true, follow: true },
    openGraph: {
      title,
      description,
      url: canonical,
      siteName: "YieldIQ",
      type: "article",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
    alternates: { canonical },
  }
}

export default async function ComparePage(
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params
  const parsed = parseSlug(slug)
  if (!parsed) notFound()
  const data = await getCompareData(parsed.ticker1, parsed.ticker2)
  if (!data) notFound()

  const t1 = data.stock1.display_ticker
  const t2 = data.stock2.display_ticker
  const canonical = `https://yieldiq.in/compare/${t1}-vs-${t2}`

  // JSON-LD: Article with two Product subjects
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: `${t1} vs ${t2} \u2014 DCF Comparison`,
    description: `Side-by-side comparison of ${data.stock1.company_name} and ${data.stock2.company_name}.`,
    url: canonical,
    author: { "@type": "Organization", name: "YieldIQ" },
    publisher: {
      "@type": "Organization",
      name: "YieldIQ",
      url: "https://yieldiq.in",
    },
    about: [
      {
        "@type": "Product",
        name: `${data.stock1.company_name} (${t1})`,
        category: data.stock1.sector,
      },
      {
        "@type": "Product",
        name: `${data.stock2.company_name} (${t2})`,
        category: data.stock2.sector,
      },
    ],
  }

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <CompareClient data={data} />
    </>
  )
}
