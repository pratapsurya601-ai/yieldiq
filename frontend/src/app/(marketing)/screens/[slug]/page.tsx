import type { Metadata } from "next"
import { notFound } from "next/navigation"
import ScreenClient from "./ScreenClient"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> }
): Promise<Metadata> {
  const { slug } = await params
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/screens/${slug}`, { next: { revalidate: 1800 } })
    if (!res.ok) return { title: "Stock Screener | YieldIQ" }
    const data = await res.json()
    return {
      title: `${data.name} \u2014 ${data.total} Indian Stocks | YieldIQ`,
      description: `${data.description}. Free filter, no signup required. Updated daily.`,
      openGraph: {
        title: `${data.name} | YieldIQ`,
        description: data.description,
        url: `https://yieldiq.in/screens/${slug}`,
      },
      alternates: { canonical: `https://yieldiq.in/screens/${slug}` },
    }
  } catch {
    return { title: "Stock Screener | YieldIQ" }
  }
}

export default async function ScreenPage(
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params

  let data = null
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/screens/${slug}`, { next: { revalidate: 1800 } })
    if (!res.ok) notFound()
    data = await res.json()
  } catch {
    notFound()
  }

  return <ScreenClient data={data} slug={slug} />
}
