import type { Metadata } from "next"
import { notFound } from "next/navigation"
import ReverseDCFClient from "./ReverseDCFClient"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export async function generateMetadata(
  { params }: { params: Promise<{ ticker: string }> }
): Promise<Metadata> {
  const { ticker } = await params
  const display = ticker.toUpperCase().replace(".NS", "").replace(".BO", "")
  try {
    const res = await fetch(`${API_BASE}/api/v1/analysis/${ticker}/reverse-dcf`, {
      next: { revalidate: 3600 },
    })
    if (!res.ok) {
      return { title: `${display} Reverse DCF | YieldIQ` }
    }
    const data = await res.json()
    const implied = data.implied_growth ? `${(data.implied_growth * 100).toFixed(1)}%` : ""
    return {
      title: `${display} Reverse DCF \u2014 Market Implies ${implied} FCF Growth | YieldIQ`,
      description: `What FCF growth rate does the market price into ${display}? Reverse DCF analysis with verdict, historical comparison, and sensitivity scenarios.`,
      openGraph: {
        title: `${display} Reverse DCF | YieldIQ`,
        description: `Market-implied growth: ${implied}. ${data.verdict_text || ""}`,
        url: `https://yieldiq.in/stocks/${display}/reverse-dcf`,
      },
      alternates: { canonical: `https://yieldiq.in/stocks/${display}/reverse-dcf` },
    }
  } catch {
    return { title: `${display} Reverse DCF | YieldIQ` }
  }
}

export default async function ReverseDCFPage(
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params

  let data = null
  try {
    const res = await fetch(`${API_BASE}/api/v1/analysis/${ticker}/reverse-dcf`, {
      next: { revalidate: 3600 },
    })
    if (!res.ok) notFound()
    data = await res.json()
  } catch {
    notFound()
  }

  return <ReverseDCFClient initialData={data} ticker={ticker} />
}
