import type { Metadata } from "next"
import { notFound } from "next/navigation"
import CompareClient from "./CompareClient"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function parseSlug(slug: string): { ticker1: string; ticker2: string } | null {
  const parts = slug.split("-vs-")
  if (parts.length !== 2) return null
  const t1 = parts[0].trim().toUpperCase()
  const t2 = parts[1].trim().toUpperCase()
  if (!t1 || !t2) return null
  return { ticker1: `${t1}.NS`, ticker2: `${t2}.NS` }
}

export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> }
): Promise<Metadata> {
  const { slug } = await params
  const parsed = parseSlug(slug)
  if (!parsed) return { title: "Compare Stocks | YieldIQ" }
  const t1 = parsed.ticker1.replace(".NS", "")
  const t2 = parsed.ticker2.replace(".NS", "")
  return {
    title: `${t1} vs ${t2} \u2014 Which is More Undervalued? DCF Comparison | YieldIQ`,
    description: `Compare ${t1} and ${t2} head-to-head. DCF fair value, YieldIQ score, moat, Piotroski, and margin of safety. Free comparison.`,
    openGraph: {
      title: `${t1} vs ${t2} \u2014 Stock Comparison | YieldIQ`,
      description: `Which is more undervalued? Compare ${t1} and ${t2} by DCF fair value, quality score, and moat.`,
      url: `https://yieldiq.in/compare/${slug}`,
      siteName: "YieldIQ",
      type: "article",
    },
    alternates: { canonical: `https://yieldiq.in/compare/${slug}` },
  }
}

export default async function ComparePage(
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params
  const parsed = parseSlug(slug)
  if (!parsed) notFound()

  try {
    const res = await fetch(
      `${API_BASE}/api/v1/public/compare?ticker1=${parsed.ticker1}&ticker2=${parsed.ticker2}`,
      { next: { revalidate: 3600 } }
    )
    if (!res.ok) notFound()
    const data = await res.json()
    return <CompareClient data={data} slug={slug} />
  } catch {
    notFound()
  }
}
