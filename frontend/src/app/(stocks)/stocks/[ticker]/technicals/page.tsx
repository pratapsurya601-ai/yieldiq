import type { Metadata } from "next"
import { notFound } from "next/navigation"
import TechnicalsClient from "./TechnicalsClient"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export async function generateMetadata(
  { params }: { params: Promise<{ ticker: string }> }
): Promise<Metadata> {
  const { ticker } = await params
  const display = ticker.toUpperCase().replace(".NS", "").replace(".BO", "")
  return {
    title: `${display} Technical Indicators \u2014 RSI, MACD, SMA Charts | YieldIQ`,
    description: `${display} technical analysis: 20/50/200-day moving averages, RSI(14), MACD, Bollinger Bands. Reference data, not buy signals.`,
    alternates: { canonical: `https://yieldiq.in/stocks/${display}/technicals` },
  }
}

export default async function TechnicalsPage(
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params

  let data = null
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/technicals/${ticker}?days=365`, {
      next: { revalidate: 3600 },
    })
    if (!res.ok) notFound()
    data = await res.json()
  } catch {
    notFound()
  }

  return <TechnicalsClient data={data} ticker={ticker} />
}
