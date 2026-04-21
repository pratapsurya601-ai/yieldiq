import type { Metadata } from "next"
import IndexDashboardClient from "./IndexDashboardClient"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export const metadata: Metadata = {
  title: "Nifty 50 Fair Value Dashboard \u2014 All 50 Stocks Valued by DCF | YieldIQ",
  description: "Free DCF valuation of all Nifty 50 stocks. See which are undervalued, overvalued, and fairly valued. Updated daily. No signup required.",
  openGraph: {
    title: "Nifty 50 Valuation Dashboard | YieldIQ",
    description: "All 50 Nifty 50 stocks ranked by DCF fair value. Free, updated daily.",
    url: "https://yieldiq.in/nifty50",
    siteName: "YieldIQ",
    type: "website",
    images: [{ url: "https://www.yieldiq.in/logo-1024.png", width: 1024, height: 1024 }],
  },
  alternates: { canonical: "https://yieldiq.in/nifty50" },
}

export default async function Nifty50Page() {
  let data = null
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/index-dashboard/nifty50`, {
      next: { revalidate: 900 },
    })
    if (res.ok) data = await res.json()
  } catch {}

  if (!data) {
    data = {
      index_id: "nifty50", index_name: "Nifty 50 Valuation Dashboard",
      description: "All 50 Nifty 50 stocks ranked by DCF fair value",
      total_stocks: 50, available_stocks: 0, stocks: [],
      summary: { undervalued: 0, fairly_valued: 0, overvalued: 0, most_undervalued: null, most_overvalued: null },
    }
  }

  return <IndexDashboardClient data={data} />
}
